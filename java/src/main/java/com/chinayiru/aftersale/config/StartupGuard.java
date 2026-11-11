package com.chinayiru.aftersale.config;

import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.stereotype.Component;

/**
 * 生产红线：演示身份头必须关闭；未接 SSO 前拒绝启动；默认开发密钥拒绝启动。
 * 这些检查发生在端口开始服务之前，属于 fail-fast。
 */
@Component
@RequiredArgsConstructor
public class StartupGuard {

    private static final String DEV_HMAC = "dev-only-hmac-secret-change-me-please";
    private static final String DEV_AGENT_TOKEN = "demo-agent-token";

    private final AppProperties properties;
    private final Environment environment;

    @PostConstruct
    public void verify() {
        if (!environment.acceptsProfiles(Profiles.of("prod"))) {
            return;
        }
        AppProperties.Demo demo = properties.getDemo();
        AppProperties.Security security = properties.getSecurity();
        if (demo.isAllowHeaderIdentity()) {
            throw new IllegalStateException("prod 禁止 demo.allow-header-identity=true：自报 X-User-Id 不得进入生产");
        }
        if (!security.isSsoEnabled()) {
            throw new IllegalStateException("prod 未接入 SSO（app.security.sso-enabled=false），按边界书拒绝启动");
        }
        if (security.getHmacSecret() == null || security.getHmacSecret().isBlank()
                || DEV_HMAC.equals(security.getHmacSecret())) {
            throw new IllegalStateException("prod 必须通过 APP_HMAC_SECRET 注入非默认 HMAC 密钥");
        }
        if (security.getAgentToken() == null || security.getAgentToken().isBlank()
                || DEV_AGENT_TOKEN.equals(security.getAgentToken())) {
            throw new IllegalStateException("prod 必须通过 APP_AGENT_TOKEN 注入非默认坐席令牌");
        }
        if (!"http".equalsIgnoreCase(properties.getAgent().getMode())) {
            throw new IllegalStateException("prod 必须使用 http 模式调用真实 AI 层，不得使用 scripted 桩");
        }
    }
}
