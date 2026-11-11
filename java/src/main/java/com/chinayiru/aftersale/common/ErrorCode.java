package com.chinayiru.aftersale.common;

/**
 * 17 个错误码的封闭集（边界书 §9）。新增错误码必须同时改契约。
 */
public enum ErrorCode {
    INVALID_ARGS(422, false),
    UNAUTHENTICATED(401, false),
    FORBIDDEN_SCOPE(403, false),
    ORDER_NOT_FOUND(404, false),
    TICKET_NOT_FOUND(404, false),
    STATE_NOT_ALLOWED(409, false),
    DUPLICATE_REQUEST(409, false),
    IDEMPOTENCY_CONFLICT(409, false),
    IN_PROGRESS(409, true),
    STALE_DRAFT(409, false),
    STALE_STATE(409, false),
    POLICY_REJECTED(409, false),
    REVIEW_NOTE_REQUIRED(422, false),
    TOOL_UNAVAILABLE(503, true),
    TOOL_TIMEOUT(504, true),
    AGENT_UNAVAILABLE(503, true),
    PERSISTENCE_FAILED(500, true);

    private final int httpStatus;
    private final boolean retryable;

    ErrorCode(int httpStatus, boolean retryable) {
        this.httpStatus = httpStatus;
        this.retryable = retryable;
    }

    public int httpStatus() {
        return httpStatus;
    }

    public boolean retryable() {
        return retryable;
    }
}
