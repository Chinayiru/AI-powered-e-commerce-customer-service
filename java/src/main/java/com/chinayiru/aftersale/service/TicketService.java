package com.chinayiru.aftersale.service;

import com.chinayiru.aftersale.api.dto.ApiDtos.AddMessageRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.CancelRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.CancelResult;
import com.chinayiru.aftersale.api.dto.ApiDtos.ConsumerTicketView;
import com.chinayiru.aftersale.api.dto.ApiDtos.CreateTicketRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.MessageResult;
import com.chinayiru.aftersale.api.dto.ApiDtos.OrderSummary;
import com.chinayiru.aftersale.api.dto.ApiDtos.TicketCreated;
import com.chinayiru.aftersale.auth.TicketTokenService;
import com.chinayiru.aftersale.common.ApiException;
import com.chinayiru.aftersale.common.ErrorCode;
import com.chinayiru.aftersale.common.TimeUtil;
import com.chinayiru.aftersale.common.TraceFilter;
import com.chinayiru.aftersale.config.AppProperties;
import com.chinayiru.aftersale.domain.AuditLog;
import com.chinayiru.aftersale.domain.Category;
import com.chinayiru.aftersale.domain.Draft;
import com.chinayiru.aftersale.domain.MessageRole;
import com.chinayiru.aftersale.domain.Ticket;
import com.chinayiru.aftersale.domain.TicketMessage;
import com.chinayiru.aftersale.domain.TicketState;
import com.chinayiru.aftersale.mapper.AuditMapper;
import com.chinayiru.aftersale.mapper.DraftMapper;
import com.chinayiru.aftersale.mapper.MessageMapper;
import com.chinayiru.aftersale.mapper.TicketMapper;
import com.chinayiru.aftersale.tool.OrderModels.Order;
import com.chinayiru.aftersale.tool.OrderToolService;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/**
 * 消费者侧用例：建单、追加消息、查询、撤销、我的订单。
 * 写接口全部先过幂等，再进业务；业务 4xx 会作为首次结果被幂等记录重放。
 */
@Service
public class TicketService {

    private final TicketMapper ticketMapper;
    private final MessageMapper messageMapper;
    private final DraftMapper draftMapper;
    private final AuditMapper auditMapper;
    private final TicketIdGenerator idGenerator;
    private final TicketTokenService ticketTokens;
    private final TicketViewMapper viewMapper;
    private final GenerationService generationService;
    private final OrderToolService orderTools;
    private final IdempotencyService idempotency;
    private final TransactionTemplate tx;
    private final AppProperties properties;

    public TicketService(TicketMapper ticketMapper, MessageMapper messageMapper, DraftMapper draftMapper,
                         AuditMapper auditMapper, TicketIdGenerator idGenerator, TicketTokenService ticketTokens,
                         TicketViewMapper viewMapper, GenerationService generationService,
                         OrderToolService orderTools, IdempotencyService idempotency,
                         TransactionTemplate tx, AppProperties properties) {
        this.ticketMapper = ticketMapper;
        this.messageMapper = messageMapper;
        this.draftMapper = draftMapper;
        this.auditMapper = auditMapper;
        this.idGenerator = idGenerator;
        this.ticketTokens = ticketTokens;
        this.viewMapper = viewMapper;
        this.generationService = generationService;
        this.orderTools = orderTools;
        this.idempotency = idempotency;
        this.tx = tx;
        this.properties = properties;
    }

    public ResponseEntity<?> create(CreateTicketRequest request, String userId) {
        String orderNo = blankToNull(request.orderNo());
        String targetId = orderNo == null ? "NOORDER" : orderNo;
        return idempotency.execute(userId, "POST /api/tickets", targetId, request.requestId(),
                idempotency.hash(request), () -> doCreate(request, userId, orderNo));
    }

    private ResponseEntity<?> doCreate(CreateTicketRequest request, String userId, String orderNo) {
        if (orderNo != null) {
            orderTools.requireOwned(userId, orderNo);
        }
        if (request.category() == Category.AFTERSALE && orderNo != null) {
            Ticket active = ticketMapper.findByActiveOrderKey(userId + ":" + orderNo);
            if (active != null) {
                throw new ApiException(ErrorCode.DUPLICATE_REQUEST, "该订单已有未结束的售后单");
            }
        }

        Ticket ticket = tx.execute(status -> {
            LocalDateTime now = TimeUtil.now();
            Ticket value = new Ticket();
            value.setTicketId(idGenerator.next(now));
            value.setCategory(request.category());
            value.setUserId(userId);
            value.setOrderNo(orderNo);
            value.setState(request.category() == Category.CONSULT ? TicketState.OPEN : TicketState.PENDING_ACCEPT);
            value.setVersion(1);
            value.setTaskEpoch(1);
            value.setCurrentAttempt(0);
            value.setStalledRounds(0);
            value.setExecutionMode(com.chinayiru.aftersale.domain.ExecutionMode.valueOf(
                    properties.getExecution().getMode()));
            value.setCreatedAt(now);
            value.setUpdatedAt(now);
            try {
                ticketMapper.insert(value);
            } catch (DuplicateKeyException ex) {
                throw new ApiException(ErrorCode.DUPLICATE_REQUEST, "该订单已有未结束的售后单");
            }

            addMessage(value.getTicketId(), MessageRole.CUSTOMER, request.text());
            if (request.category() == Category.CONSULT) {
                move(value, TicketState.OPEN, TicketState.AI_RUNNING, null, false, null);
                String taskId = UUID.randomUUID().toString();
                ticketMapper.updateGeneration(value.getTicketId(), taskId, 1, TimeUtil.now());
                audit(value.getTicketId(), "CREATED", "category=CONSULT", null);
            } else if (orderNo != null) {
                move(value, TicketState.PENDING_ACCEPT, TicketState.AI_RUNNING, null, false, null);
                String taskId = UUID.randomUUID().toString();
                ticketMapper.updateGeneration(value.getTicketId(), taskId, 1, TimeUtil.now());
                audit(value.getTicketId(), "CREATED", "category=AFTERSALE, orderNo=" + orderNo, null);
            } else {
                move(value, TicketState.PENDING_ACCEPT, TicketState.WAITING_INPUT, null, false, 0);
                addMessage(value.getTicketId(), MessageRole.AGENT,
                        "请提供订单号，我帮您核实订单状态和可退金额。");
                audit(value.getTicketId(), "CREATED", "category=AFTERSALE, orderNo=missing", null);
            }
            return ticketMapper.findById(value.getTicketId());
        });

        if (ticket.getState() == TicketState.AI_RUNNING) {
            String message = request.text();
            ticket = generationService.generate(ticket.getTicketId(), message, request.requestId(), null)
                    .ticket();
        }
        TicketCreated created = viewMapper.ticketCreated(ticket,
                ticketTokens.issue(ticket.getTicketId(), userId));
        return ResponseEntity.status(201).body(created);
    }

    public ResponseEntity<?> addMessage(String ticketId, String userId, AddMessageRequest request) {
        Ticket ticket = requireOwned(ticketId, userId);
        return idempotency.execute(userId, "POST /api/tickets/messages", ticketId, request.requestId(),
                idempotency.hash(request), () -> doAddMessage(ticketId, userId, request));
    }

    private ResponseEntity<?> doAddMessage(String ticketId, String userId, AddMessageRequest request) {
        Ticket before = requireOwned(ticketId, userId);
        if (!TicketState.CUSTOMER_MESSAGEABLE.contains(before.getState())) {
            throw new ApiException(ErrorCode.STATE_NOT_ALLOWED, "当前状态不允许继续发送消息");
        }

        if (before.getState() == TicketState.TRANSFERRED) {
            Ticket after = tx.execute(status -> {
                addMessage(ticketId, MessageRole.CUSTOMER, request.text());
                move(before, TicketState.TRANSFERRED, TicketState.TRANSFERRED, null, true, null);
                audit(ticketId, "CUSTOMER_MESSAGE_AFTER_TRANSFER", null, null);
                return ticketMapper.findById(ticketId);
            });
            return ResponseEntity.ok(new MessageResult(
                    com.chinayiru.aftersale.domain.DisplayStates.of(after.getState()), after.getVersion(),
                    viewMapper.consumerMessages(messageMapper.listByTicket(ticketId)), null));
        }

        Ticket running = tx.execute(status -> {
            addMessage(ticketId, MessageRole.CUSTOMER, request.text());
            move(before, before.getState(), TicketState.AI_RUNNING, null, true, null);
            ticketMapper.updateGeneration(ticketId, UUID.randomUUID().toString(), 1, TimeUtil.now());
            audit(ticketId, "CUSTOMER_MESSAGE", null, null);
            return ticketMapper.findById(ticketId);
        });

        GenerationOutcome outcome = generationService.generate(ticketId, request.text(),
                request.requestId(), null);
        Ticket after = outcome.ticket() == null ? ticketMapper.findById(ticketId) : outcome.ticket();
        return ResponseEntity.ok(new MessageResult(
                com.chinayiru.aftersale.domain.DisplayStates.of(after.getState()), after.getVersion(),
                viewMapper.consumerMessages(messageMapper.listByTicket(ticketId)), outcome.createdTicket()));
    }

    public ConsumerTicketView get(String ticketId, String userId) {
        Ticket ticket = requireOwned(ticketId, userId);
        return viewMapper.consumerView(ticket, messageMapper.listByTicket(ticketId));
    }

    public ResponseEntity<?> cancel(String ticketId, String userId, CancelRequest request) {
        requireOwned(ticketId, userId);
        return idempotency.execute(userId, "POST /api/tickets/cancel", ticketId, request.requestId(),
                idempotency.hash(request), () -> doCancel(ticketId, userId, request));
    }

    private ResponseEntity<?> doCancel(String ticketId, String userId, CancelRequest request) {
        Ticket ticket = requireOwned(ticketId, userId);
        if (!TicketState.CANCELABLE.contains(ticket.getState())) {
            throw new ApiException(ErrorCode.STATE_NOT_ALLOWED, "当前状态不允许撤销");
        }
        if (ticket.getVersion() != request.expectedVersion()) {
            throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
        }
        Ticket cancelled = tx.execute(status -> {
            int rows = ticketMapper.transition(ticketId, ticket.getVersion(),
                    Set.of(ticket.getState().name()), TicketState.CANCELLED,
                    null, false, false, null, null, false, TimeUtil.now());
            if (rows != 1) {
                throw new ApiException(ErrorCode.STALE_STATE, "工单已被更新，请刷新后重试");
            }
            draftMapper.supersedeAll(ticketId);
            audit(ticketId, "CANCELLED", null, null);
            return ticketMapper.findById(ticketId);
        });
        return ResponseEntity.ok(new CancelResult(
                com.chinayiru.aftersale.domain.DisplayStates.of(cancelled.getState()), cancelled.getVersion()));
    }

    public List<OrderSummary> orders(String userId) {
        return orderTools.listForUser(userId).stream()
                .map(o -> new OrderSummary(o.orderNo(), OrderToolService.statusLabel(o.status()), o.amountCents()))
                .toList();
    }

    private Ticket requireOwned(String ticketId, String userId) {
        Ticket ticket = ticketMapper.findById(ticketId);
        if (ticket == null) {
            throw new ApiException(ErrorCode.TICKET_NOT_FOUND, "工单不存在");
        }
        if (!ticket.getUserId().equals(userId)) {
            throw new ApiException(ErrorCode.FORBIDDEN_SCOPE, "无权访问该工单");
        }
        return ticket;
    }

    private void move(Ticket ticket, TicketState from, TicketState to, com.chinayiru.aftersale.domain.TransferReason reason,
                      boolean epochIncrement, Integer stalledRounds) {
        int rows = ticketMapper.transition(ticket.getTicketId(), ticket.getVersion(),
                Set.of(from.name()), to, reason, false, epochIncrement, stalledRounds,
                null, false, TimeUtil.now());
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

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }
}
