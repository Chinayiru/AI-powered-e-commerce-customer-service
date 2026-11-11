package com.chinayiru.aftersale.domain;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class AuditLog {
    private Long id;
    private String ticketId;
    private String action;
    private String detail;
    private String traceId;
    private LocalDateTime createdAt;
}
