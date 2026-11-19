package com.chinayiru.aftersale.agent;

import com.chinayiru.aftersale.config.AppProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThatThrownBy;

class HttpAgentClientConfigTest {
    @ParameterizedTest
    @ValueSource(strings = {"", "file:///tmp/agent", "https://user:private-value@agent.example",
            "https://agent.example?key=private-value", "https://agent.example#private-value",
            "https://agent.example.invalid"})
    void rejectsMissingOrCredentialBearingUrlsWithoutEchoingTheValue(String url) {
        AppProperties properties = new AppProperties();
        properties.getAgent().setBaseUrl(url);
        assertThatThrownBy(() -> new HttpAgentClient(properties, new ObjectMapper()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("APP_AGENT_BASE_URL")
                .hasMessageNotContaining("private-value");
    }
}
