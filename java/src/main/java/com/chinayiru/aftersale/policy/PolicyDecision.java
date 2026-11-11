package com.chinayiru.aftersale.policy;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;

/**
 * Java 规则引擎给出的政策结论。Python 不参与、也看不到这个对象。
 */
public record PolicyDecision(
        boolean allowed,
        String code,
        String policyVersion,
        String clauseId,
        Long maxRefundableCents,
        boolean needHumanConfirm,
        String explanation) {

    private static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");

    public static PolicyDecision allowed(long maxRefundable, String policyVersion, String code, String clauseId) {
        return new PolicyDecision(true, code, policyVersion, clauseId, maxRefundable, true,
                "允许生成退款建议，仍需人工确认");
    }

    public static PolicyDecision denied(String code, String policyVersion, String clauseId, String explanation) {
        return new PolicyDecision(false, code, policyVersion, clauseId, null, true, explanation);
    }

    public static long daysSinceDelivery(OffsetDateTime deliveredAt) {
        if (deliveredAt == null) {
            return 0;
        }
        LocalDate delivered = deliveredAt.atZoneSameInstant(ZONE).toLocalDate();
        return Math.max(0, ChronoUnit.DAYS.between(delivered, LocalDate.now(ZONE)));
    }
}
