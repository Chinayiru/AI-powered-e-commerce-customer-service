package com.chinayiru.aftersale.agent;

import com.chinayiru.aftersale.config.AppProperties;
import com.chinayiru.aftersale.tool.OrderToolService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AgentClientConfig {

    @Bean
    @ConditionalOnMissingBean(AgentClient.class)
    public AgentClient agentClient(AppProperties properties, ObjectMapper objectMapper, OrderToolService orderTools) {
        if ("http".equalsIgnoreCase(properties.getAgent().getMode())) {
            return new HttpAgentClient(properties, objectMapper);
        }
        return new ScriptedAgentClient(properties, orderTools);
    }
}
