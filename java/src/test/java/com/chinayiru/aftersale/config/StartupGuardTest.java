package com.chinayiru.aftersale.config;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 启动红线的单元测试：不启动 Spring 容器，直接验证 profile 白名单与密钥约束。
 *
 * <p>这些用例保护的是“生产不能带着演示凭证启动”这条边界，故意不经过
 * ApiIntegrationTest 的 test profile，否则白名单会掩盖问题。</p>
 */
class StartupGuardTest {

    private static final String SAMPLE_HMAC = "test-only-hmac-fixture-0123456789abcdef";
    private static final String SAMPLE_AGENT = "test-only-agent-fixture-0123456789abcdef";
    private static final String STRONG_HMAC = "hmac-0123456789abcdef0123456789abcd";
    private static final String STRONG_AGENT = "agent-0123456789abcdef0123456789ab";

    @Test
    void devProfileRejectsRepositoryTestSecrets() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("dev");

        assertThatThrownBy(() -> new StartupGuard(props(SAMPLE_HMAC, SAMPLE_AGENT, false), env).verify())
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("示例密钥");
    }

    @Test
    void testProfileMayUseRepositorySampleSecrets() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("test");

        assertThatCode(() -> new StartupGuard(props(SAMPLE_HMAC, SAMPLE_AGENT, false), env).verify())
                .doesNotThrowAnyException();
    }

    @Test
    void devProfileRejectsMissingSecrets() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("dev");
        assertThatThrownBy(() -> new StartupGuard(props("", "", true), env).verify())
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("未配置");
    }

    @Test
    void devProfileAcceptsInjectedSecretsWithDemoIdentity() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("dev");
        assertThatCode(() -> new StartupGuard(props(STRONG_HMAC, STRONG_AGENT, true), env).verify())
                .doesNotThrowAnyException();
    }

    @Test
    void nonDemoProfileRejectsSampleSecretEvenWithSuffix() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("mysql");

        // 旧实现用 equals 比对，追加一个字符即可绕过；现在必须按包含式标记拒绝。
        assertThatThrownBy(() ->
                new StartupGuard(props(SAMPLE_HMAC + "x", STRONG_AGENT, false), env).verify())
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("示例密钥");
    }

    @Test
    void nonDemoProfileRejectsTooShortSecret() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("mysql");

        assertThatThrownBy(() ->
                new StartupGuard(props("a".repeat(31), STRONG_AGENT, false), env).verify())
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("长度不足");
    }

    @Test
    void nonDemoProfileRejectsHeaderIdentity() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("mysql");

        assertThatThrownBy(() ->
                new StartupGuard(props(STRONG_HMAC, STRONG_AGENT, true), env).verify())
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("allow-header-identity");
    }

    @Test
    void nonDemoProfileRejectsSharedHmacAndAgentToken() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("mysql");

        assertThatThrownBy(() ->
                new StartupGuard(props(STRONG_HMAC, STRONG_HMAC, false), env).verify())
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("两把独立凭证");
    }

    @Test
    void nonDemoProfileAcceptsStrongIndependentSecrets() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("mysql");

        assertThatCode(() -> new StartupGuard(props(STRONG_HMAC, STRONG_AGENT, false), env).verify())
                .doesNotThrowAnyException();
    }

    @Test
    void mixedDevAndProdProfilesDoNotBypassGuard() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("dev", "prod");

        // 只要还有非 dev/test profile，就不能走演示密钥白名单。
        assertThatThrownBy(() ->
                new StartupGuard(props(SAMPLE_HMAC, SAMPLE_AGENT, false), env).verify())
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void prodRequiresSsoEnabled() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("prod");

        assertThatThrownBy(() ->
                new StartupGuard(props(STRONG_HMAC, STRONG_AGENT, false), env).verify())
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("SSO");
    }

    @Test
    void prodRequiresHttpAgentMode() {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles("prod");

        AppProperties properties = props(STRONG_HMAC, STRONG_AGENT, false);
        properties.getSecurity().setSsoEnabled(true);
        properties.getAgent().setMode("scripted");

        assertThatThrownBy(() -> new StartupGuard(properties, env).verify())
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("http");
    }

    private static AppProperties props(String hmacSecret, String agentToken, boolean allowHeaderIdentity) {
        AppProperties properties = new AppProperties();
        properties.getSecurity().setHmacSecret(hmacSecret);
        properties.getSecurity().setAgentToken(agentToken);
        properties.getDemo().setAllowHeaderIdentity(allowHeaderIdentity);
        properties.getAgent().setMode("http");
        return properties;
    }
}
