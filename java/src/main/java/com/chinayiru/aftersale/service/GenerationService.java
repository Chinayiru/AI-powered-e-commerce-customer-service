package com.chinayiru.aftersale.service;

import com.chinayiru.aftersale.agent.AgentClient;
import com.chinayiru.aftersale.agent.AgentContract;
import com.chinayiru.aftersale.agent.AgentUnavailableException;
import com.chinayiru.aftersale.api.dto.ApiDtos.TicketCreated;
import com.chinayiru.aftersale.auth.InternalIdentityService;
import com.chinayiru.aftersale.auth.TicketTokenService;
import com.chinayiru.aftersale.common.Hashing;
import com.chinayiru.aftersale.common.JsonCodec;
import com.chinayiru.aftersale.common.TimeUtil;
import com.chinayiru.aftersale.common.TraceFilter;
import com.chinayiru.aftersale.config.AppProperties;
import com.chinayiru.aftersale.domain.ActionType;
import com.chinayiru.aftersale.domain.AuditLog;
import com.chinayiru.aftersale.domain.Category;
import com.chinayiru.aftersale.domain.Draft;
import com.chinayiru.aftersale.domain.IntentType;
import com.chinayiru.aftersale.domain.MessageRole;
import com.chinayiru.aftersale.domain.Ticket;
import com.chinayiru.aftersale.domain.TicketMessage;
import com.chinayiru.aftersale.domain.TicketState;
import com.chinayiru.aftersale.domain.ToolCall;
import com.chinayiru.aftersale.domain.TransferReason;
import com.chinayiru.aftersale.mapper.AuditMapper;
import com.chinayiru.aftersale.mapper.DraftMapper;
import com.chinayiru.aftersale.mapper.MessageMapper;
import com.chinayiru.aftersale.mapper.TicketMapper;
import com.chinayiru.aftersale.mapper.ToolCallMapper;
import com.chinayiru.aftersale.policy.PolicyDecision;
import com.chinayiru.aftersale.policy.PolicyService;
import com.chinayiru.aftersale.tool.OrderModels.Order;
import com.chinayiru.aftersale.tool.OrderModels.PackageInfo;
import com.chinayiru.aftersale.tool.OrderModels.Shipment;
import com.chinayiru.aftersale.tool.OrderToolService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

/**
 * 生成任务：把 Python 的建议 + Java 政策引擎的结论落成草稿/转人工。
 *
 * 外部调用在事务外；状态迁移 + 草稿落库在同一事务内。
 * 迟到结果：仅当 state 仍为 AI_RUNNING 且 generationTaskId/taskEpoch/currentAttempt
 * 全部匹配时才发布，否则记 LATE_RESULT_DROPPED。
 */
@Service
public class GenerationService {

    private final AgentClient agentClient;
    private final InternalIdentityService internalIdentity;
    private final TicketTokenService ticketTokens;
    private final TicketViewMapper viewMapper;
    private final TicketMapper ticketMapper;
    private final MessageMapper messageMapper;
    private final DraftMapper draftMapper;
    private final ToolCallMapper toolCallMapper;
    private final AuditMapper auditMapper;
    private final OrderToolService orderTools;
    private final PolicyService policyService;
    private final AssociatedTicketService associatedTickets;
    private final JsonCodec json;
    private final TransactionTemplate tx;
    private final AppProperties properties;

    public GenerationService(AgentClient agentClient, InternalIdentityService internalIdentity,
                             TicketTokenService ticketTokens, TicketViewMapper viewMapper,
                             TicketMapper ticketMapper, MessageMapper messageMapper,
                             DraftMapper draftMapper, ToolCallMapper toolCallMapper,
                             AuditMapper auditMapper, OrderToolService orderTools,
                             PolicyService policyService, AssociatedTicketService associatedTickets,
                             JsonCodec json, TransactionTemplate tx, AppProperties properties) {
        this.agentClient = agentClient;
        this.internalIdentity = internalIdentity;
        this.ticketTokens = ticketTokens;
        this.viewMapper = viewMapper;
        this.ticketMapper = ticketMapper;
        this.messageMapper = messageMapper;
        this.draftMapper = draftMapper;
        this.toolCallMapper = toolCallMapper;
        this.auditMapper = auditMapper;
        this.orderTools = orderTools;
        this.policyService = policyService;
        this.associatedTickets = associatedTickets;
        this.json = json;
        this.tx = tx;
        this.properties = properties;
    }

    public GenerationOutcome generate(String ticketId, String messageText, String requestId, String traceId) {
        Ticket ticket = ticketMapper.findById(ticketId);
        if (ticket == null || ticket.getState() != TicketState.AI_RUNNING) {
            return new GenerationOutcome(ticket, null);
        }
        String taskId = ticket.getGenerationTaskId();
        int epoch = ticket.getTaskEpoch();
        int attempt = ticket.getCurrentAttempt();
        List<TicketMessage> messages = messageMapper.listByTicket(ticketId);
        String effectiveMessage = messageText == null ? lastCustomerText(messages) : messageText;

        AgentContract.AskResponse response;
        try {
            response = agentClient.ask(buildRequest(ticket, effectiveMessage, requestId, attempt, messages),
                    internalIdentity.issueForAgent(ticket.getUserId()));
        } catch (AgentUnavailableException ex) {
            transferDueToAgentFailure(ticket, traceId);
            return new GenerationOutcome(ticketMapper.findById(ticketId), null);
        }

        if (ticket.getCategory() == Category.CONSULT && response.intent() == IntentType.REFUND_REQUEST) {
            return handleConsultToAftersale(ticket, response, effectiveMessage, requestId, traceId,
                    taskId, epoch, attempt);
        }

        tx.executeWithoutResult(status -> publish(ticket, response, taskId, epoch, attempt, traceId));
        return new GenerationOutcome(ticketMapper.findById(ticketId), null);
    }

    private AgentContract.AskRequest buildRequest(Ticket ticket, String message, String requestId,
                                                  int attempt, List<TicketMessage> messages) {
        List<AgentContract.History> history = messages.stream()
                .filter(m -> m.getRole() == MessageRole.CUSTOMER || m.getRole() == MessageRole.AGENT)
                .map(m -> new AgentContract.History(m.getRole().name(), m.getText(),
                        m.getCreatedAt() == null ? null : m.getCreatedAt().toString()))
                .toList();
        if (history.size() > 12) {
            history = history.subList(history.size() - 12, history.size());
        }
        String summary = "客户诉求：" + truncate(message, 120)
                + (ticket.getOrderNo() == null ? "" : "；订单 " + ticket.getOrderNo());
        return new AgentContract.AskRequest(
                com.chinayiru.aftersale.common.TraceFilter.currentTraceId(),
                ticket.getTicketId(), requestId, attempt, ticket.getTaskEpoch(),
                ticket.getUserId(), ticket.getCategory().name(), message,
                new AgentContract.Context(ticket.getOrderNo(), truncate(summary, 300), history));
    }

    private GenerationOutcome handleConsultToAftersale(Ticket consult, AgentContract.AskResponse response,
                                                      String messageText, String requestId, String traceId,
                                                      String taskId, int epoch, int attempt) {
        AssociatedTicketService.Shell shell = tx.execute(status -> {
            Ticket current = ticketMapper.findById(consult.getTicketId());
            if (!current(taskId, epoch, attempt, current)) {
                audit(consult.getTicketId(), "LATE_RESULT_DROPPED", "consult-refund", traceId);
                return null;
            }
            String orderNo = current.getOrderNo();
            if (orderNo == null && response.slots() != null && response.slots().orderNo() != null) {
                orderNo = response.slots().orderNo();
                Optional<Order> order = orderTools.findOwned(current.getUserId(), orderNo);
                if (order.isEmpty()) {
                    markOrderNotFound(current, orderNo, traceId);
                    return null;
                }
                ticketMapper.updateOrderNo(current.getTicketId(), orderNo, TimeUtil.now());
                current = ticketMapper.findById(current.getTicketId());
            }
            if (orderNo == null) {
                markWaitingInput(current, null, TransferReason.INSUFFICIENT_INFO, traceId);
                return null;
            }
            AssociatedTicketService.Shell created = associatedTickets.createShell(current, orderNo, traceId);
            int rows = ticketMapper.transition(current.getTicketId(), current.getVersion(),
                    Set.of(TicketState.AI_RUNNING.name()), TicketState.REPLIED,
                    null, false, false, 0, null, false, TimeUtil.now());
            if (rows != 1) {
                audit(current.getTicketId(), "LATE_RESULT_DROPPED", "consult-refund-transition", traceId);
                return null;
            }
            audit(current.getTicketId(), "CONSULT_TO_AFTERSALE",
                    "newTicketId=" + created.ticket().getTicketId(), traceId);
            return created;
        });

        if (shell == null) {
            return new GenerationOutcome(ticketMapper.findById(consult.getTicketId()), null);
        }
        if (shell.created()) {
            generate(shell.ticket().getTicketId(), messageText, requestId, traceId);
        }
        Ticket newTicket = ticketMapper.findById(shell.ticket().getTicketId());
        TicketCreated created = viewMapper.ticketCreated(newTicket,
                ticketTokens.issue(newTicket.getTicketId(), newTicket.getUserId()));
        return new GenerationOutcome(ticketMapper.findById(consult.getTicketId()), created);
    }

    private void publish(Ticket original, AgentContract.AskResponse response,
                         String taskId, int epoch, int attempt, String traceId) {
        Ticket ticket = ticketMapper.findById(original.getTicketId());
        if (!current(taskId, epoch, attempt, ticket)) {
            audit(original.getTicketId(), "LATE_RESULT_DROPPED", "publish", traceId);
            return;
        }
        if (ticket.getCategory() == Category.CONSULT && response.intent() == IntentType.REFUND_REQUEST) {
            return;
        }

        String candidate = ticket.getOrderNo();
        if (candidate == null && response.slots() != null && response.slots().orderNo() != null) {
            candidate = response.slots().orderNo();
            Optional<Order> found = orderTools.findOwned(ticket.getUserId(), candidate);
            if (found.isEmpty()) {
                markOrderNotFound(ticket, candidate, traceId);
                return;
            }
            ticketMapper.updateOrderNo(ticket.getTicketId(), candidate, TimeUtil.now());
            ticket = ticketMapper.findById(ticket.getTicketId());
        }
        boolean needsOrder = needsOrder(ticket.getCategory(), response.intent());
        Optional<Order> maybeOrder = candidate == null
                ? Optional.empty()
                : orderTools.findOwned(ticket.getUserId(), candidate);
        if (candidate != null) {
            recordToolCall(ticket.getTicketId(), response.intent(), candidate, maybeOrder, traceId);
        }
        // 已明确给出订单号但查无此单：首次提示核对，第二次无论意图如何都按 ORDER_NOT_FOUND 转人工。
        if (candidate != null && maybeOrder.isEmpty() && ticket.getStalledRounds() > 0) {
            markOrderNotFound(ticket, candidate, traceId);
            return;
        }
        if (needsOrder && maybeOrder.isEmpty()) {
            if (candidate == null) {
                markWaitingInput(ticket, null, TransferReason.INSUFFICIENT_INFO, traceId);
            } else {
                markOrderNotFound(ticket, candidate, traceId);
            }
            return;
        }

        if (response.intent() == IntentType.HANDOFF) {
            TransferReason reason = response.transferReason() == null
                    ? TransferReason.OUT_OF_SCOPE : response.transferReason();
            transfer(ticket, reason, safeReply(response.replyDraft(), "已为您转接人工客服，请稍候。"), traceId);
            return;
        }

        if (ticket.getCategory() == Category.CONSULT) {
            publishConsult(ticket, response, traceId);
            return;
        }

        Order order = maybeOrder.orElse(null);
        boolean refundIntent = response.intent() == IntentType.REFUND_REQUEST
                || response.intent() == IntentType.REFUND_ELIGIBILITY;
        PolicyDecision policy;
        Long amount = response.suggestedAction() == null ? null : response.suggestedAction().amountCents();
        if (refundIntent) {
            policy = policyService.evaluate(order, amount);
            if (!policy.allowed() && !"OUTSIDE_RETURN_WINDOW".equals(policy.code())) {
                transfer(ticket, TransferReason.POLICY_BLOCKED,
                        policy.explanation() + (response.replyDraft() == null ? "" : " " + response.replyDraft()),
                        traceId);
                return;
            }
        } else {
            policy = new PolicyDecision(true, "NO_REFUND", properties.getPolicy().getVersion(),
                    null, null, true, "非退款建议，不需要退款政策拦截");
        }

        boolean needReview = response.needHumanReview()
                || response.confidence() < properties.getIntent().getConfidenceThreshold()
                || (amount != null && amount > properties.getRefund().getAutoSuggestLimitCents());
        String reply = safeReply(response.replyDraft(),
                refundIntent ? "请坐席根据订单情况补充回复。" : policy.explanation());

        Draft draft = new Draft();
        draft.setDraftId(UUID.randomUUID().toString());
        draft.setTicketId(ticket.getTicketId());
        draft.setDraftVersion(draftMapper.maxVersion(ticket.getTicketId()) + 1);
        draft.setGenerationTaskId(taskId);
        draft.setIntent(response.intent());
        draft.setConfidence(BigDecimal.valueOf(response.confidence()));
        draft.setReplyType(response.replyType());
        draft.setReplyDraft(reply);
        AgentContract.SuggestedAction action = response.suggestedAction() == null
                ? new AgentContract.SuggestedAction(ActionType.NONE, null, true)
                : response.suggestedAction();
        draft.setSuggestedActionJson(json.write(action));
        draft.setCitationsJson(json.write(response.citations() == null ? List.of() : response.citations()));
        draft.setPolicyCheckJson(json.write(policy));
        draft.setPolicyVersion(policy.policyVersion());
        draft.setNeedHumanReview(needReview);
        draft.setSuperseded(false);
        draft.setCreatedAt(TimeUtil.now());
        draftMapper.insert(draft);
        draftMapper.supersedeOthers(ticket.getTicketId(), draft.getDraftId());

        int rows = ticketMapper.transition(ticket.getTicketId(), ticket.getVersion(),
                Set.of(TicketState.AI_RUNNING.name()), TicketState.DRAFT_READY,
                null, false, false, 0, null, false, TimeUtil.now());
        if (rows != 1) {
            audit(ticket.getTicketId(), "LATE_RESULT_DROPPED", "draft-transition", traceId);
            return;
        }
        audit(ticket.getTicketId(), "DRAFT_CREATED",
                "draftVersion=" + draft.getDraftVersion() + ", policy=" + policy.code(), traceId);
    }

    private void publishConsult(Ticket ticket, AgentContract.AskResponse response, String traceId) {
        if (response.confidence() < properties.getIntent().getConfidenceThreshold()) {
            transfer(ticket, TransferReason.LOW_CONFIDENCE, "已转人工进一步核实。", traceId);
            return;
        }
        if (response.replyType() == com.chinayiru.aftersale.domain.ReplyType.DECISIONAL) {
            TransferReason reason = response.transferReason() == null
                    ? TransferReason.OUT_OF_SCOPE : response.transferReason();
            transfer(ticket, reason, safeReply(response.replyDraft(), "该问题需要人工处理，已转接人工客服。"), traceId);
            return;
        }
        if (response.replyDraft() == null || response.replyDraft().isBlank()
                || response.citations() == null || response.citations().isEmpty()) {
            transfer(ticket, TransferReason.NO_EVIDENCE, "暂未检索到可靠依据，已转人工核实。", traceId);
            return;
        }
        int rows = ticketMapper.transition(ticket.getTicketId(), ticket.getVersion(),
                Set.of(TicketState.AI_RUNNING.name()), TicketState.REPLIED,
                null, false, false, 0, null, false, TimeUtil.now());
        if (rows != 1) {
            audit(ticket.getTicketId(), "LATE_RESULT_DROPPED", "consult-reply", traceId);
            return;
        }
        addAgentMessage(ticket.getTicketId(), response.replyDraft());
        audit(ticket.getTicketId(), "CONSULT_REPLIED", "confidence=" + response.confidence(), traceId);
    }

    private void transferDueToAgentFailure(Ticket ticket, String traceId) {
        tx.executeWithoutResult(status -> {
            Ticket current = ticketMapper.findById(ticket.getTicketId());
            if (current == null || current.getState() != TicketState.AI_RUNNING) {
                return;
            }
            int rows = ticketMapper.transition(current.getTicketId(), current.getVersion(),
                    Set.of(TicketState.AI_RUNNING.name()), TicketState.TRANSFERRED,
                    TransferReason.TOOL_FAILED, false, false, 0, null, false, TimeUtil.now());
            if (rows == 1) {
                addAgentMessage(current.getTicketId(), "AI 服务暂时不可用，已转人工处理。");
                audit(current.getTicketId(), "TRANSFERRED", "TOOL_FAILED", traceId);
            }
        });
    }

    private void transfer(Ticket ticket, TransferReason reason, String message, String traceId) {
        int rows = ticketMapper.transition(ticket.getTicketId(), ticket.getVersion(),
                Set.of(TicketState.AI_RUNNING.name()), TicketState.TRANSFERRED,
                reason, false, false, 0, null, false, TimeUtil.now());
        if (rows != 1) {
            audit(ticket.getTicketId(), "LATE_RESULT_DROPPED", "transfer", traceId);
            return;
        }
        addAgentMessage(ticket.getTicketId(), message);
        audit(ticket.getTicketId(), "TRANSFERRED", reason.name(), traceId);
    }

    private void markWaitingInput(Ticket ticket, String orderNo, TransferReason reason, String traceId) {
        int next = ticket.getStalledRounds() + 1;
        boolean transfer = next >= properties.getConsult().getStallRounds();
        TicketState target = transfer ? TicketState.TRANSFERRED : TicketState.WAITING_INPUT;
        int rows = ticketMapper.transition(ticket.getTicketId(), ticket.getVersion(),
                Set.of(TicketState.AI_RUNNING.name()), target,
                transfer ? reason : null, false, false, next, orderNo, false, TimeUtil.now());
        if (rows != 1) {
            audit(ticket.getTicketId(), "LATE_RESULT_DROPPED", "waiting-input", traceId);
            return;
        }
        String prompt = transfer
                ? "多次未能补齐订单信息，已转人工处理。"
                : "请提供订单号，我帮您核实订单状态和可退金额。";
        addAgentMessage(ticket.getTicketId(), prompt);
        audit(ticket.getTicketId(), transfer ? "TRANSFERRED" : "WAITING_INPUT",
                reason.name() + ", stalledRounds=" + next, traceId);
    }

    private void markOrderNotFound(Ticket ticket, String orderNo, String traceId) {
        int next = ticket.getStalledRounds() + 1;
        boolean transfer = next >= properties.getConsult().getStallRounds();
        TicketState target = transfer ? TicketState.TRANSFERRED : TicketState.WAITING_INPUT;
        int rows = ticketMapper.transition(ticket.getTicketId(), ticket.getVersion(),
                Set.of(TicketState.AI_RUNNING.name()), target,
                transfer ? TransferReason.ORDER_NOT_FOUND : null, false, false, next, orderNo, false,
                TimeUtil.now());
        if (rows != 1) {
            audit(ticket.getTicketId(), "LATE_RESULT_DROPPED", "order-not-found", traceId);
            return;
        }
        String prompt = transfer
                ? "多次未查询到订单 " + orderNo + "，已转人工处理。"
                : "没查到订单 " + orderNo + "，请核对订单号后重新提供。";
        addAgentMessage(ticket.getTicketId(), prompt);
        audit(ticket.getTicketId(), transfer ? "TRANSFERRED" : "WAITING_INPUT",
                TransferReason.ORDER_NOT_FOUND.name() + ", stalledRounds=" + next, traceId);
    }

    private void recordToolCall(String ticketId, IntentType intent, String orderNo,
                                Optional<Order> order, String traceId) {
        long start = System.nanoTime();
        ToolCall call = new ToolCall();
        call.setTicketId(ticketId);
        call.setStep(toolCallMapper.nextStep(ticketId));
        call.setCreatedAt(TimeUtil.now());
        call.setRequestHash(Hashing.shortHash(orderNo));
        if (order.isEmpty()) {
            call.setName("queryOrder");
            call.setOk(false);
            call.setErrorCode("ORDER_NOT_FOUND");
            call.setLatencyMs((int) ((System.nanoTime() - start) / 1_000_000));
            call.setSummary("未查询到订单 " + orderNo);
            toolCallMapper.insert(call);
            return;
        }
        Order value = order.get();
        call.setName(intent == IntentType.LOGISTICS ? "getLogistics" : "queryOrder");
        call.setOk(true);
        call.setLatencyMs((int) ((System.nanoTime() - start) / 1_000_000));
        call.setResponseHash(Hashing.shortHash(json.write(value)));
        if (intent == IntentType.LOGISTICS) {
            Shipment shipment = orderTools.shipmentFor(value.userId(), orderNo);
            List<String> statuses = new ArrayList<>();
            for (PackageInfo pkg : shipment.shipments()) {
                statuses.add(pkg.trackingNo() + ":" + pkg.status());
            }
            call.setSummary("物流 " + shipment.status() + " " + String.join(",", statuses));
        } else {
            call.setSummary("订单 " + orderNo + " 状态 " + value.status()
                    + "，可退 " + value.refundableAmountCents() + " 分");
        }
        toolCallMapper.insert(call);
    }

    private void addAgentMessage(String ticketId, String text) {
        TicketMessage message = new TicketMessage();
        message.setTicketId(ticketId);
        message.setRole(MessageRole.AGENT);
        message.setText(text);
        message.setCreatedAt(TimeUtil.now());
        messageMapper.insert(message);
    }

    private void audit(String ticketId, String action, String detail, String traceId) {
        AuditLog log = new AuditLog();
        log.setTicketId(ticketId);
        log.setAction(action);
        log.setDetail(detail);
        log.setTraceId(traceId == null ? TraceFilter.currentTraceId() : traceId);
        log.setCreatedAt(TimeUtil.now());
        auditMapper.insert(log);
    }

    private static boolean needsOrder(Category category, IntentType intent) {
        if (category == Category.AFTERSALE) {
            return true;
        }
        return intent == IntentType.REFUND_REQUEST
                || intent == IntentType.REFUND_ELIGIBILITY
                || intent == IntentType.LOGISTICS;
    }

    private static boolean current(String taskId, int epoch, int attempt, Ticket ticket) {
        return ticket != null
                && ticket.getState() == TicketState.AI_RUNNING
                && taskId.equals(ticket.getGenerationTaskId())
                && ticket.getTaskEpoch() == epoch
                && ticket.getCurrentAttempt() == attempt;
    }

    private static String lastCustomerText(List<TicketMessage> messages) {
        for (int i = messages.size() - 1; i >= 0; i--) {
            if (messages.get(i).getRole() == MessageRole.CUSTOMER) {
                return messages.get(i).getText();
            }
        }
        return "";
    }

    private static String safeReply(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }

    private static String truncate(String value, int max) {
        if (value == null) {
            return "";
        }
        String normalized = value.replaceAll("\\s+", " ").trim();
        return normalized.length() <= max ? normalized : normalized.substring(0, max) + "…";
    }

    @SuppressWarnings("unused")
    private static String lower(String value) {
        return value == null ? "" : value.toLowerCase(Locale.ROOT);
    }
}
