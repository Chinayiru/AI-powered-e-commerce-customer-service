package com.chinayiru.aftersale.domain;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class ToolCall {
    private Long callId;
    private String ticketId;
    private int step;
    private String name;
    private boolean ok;
    private int latencyMs;
    private String errorCode;
    private String requestHash;
    private String responseHash;
    private String summary;
    private LocalDateTime createdAt;
}
