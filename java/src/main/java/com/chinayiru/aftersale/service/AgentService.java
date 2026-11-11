package com.chinayiru.aftersale.service;

import com.chinayiru.aftersale.api.dto.ApiDtos.AgentTicketView;
import com.chinayiru.aftersale.api.dto.ApiDtos.CloseRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.HandoffRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.PolicyCheckView;
import com.chinayiru.aftersale.api.dto.ApiDtos.RegenerateRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.ReplyRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.SendRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.SendResult;
import com.chinayiru.aftersale.api.dto.ApiDtos.SuggestedAction;
import com.chinayiru.aftersale.api.dto.ApiDtos.TicketStateResponse;
import com.chinayiru.aftersale.common.ApiException;
import com.chinayiru.aftersale.common.ErrorCode;
import com.chinayiru.aftersale.common.JsonCodec;
import com.chinayiru.aftersale.common.TimeUtil;
import com.chinayiru.aftersale.common.TraceFilter;
import com.chinayiru.aftersale.domain.AuditLog;
import com.chinayiru.aftersale.domain.Draft;
import com.chinayiru.aftersale.domain.ExecutionState;
import com.chinayiru.aftersale.domain.ExecutionTask;
import com.chinayiru.aftersale.domain.MessageRole;
import com.chinayiru.aftersale.domain.Ticket;
import com.chinayiru.aftersale.domain.TicketMessage;
import com.chinayiru.aftersale.domain.TicketState;
import com.chinayiru.aftersale.mapper.AuditMapper;
import com.chinayiru.aftersale.mapper.DraftMapper;
import com.chinayiru.aftersale.mapper.ExecutionTaskMapper;
import com.chinayiru.aftersale.mapper.MessageMapper;
import com.chinayiru.aftersale.mapper.TicketMapper;
import com.chinayiru.aftersale.mapper.ToolCallMapper;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

/**
 * 坐席侧用例：查看、确认发送、重新生成、转交、回复、关闭。
 * send 严格按文档分三段：tx1 确认、事务外模拟执行、tx2 执行结果；
 * 执行失败返回 202 + CONFIRMED，且待执行任务与确认同事务落库。
 */
@Service
public class AgentService {

    private static final Set<TicketState> CLOSABLE = Set.of(TicketState.TRANSFERRED, TicketState.REPLIED);

    private final TicketMapper ticketMapper;
    private final MessageMapper messageMapper;
    private final DraftMapper draftMapper;
    private final ToolCallMapper toolCallMapper;
    private final ExecutionTaskMapper executionTaskMapper;
    private final AuditMapper auditMapper;
    private final TicketViewMapper viewMapper;
    private final IdempotencyService idempotency;
    private final GenerationService generationService;
    private final JsonCodec json;
    private final TransactionTemplate tx;

    public AgentService(TicketMapper ticketMapper, MessageMapper messageMapper, DraftMapper draftMapper,
                        ToolCallMapper toolCallMapper, ExecutionTaskMapper executionTaskMapper,
                        AuditMapper auditMapper, TicketViewMapper viewMapper, IdempotencyService idempotency,
                        GenerationService generationService, JsonCodec json, TransactionTemplate tx) {
        this.ticketMapper = ticketMapper;
        this.messageMapper = messageMapper;
        this.draftMapper = draftMapper;
        this.toolCallMapper = toolCallMapper;
        this.executionTaskMapper = executionTaskMapper;
        this.auditMapper = auditMapper;
        this.viewMapper = viewMapper;
        this.idempotency = idempotency;
        this.generationService = generationService;
        this.json = json;
        this.tx = tx;
    }

    public AgentTicketView view(String ticketId) {
        Ticket ticket = requireTicket(ticketId);
        Draft draft = draftMapper.findLatestActive(ticketId);
        return viewMapper.agentView(ticket, messageMapper.listByTicket(ticketId), draft,
                toolCallMapper.listByTicket(ticketId));
    }

    public ResponseEntity<?> send(String ticketId, SendRequest request) {
        requireTicket(ticketId);
        return idempotency.execute("agent", "POST /api/agent/send", ticketId, request.requestId(),
                idempotency.hash(request), () -> doSend(ticketId, request));
    }

    private ResponseEntity<?> doSend(String ticketId, SendRequest request) {
        Ticket ticket = requireTicket(ticketId);
        if (!TicketState.SEND_FROM.contains(ticket.getState())) {
            throw new ApiException(ErrorCode.STATE_NOT_ALLOWED, "当前状态不允许确认发送");
        }
        if (ticket.getVersion() != request.expectedVersion()) {
            throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
        }
        Draft draft = draftMapper.findLatestActive(ticketId);
        if (draft == null || draft.getDraftVersion() != request.draftVersion()) {
            throw new ApiException(ErrorCode.STALE_DRAFT, "草稿已被更新，请刷新后重试");
        }

        PolicyCheckView policy = json.read(draft.getPolicyCheckJson(), PolicyCheckView.class);
        if (policy == null || !policy.allowed()) {
            throw new ApiException(ErrorCode.POLICY_REJECTED, "政策校验未通过，不能确认发送");
        }
        SuggestedAction action = json.read(draft.getSuggestedActionJson(), SuggestedAction.class);
        Long amount = action == null ? null : action.amountCents();
        if (amount != null) {
            if (policy.maxRefundableCents() == null || amount > policy.maxRefundableCents()) {
                throw new ApiException(ErrorCode.POLICY_REJECTED, "建议金额超过可退上限");
            }
        }
        if (draft.isNeedHumanReview() && (request.reviewNote() == null || request.reviewNote().trim().length() < 5)) {
            throw new ApiException(ErrorCode.REVIEW_NOTE_REQUIRED, "该草稿需要复核说明（至少 5 个字符）");
        }
        if (containsInternalCode(request.text())) {
            throw new ApiException(ErrorCode.INVALID_ARGS, "回复正文不能包含内部状态或字段名");
        }

        int distance = editDistance(draft.getReplyDraft(), request.text());
        boolean edited = distance > 0;

        Ticket confirmed = tx.execute(status -> {
            int rows = ticketMapper.transition(ticketId, ticket.getVersion(),
                    Set.of(ticket.getState().name()), TicketState.CONFIRMED,
                    null, false, false, null, null, false, TimeUtil.now());
            if (rows != 1) {
                throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
            }
            addMessage(ticketId, MessageRole.AGENT, request.text());

            ExecutionTask task = new ExecutionTask();
            task.setTaskId(UUID.randomUUID().toString());
            task.setTicketId(ticketId);
            task.setRequestId(request.requestId());
            task.setState(ExecutionState.PENDING);
            task.setAttempts(0);
            task.setCreatedAt(TimeUtil.now());
            task.setUpdatedAt(TimeUtil.now());
            executionTaskMapper.insert(task);

            audit(ticketId, "SENT", "edited=" + edited + ", editDistance=" + distance
                    + ", reviewNote=" + (request.reviewNote() == null ? "" : request.reviewNote()), null);
            return ticketMapper.findById(ticketId);
        });

        try {
            Ticket closed = tx.execute(status -> {
                move(confirmed, TicketState.CONFIRMED, TicketState.EXECUTING, null, false, false);
                ExecutionTask task = executionTaskMapper.findByTicketAndRequest(ticketId, request.requestId());
                if (task != null) {
                    executionTaskMapper.markDone(task.getTaskId(), TimeUtil.now());
                }
                addMessage(ticketId, MessageRole.AGENT, "退款申请已受理（演示环境，未真实退款）。");
                move(ticketMapper.findById(ticketId), TicketState.EXECUTING, TicketState.CLOSED, null, false, true);
                audit(ticketId, "EXECUTED", "SIMULATED", null);
                return ticketMapper.findById(ticketId);
            });
            return ResponseEntity.ok(new SendResult(closed.getState().name(), edited, distance,
                    draft.getDraftVersion()));
        } catch (RuntimeException ex) {
            ExecutionTask task = executionTaskMapper.findByTicketAndRequest(ticketId, request.requestId());
            if (task != null) {
                executionTaskMapper.markFailed(task.getTaskId(), ErrorCode.PERSISTENCE_FAILED.name(), TimeUtil.now());
            }
            return ResponseEntity.status(202)
                    .body(new SendResult(TicketState.CONFIRMED.name(), edited, distance, draft.getDraftVersion()));
        }
    }

    public ResponseEntity<?> regenerate(String ticketId, RegenerateRequest request) {
        requireTicket(ticketId);
        return idempotency.execute("agent", "POST /api/agent/regenerate", ticketId, request.requestId(),
                idempotency.hash(request), () -> doRegenerate(ticketId, request));
    }

    private ResponseEntity<?> doRegenerate(String ticketId, RegenerateRequest request) {
        Ticket ticket = requireTicket(ticketId);
        if (ticket.getState() != TicketState.DRAFT_READY) {
            throw new ApiException(ErrorCode.STATE_NOT_ALLOWED, "只有草稿就绪的工单可以重新生成");
        }
        if (ticket.getVersion() != request.expectedVersion()) {
            throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
        }
        Ticket running = tx.execute(status -> {
            move(ticket, TicketState.DRAFT_READY, TicketState.AI_RUNNING, null, true, false);
            draftMapper.supersedeAll(ticketId);
            ticketMapper.updateGeneration(ticketId, UUID.randomUUID().toString(), 1, TimeUtil.now());
            audit(ticketId, "REGENERATE", request.note(), null);
            return ticketMapper.findById(ticketId);
        });
        generationService.generate(ticketId, lastCustomerText(ticketId), request.requestId(), null);
        Ticket after = ticketMapper.findById(ticketId);
        return ResponseEntity.status(202)
                .body(new TicketStateResponse(after.getTicketId(), after.getState().name(), after.getVersion()));
    }

    public ResponseEntity<?> handoff(String ticketId, HandoffRequest request) {
        requireTicket(ticketId);
        return idempotency.execute("agent", "POST /api/agent/handoff", ticketId, request.requestId(),
                idempotency.hash(request), () -> {
                    Ticket ticket = requireTicket(ticketId);
                    if (!TicketState.HANDOFF_FROM.contains(ticket.getState())) {
                        throw new ApiException(ErrorCode.STATE_NOT_ALLOWED, "当前状态不允许转交");
                    }
                    if (ticket.getVersion() != request.expectedVersion()) {
                        throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
                    }
                    Ticket after = tx.execute(status -> {
                        int rows = ticketMapper.transition(ticketId, ticket.getVersion(),
                                Set.of(ticket.getState().name()), TicketState.TRANSFERRED,
                                request.reason(), false, true, null, null, false, TimeUtil.now());
                        if (rows != 1) {
                            throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
                        }
                        addMessage(ticketId, MessageRole.AGENT, "已转交人工专员继续处理。");
                        audit(ticketId, "HANDOFF", request.reason().name(), null);
                        return ticketMapper.findById(ticketId);
                    });
                    return ResponseEntity.ok(new TicketStateResponse(after.getTicketId(),
                            after.getState().name(), after.getVersion()));
                });
    }

    public ResponseEntity<?> reply(String ticketId, ReplyRequest request) {
        requireTicket(ticketId);
        return idempotency.execute("agent", "POST /api/agent/reply", ticketId, request.requestId(),
                idempotency.hash(request), () -> {
                    Ticket ticket = requireTicket(ticketId);
                    if (ticket.getState() != TicketState.TRANSFERRED) {
                        throw new ApiException(ErrorCode.STATE_NOT_ALLOWED, "只有待人工处理的工单可以回复");
                    }
                    if (ticket.getVersion() != request.expectedVersion()) {
                        throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
                    }
                    Ticket after = tx.execute(status -> {
                        addMessage(ticketId, MessageRole.AGENT, request.text());
                        int rows = ticketMapper.transition(ticketId, ticket.getVersion(),
                                Set.of(TicketState.TRANSFERRED.name()), TicketState.REPLIED,
                                null, false, false, null, null, false, TimeUtil.now());
                        if (rows != 1) {
                            throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
                        }
                        audit(ticketId, "REPLIED", null, null);
                        return ticketMapper.findById(ticketId);
                    });
                    return ResponseEntity.ok(new TicketStateResponse(after.getTicketId(),
                            after.getState().name(), after.getVersion()));
                });
    }

    public ResponseEntity<?> close(String ticketId, CloseRequest request) {
        requireTicket(ticketId);
        return idempotency.execute("agent", "POST /api/agent/close", ticketId, request.requestId(),
                idempotency.hash(request), () -> {
                    Ticket ticket = requireTicket(ticketId);
                    if (!CLOSABLE.contains(ticket.getState())) {
                        throw new ApiException(ErrorCode.STATE_NOT_ALLOWED, "当前状态不允许关闭");
                    }
                    if (ticket.getVersion() != request.expectedVersion()) {
                        throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
                    }
                    Ticket after = tx.execute(status -> {
                        int rows = ticketMapper.transition(ticketId, ticket.getVersion(),
                                Set.of(ticket.getState().name()), TicketState.CLOSED,
                                null, false, false, null, null, true, TimeUtil.now());
                        if (rows != 1) {
                            throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
                        }
                        audit(ticketId, "CLOSED", null, null);
                        return ticketMapper.findById(ticketId);
                    });
                    return ResponseEntity.ok(new TicketStateResponse(after.getTicketId(),
                            after.getState().name(), after.getVersion()));
                });
    }

    private Ticket requireTicket(String ticketId) {
        Ticket ticket = ticketMapper.findById(ticketId);
        if (ticket == null) {
            throw new ApiException(ErrorCode.TICKET_NOT_FOUND, "工单不存在");
        }
        return ticket;
    }

    private void move(Ticket ticket, TicketState from, TicketState to,
                      com.chinayiru.aftersale.domain.TransferReason reason,
                      boolean epochIncrement, boolean closed) {
        int rows = ticketMapper.transition(ticket.getTicketId(), ticket.getVersion(),
                Set.of(from.name()), to, reason, false, epochIncrement, null, null, closed, TimeUtil.now());
        if (rows != 1) {
            throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
        }
    }

    private void addMessage(String ticketId, MessageRole role, String text) {
        TicketMessage message = new TicketMessage();
        message.setTicketId(ticketId);
        message.setRole(role);
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

    private String lastCustomerText(String ticketId) {
        List<TicketMessage> messages = messageMapper.listByTicket(ticketId);
        for (int i = messages.size() - 1; i >= 0; i--) {
            if (messages.get(i).getRole() == MessageRole.CUSTOMER) {
                return messages.get(i).getText();
            }
        }
        return "请重新生成处理建议。";
    }

    private static boolean containsInternalCode(String text) {
        String upper = text.toUpperCase(Locale.ROOT);
        String[] tokens = {"OPEN", "PENDING_ACCEPT", "AI_RUNNING", "WAITING_INPUT", "DRAFT_READY",
                "CONFIRMED", "EXECUTING", "REPLIED", "TRANSFERRED", "CLOSED", "CANCELLED",
                "TASKEPOCH", "GENERATIONTASKID", "POLICYCHECK", "DRAFTVERSION", "NEEDHUMANREVIEW"};
        for (String token : tokens) {
            if (upper.contains(token)) {
                return true;
            }
        }
        return false;
    }

    private static int editDistance(String left, String right) {
        if (left == null) {
            left = "";
        }
        if (right == null) {
            right = "";
        }
        int[] previous = new int[right.length() + 1];
        int[] current = new int[right.length() + 1];
        for (int j = 0; j <= right.length(); j++) {
            previous[j] = j;
        }
        for (int i = 1; i <= left.length(); i++) {
            current[0] = i;
            for (int j = 1; j <= right.length(); j++) {
                int cost = left.charAt(i - 1) == right.charAt(j - 1) ? 0 : 1;
                current[j] = Math.min(Math.min(current[j - 1] + 1, previous[j] + 1), previous[j - 1] + cost);
            }
            int[] swap = previous;
            previous = current;
            current = swap;
        }
        return previous[right.length()];
    }
}
