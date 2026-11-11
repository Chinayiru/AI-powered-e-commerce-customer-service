package com.chinayiru.aftersale.agent;

import com.chinayiru.aftersale.agent.AgentContract.AskResponse;
import com.chinayiru.aftersale.common.ErrorCode;
import com.chinayiru.aftersale.domain.ActionType;

import java.util.List;

/**
 * 对 Python 返回值做契约级校验。无效响应不能进入状态机，按 AI 不可用降级。
 */
public final class AgentResponseValidator {

    private AgentResponseValidator() {
    }

    public static void validate(AskResponse response) {
        if (response == null) {
            throw unavailable("AI 返回为空");
        }
        if (response.intent() == null || response.replyType() == null) {
            throw unavailable("AI 返回缺少 intent/replyType");
        }
        if (response.model() == null || isBlank(response.model().provider())
                || isBlank(response.model().promptVersion())) {
            throw unavailable("AI 返回缺少 model");
        }
        if (!Double.isFinite(response.confidence())
                || response.confidence() < 0.0 || response.confidence() > 1.0) {
            throw unavailable("AI 返回 confidence 越界");
        }
        if (response.replyDraft() != null && response.replyDraft().length() > 200) {
            throw unavailable("AI 返回 replyDraft 超过 200 字");
        }
        if (response.intent() == com.chinayiru.aftersale.domain.IntentType.HANDOFF
                && response.transferReason() == null) {
            throw unavailable("AI 返回 HANDOFF 但缺少 transferReason");
        }
        AgentContract.SuggestedAction action = response.suggestedAction();
        if (action != null) {
            if (action.action() == null) {
                throw unavailable("AI 返回 suggestedAction 缺少 action");
            }
            if (action.action() == ActionType.REFUND
                    && (action.amountCents() == null || action.amountCents() <= 0)) {
                throw unavailable("AI 返回 REFUND 但金额不合法");
            }
        }
        List<AgentContract.Citation> citations = response.citations();
        if (citations != null) {
            for (AgentContract.Citation citation : citations) {
                if (citation == null || isBlank(citation.docId()) || isBlank(citation.title())
                        || isBlank(citation.policyVersion())) {
                    throw unavailable("AI 返回 citation 不完整");
                }
            }
        }
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private static AgentUnavailableException unavailable(String message) {
        return new AgentUnavailableException(ErrorCode.AGENT_UNAVAILABLE, message);
    }
}
