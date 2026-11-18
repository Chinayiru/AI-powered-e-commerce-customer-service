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
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 内部身份 X-Internal-Identity = base64url(JSON{userId,role,exp,nonce}) + "." + HMAC。
 *
 * <p>nonce 以 (nonce,userId,role) 全局去重，而不是按 path 去重：一次调用只能
 * 使用一次身份串，跨端点重放同样返回 401。Python 每发一个工具请求都会重新
 * 签发身份，因此不影响一次 ask 查询订单 + 物流的合法链路。</p>
 */
@Service
public class InternalIdentityService {

    public record Identity(String userId, String role) {
    }

    private static final String ROLE_AGENT = "agent";
    private static final Set<String> ALLOWED_ROLES = Set.of("agent", "python", "system", "service");
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    private final HmacService hmac;
    private final ObjectMapper mapper;
    private final AppProperties properties;
    private final ConcurrentHashMap<String, Long> nonces = new ConcurrentHashMap<>();
    private final AtomicLong operations = new AtomicLong();

    public InternalIdentityService(HmacService hmac, ObjectMapper mapper, AppProperties properties) {
        this.hmac = hmac;
        this.mapper = mapper;
        this.properties = properties;
    }

    public String issue(String userId, String role) {
        if (userId == null || userId.isBlank()) {
            throw new IllegalArgumentException("内部身份 userId 不能为空");
        }
        if (!ALLOWED_ROLES.contains(role)) {
            throw new IllegalArgumentException("不支持内部角色: " + role);
        }
        long exp = Instant.now()
                .plus(Duration.ofSeconds(properties.getSecurity().getInternalIdentityTtlSeconds()))
                .getEpochSecond();
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("userId", userId);
        payload.put("role", role);
        payload.put("exp", exp);
        payload.put("nonce", UUID.randomUUID().toString());
        try {
            String encoded = hmac.encode(mapper.writeValueAsString(payload));
            return encoded + "." + hmac.sign(encoded);
        } catch (Exception ex) {
            throw new IllegalStateException("内部身份签发失败", ex);
        }
    }

    public String issueForAgent(String userId) {
        return issue(userId, ROLE_AGENT);
    }

    public Identity verify(String header, String path) {
        if (header == null || header.isBlank()) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "缺少内部身份");
        }
        String[] parts = header.trim().split("\\.");
        if (parts.length != 2 || !hmac.verify(parts[0], parts[1])) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "内部身份签名无效");
        }
        try {
            Map<String, Object> payload = mapper.readValue(hmac.decode(parts[0]), MAP_TYPE);
            Object userIdValue = payload.get("userId");
            Object roleValue = payload.get("role");
            Object nonceValue = payload.get("nonce");
            Object expValue = payload.get("exp");
            if (!(userIdValue instanceof String userId) || !(roleValue instanceof String role)
                    || !(nonceValue instanceof String nonce) || !(expValue instanceof Number expNumber)) {
                throw new ApiException(ErrorCode.UNAUTHENTICATED, "内部身份内容不合法");
            }
            long exp = expNumber.longValue();
            if (userId.isBlank() || !ALLOWED_ROLES.contains(role)
                    || nonce.isBlank() || exp < Instant.now().getEpochSecond()) {
                throw new ApiException(ErrorCode.UNAUTHENTICATED, "内部身份无效或已过期");
            }
            // path 参数保留用于接口兼容；nonce 全局唯一，不能靠换端点绕过重放保护。
            rememberNonce(nonce + "|" + userId + "|" + role, exp);
            return new Identity(userId, role);
        } catch (ApiException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "内部身份内容不合法");
        }
    }

    private void rememberNonce(String key, long exp) {
        long now = Instant.now().getEpochSecond();
        Long previous = nonces.putIfAbsent(key, exp);
        if (previous != null) {
            if (previous >= now) {
                throw new ApiException(ErrorCode.UNAUTHENTICATED, "内部身份已被使用（nonce 重放）");
            }
            nonces.put(key, exp);
        }
        if (operations.incrementAndGet() % 256 == 0 || nonces.size() > 10_000) {
            nonces.entrySet().removeIf(entry -> entry.getValue() < now);
        }
    }
}
