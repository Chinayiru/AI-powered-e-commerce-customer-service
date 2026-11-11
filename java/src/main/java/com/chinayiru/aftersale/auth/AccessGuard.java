package com.chinayiru.aftersale.auth;

import com.chinayiru.aftersale.common.ApiException;
import com.chinayiru.aftersale.common.ErrorCode;
import com.chinayiru.aftersale.config.AppProperties;
import org.springframework.stereotype.Service;

/**
 * 入口身份与坐席身份校验。
 * 演示阶段消费者可用 X-User-Id（仅白名单），生产必须关闭并由 SSO 提供。
 */
@Service
public class AccessGuard {

    private final AppProperties properties;
    private final TicketTokenService ticketTokens;

    public AccessGuard(AppProperties properties, TicketTokenService ticketTokens) {
        this.properties = properties;
        this.ticketTokens = ticketTokens;
    }

    public String requireUser(String xUserId) {
        if (!properties.getDemo().isAllowHeaderIdentity()) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "演示身份已关闭，请通过 SSO 登录");
        }
        if (xUserId == null || xUserId.isBlank()) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "缺少消费者身份");
        }
        if (!properties.getDemo().getAllowedUserIds().contains(xUserId)) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "消费者身份不在演示白名单内");
        }
        return xUserId;
    }

    public void requireAgent(String token) {
        if (!HmacService.constantTimeEquals(token, properties.getSecurity().getAgentToken())) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "坐席凭证无效");
        }
    }

    public TicketTokenService.Claims requireTicket(String ticketId, String authorization) {
        return ticketTokens.verify(authorization, ticketId);
    }
}
