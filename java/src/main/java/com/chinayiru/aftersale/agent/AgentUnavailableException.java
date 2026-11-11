package com.chinayiru.aftersale.agent;

import com.chinayiru.aftersale.common.ErrorCode;

/**
 * Python AI 层不可用/超时/返回不符合契约。调用方统一降级为 TRANSFERRED(TOOL_FAILED)，
 * 对外仍是 200，不把 5xx 抛给客户。
 */
public class AgentUnavailableException extends RuntimeException {

    private final ErrorCode code;

    public AgentUnavailableException(ErrorCode code, String message) {
        super(message);
        this.code = code;
    }

    public AgentUnavailableException(ErrorCode code, String message, Throwable cause) {
        super(message, cause);
        this.code = code;
    }

    public ErrorCode getCode() {
        return code;
    }
}
