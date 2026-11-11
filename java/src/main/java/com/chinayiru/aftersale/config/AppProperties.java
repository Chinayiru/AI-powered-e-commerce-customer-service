package com.chinayiru.aftersale.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

@Data
@ConfigurationProperties(prefix = "app")
public class AppProperties {

    private Demo demo = new Demo();
    private Security security = new Security();
    private Intent intent = new Intent();
    private Refund refund = new Refund();
    private Consult consult = new Consult();
    private Policy policy = new Policy();
    private Execution execution = new Execution();
    private Idempotency idempotency = new Idempotency();
    private Agent agent = new Agent();

    @Data
    public static class Demo {
        private boolean allowHeaderIdentity = false;
        private List<String> allowedUserIds = new ArrayList<>(List.of("U001", "U002"));
    }

    @Data
    public static class Security {
        private String hmacSecret;
        private String agentToken;
        private long ticketTokenTtlHours = 168;
        private long internalIdentityTtlSeconds = 300;
        private long nonceCacheSeconds = 300;
        private boolean ssoEnabled = false;
    }

    @Data
    public static class Intent {
        private double confidenceThreshold = 0.60;
    }

    @Data
    public static class Refund {
        private long autoSuggestLimitCents = 5000;
    }

    @Data
    public static class Consult {
        private int stallRounds = 2;
    }

    @Data
    public static class Policy {
        private String version = "2026-11";
    }

    @Data
    public static class Execution {
        private String mode = "SIMULATED";
    }

    @Data
    public static class Idempotency {
        private long leaseSeconds = 60;
    }

    @Data
    public static class Agent {
        private String mode = "scripted";
        private String baseUrl = "http://localhost:8000";
        private int timeoutMs = 8000;
        private String promptVersion = "p1.0.0";
    }
}
