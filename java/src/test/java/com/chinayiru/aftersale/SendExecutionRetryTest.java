package com.chinayiru.aftersale;

import com.chinayiru.aftersale.service.SimulatedExecutor;
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

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;

/**
 * send 的"确认后执行"两段式回归测试。
 *
 * <p>覆盖此前无人测试的分支：执行段失败 → 202 + CONFIRMED。旧实现既不允许从 CONFIRMED 继续，
 * 也没有任何出口，工单永久卡死；这里逐条钉住修复后的行为，同时确认
 * "同一 requestId 不得重复批准或执行"这条契约约束没被破坏。
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class SendExecutionRetryTest {

    private static final String AGENT_TOKEN = "test-only-agent-fixture-0123456789abcdef";

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;
    @Autowired
    private JdbcTemplate jdbc;

    @MockBean
    private SimulatedExecutor executor;

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
    void executionFailureReturns202AndLeavesTicketRetryable() throws Exception {
        String ticketId = prepareDraftReadyTicket();
        JsonNode view = agentView(ticketId);
        String draftReply = view.path("draft").path("replyDraft").asText();
        int version = view.path("ticket").path("version").asInt();

        doThrow(new IllegalStateException("simulated execution failure"))
                .when(executor).execute(anyString(), anyString());
        MvcResult failed = send(ticketId, draftReply, version, "已人工复核", UUID.randomUUID().toString());

        assertThat(failed.getResponse().getStatus()).isEqualTo(202);
        JsonNode failedBody = json(failed);
        assertThat(failedBody.path("state").asText()).isEqualTo("CONFIRMED");
        // 202 必须回传版本，否则客户端无法构造下一次重试的 expectedVersion。
        assertThat(failedBody.path("version").asInt()).isEqualTo(version + 1);
        assertThat(state(ticketId)).isEqualTo("CONFIRMED");
        assertThat(taskStates(ticketId)).containsExactly("FAILED");
    }

    @Test
    void sameRequestIdIsReplayedAndNotReexecuted() throws Exception {
        String ticketId = prepareDraftReadyTicket();
        JsonNode view = agentView(ticketId);
        String draftReply = view.path("draft").path("replyDraft").asText();
        int version = view.path("ticket").path("version").asInt();
        String requestId = UUID.randomUUID().toString();

        doThrow(new IllegalStateException("boom")).when(executor).execute(anyString(), anyString());
        assertThat(send(ticketId, draftReply, version, "已人工复核", requestId)
                .getResponse().getStatus()).isEqualTo(202);

        // 契约：同一 requestId 重复提交返回原 202 结果，不得重复执行。
        doNothing().when(executor).execute(anyString(), anyString());
        MvcResult replayed = send(ticketId, draftReply, version, "已人工复核", requestId);
        assertThat(replayed.getResponse().getStatus()).isEqualTo(202);
        assertThat(json(replayed).path("state").asText()).isEqualTo("CONFIRMED");
        verify(executor, times(1)).execute(anyString(), anyString());
        assertThat(state(ticketId)).isEqualTo("CONFIRMED");
    }

    @Test
    void retryWithNewRequestIdClosesTicket() throws Exception {
        String ticketId = prepareDraftReadyTicket();
        JsonNode view = agentView(ticketId);
        String draftReply = view.path("draft").path("replyDraft").asText();
        int version = view.path("ticket").path("version").asInt();

        doThrow(new IllegalStateException("boom")).when(executor).execute(anyString(), anyString());
        MvcResult failed = send(ticketId, draftReply, version, "已人工复核", UUID.randomUUID().toString());
        assertThat(failed.getResponse().getStatus()).isEqualTo(202);
        int retryVersion = json(failed).path("version").asInt();

        doNothing().when(executor).execute(anyString(), anyString());
        MvcResult retried = send(ticketId, draftReply, retryVersion, "已人工复核",
                UUID.randomUUID().toString());
        assertThat(retried.getResponse().getStatus()).isEqualTo(200);
        assertThat(json(retried).path("state").asText()).isEqualTo("CLOSED");
        assertThat(state(ticketId)).isEqualTo("CLOSED");

        // 确认段只落库一次：坐席回复不应被写两遍；重试要补一条任务，审计链不能断。
        assertThat(jdbc.queryForObject(
                "SELECT COUNT(*) FROM ticket_message WHERE ticket_id = ? AND text = ?",
                Integer.class, ticketId, draftReply)).isEqualTo(1);
        assertThat(taskStates(ticketId)).containsExactlyInAnyOrder("FAILED", "DONE");
    }

    @Test
    void successfulSendIsReplayedByIdempotency() throws Exception {
        String ticketId = prepareDraftReadyTicket();
        JsonNode view = agentView(ticketId);
        String draftReply = view.path("draft").path("replyDraft").asText();
        int version = view.path("ticket").path("version").asInt();
        String requestId = UUID.randomUUID().toString();

        assertThat(send(ticketId, draftReply, version, "已人工复核", requestId)
                .getResponse().getStatus()).isEqualTo(200);
        MvcResult replayed = send(ticketId, draftReply, version, "已人工复核", requestId);
        assertThat(replayed.getResponse().getStatus()).isEqualTo(200);
        assertThat(json(replayed).path("state").asText()).isEqualTo("CLOSED");
        verify(executor, times(1)).execute(anyString(), anyString());
    }

    @Test
    void retryWithStaleVersionIsRejected() throws Exception {
        String ticketId = prepareDraftReadyTicket();
        JsonNode view = agentView(ticketId);
        String draftReply = view.path("draft").path("replyDraft").asText();
        int version = view.path("ticket").path("version").asInt();

        doThrow(new IllegalStateException("boom")).when(executor).execute(anyString(), anyString());
        assertThat(send(ticketId, draftReply, version, "已人工复核", UUID.randomUUID().toString())
                .getResponse().getStatus()).isEqualTo(202);

        MvcResult stale = send(ticketId, draftReply, version, "已人工复核", UUID.randomUUID().toString());
        assertThat(stale.getResponse().getStatus()).isEqualTo(409);
        assertThat(json(stale).path("code").asText()).isEqualTo("STALE_STATE");
        assertThat(state(ticketId)).isEqualTo("CONFIRMED");
    }

    private String prepareDraftReadyTicket() throws Exception {
        MvcResult created = postJson("/api/tickets", ticketBody("AFTERSALE", "我要退款", "O1001", "U001"),
                "X-User-Id", "U001");
        assertThat(created.getResponse().getStatus()).isEqualTo(201);
        String ticketId = json(created).path("ticketId").asText();
        assertThat(state(ticketId)).isEqualTo("DRAFT_READY");
        return ticketId;
    }

    private MvcResult send(String ticketId, String text, int expectedVersion, String reviewNote,
                           String requestId) throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("text", text);
        body.put("draftVersion", 1);
        body.put("reviewNote", reviewNote);
        body.put("expectedVersion", expectedVersion);
        body.put("requestId", requestId);
        return postJson("/api/agent/tickets/" + ticketId + "/send", body, "X-Agent-Token", AGENT_TOKEN);
    }

    private String state(String ticketId) {
        return jdbc.queryForObject("SELECT state FROM aftersale_ticket WHERE ticket_id = ?",
                String.class, ticketId);
    }

    private List<String> taskStates(String ticketId) {
        return jdbc.queryForList("SELECT state FROM execution_task WHERE ticket_id = ? ORDER BY task_id",
                String.class, ticketId);
    }

    private JsonNode agentView(String ticketId) throws Exception {
        MvcResult result = mockMvc.perform(get("/api/agent/tickets/{id}", ticketId)
                .header("X-Agent-Token", AGENT_TOKEN)).andReturn();
        assertThat(result.getResponse().getStatus()).isEqualTo(200);
        return json(result);
    }

    private Map<String, Object> ticketBody(String category, String text, String orderNo, String userId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("category", category);
        body.put("text", text);
        if (orderNo != null) {
            body.put("orderNo", orderNo);
        }
        body.put("requestId", UUID.randomUUID().toString());
        return body;
    }

    private MvcResult postJson(String path, Object body, String... headers) throws Exception {
        var builder = post(path).contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsBytes(body));
        for (int i = 0; i + 1 < headers.length; i += 2) {
            builder.header(headers[i], headers[i + 1]);
        }
        return mockMvc.perform(builder).andReturn();
    }

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsByteArray());
    }
}
