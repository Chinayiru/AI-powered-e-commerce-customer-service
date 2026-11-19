package com.chinayiru.aftersale;

import com.chinayiru.aftersale.agent.AgentClient;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;

/**
 * 生成链路未预期异常必须收敛为 TRANSFERRED(TOOL_FAILED)，不能让工单停在 AI_RUNNING。
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class GenerationFailureTest {

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;
    @Autowired
    private JdbcTemplate jdbc;
    @MockBean
    private AgentClient agentClient;

    @BeforeEach
    void cleanDatabase() {
        jdbc.update("DELETE FROM idempotency_record");
        jdbc.update("DELETE FROM execution_task");
        jdbc.update("DELETE FROM audit_log");
        jdbc.update("DELETE FROM tool_call");
        jdbc.update("DELETE FROM draft");
        jdbc.update("DELETE FROM ticket_message");
        jdbc.update("DELETE FROM aftersale_ticket");
        jdbc.update("DELETE FROM ticket_sequence");
    }

    @Test
    void unexpectedAgentExceptionTransfersInsteadOfLeavingAiRunning() throws Exception {
        when(agentClient.ask(any(), any())).thenThrow(new IllegalStateException("boom"));

        MvcResult created = mockMvc.perform(post("/api/tickets")
                .header("X-User-Id", "U001")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsBytes(body()))).andReturn();
        assertThat(created.getResponse().getStatus()).isEqualTo(201);
        String ticketId = json(created).path("ticketId").asText();

        JsonNode view = json(mockMvc.perform(get("/api/agent/tickets/{id}", ticketId)
                .header("X-Agent-Token", "demo-agent-token")).andReturn());
        assertThat(view.path("ticket").path("state").asText()).isEqualTo("TRANSFERRED");
        assertThat(view.path("ticket").path("transferReason").asText()).isEqualTo("TOOL_FAILED");
        String detail = jdbc.queryForObject(
                "SELECT detail FROM audit_log WHERE ticket_id = ? AND action = 'TRANSFERRED'",
                String.class, ticketId);
        assertThat(detail).contains("IllegalStateException");
    }

    private java.util.Map<String, Object> body() {
        return java.util.Map.of(
                "category", "AFTERSALE",
                "text", "我要退款",
                "orderNo", "O1001",
                "requestId", UUID.randomUUID().toString());
    }

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsByteArray());
    }
}
