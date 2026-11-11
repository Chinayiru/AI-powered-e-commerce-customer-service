package com.chinayiru.aftersale.domain;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class IdempotencyRecord {
    private String userId;
    private String endpoint;
    private String targetId;
    private String requestId;
    private String requestHash;
    private IdemState state;
    private String response;
    private String errorCode;
    private LocalDateTime updatedAt;
    private LocalDateTime createdAt;
}
