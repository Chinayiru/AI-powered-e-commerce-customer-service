package com.chinayiru.aftersale.policy;

import com.chinayiru.aftersale.config.AppProperties;
import com.chinayiru.aftersale.tool.OrderModels.Order;
import com.chinayiru.aftersale.tool.OrderToolService;
import org.junit.jupiter.api.Test;

import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 政策引擎的边界用例：金额缺失、签收时间缺失/超窗、金额上限。
 * 这些判断必须在 Java 侧完成，Python 只提供建议金额。
 */
class PolicyServiceTest {

    private static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");
    private final PolicyService service = new PolicyService(new AppProperties());

    @Test
    void deliveredOrderWithoutDeliveryTimeIsNotTreatedAsDayZero() {
        PolicyDecision decision = service.evaluate(order(OrderToolService.DELIVERED, 5800, null), 5800L);

        assertThat(decision.allowed()).isFalse();
        assertThat(decision.code()).isEqualTo("ORDER_TIME_UNKNOWN");
    }

    @Test
    void refundRequestWithoutAmountIsRejected() {
        PolicyDecision decision = service.evaluate(order(OrderToolService.PAID, 5800, null), null);

        assertThat(decision.allowed()).isFalse();
        assertThat(decision.code()).isEqualTo("AMOUNT_MISSING");
    }

    @Test
    void eligibilityQuestionWithoutAmountCanStillBeEvaluated() {
        PolicyDecision decision = service.evaluate(order(OrderToolService.PAID, 5800, null), null, false);

        assertThat(decision.allowed()).isTrue();
        assertThat(decision.code()).isEqualTo("REFUND_ONLY_BEFORE_SHIP");
    }

    @Test
    void exactRefundableAmountIsAllowed() {
        PolicyDecision decision = service.evaluate(order(OrderToolService.PAID, 5800, null), 5800L);

        assertThat(decision.allowed()).isTrue();
        assertThat(decision.maxRefundableCents()).isEqualTo(5800L);
    }

    @Test
    void amountAboveRefundableLimitIsRejected() {
        PolicyDecision decision = service.evaluate(order(OrderToolService.PAID, 5800, null), 5801L);

        assertThat(decision.allowed()).isFalse();
        assertThat(decision.code()).isEqualTo("AMOUNT_EXCEEDS_MAX");
    }

    @Test
    void deliveredTenDaysAgoIsOutsideReturnWindow() {
        PolicyDecision decision = service.evaluate(
                order(OrderToolService.DELIVERED, 5800, OffsetDateTime.now(ZONE).minusDays(10)), 5800L);

        assertThat(decision.allowed()).isFalse();
        assertThat(decision.code()).isEqualTo("OUTSIDE_RETURN_WINDOW");
    }

    @Test
    void nullDeliveryTimeHasNoDayCount() {
        assertThat(PolicyDecision.daysSinceDelivery(null)).isNull();
    }

    private static Order order(String status, long refundableCents, OffsetDateTime deliveredAt) {
        return new Order("O1001", "U001", status, refundableCents, refundableCents, 0,
                OffsetDateTime.now(ZONE).minusDays(1), deliveredAt, List.of());
    }
}
