package com.chinayiru.aftersale.policy;

import com.chinayiru.aftersale.config.AppProperties;
import com.chinayiru.aftersale.tool.OrderModels.Order;
import com.chinayiru.aftersale.tool.OrderToolService;
import org.springframework.stereotype.Service;

/**
 * 退款政策规则引擎。所有“能不能退/能退多少”的判断都在这里，Python 只给建议。
 *
 * 规则（BOUNDARY §7.3 / DATA_DICTIONARY）：
 * - 仅整单退款建议；已发生部分退款、重复退款、金额为 0 一律拒绝；
 * - 未发货可“仅退款”；已发货/已签收可“退货退款”；
 * - 七天无理由自签收次日起算，超窗口允许生成草稿但 allowed=false，send 必须拒绝；
 * - 硬上限 = 订单 refundableAmountCents，不是配置项。
 */
@Service
public class PolicyService {

    private final AppProperties properties;

    public PolicyService(AppProperties properties) {
        this.properties = properties;
    }

    public PolicyDecision evaluate(Order order, Long requestedAmountCents) {
        String version = properties.getPolicy().getVersion();
        if (order == null) {
            return PolicyDecision.denied("ORDER_NOT_FOUND", version, "3.1", "未查询到订单，无法判断退款资格。");
        }
        if (OrderToolService.CLOSED.equals(order.status())) {
            return PolicyDecision.denied("ORDER_CLOSED", version, "3.3", "订单已关闭，通常不支持退款，需人工核实。");
        }
        if (order.refundedAmountCents() > 0) {
            return PolicyDecision.denied("ALREADY_REFUNDED", version, "3.3",
                    "该订单已有退款记录，部分/重复退款需人工核实。");
        }
        if (order.refundableAmountCents() <= 0) {
            return PolicyDecision.denied("NOT_REFUNDABLE", version, "3.3",
                    "该订单当前可退金额为 0，需人工核实。");
        }
        if (requestedAmountCents != null && requestedAmountCents == 0) {
            return PolicyDecision.denied("ZERO_AMOUNT", version, "3.1", "退款金额不能为 0。");
        }
        if (requestedAmountCents != null && requestedAmountCents > order.refundableAmountCents()) {
            return PolicyDecision.denied("AMOUNT_EXCEEDS_MAX", version, "3.1",
                    "建议金额超过订单可退上限。");
        }
        if (requestedAmountCents != null && requestedAmountCents < order.refundableAmountCents()) {
            return PolicyDecision.denied("PARTIAL_REFUND_NOT_SUPPORTED", version, "3.3",
                    "当前仅支持整单退款建议，部分退款需转人工。");
        }
        if (OrderToolService.DELIVERED.equals(order.status())) {
            long days = PolicyDecision.daysSinceDelivery(order.deliveredAt());
            if (days > 7) {
                return PolicyDecision.denied("OUTSIDE_RETURN_WINDOW", version, "3.2",
                        "已超出七天无理由窗口，需人工按政策核实。");
            }
            return PolicyDecision.allowed(order.refundableAmountCents(), version,
                    "REFUND_WITHIN_WINDOW", "3.2");
        }
        if (OrderToolService.SHIPPED.equals(order.status())) {
            return PolicyDecision.allowed(order.refundableAmountCents(), version,
                    "REFUND_RETURN_REQUIRED", "3.1");
        }
        if (OrderToolService.PAID.equals(order.status())) {
            return PolicyDecision.allowed(order.refundableAmountCents(), version,
                    "REFUND_ONLY_BEFORE_SHIP", "3.1");
        }
        return PolicyDecision.denied("ORDER_STATUS_UNSUPPORTED", version, "3.1",
                "订单状态不支持自动给出退款建议，需人工核实。");
    }
}
