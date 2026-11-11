package com.chinayiru.aftersale.auth;

import com.chinayiru.aftersale.common.ApiException;
import com.chinayiru.aftersale.common.ErrorCode;
import com.chinayiru.aftersale.config.AppProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * ticketToken：HMAC 绑定 ticketId + userId + exp。工单接口只认 token，
 * 路径里的 ticketId 必须与 token 内一致，否则 403 FORBIDDEN_SCOPE。
 */
@Service
public class TicketTokenService {

    public record Claims(String ticketId, String userId, long expiresAt) {
    }

    private static final String BEARER = "Bearer ";
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    private final HmacService hmac;
    private final ObjectMapper mapper;
    private final AppProperties properties;

    public TicketTokenService(HmacService hmac, ObjectMapper mapper, AppProperties properties) {
        this.hmac = hmac;
        this.mapper = mapper;
        this.properties = properties;
    }

    public String issue(String ticketId, String userId) {
        long exp = Instant.now()
                .plus(Duration.ofHours(properties.getSecurity().getTicketTokenTtlHours()))
                .getEpochSecond();
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("ticketId", ticketId);
        payload.put("userId", userId);
        payload.put("exp", exp);
        try {
            String encoded = hmac.encode(mapper.writeValueAsString(payload));
            return encoded + "." + hmac.sign(encoded);
        } catch (Exception ex) {
            throw new IllegalStateException("ticketToken 签发失败", ex);
        }
    }

    public Claims verify(String authorizationHeader, String pathTicketId) {
        if (authorizationHeader == null || !authorizationHeader.startsWith(BEARER)) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "缺少登录凭证");
        }
        String token = authorizationHeader.substring(BEARER.length()).trim();
        String[] parts = token.split("\\.");
        if (parts.length != 2 || !hmac.verify(parts[0], parts[1])) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "登录凭证无效");
        }
        Claims claims = parse(parts[0]);
        if (claims.expiresAt() < Instant.now().getEpochSecond()) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "登录凭证已过期");
        }
        if (!claims.ticketId().equals(pathTicketId)) {
            throw new ApiException(ErrorCode.FORBIDDEN_SCOPE, "无权访问该工单");
        }
        return claims;
    }

    private Claims parse(String encodedPayload) {
        try {
            Map<String, Object> payload = mapper.readValue(hmac.decode(encodedPayload), MAP_TYPE);
            Object ticketId = payload.get("ticketId");
            Object userId = payload.get("userId");
            Object exp = payload.get("exp");
            if (!(ticketId instanceof String) || !(userId instanceof String) || !(exp instanceof Number)) {
                throw new ApiException(ErrorCode.UNAUTHENTICATED, "登录凭证内容不合法");
            }
            return new Claims((String) ticketId, (String) userId, ((Number) exp).longValue());
        } catch (ApiException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "登录凭证内容不合法");
        }
    }
}
