package com.chinayiru.aftersale.domain;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Ticket {
    private String ticketId;
    private Category category;
    private String parentConsultTicketId;
    private String userId;
    private String orderNo;
    private TicketState state;
    private int version;
    private int taskEpoch;
    private int currentAttempt;
    private int stalledRounds;
    private ExecutionMode executionMode;
    private TransferReason transferReason;
    /** 实现字段：当前逻辑生成任务；用于迟到响应判定。契约未列入 ticket 表，但 §7.2 要求可判定。 */
    private String generationTaskId;
    private String activeOrderKey;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private LocalDateTime closedAt;
}
