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

    /**
     * 返回签收至今天数；缺少签收时间时返回 {@code null}，由调用方按“时间未知”拒绝，
     * 不能把未知当成第 0 天，否则会绕过七天无理由窗口。
     */
    public static Long daysSinceDelivery(OffsetDateTime deliveredAt) {
        if (deliveredAt == null) {
            return null;
        }
        LocalDate delivered = deliveredAt.atZoneSameInstant(ZONE).toLocalDate();
        return Math.max(0, ChronoUnit.DAYS.between(delivered, LocalDate.now(ZONE)));
    }
}
