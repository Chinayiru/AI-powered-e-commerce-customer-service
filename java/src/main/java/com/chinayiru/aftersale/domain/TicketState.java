package com.chinayiru.aftersale.domain;

import java.util.EnumSet;
import java.util.Set;

/**
 * 11 个状态的全集。CONSULT 与 AFTERSALE 共用一张表，但只允许各自的子集。
 */
public enum TicketState {
    OPEN,
    PENDING_ACCEPT,
    AI_RUNNING,
    WAITING_INPUT,
    DRAFT_READY,
    CONFIRMED,
    EXECUTING,
    REPLIED,
    TRANSFERRED,
    CLOSED,
    CANCELLED;

    public static final Set<TicketState> CONSULT_STATES = EnumSet.of(
            OPEN, AI_RUNNING, WAITING_INPUT, REPLIED, TRANSFERRED, CLOSED, CANCELLED);

    public static final Set<TicketState> AFTERSALE_STATES = EnumSet.of(
            PENDING_ACCEPT, AI_RUNNING, WAITING_INPUT, DRAFT_READY, CONFIRMED,
            EXECUTING, REPLIED, TRANSFERRED, CLOSED, CANCELLED);

    /** 客户可主动撤销的状态白名单。 */
    public static final Set<TicketState> CANCELABLE = EnumSet.of(
            PENDING_ACCEPT, WAITING_INPUT, AI_RUNNING, DRAFT_READY, REPLIED, TRANSFERRED);

    /** 客户可继续发消息的状态。 */
    public static final Set<TicketState> CUSTOMER_MESSAGEABLE = EnumSet.of(
            OPEN, PENDING_ACCEPT, AI_RUNNING, WAITING_INPUT, DRAFT_READY, REPLIED, TRANSFERRED);

    /** 转人工接口允许的起点。 */
    public static final Set<TicketState> HANDOFF_FROM = EnumSet.of(AI_RUNNING, DRAFT_READY, WAITING_INPUT);

    /** 坐席确认允许的起点。 */
    public static final Set<TicketState> SEND_FROM = EnumSet.of(DRAFT_READY, TRANSFERRED);
}
