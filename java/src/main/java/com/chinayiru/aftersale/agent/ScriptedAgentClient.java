package com.chinayiru.aftersale.agent;

import com.chinayiru.aftersale.agent.AgentContract.AskRequest;
import com.chinayiru.aftersale.agent.AgentContract.AskResponse;
import com.chinayiru.aftersale.agent.AgentContract.Citation;
import com.chinayiru.aftersale.agent.AgentContract.Context;
import com.chinayiru.aftersale.agent.AgentContract.History;
import com.chinayiru.aftersale.agent.AgentContract.Model;
import com.chinayiru.aftersale.agent.AgentContract.Slots;
import com.chinayiru.aftersale.agent.AgentContract.SuggestedAction;
import com.chinayiru.aftersale.config.AppProperties;
import com.chinayiru.aftersale.domain.ActionType;
import com.chinayiru.aftersale.domain.IntentType;
import com.chinayiru.aftersale.domain.ReplyType;
import com.chinayiru.aftersale.domain.TransferReason;
import com.chinayiru.aftersale.tool.OrderModels.Order;
import com.chinayiru.aftersale.tool.OrderModels.PackageInfo;
import com.chinayiru.aftersale.tool.OrderModels.Shipment;
import com.chinayiru.aftersale.tool.OrderToolService;
import org.springframework.util.StringUtils;

import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 本地脚本化 AI 桩：用于 M-S 验收与无 Python 时的演示。
 *
 * 它只模拟 Python 的“意图/槽位/草稿/置信度”，不产生政策结论，也不写库。
 * 重点覆盖 DEMO 中的 O1001/O1002/O1003/O1004/O1006/O9999 与多轮补单号场景。
 */
public class ScriptedAgentClient implements AgentClient {

    private static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");
    private static final Pattern ORDER_PATTERN = Pattern.compile("(?<![A-Za-z0-9])O\\d{4,}");
    private static final DateTimeFormatter EVENT_TIME = DateTimeFormatter.ofPattern("MM-dd HH:mm");

    private static final List<String> SAFETY_WORDS = List.of(
            "投诉", "12315", "消协", "律师", "起诉", "曝光", "威胁", "人身", "监管", "举报");
    private static final List<String> HUMAN_WORDS = List.of(
            "转人工", "人工客服", "真人", "找人工", "要人工", "人工处理");
    private static final List<String> POLICY_WORDS = List.of(
            "政策", "规则", "运费", "时效", "流程", "七天", "无理由", "退款条件");
    private static final List<String> REFUND_REQUEST_WORDS = List.of(
            "退款", "退钱", "退掉", "帮我退", "申请退", "退了吧", "不想要", "不要了");
    private static final List<String> LOGISTICS_WORDS = List.of(
            "物流", "快递", "到哪", "发货", "签收", "包裹", "运单", "多久", "什么时候到");
    private static final List<String> ELIGIBILITY_WORDS = List.of(
            "能退", "可以退", "可退", "退货", "退换", "拆", "还能退", "退吗");
    private static final List<String> REFUND_QUESTION_WORDS = List.of(
            "怎么办", "怎么退", "如何退", "能否", "可以吗", "能吗", "行吗");

    private final AppProperties properties;
    private final OrderToolService orderTools;

    public ScriptedAgentClient(AppProperties properties, OrderToolService orderTools) {
        this.properties = properties;
        this.orderTools = orderTools;
    }

    @Override
    public String provider() {
        return "scripted";
    }

    @Override
    public AskResponse ask(AskRequest request, String internalIdentity) {
        String message = request.message() == null ? "" : request.message();
        String historyText = historyText(request.context());
        String allText = message + " " + historyText;

        List<String> orderNos = extractOrderNos(request.context(), message, historyText);
        boolean ambiguous = orderNos.size() > 1;
        String orderNo = orderNos.isEmpty() ? null : orderNos.get(0);
        Optional<Order> order = orderNo == null
                ? Optional.empty()
                : orderTools.findOwned(request.userId(), orderNo);

        boolean safety = containsAny(message, SAFETY_WORDS);
        boolean wantsHuman = containsAny(message, HUMAN_WORDS);
        boolean policy = containsAny(message, POLICY_WORDS);
        boolean refundRequest = containsAny(message, REFUND_REQUEST_WORDS);
        boolean refundQuestion = containsAny(message, REFUND_QUESTION_WORDS)
                || message.strip().endsWith("吗") || message.strip().endsWith("吗？")
                || message.strip().endsWith("吗?");
        boolean logistics = containsAny(message, LOGISTICS_WORDS);
        boolean eligibility = containsAny(message, ELIGIBILITY_WORDS);

        if (safety) {
            return response(IntentType.HANDOFF, orderNo, List.of(), 0.95, ReplyType.DECISIONAL,
                    false, TransferReason.OUT_OF_SCOPE, null,
                    "您反馈的问题涉及投诉/监管，已转交人工专员处理。", policyCitations("complaint-policy", "投诉与升级处理", "5.1"),
                    false);
        }
        if (wantsHuman) {
            return response(IntentType.HANDOFF, orderNo, List.of(), 0.95, ReplyType.DECISIONAL,
                    false, TransferReason.USER_REQUESTED, null,
                    "已为您转接人工客服，请稍候。", List.of(), false);
        }
        if (ambiguous) {
            return response(IntentType.HANDOFF, null, List.of(), 0.92, ReplyType.DECISIONAL,
                    false, TransferReason.AMBIGUOUS_ORDER, null,
                    "检测到多个订单号，请确认要处理哪一笔订单。", List.of(), false);
        }

        if (policy) {
            return policyReply(orderNo, order);
        }
        if (refundRequest && refundQuestion) {
            return eligibilityReply(orderNo, order);
        }
        if (refundRequest) {
            return refundRequestReply(orderNo, order);
        }
        if (logistics) {
            return logisticsReply(orderNo, order, allText);
        }
        if (eligibility) {
            return eligibilityReply(orderNo, order);
        }
        return otherReply(orderNo, order, message);
    }

    private AskResponse refundRequestReply(String orderNo, Optional<Order> order) {
        if (orderNo == null) {
            return response(IntentType.REFUND_REQUEST, null, List.of("orderNo"), 0.80, ReplyType.DECISIONAL,
                    false, null, null,
                    "请提供订单号，我先帮您核实订单状态和可退金额。", List.of(), false);
        }
        if (order.isEmpty()) {
            return response(IntentType.REFUND_REQUEST, orderNo, List.of(), 0.85, ReplyType.DECISIONAL,
                    false, null, null,
                    "没查到订单 " + orderNo + "，请核对订单号后再试。", List.of(), false);
        }
        Order value = order.get();
        if (value.refundableAmountCents() <= 0) {
            return response(IntentType.REFUND_REQUEST, orderNo, List.of(), 0.90, ReplyType.DECISIONAL,
                    false, null, new SuggestedAction(ActionType.NONE, null, true),
                    "该订单当前可退金额为 0，建议转人工核实退款记录。",
                    policyCitations("refund-policy", "退款与售后政策", "3.1"), false);
        }
        boolean needReview = value.refundableAmountCents() > properties.getRefund().getAutoSuggestLimitCents();
        String reply = "建议整单退款 " + yuan(value.refundableAmountCents())
                + (needReview ? "，金额超过免审上限，需人工复核后执行。" : "，待坐席确认后执行。")
                + "（演示环境，未真实退款）";
        return response(IntentType.REFUND_REQUEST, orderNo, List.of(),
                0.92, ReplyType.DECISIONAL, needReview, null,
                new SuggestedAction(ActionType.REFUND, value.refundableAmountCents(), true),
                reply, policyCitations("refund-policy", "退款与售后政策", "3.1"), false);
    }

    private AskResponse eligibilityReply(String orderNo, Optional<Order> order) {
        if (orderNo == null) {
            return response(IntentType.REFUND_ELIGIBILITY, null, List.of("orderNo"), 0.72, ReplyType.INFORMATIONAL,
                    false, null, null,
                    "请提供订单号，我帮您判断是否还在退货退款期限内。", List.of(), false);
        }
        if (order.isEmpty()) {
            return response(IntentType.REFUND_ELIGIBILITY, orderNo, List.of(), 0.85, ReplyType.INFORMATIONAL,
                    false, null, null,
                    "没查到订单 " + orderNo + "，请核对订单号后再试。", List.of(), false);
        }
        Order value = order.get();
        String draft;
        if (OrderToolService.PAID.equals(value.status())) {
            draft = "订单 " + orderNo + " 当前待发货，实付 " + yuan(value.amountCents())
                    + "；未发货可申请仅退款，需坐席确认。";
        } else if (OrderToolService.SHIPPED.equals(value.status())) {
            draft = "订单 " + orderNo + " 已发货，实付 " + yuan(value.amountCents())
                    + "；可申请退货退款，需按指引寄回商品。";
        } else if (OrderToolService.DELIVERED.equals(value.status())) {
            long days = daysSinceDelivery(value);
            String window = days <= 7
                    ? "仍在七天无理由窗口内（自签收次日起算）。"
                    : "已超出七天无理由窗口，是否可退需人工按政策核实。";
            draft = "订单 " + orderNo + " 已签收 " + days + " 天，" + window;
        } else {
            draft = "订单 " + orderNo + " 当前状态为" + OrderToolService.statusLabel(value.status())
                    + "，通常不支持退款，建议转人工核实。";
        }
        if (value.refundedAmountCents() > 0) {
            draft = draft + " 该订单已退 " + yuan(value.refundedAmountCents())
                    + "，剩余可退 " + yuan(value.refundableAmountCents()) + "。";
        }
        boolean needReview = value.refundableAmountCents() > properties.getRefund().getAutoSuggestLimitCents();
        return response(IntentType.REFUND_ELIGIBILITY, orderNo, List.of(), 0.88, ReplyType.INFORMATIONAL,
                needReview, null, null, draft,
                policyCitations("refund-policy", "退款与售后政策", "3.1"), false);
    }

    private AskResponse logisticsReply(String orderNo, Optional<Order> order, String allText) {
        if (orderNo == null) {
            return response(IntentType.LOGISTICS, null, List.of("orderNo"), 0.74, ReplyType.INFORMATIONAL,
                    false, null, null,
                    "请提供订单号，我帮您查询物流进度。", List.of(), false);
        }
        if (order.isEmpty()) {
            return response(IntentType.LOGISTICS, orderNo, List.of(), 0.86, ReplyType.INFORMATIONAL,
                    false, null, null,
                    "没查到订单 " + orderNo + "，请核对订单号后再试。", List.of(), false);
        }
        Shipment shipment = orderTools.shipmentFor(order.get().userId(), orderNo);
        String draft;
        if (shipment.shipments().isEmpty()) {
            draft = "订单 " + orderNo + " 尚未发货，暂无物流轨迹。";
        } else {
            PackageInfo pkg = shipment.shipments().stream()
                    .filter(p -> "EXCEPTION".equals(p.status()))
                    .findFirst()
                    .orElse(shipment.shipments().get(0));
            String latest = pkg.events().isEmpty()
                    ? "暂无轨迹"
                    : pkg.events().get(pkg.events().size() - 1).text();
            String when = pkg.events().isEmpty()
                    ? ""
                    : "（" + pkg.events().get(pkg.events().size() - 1).at().atZoneSameInstant(ZONE)
                    .format(EVENT_TIME) + "）";
            draft = "订单 " + orderNo + " " + OrderToolService.statusLabel(order.get().status())
                    + "，包裹 " + pkg.trackingNo() + " " + logisticsLabel(pkg.status())
                    + "；最新：" + latest + when + "。";
        }
        return response(IntentType.LOGISTICS, orderNo, List.of(), 0.90, ReplyType.INFORMATIONAL,
                false, null, null, draft,
                policyCitations("logistics-policy", "物流时效说明", "2.2"), false);
    }

    private AskResponse policyReply(String orderNo, Optional<Order> order) {
        boolean freight = false;
        String draft = "退款政策：七天无理由自签收次日起算；仅退款只在未发货时成立；"
                + "已发货/已签收可申请退货退款，商品需保持完好。";
        if (order.isPresent()) {
            Order value = order.get();
            draft = draft + " 订单 " + value.orderNo() + " 当前" + OrderToolService.statusLabel(value.status())
                    + "，可退 " + yuan(value.refundableAmountCents()) + "。";
        } else {
            freight = true;
        }
        List<Citation> citations = new ArrayList<>(policyCitations("refund-policy", "退款与售后政策", "3.1"));
        if (freight) {
            citations.addAll(policyCitations("freight-policy", "退货运费规则", "3.4"));
            draft = draft + " 退货运费：质量问题由商家承担，七天无理由由消费者承担。";
        }
        return response(IntentType.POLICY, orderNo, List.of(), 0.86, ReplyType.INFORMATIONAL,
                false, null, null, draft, citations, false);
    }

    private AskResponse otherReply(String orderNo, Optional<Order> order, String message) {
        if (containsAny(message, List.of("你好", "您好", "在吗", "hi", "hello"))) {
            return response(IntentType.OTHER, orderNo, List.of(), 0.66, ReplyType.INFORMATIONAL,
                    false, null, null,
                    "您好，请提供订单号和具体问题（如退款、物流、退货政策），我帮您核实。",
                    List.of(), false);
        }
        boolean vague = message.length() < 8 || containsAny(message, List.of("那个", "看看", "怎么弄", "不太行"));
        if (vague) {
            return response(IntentType.OTHER, orderNo, List.of(), 0.48, ReplyType.INFORMATIONAL,
                    false, null, null,
                    "请补充订单号和具体诉求，我再帮您核实。", List.of(), false);
        }
        return response(IntentType.OTHER, orderNo, List.of(), 0.58, ReplyType.INFORMATIONAL,
                false, null, null,
                "已收到您的描述，请补充订单号和期望的处理方式。", List.of(), false);
    }

    private AskResponse response(IntentType intent, String orderNo, List<String> missing,
                                 double confidence, ReplyType replyType, boolean needHumanReview,
                                 TransferReason transferReason, SuggestedAction action,
                                 String replyDraft, List<Citation> citations, boolean degraded) {
        return new AskResponse(
                intent,
                new Slots(orderNo, missing),
                confidence,
                replyType,
                needHumanReview,
                transferReason,
                action,
                replyDraft,
                citations,
                degraded,
                new Model(provider(), properties.getAgent().getPromptVersion()));
    }

    private static List<String> extractOrderNos(Context context, String message, String historyText) {
        Set<String> found = new LinkedHashSet<>();
        if (context != null && StringUtils.hasText(context.orderNo())) {
            found.add(context.orderNo().trim());
        }
        collect(found, message);
        collect(found, historyText);
        return new ArrayList<>(found);
    }

    private static void collect(Set<String> target, String text) {
        if (text == null) {
            return;
        }
        Matcher matcher = ORDER_PATTERN.matcher(text);
        while (matcher.find()) {
            target.add(matcher.group());
        }
    }

    private static String historyText(Context context) {
        if (context == null || context.history() == null) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        for (History history : context.history()) {
            if (history != null && history.text() != null) {
                sb.append(history.text()).append(' ');
            }
        }
        return sb.toString();
    }

    private static boolean containsAny(String text, List<String> words) {
        if (text == null) {
            return false;
        }
        String lower = text.toLowerCase(Locale.ROOT);
        for (String word : words) {
            if (lower.contains(word.toLowerCase(Locale.ROOT))) {
                return true;
            }
        }
        return false;
    }

    private static List<Citation> policyCitations(String docId, String title, String clauseId) {
        return List.of(new Citation(docId, title, clauseId, "2026-11"));
    }

    private static long daysSinceDelivery(Order order) {
        if (order.deliveredAt() == null) {
            return 0;
        }
        LocalDate delivered = order.deliveredAt().atZoneSameInstant(ZONE).toLocalDate();
        return Math.max(0, ChronoUnit.DAYS.between(delivered, LocalDate.now(ZONE)));
    }

    private static String logisticsLabel(String status) {
        return switch (status) {
            case "NOT_SHIPPED" -> "未发货";
            case "IN_TRANSIT" -> "运输中";
            case "DELIVERED" -> "已签收";
            case "EXCEPTION" -> "异常";
            default -> "未知";
        };
    }

    public static String yuan(long cents) {
        return String.format(Locale.CHINA, "¥%.2f", cents / 100.0);
    }
}
