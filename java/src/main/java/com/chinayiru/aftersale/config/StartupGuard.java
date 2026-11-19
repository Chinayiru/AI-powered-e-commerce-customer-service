package com.chinayiru.aftersale.config;

import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.List;
import java.util.Locale;

/**
 * 凭证红线：只有 test 允许使用合成测试夹具；dev 与其余 profile 必须注入
 * 足够长、非示例串的密钥，且禁止自报消费者身份（mysql/profile 也一样）。
 *
 * <p>这些检查发生在端口开始服务之前，属于 fail-fast。用“包含示例标记”而不是
 * 精确 equals，避免在演示串后追加一个字符就绕过。</p>
 */
@Component
@RequiredArgsConstructor
public class StartupGuard {

    private static final List<String> SAMPLE_MARKERS = List.of(
            "dev-only", "change-me", "demo-agent", "please", "example", "test-only", "redacted", "replace-me");
    private static final int MIN_SECRET_LENGTH = 32;

    private final AppProperties properties;
    private final Environment environment;

    @PostConstruct
    public void verify() {
        AppProperties.Demo demo = properties.getDemo();
        AppProperties.Security security = properties.getSecurity();

        if (!isDemoOnlyProfile() && demo.isAllowHeaderIdentity()) {
            throw new IllegalStateException(
                    "非 dev/test profile 禁止 demo.allow-header-identity=true：自报 X-User-Id 不得进入生产");
        }
        validateSecret("APP_HMAC_SECRET (app.security.hmac-secret)", security.getHmacSecret(), isTestOnlyProfile());
        validateSecret("APP_AGENT_TOKEN (app.security.agent-token)", security.getAgentToken(), isTestOnlyProfile());
        if (security.getHmacSecret().equals(security.getAgentToken())) {
            throw new IllegalStateException("HMAC 密钥与坐席令牌不得相同，必须使用两把独立凭证");
        }

        // prod 额外要求 SSO 与真实 AI 层；其他非 dev 环境先允许联调，但密钥仍受上面的约束。
        if (environment.acceptsProfiles(Profiles.of("prod"))) {
            if (!security.isSsoEnabled()) {
                throw new IllegalStateException(
                        "prod 未接入 SSO（app.security.sso-enabled=false），按边界书拒绝启动");
            }
            if (!"http".equalsIgnoreCase(properties.getAgent().getMode())) {
                throw new IllegalStateException("prod 必须使用 http 模式调用真实 AI 层，不得使用 scripted 桩");
            }
        }
    }

    private boolean isDemoOnlyProfile() {
        String[] active = environment.getActiveProfiles();
        if (active.length == 0) {
            // spring.profiles.default=dev 时 getActiveProfiles() 为空，需要看默认 profile。
            String[] defaults = environment.getDefaultProfiles();
            return defaults.length > 0 && Arrays.stream(defaults).allMatch(StartupGuard::isDemoProfile);
        }
        return Arrays.stream(active).allMatch(StartupGuard::isDemoProfile);
    }

    private static boolean isDemoProfile(String profile) {
        return "dev".equalsIgnoreCase(profile) || "test".equalsIgnoreCase(profile);
    }

    private boolean isTestOnlyProfile() {
        String[] active = environment.getActiveProfiles();
        String[] profiles = active.length == 0 ? environment.getDefaultProfiles() : active;
        return profiles.length > 0 && Arrays.stream(profiles).allMatch("test"::equalsIgnoreCase);
    }

    private static void validateSecret(String name, String value, boolean testOnly) {
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " 未配置，拒绝启动");
        }
        if (value.length() < MIN_SECRET_LENGTH) {
            throw new IllegalStateException(name + " 长度不足 " + MIN_SECRET_LENGTH + " 字符");
        }
        if (!testOnly && isSampleSecret(value)) {
            throw new IllegalStateException(name + " 仍是仓库示例密钥，拒绝启动");
        }
    }

    private static boolean isSampleSecret(String value) {
        if (value == null) {
            return false;
        }
        String normalized = value.toLowerCase(Locale.ROOT);
        return SAMPLE_MARKERS.stream().anyMatch(normalized::contains);
    }
}
