package com.chinayiru.aftersale.agent;

import com.chinayiru.aftersale.domain.ActionType;
import com.chinayiru.aftersale.domain.IntentType;
import com.chinayiru.aftersale.domain.ReplyType;
import com.chinayiru.aftersale.domain.TransferReason;

import java.util.List;

/**
 * Java ↔ Python 的内部契约（/internal/agent/ask）。字段与 OpenAPI v1.5.1 一致，
 * 不在此结构中携带 policyCheck：政策结论必须由 Java 规则引擎给出。
 */
public final class AgentContract {

    private AgentContract() {
    }

    public record AskRequest(
            String traceId,
            String ticketId,
            String requestId,
            int attempt,
            int taskEpoch,
            String userId,
            String category,
            String message,
            Context context) {
    }

    public record Context(String orderNo, String summary, List<History> history) {
    }

    public record History(String role, String text, String createdAt) {
    }

    public record AskResponse(
            IntentType intent,
            Slots slots,
            double confidence,
            ReplyType replyType,
            boolean needHumanReview,
            TransferReason transferReason,
            SuggestedAction suggestedAction,
            String replyDraft,
            List<Citation> citations,
            boolean degraded,
            Model model) {
    }

    public record Slots(String orderNo, List<String> missing) {
    }

    public record SuggestedAction(ActionType action, Long amountCents, Boolean needHumanConfirm) {
    }

    public record Citation(String docId, String title, String clauseId, String policyVersion) {
    }

    public record Model(String provider, String promptVersion) {
    }
}
