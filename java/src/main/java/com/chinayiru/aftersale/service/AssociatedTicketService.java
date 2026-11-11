package com.chinayiru.aftersale.service;

import com.chinayiru.aftersale.common.TimeUtil;
import com.chinayiru.aftersale.common.TraceFilter;
import com.chinayiru.aftersale.config.AppProperties;
import com.chinayiru.aftersale.domain.AuditLog;
import com.chinayiru.aftersale.domain.Category;
import com.chinayiru.aftersale.domain.MessageRole;
import com.chinayiru.aftersale.domain.Ticket;
import com.chinayiru.aftersale.domain.TicketMessage;
import com.chinayiru.aftersale.domain.TicketState;
import com.chinayiru.aftersale.mapper.AuditMapper;
import com.chinayiru.aftersale.mapper.MessageMapper;
import com.chinayiru.aftersale.mapper.TicketMapper;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/**
 * 咨询中途要退款时，创建（或复用）关联售后单。
 * 关联单必须复制咨询单最近 6 条客户/坐席消息，原咨询单保持原状态（通常 REPLIED）。
 */
@Service
public class AssociatedTicketService {

    public record Shell(Ticket ticket, boolean created) {
    }

    private final TicketMapper ticketMapper;
    private final MessageMapper messageMapper;
    private final AuditMapper auditMapper;
    private final TicketIdGenerator idGenerator;
    private final AppProperties properties;

    public AssociatedTicketService(TicketMapper ticketMapper, MessageMapper messageMapper,
                                   AuditMapper auditMapper, TicketIdGenerator idGenerator,
                                   AppProperties properties) {
        this.ticketMapper = ticketMapper;
        this.messageMapper = messageMapper;
        this.auditMapper = auditMapper;
        this.idGenerator = idGenerator;
        this.properties = properties;
    }

    @Transactional
    public Shell createShell(Ticket consult, String orderNo, String traceId) {
        String activeKey = consult.getUserId() + ":" + orderNo;
        Ticket existing = ticketMapper.findByActiveOrderKey(activeKey);
        if (existing != null) {
            return new Shell(existing, false);
        }

        LocalDateTime now = TimeUtil.now();
        Ticket ticket = new Ticket();
        ticket.setTicketId(idGenerator.next(now));
        ticket.setCategory(Category.AFTERSALE);
        ticket.setParentConsultTicketId(consult.getTicketId());
        ticket.setUserId(consult.getUserId());
        ticket.setOrderNo(orderNo);
        ticket.setState(TicketState.PENDING_ACCEPT);
        ticket.setVersion(1);
        ticket.setTaskEpoch(1);
        ticket.setCurrentAttempt(0);
        ticket.setStalledRounds(0);
        ticket.setExecutionMode(consult.getExecutionMode());
        ticket.setCreatedAt(now);
        ticket.setUpdatedAt(now);
        try {
            ticketMapper.insert(ticket);
        } catch (DuplicateKeyException ex) {
            Ticket raced = ticketMapper.findByActiveOrderKey(activeKey);
            if (raced != null) {
                return new Shell(raced, false);
            }
            throw ex;
        }

        List<TicketMessage> recent = messageMapper.listRecent(consult.getTicketId(), 6);
        for (TicketMessage source : recent) {
            if (source.getRole() == MessageRole.SYSTEM) {
                continue;
            }
            TicketMessage copy = new TicketMessage();
            copy.setTicketId(ticket.getTicketId());
            copy.setRole(source.getRole());
            copy.setText(source.getText());
            copy.setCreatedAt(now);
            messageMapper.insert(copy);
        }

        String taskId = UUID.randomUUID().toString();
        int moved = ticketMapper.transition(ticket.getTicketId(), ticket.getVersion(),
                Set.of(TicketState.PENDING_ACCEPT.name()), TicketState.AI_RUNNING,
                null, false, false, 0, null, false, now);
        if (moved != 1) {
            throw new IllegalStateException("关联售后单进入 AI_RUNNING 失败");
        }
        ticketMapper.updateGeneration(ticket.getTicketId(), taskId, 1, now);

        AuditLog audit = new AuditLog();
        audit.setTicketId(ticket.getTicketId());
        audit.setAction("ASSOCIATED_TICKET_CREATED");
        audit.setDetail("parentConsultTicketId=" + consult.getTicketId() + ", orderNo=" + orderNo);
        audit.setTraceId(traceId == null ? TraceFilter.currentTraceId() : traceId);
        audit.setCreatedAt(now);
        auditMapper.insert(audit);

        return new Shell(ticketMapper.findById(ticket.getTicketId()), true);
    }
}
