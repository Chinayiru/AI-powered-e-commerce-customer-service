package com.chinayiru.aftersale.service;

import com.chinayiru.aftersale.api.dto.ApiDtos.AgentTicketView;
import com.chinayiru.aftersale.api.dto.ApiDtos.ChatMessage;
import com.chinayiru.aftersale.api.dto.ApiDtos.CitationView;
import com.chinayiru.aftersale.api.dto.ApiDtos.ConsumerMessage;
import com.chinayiru.aftersale.api.dto.ApiDtos.ConsumerTicketView;
import com.chinayiru.aftersale.api.dto.ApiDtos.DraftView;
import com.chinayiru.aftersale.api.dto.ApiDtos.PolicyCheckView;
import com.chinayiru.aftersale.api.dto.ApiDtos.SuggestedAction;
import com.chinayiru.aftersale.api.dto.ApiDtos.TicketCreated;
import com.chinayiru.aftersale.api.dto.ApiDtos.TicketMeta;
import com.chinayiru.aftersale.api.dto.ApiDtos.ToolCallView;
import com.chinayiru.aftersale.common.JsonCodec;
import com.chinayiru.aftersale.common.TimeUtil;
import com.chinayiru.aftersale.domain.Draft;
import com.chinayiru.aftersale.domain.DisplayStates;
import com.chinayiru.aftersale.domain.MessageRole;
import com.chinayiru.aftersale.domain.Ticket;
import com.chinayiru.aftersale.domain.TicketMessage;
import com.chinayiru.aftersale.domain.ToolCall;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.List;

/**
 * 同一份实体到三种视图的映射：消费者（白名单）、坐席（全量）、创建结果。
 */
@Component
public class TicketViewMapper {

    private final JsonCodec json;

    public TicketViewMapper(JsonCodec json) {
        this.json = json;
    }

    public TicketCreated ticketCreated(Ticket ticket, String token) {
        return new TicketCreated(ticket.getTicketId(), token, DisplayStates.of(ticket.getState()),
                ticket.getVersion(), ticket.getCategory(), TimeUtil.offset(ticket.getCreatedAt()),
                ticket.getExecutionMode().name());
    }

    public ConsumerTicketView consumerView(Ticket ticket, List<TicketMessage> messages) {
        List<ConsumerMessage> visible = consumerMessages(messages);
        String reply = null;
        for (int i = visible.size() - 1; i >= 0; i--) {
            if (visible.get(i).role() == MessageRole.AGENT) {
                reply = visible.get(i).text();
                break;
            }
        }
        return new ConsumerTicketView(ticket.getTicketId(), DisplayStates.of(ticket.getState()),
                ticket.getVersion(), reply, visible, TimeUtil.offset(ticket.getUpdatedAt()));
    }

    public List<ConsumerMessage> consumerMessages(List<TicketMessage> messages) {
        return messages.stream()
                .filter(m -> m.getRole() == MessageRole.CUSTOMER || m.getRole() == MessageRole.AGENT)
                .map(m -> new ConsumerMessage(String.valueOf(m.getMessageId()), m.getRole(), m.getText(),
                        TimeUtil.offset(m.getCreatedAt())))
                .toList();
    }

    public List<ChatMessage> chatMessages(List<TicketMessage> messages) {
        return messages.stream()
                .map(m -> new ChatMessage(String.valueOf(m.getMessageId()), m.getRole(), m.getText(),
                        TimeUtil.offset(m.getCreatedAt())))
                .toList();
    }

    public AgentTicketView agentView(Ticket ticket, List<TicketMessage> messages,
                                     Draft draft, List<ToolCall> toolCalls) {
        TicketMeta meta = new TicketMeta(ticket.getTicketId(), ticket.getCategory(), ticket.getState().name(),
                ticket.getVersion(), ticket.getOrderNo(),
                ticket.getTransferReason() == null ? null : ticket.getTransferReason().name(),
                ticket.getExecutionMode().name(), TimeUtil.offset(ticket.getCreatedAt()));
        DraftView draftView = draft == null ? null : draftView(draft);
        PolicyCheckView policy = draft == null ? null : policyView(draft);
        return new AgentTicketView(meta, chatMessages(messages),
                draft == null || draft.getIntent() == null ? null : draft.getIntent().name(),
                draft == null || draft.getConfidence() == null ? null : draft.getConfidence().doubleValue(),
                draft != null && draft.isNeedHumanReview(),
                draftView, policy,
                toolCalls.stream().map(this::toolCallView).toList());
    }

    public DraftView draftView(Draft draft) {
        SuggestedAction action = json.read(draft.getSuggestedActionJson(), SuggestedAction.class);
        List<CitationView> citations = List.of();
        if (draft.getCitationsJson() != null) {
            CitationView[] values = json.read(draft.getCitationsJson(), CitationView[].class);
            if (values != null) {
                citations = Arrays.asList(values);
            }
        }
        return new DraftView(draft.getDraftId(), draft.getDraftVersion(), draft.getGenerationTaskId(),
                action, draft.getReplyDraft(), citations,
                draft.getConfidence() == null ? null : draft.getConfidence().doubleValue(),
                draft.getReplyType() == null ? null : draft.getReplyType().name(), draft.isSuperseded());
    }

    public PolicyCheckView policyView(Draft draft) {
        return json.read(draft.getPolicyCheckJson(), PolicyCheckView.class);
    }

    private ToolCallView toolCallView(ToolCall call) {
        return new ToolCallView(call.getStep(), call.getName(), call.isOk(),
                (long) call.getLatencyMs(), call.getErrorCode(), call.getSummary());
    }
}
