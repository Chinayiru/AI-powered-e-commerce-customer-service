package com.chinayiru.aftersale.tool;

import com.chinayiru.aftersale.common.ApiException;
import com.chinayiru.aftersale.common.ErrorCode;
import com.chinayiru.aftersale.tool.OrderModels.Event;
import com.chinayiru.aftersale.tool.OrderModels.Item;
import com.chinayiru.aftersale.tool.OrderModels.Order;
import com.chinayiru.aftersale.tool.OrderModels.PackageInfo;
import com.chinayiru.aftersale.tool.OrderModels.Shipment;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Mock 订单/物流工具。Java 是事实层：Python 只能通过 /internal/tools/* 读取，
 * 由本服务按 userId 做归属过滤；越权一律 404 ORDER_NOT_FOUND。
 *
 * 夹具覆盖演示所需的正常与脏数据（金额上限、退款窗口、已退款、多包裹异常）。
 */
@Service
public class OrderToolService {

    public static final String PAID = "PAID";
    public static final String SHIPPED = "SHIPPED";
    public static final String DELIVERED = "DELIVERED";
    public static final String CLOSED = "CLOSED";

    private static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");
    private final Map<String, Order> orders = new LinkedHashMap<>();
    private final Map<String, Shipment> shipments = new LinkedHashMap<>();
    private final OffsetDateTime now;

    public OrderToolService() {
        this.now = OffsetDateTime.now(ZONE).truncatedTo(ChronoUnit.SECONDS);
        OffsetDateTime paidAt = now.minusDays(10);
        OffsetDateTime paidAt5 = now.minusDays(5);
        OffsetDateTime deliveredOld = now.minusDays(30);
        OffsetDateTime deliveredFresh = now.minusDays(1);

        order("O1001", "U001", PAID, 5800, 5800, 0, paidAt, null,
                List.of(item("SKU-1", "静音落地扇", 1, 5800)));
        order("O1002", "U001", SHIPPED, 12900, 12900, 0, paidAt5, null,
                List.of(item("SKU-2", "空气炸锅", 1, 12900)));
        order("O1003", "U001", DELIVERED, 8800, 8800, 0, now.minusDays(40), deliveredOld,
                List.of(item("SKU-3", "护眼台灯", 1, 8800)));
        order("O1004", "U002", SHIPPED, 9900, 9900, 0, paidAt5, null,
                List.of(item("SKU-4", "保温杯", 1, 9900)));
        order("O1005", "U001", PAID, 3000, 3000, 0, now.minusDays(3), null,
                List.of(item("SKU-5", "数据线", 2, 1500)));
        order("O1006", "U001", PAID, 25000, 25000, 0, now.minusDays(2), null,
                List.of(item("SKU-6", "蓝牙耳机", 1, 25000)));
        order("O1007", "U001", DELIVERED, 6600, 6600, 0, now.minusDays(8), deliveredFresh,
                List.of(item("SKU-7", "键盘", 1, 6600)));
        order("O1008", "U001", SHIPPED, 4000, 4000, 0, now.minusDays(4), null,
                List.of(item("SKU-8", "鼠标", 1, 4000)));
        // 脏数据：0 元订单
        order("O1009", "U001", PAID, 0, 0, 0, now.minusDays(6), null, List.of());
        // 脏数据：已全额退款
        order("O1010", "U001", DELIVERED, 5000, 0, 5000, now.minusDays(12),
                now.minusDays(5), List.of(item("SKU-10", "电水壶", 1, 5000)));
        // 脏数据：两个包裹，其中一个异常
        order("O1011", "U001", SHIPPED, 7200, 7200, 0, paidAt5, null,
                List.of(item("SKU-11", "组合装", 1, 7200)));
        // 已关闭订单
        order("O1012", "U001", CLOSED, 4500, 0, 0, now.minusDays(20), now.minusDays(15),
                List.of(item("SKU-12", "收纳盒", 1, 4500)));

        shipment("O1001", "NOT_SHIPPED", List.of());
        shipment("O1002", "IN_TRANSIT", List.of(pkg("SF", "SF1002", "IN_TRANSIT",
                List.of(event(now.minusDays(2), "PICKED_UP", "已揽收"),
                        event(now.minusDays(1), "ARRIVED_HUB", "到达分拨中心")))));
        shipment("O1003", "DELIVERED", List.of(pkg("YTO", "YT1003", "DELIVERED",
                List.of(event(deliveredOld.minusDays(1), "PICKED_UP", "已揽收"),
                        event(deliveredOld, "DELIVERED", "已签收")))));
        shipment("O1004", "IN_TRANSIT", List.of(pkg("ZTO", "ZTO1004", "IN_TRANSIT",
                List.of(event(now.minusDays(1), "ARRIVED_HUB", "到达分拨中心")))));
        shipment("O1005", "NOT_SHIPPED", List.of());
        shipment("O1006", "NOT_SHIPPED", List.of());
        shipment("O1007", "DELIVERED", List.of(pkg("JD", "JD1007", "DELIVERED",
                List.of(event(deliveredFresh, "DELIVERED", "已签收")))));
        shipment("O1008", "IN_TRANSIT", List.of(
                pkg("JD", "JD1008A", "DELIVERED",
                        List.of(event(deliveredFresh, "DELIVERED", "已签收"))),
                pkg("JD", "JD1008B", "IN_TRANSIT",
                        List.of(event(now.minusHours(6), "IN_TRANSIT", "运输中")))));
        shipment("O1009", "NOT_SHIPPED", List.of());
        shipment("O1010", "DELIVERED", List.of(pkg("EMS", "EMS1010", "DELIVERED",
                List.of(event(now.minusDays(5), "DELIVERED", "已签收")))));
        shipment("O1011", "EXCEPTION", List.of(
                pkg("YTO", "YT1011A", "DELIVERED",
                        List.of(event(now.minusDays(2), "DELIVERED", "已签收"))),
                pkg("YTO", "YT1011B", "EXCEPTION",
                        List.of(event(now.minusDays(1), "EXCEPTION", "包裹破损，待处理")))));
        shipment("O1012", "DELIVERED", List.of(pkg("SF", "SF1012", "DELIVERED",
                List.of(event(now.minusDays(15), "DELIVERED", "已签收")))));
    }

    public Optional<Order> findOwned(String userId, String orderNo) {
        if (orderNo == null || orderNo.isBlank() || userId == null) {
            return Optional.empty();
        }
        Order order = orders.get(orderNo);
        return order != null && order.userId().equals(userId) ? Optional.of(order) : Optional.empty();
    }

    public Order requireOwned(String userId, String orderNo) {
        return findOwned(userId, orderNo)
                .orElseThrow(() -> new ApiException(ErrorCode.ORDER_NOT_FOUND, "订单不存在或不属于当前用户"));
    }

    public List<Order> listForUser(String userId) {
        List<Order> result = new ArrayList<>();
        for (Order order : orders.values()) {
            if (order.userId().equals(userId)) {
                result.add(order);
            }
        }
        result.sort(Comparator.comparing(Order::orderNo));
        return result;
    }

    public Shipment shipmentFor(String userId, String orderNo) {
        requireOwned(userId, orderNo);
        return shipments.getOrDefault(orderNo, new Shipment(orderNo, "NOT_SHIPPED", List.of()));
    }

    public static String statusLabel(String status) {
        if (PAID.equals(status)) {
            return "待发货";
        }
        if (SHIPPED.equals(status)) {
            return "已发货";
        }
        if (DELIVERED.equals(status)) {
            return "已签收";
        }
        if (CLOSED.equals(status)) {
            return "已关闭";
        }
        return "未知";
    }

    private void order(String orderNo, String userId, String status, long amount, long refundable,
                       long refunded, OffsetDateTime paidAt, OffsetDateTime deliveredAt, List<Item> items) {
        orders.put(orderNo, new Order(orderNo, userId, status, amount, refundable, refunded,
                paidAt, deliveredAt, items));
    }

    private void shipment(String orderNo, String status, List<PackageInfo> packages) {
        shipments.put(orderNo, new Shipment(orderNo, status, packages));
    }

    private static Item item(String skuId, String title, int qty, long unitAmountCents) {
        return new Item(skuId, title, qty, unitAmountCents);
    }

    private static PackageInfo pkg(String carrier, String trackingNo, String status, List<Event> events) {
        return new PackageInfo(carrier, trackingNo, status, events);
    }

    private static Event event(OffsetDateTime at, String code, String text) {
        return new Event(at, code, text);
    }
}
