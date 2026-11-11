package com.chinayiru.aftersale.api.dto;

import com.chinayiru.aftersale.domain.Category;
import com.chinayiru.aftersale.domain.MessageRole;
import com.chinayiru.aftersale.domain.TransferReason;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.time.OffsetDateTime;
import java.util.List;

public final class ApiDtos {

    private ApiDtos() {
    }

    // ---------- 消费者 ----------

    public record CreateTicketRequest(
            @NotNull Category category,
            @NotBlank @Size(max = 500) String text,
            String orderNo,
            @NotBlank String requestId) {
    }

    public record AddMessageRequest(
            @NotBlank @Size(max = 500) String text,
            @NotBlank String requestId) {
    }

    public record CancelRequest(
            @NotBlank String requestId,
            @Min(1) int expectedVersion) {
    }

    public record TicketCreated(
            String ticketId,
            String ticketToken,
            String displayState,
            int version,
            Category category,
            OffsetDateTime createdAt,
            String executionMode) {
    }

    public record ConsumerMessage(String id, MessageRole role, String text, OffsetDateTime createdAt) {
    }

    public record ConsumerTicketView(
            String ticketId,
            String displayState,
            int version,
            String reply,
            List<ConsumerMessage> messages,
            OffsetDateTime updatedAt) {
    }

    public record MessageResult(
            String displayState,
            int version,
            List<ConsumerMessage> messages,
            TicketCreated createdTicket) {
    }

    public record CancelResult(String displayState, int version) {
    }

    public record OrderSummary(String orderNo, String statusLabel, long amountCents) {
    }

    // ---------- 坐席 ----------

    public record AgentTicketView(
            TicketMeta ticket,
            List<ChatMessage> messages,
            String intent,
            Double confidence,
            boolean needHumanReview,
            DraftView draft,
            PolicyCheckView policyCheck,
            List<ToolCallView> toolCalls) {
    }

    public record TicketMeta(
            String ticketId,
            Category category,
            String state,
            int version,
            String orderNo,
            String transferReason,
            String executionMode,
            OffsetDateTime createdAt) {
    }

    public record ChatMessage(String id, MessageRole role, String text, OffsetDateTime createdAt) {
    }

    public record DraftView(
            String draftId,
            int draftVersion,
            String generationTaskId,
            SuggestedAction suggestedAction,
            String replyDraft,
            List<CitationView> citations,
            Double confidence,
            String replyType,
            boolean superseded) {
    }

    public record SuggestedAction(String action, Long amountCents, Boolean needHumanConfirm) {
    }

    public record CitationView(String docId, String title, String clauseId, String policyVersion) {
    }

    public record PolicyCheckView(
            boolean allowed,
            String code,
            String policyVersion,
            String clauseId,
            Long maxRefundableCents,
            boolean needHumanConfirm) {
    }

    public record ToolCallView(int step, String name, boolean ok, Long latencyMs,
                               String errorCode, String summary) {
    }

    public record SendRequest(
            @NotBlank @Size(max = 500) String text,
            @Min(1) int draftVersion,
            @Size(min = 5, max = 500) String reviewNote,
            int expectedVersion,
            @NotBlank String requestId) {
    }

    public record RegenerateRequest(String note, int expectedVersion, @NotBlank String requestId) {
    }

    public record HandoffRequest(
            @NotNull TransferReason reason,
            int expectedVersion,
            @NotBlank String requestId) {
    }

    public record ReplyRequest(
            @NotBlank @Size(max = 500) String text,
            int expectedVersion,
            @NotBlank String requestId) {
    }

    public record CloseRequest(int expectedVersion, @NotBlank String requestId) {
    }

    public record TicketStateResponse(String ticketId, String state, int version) {
    }

    public record SendResult(String state, boolean edited, int editDistance, int draftVersion) {
    }

    // ---------- 内部工具 ----------

    public record OrderQueryRequest(String orderNo) {
    }

    public record LogisticsQueryRequest(String orderNo) {
    }
}
