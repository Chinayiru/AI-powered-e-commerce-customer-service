package com.chinayiru.aftersale.tool;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * /internal/tools/* 的响应模型，字段名与 OpenAPI 保持一致。
 */
public final class OrderModels {

    private OrderModels() {
    }

    public record Order(
            String orderNo,
            String userId,
            String status,
            long amountCents,
            long refundableAmountCents,
            long refundedAmountCents,
            OffsetDateTime paidAt,
            OffsetDateTime deliveredAt,
            List<Item> items) {
    }

    public record Item(String skuId, String title, int qty, long unitAmountCents) {
    }

    public record Shipment(
            String orderNo,
            String status,
            List<PackageInfo> shipments) {
    }

    public record PackageInfo(
            String carrierCode,
            String trackingNo,
            String status,
            List<Event> events) {
    }

    public record Event(OffsetDateTime at, String code, String text) {
    }
}
