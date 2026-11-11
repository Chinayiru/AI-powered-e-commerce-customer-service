package com.chinayiru.aftersale.domain;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class TicketMessage {
    private Long messageId;
    private String ticketId;
    private MessageRole role;
    private String text;
    private LocalDateTime createdAt;
}
