package com.chinayiru.aftersale.common;

public record ErrorResponse(String code, String message, String traceId, boolean retryable) {
}
