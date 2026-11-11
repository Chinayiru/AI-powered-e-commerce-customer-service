package com.chinayiru.aftersale.domain;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class ExecutionTask {
    private String taskId;
    private String ticketId;
    private String requestId;
    private ExecutionState state;
    private int attempts;
    private String lastError;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
