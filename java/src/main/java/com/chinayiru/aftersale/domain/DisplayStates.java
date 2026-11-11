package com.chinayiru.aftersale.domain;

/**
 * 消费者只能看到这 6 个中文状态；内部 state / transferReason 永不外露。
 */
public final class DisplayStates {

    public static final String PROCESSING = "处理中";
    public static final String WAITING_INPUT = "待补充信息";
    public static final String TRANSFERRED = "待人工处理";
    public static final String REPLIED = "已回复";
    public static final String CLOSED = "已完成";
    public static final String CANCELLED = "已取消";

    private DisplayStates() {
    }

    public static String of(TicketState state) {
        if (state == null) {
            return PROCESSING;
        }
        return switch (state) {
            case OPEN, PENDING_ACCEPT, AI_RUNNING, DRAFT_READY, CONFIRMED, EXECUTING -> PROCESSING;
            case WAITING_INPUT -> WAITING_INPUT;
            case REPLIED -> REPLIED;
            case TRANSFERRED -> TRANSFERRED;
            case CLOSED -> CLOSED;
            case CANCELLED -> CANCELLED;
        };
    }
}
