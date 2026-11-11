package com.chinayiru.aftersale.common;

import lombok.Getter;

@Getter
public class ApiException extends RuntimeException {

    private final ErrorCode code;
    private final Integer retryAfterSeconds;

    public ApiException(ErrorCode code, String message) {
        this(code, message, null);
    }

    public ApiException(ErrorCode code, String message, Integer retryAfterSeconds) {
        super(message);
        this.code = code;
        this.retryAfterSeconds = retryAfterSeconds;
    }

    public static ApiException invalid(String message) {
        return new ApiException(ErrorCode.INVALID_ARGS, message);
    }

    public static ApiException state(String message) {
        return new ApiException(ErrorCode.STATE_NOT_ALLOWED, message);
    }

    public static ApiException notFound() {
        return new ApiException(ErrorCode.TICKET_NOT_FOUND, "工单不存在");
    }
}
