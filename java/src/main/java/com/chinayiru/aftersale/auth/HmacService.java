package com.chinayiru.aftersale.auth;

import com.chinayiru.aftersale.common.ApiException;
import com.chinayiru.aftersale.common.ErrorCode;
import com.chinayiru.aftersale.config.AppProperties;
import org.springframework.stereotype.Service;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;

/**
 * HMAC-SHA256 签名/验签。所有 token 的签名只覆盖 base64url(payload)，
 * 避免 JSON 重新序列化导致签名漂移。
 */
@Service
public class HmacService {

    private static final String ALGORITHM = "HmacSHA256";
    private final byte[] secret;

    public HmacService(AppProperties properties) {
        String configured = properties.getSecurity().getHmacSecret();
        if (configured == null || configured.isBlank()) {
            throw new IllegalStateException("app.security.hmac-secret 未配置，拒绝启动");
        }
        this.secret = configured.getBytes(StandardCharsets.UTF_8);
    }

    public String sign(String payload) {
        try {
            Mac mac = Mac.getInstance(ALGORITHM);
            mac.init(new SecretKeySpec(secret, ALGORITHM));
            return base64Url(mac.doFinal(payload.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) {
            throw new IllegalStateException("HMAC 计算失败", ex);
        }
    }

    public boolean verify(String payload, String signature) {
        if (payload == null || signature == null) {
            return false;
        }
        byte[] expected = sign(payload).getBytes(StandardCharsets.UTF_8);
        byte[] actual = signature.getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(expected, actual);
    }

    public String encode(String payload) {
        return base64Url(payload.getBytes(StandardCharsets.UTF_8));
    }

    public String decode(String encoded) {
        try {
            return new String(Base64.getUrlDecoder().decode(encoded), StandardCharsets.UTF_8);
        } catch (IllegalArgumentException ex) {
            throw new ApiException(ErrorCode.UNAUTHENTICATED, "凭证格式不合法");
        }
    }

    public static String base64Url(byte[] bytes) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public static boolean constantTimeEquals(String left, String right) {
        if (left == null || right == null) {
            return false;
        }
        return MessageDigest.isEqual(
                left.getBytes(StandardCharsets.UTF_8), right.getBytes(StandardCharsets.UTF_8));
    }
}
