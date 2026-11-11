package com.chinayiru.aftersale.domain;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
public class Draft {
    private String draftId;
    private String ticketId;
    private int draftVersion;
    private String generationTaskId;
    private IntentType intent;
    private BigDecimal confidence;
    private ReplyType replyType;
    private String replyDraft;
    private String suggestedActionJson;
    private String citationsJson;
    private String policyCheckJson;
    private String policyVersion;
    private boolean needHumanReview;
    private boolean superseded;
    private LocalDateTime createdAt;
}
