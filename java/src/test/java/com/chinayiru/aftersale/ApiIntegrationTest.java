package com.chinayiru.aftersale;

import com.chinayiru.aftersale.auth.InternalIdentityService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;

/**
 * M-S 主要验收路径的 HTTP 集成测试。使用 scripted agent 与 H2，覆盖 AC01–AC26 中
 * 不依赖真实 Python/MySQL 的部分；结果按 TEST_PLAN 的 AC 编号在断言旁标注。
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class ApiIntegrationTest {

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;
    @Autowired
    private JdbcTemplate jdbc;
    @Autowired
    private InternalIdentityService internalIdentity;

    private static final String AGENT_TOKEN = "demo-agent-token";

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
    void createsConsultWithoutLeakingInternalFields() throws Exception {
        JsonNode created = createTicket("CONSULT", "我买的 O1001 想退款，怎么办？", "O1001", "U001");
        assertThat(created.path("ticketId").asText()).startsWith("T");
        assertThat(created.hasNonNull("ticketToken")).isTrue();
        assertThat(created.path("category").asText()).isEqualTo("CONSULT");
        // AC04：消费者响应不能出现内部状态/意图/置信度。
        assertThat(created.has("state")).isFalse();
        assertThat(created.has("intent")).isFalse();
        assertThat(created.has("confidence")).isFalse();
        assertThat(created.has("policyCheck")).isFalse();

        JsonNode view = json(mockMvc.perform(get("/api/tickets/{id}", created.path("ticketId").asText())
                .header("Authorization", "Bearer " + created.path("ticketToken").asText())).andReturn());
        assertThat(view.has("messages")).isTrue();
        assertThat(view.has("state")).isFalse();
        assertThat(view.has("intent")).isFalse();
        assertThat(view.has("policyCheck")).isFalse();
    }

    @Test
    void sameRequestIdReplaysSameTicket() throws Exception {
        String requestId = UUID.randomUUID().toString();
        JsonNode first = createTicketWithId("CONSULT", "订单 O1002 的物流到哪了", "O1002", "U001", requestId);
        JsonNode second = createTicketWithId("CONSULT", "订单 O1002 的物流到哪了", "O1002", "U001", requestId);
        assertThat(second.path("ticketId").asText()).isEqualTo(first.path("ticketId").asText());
    }

    @Test
    void sameRequestIdDifferentBodyConflicts() throws Exception {
        String requestId = UUID.randomUUID().toString();
        createTicketWithId("CONSULT", "订单 O1002 的物流到哪了", "O1002", "U001", requestId);
        MvcResult conflict = postJson("/api/tickets", ticketBody("CONSULT", "换个说法", "O1002", requestId),
                "X-User-Id", "U001");
        assertThat(conflict.getResponse().getStatus()).isEqualTo(409);
        assertThat(json(conflict).path("code").asText()).isEqualTo("IDEMPOTENCY_CONFLICT");
    }

    @Test
    void duplicateActiveAftersaleForSameOrderIsRejected() throws Exception {
        createTicket("AFTERSALE", "我要退款", "O1001", "U001");
        MvcResult duplicate = postJson("/api/tickets", ticketBody("AFTERSALE", "再退一次", "O1001", null),
                "X-User-Id", "U001");
        assertThat(duplicate.getResponse().getStatus()).isEqualTo(409);
        assertThat(json(duplicate).path("code").asText()).isEqualTo("DUPLICATE_REQUEST");
    }

    @Test
    void consultRefundCreatesAssociatedAftersale() throws Exception {
        JsonNode consult = createTicket("CONSULT", "我买的 O1001 想退款，怎么办？", "O1001", "U001");
        JsonNode result = json(mockMvc.perform(post("/api/tickets/{id}/messages", consult.path("ticketId").asText())
                .header("Authorization", "Bearer " + consult.path("ticketToken").asText())
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsBytes(messageBody("那就帮我退了吧", null)))).andReturn());
        assertThat(result.hasNonNull("createdTicket")).isTrue();
        JsonNode associated = result.path("createdTicket");
        assertThat(associated.path("category").asText()).isEqualTo("AFTERSALE");
        assertThat(associated.path("ticketId").asText()).isNotEqualTo(consult.path("ticketId").asText());
        assertThat(associated.path("displayState").asText()).isEqualTo("处理中");
    }

    @Test
    void aftersaleWithoutOrderWaitsThenTransfers() throws Exception {
        JsonNode created = createTicket("AFTERSALE", "我要退款", null, "U001");
        assertThat(created.path("displayState").asText()).isEqualTo("待补充信息");
        String ticketId = created.path("ticketId").asText();
        String token = created.path("ticketToken").asText();

        for (int i = 0; i < 2; i++) {
            JsonNode result = json(mockMvc.perform(post("/api/tickets/{id}/messages", ticketId)
                    .header("Authorization", "Bearer " + token)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(objectMapper.writeValueAsBytes(messageBody("我没有订单号" + i, null)))).andReturn());
            if (i == 1) {
                assertThat(result.path("displayState").asText()).isEqualTo("待人工处理");
            }
        }
        JsonNode agent = agentView(ticketId);
        assertThat(agent.path("ticket").path("state").asText()).isEqualTo("TRANSFERRED");
        assertThat(agent.path("ticket").path("transferReason").asText()).isEqualTo("INSUFFICIENT_INFO");
    }

    @Test
    void unknownOrderFirstAsksThenTransfers() throws Exception {
        JsonNode created = createTicket("CONSULT", "订单 O9999 到哪了", null, "U001");
        assertThat(created.path("displayState").asText()).isEqualTo("待补充信息");
        String ticketId = created.path("ticketId").asText();
        String token = created.path("ticketToken").asText();
        JsonNode result = json(mockMvc.perform(post("/api/tickets/{id}/messages", ticketId)
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsBytes(messageBody("就是 O9999", null)))).andReturn());
        assertThat(result.path("displayState").asText()).isEqualTo("待人工处理");
        JsonNode agent = agentView(ticketId);
        assertThat(agent.path("ticket").path("state").asText()).isEqualTo("TRANSFERRED");
        assertThat(agent.path("ticket").path("transferReason").asText()).isEqualTo("ORDER_NOT_FOUND");
    }

    @Test
    void outsideReturnWindowDraftCannotBeSent() throws Exception {
        JsonNode created = createTicket("AFTERSALE", "我要退款", "O1003", "U001");
        String ticketId = created.path("ticketId").asText();
        JsonNode agent = agentView(ticketId);
        assertThat(agent.path("ticket").path("state").asText()).isEqualTo("DRAFT_READY");
        assertThat(agent.path("policyCheck").path("allowed").asBoolean()).isFalse();
        assertThat(agent.path("policyCheck").path("code").asText()).isEqualTo("OUTSIDE_RETURN_WINDOW");

        MvcResult send = postJson("/api/agent/tickets/" + ticketId + "/send",
                sendBody("已为您提交退款申请（演示环境，未真实退款）。", 1, "已人工复核", 3, null),
                "X-Agent-Token", AGENT_TOKEN);
        assertThat(send.getResponse().getStatus()).isEqualTo(409);
        assertThat(json(send).path("code").asText()).isEqualTo("POLICY_REJECTED");
        assertThat(agentView(ticketId).path("ticket").path("state").asText()).isEqualTo("DRAFT_READY");
    }

    @Test
    void overLimitDraftRequiresReviewNote() throws Exception {
        JsonNode created = createTicket("AFTERSALE", "我要退款", "O1006", "U001");
        String ticketId = created.path("ticketId").asText();
        JsonNode agent = agentView(ticketId);
        assertThat(agent.path("draft").path("suggestedAction").path("amountCents").asLong()).isEqualTo(25000);
        assertThat(agent.path("needHumanReview").asBoolean()).isTrue();

        MvcResult withoutNote = postJson("/api/agent/tickets/" + ticketId + "/send",
                sendBody("已为您提交退款申请（演示环境，未真实退款）。", 1, null, 3, null),
                "X-Agent-Token", AGENT_TOKEN);
        assertThat(withoutNote.getResponse().getStatus()).isEqualTo(422);
        assertThat(json(withoutNote).path("code").asText()).isEqualTo("REVIEW_NOTE_REQUIRED");

        MvcResult withNote = postJson("/api/agent/tickets/" + ticketId + "/send",
                sendBody("已为您提交退款申请（演示环境，未真实退款）。", 1, "已人工复核确认", 3, null),
                "X-Agent-Token", AGENT_TOKEN);
        assertThat(withNote.getResponse().getStatus()).isEqualTo(200);
        assertThat(json(withNote).path("state").asText()).isEqualTo("CLOSED");
    }

    @Test
    void sendIsIdempotentAndConsumerSeesCompletion() throws Exception {
        JsonNode created = createTicket("AFTERSALE", "我要退款", "O1001", "U001");
        String ticketId = created.path("ticketId").asText();
        String requestId = UUID.randomUUID().toString();
        Map<String, Object> body = sendBody("已为您提交退款申请（演示环境，未真实退款）。", 1,
                "已人工复核", 3, requestId);

        MvcResult first = postJson("/api/agent/tickets/" + ticketId + "/send", body,
                "X-Agent-Token", AGENT_TOKEN);
        assertThat(first.getResponse().getStatus()).isEqualTo(200);
        assertThat(json(first).path("state").asText()).isEqualTo("CLOSED");

        MvcResult replay = postJson("/api/agent/tickets/" + ticketId + "/send", body,
                "X-Agent-Token", AGENT_TOKEN);
        assertThat(replay.getResponse().getStatus()).isEqualTo(200);
        assertThat(json(replay).path("state").asText()).isEqualTo("CLOSED");

        JsonNode view = json(mockMvc.perform(get("/api/tickets/{id}", ticketId)
                .header("Authorization", "Bearer " + created.path("ticketToken").asText())).andReturn());
        assertThat(view.path("displayState").asText()).isEqualTo("已完成");
        assertThat(view.toString()).contains("演示环境，未真实退款");
        assertThat(view.has("state")).isFalse();
    }

    @Test
    void staleDraftVersionRejectedAfterRegenerate() throws Exception {
        JsonNode created = createTicket("AFTERSALE", "我要退款", "O1001", "U001");
        String ticketId = created.path("ticketId").asText();
        MvcResult regenerated = postJson("/api/agent/tickets/" + ticketId + "/regenerate",
                regenerateBody(3, null), "X-Agent-Token", AGENT_TOKEN);
        assertThat(regenerated.getResponse().getStatus()).isEqualTo(202);
        JsonNode agent = agentView(ticketId);
        assertThat(agent.path("ticket").path("state").asText()).isEqualTo("DRAFT_READY");
        assertThat(agent.path("draft").path("draftVersion").asInt()).isEqualTo(2);

        MvcResult send = postJson("/api/agent/tickets/" + ticketId + "/send",
                sendBody("已为您提交退款申请（演示环境，未真实退款）。", 1, "已人工复核",
                        agent.path("ticket").path("version").asInt(), null),
                "X-Agent-Token", AGENT_TOKEN);
        assertThat(send.getResponse().getStatus()).isEqualTo(409);
        assertThat(json(send).path("code").asText()).isEqualTo("STALE_DRAFT");
    }

    @Test
    void cancelDraftReadyThenRejectSecondCancel() throws Exception {
        JsonNode created = createTicket("AFTERSALE", "我要退款", "O1001", "U001");
        String ticketId = created.path("ticketId").asText();
        String token = created.path("ticketToken").asText();
        JsonNode cancelled = json(mockMvc.perform(post("/api/tickets/{id}/cancel", ticketId)
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsBytes(Map.of("requestId", UUID.randomUUID().toString(),
                        "expectedVersion", 3)))).andReturn());
        assertThat(cancelled.path("displayState").asText()).isEqualTo("已取消");

        MvcResult again = postJson("/api/tickets/" + ticketId + "/cancel",
                Map.of("requestId", UUID.randomUUID().toString(), "expectedVersion", 4),
                "Authorization", "Bearer " + token);
        assertThat(again.getResponse().getStatus()).isEqualTo(409);
        assertThat(json(again).path("code").asText()).isEqualTo("STATE_NOT_ALLOWED");
    }

    @Test
    void ticketTokenScopeIsEnforced() throws Exception {
        JsonNode mine = createTicket("CONSULT", "订单 O1002 的物流到哪了", "O1002", "U001");
        JsonNode other = createTicket("CONSULT", "订单 O1004 的物流到哪了", "O1004", "U002");
        String otherToken = other.path("ticketToken").asText();

        MvcResult forbidden = mockMvc.perform(get("/api/tickets/{id}", mine.path("ticketId").asText())
                .header("Authorization", "Bearer " + otherToken)).andReturn();
        assertThat(forbidden.getResponse().getStatus()).isEqualTo(403);
        assertThat(json(forbidden).path("code").asText()).isEqualTo("FORBIDDEN_SCOPE");

        MvcResult missing = mockMvc.perform(get("/api/tickets/{id}", mine.path("ticketId").asText())).andReturn();
        assertThat(missing.getResponse().getStatus()).isEqualTo(401);

        MvcResult agentMissing = mockMvc.perform(get("/api/agent/tickets/{id}",
                mine.path("ticketId").asText())).andReturn();
        assertThat(agentMissing.getResponse().getStatus()).isEqualTo(401);
    }

    @Test
    void unknownRequestFieldsAreIgnored() throws Exception {
        Map<String, Object> body = ticketBody("CONSULT", "订单 O1002 的物流到哪了", "O1002", null);
        body.put("unexpectedField", "ignored");
        MvcResult result = postJson("/api/tickets", body, "X-User-Id", "U001");
        assertThat(result.getResponse().getStatus()).isEqualTo(201);
    }

    @Test
    void traceIdIsPropagatedToAudit() throws Exception {
        String traceId = "trace-ac25-test";
        MvcResult result = mockMvc.perform(post("/api/tickets")
                .header("X-User-Id", "U001")
                .header("X-Trace-Id", traceId)
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsBytes(ticketBody("CONSULT", "订单 O1002 的物流到哪了",
                        "O1002", null)))).andReturn();
        assertThat(result.getResponse().getStatus()).isEqualTo(201);
        String ticketId = json(result).path("ticketId").asText();
        String audited = jdbc.queryForObject(
                "SELECT trace_id FROM audit_log WHERE ticket_id = ? ORDER BY id DESC LIMIT 1",
                String.class, ticketId);
        assertThat(audited).isEqualTo(traceId);
    }

    @Test
    void internalToolsVerifyIdentityAndOwnership() throws Exception {
        MvcResult anonymous = postJson("/internal/tools/queryOrder", Map.of("orderNo", "O1001"));
        assertThat(anonymous.getResponse().getStatus()).isEqualTo(401);

        String identity = internalIdentity.issue("U001", "python");
        MvcResult own = postJson("/internal/tools/queryOrder", Map.of("orderNo", "O1001"),
                "X-Internal-Identity", identity);
        assertThat(own.getResponse().getStatus()).isEqualTo(200);
        assertThat(json(own).path("orderNo").asText()).isEqualTo("O1001");

        MvcResult replay = postJson("/internal/tools/queryOrder", Map.of("orderNo", "O1001"),
                "X-Internal-Identity", identity);
        assertThat(replay.getResponse().getStatus()).isEqualTo(401);

        String other = internalIdentity.issue("U002", "python");
        MvcResult forbidden = postJson("/internal/tools/queryOrder", Map.of("orderNo", "O1001"),
                "X-Internal-Identity", other);
        assertThat(forbidden.getResponse().getStatus()).isEqualTo(404);
        assertThat(json(forbidden).path("code").asText()).isEqualTo("ORDER_NOT_FOUND");
    }

    @Test
    void handoffReplyAndCloseFlow() throws Exception {
        JsonNode created = createTicket("AFTERSALE", "我要退款", "O1001", "U001");
        String ticketId = created.path("ticketId").asText();

        MvcResult badReason = postJson("/api/agent/tickets/" + ticketId + "/handoff",
                handoffBody("NOT_A_REASON", 3, null), "X-Agent-Token", AGENT_TOKEN);
        assertThat(badReason.getResponse().getStatus()).isEqualTo(422);

        MvcResult handedOff = postJson("/api/agent/tickets/" + ticketId + "/handoff",
                handoffBody("POLICY_BLOCKED", 3, null), "X-Agent-Token", AGENT_TOKEN);
        assertThat(handedOff.getResponse().getStatus()).isEqualTo(200);
        assertThat(json(handedOff).path("state").asText()).isEqualTo("TRANSFERRED");

        MvcResult replied = postJson("/api/agent/tickets/" + ticketId + "/reply",
                writeBody("已核实，稍后回电。", 4, null), "X-Agent-Token", AGENT_TOKEN);
        assertThat(replied.getResponse().getStatus()).isEqualTo(200);
        assertThat(json(replied).path("state").asText()).isEqualTo("REPLIED");

        MvcResult closed = postJson("/api/agent/tickets/" + ticketId + "/close",
                versionBody(5, null), "X-Agent-Token", AGENT_TOKEN);
        assertThat(closed.getResponse().getStatus()).isEqualTo(200);
        assertThat(json(closed).path("state").asText()).isEqualTo("CLOSED");
    }

    @Test
    void alreadyRefundedOrderTransfersWithoutDraft() throws Exception {
        JsonNode created = createTicket("AFTERSALE", "我要退款", "O1010", "U001");
        JsonNode agent = agentView(created.path("ticketId").asText());
        assertThat(agent.path("ticket").path("state").asText()).isEqualTo("TRANSFERRED");
        assertThat(agent.path("ticket").path("transferReason").asText()).isEqualTo("POLICY_BLOCKED");
        assertThat(agent.path("draft").isNull() || agent.path("draft").isMissingNode()).isTrue();
    }

    @Test
    void editDistanceIsComputedServerSide() throws Exception {
        JsonNode created = createTicket("AFTERSALE", "我要退款", "O1001", "U001");
        String ticketId = created.path("ticketId").asText();
        JsonNode agent = agentView(ticketId);
        String draftReply = agent.path("draft").path("replyDraft").asText();

        MvcResult sent = postJson("/api/agent/tickets/" + ticketId + "/send",
                sendBody(draftReply, 1, "已人工复核", 3, null), "X-Agent-Token", AGENT_TOKEN);
        assertThat(sent.getResponse().getStatus()).isEqualTo(200);
        assertThat(json(sent).path("edited").asBoolean()).isFalse();
        assertThat(json(sent).path("editDistance").asInt()).isZero();
    }

    private JsonNode createTicket(String category, String text, String orderNo, String userId) throws Exception {
        return createTicketWithId(category, text, orderNo, userId, UUID.randomUUID().toString());
    }

    private JsonNode createTicketWithId(String category, String text, String orderNo, String userId,
                                        String requestId) throws Exception {
        MvcResult result = postJson("/api/tickets", ticketBody(category, text, orderNo, requestId),
                "X-User-Id", userId);
        assertThat(result.getResponse().getStatus()).isEqualTo(201);
        return json(result);
    }

    private JsonNode agentView(String ticketId) throws Exception {
        MvcResult result = mockMvc.perform(get("/api/agent/tickets/{id}", ticketId)
                .header("X-Agent-Token", AGENT_TOKEN)).andReturn();
        assertThat(result.getResponse().getStatus()).isEqualTo(200);
        return json(result);
    }

    private Map<String, Object> ticketBody(String category, String text, String orderNo, String requestId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("category", category);
        body.put("text", text);
        if (orderNo != null) {
            body.put("orderNo", orderNo);
        }
        body.put("requestId", requestId == null ? UUID.randomUUID().toString() : requestId);
        return body;
    }

    private Map<String, Object> messageBody(String text, String requestId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("text", text);
        body.put("requestId", requestId == null ? UUID.randomUUID().toString() : requestId);
        return body;
    }

    private Map<String, Object> sendBody(String text, int draftVersion, String reviewNote,
                                         int expectedVersion, String requestId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("text", text);
        body.put("draftVersion", draftVersion);
        if (reviewNote != null) {
            body.put("reviewNote", reviewNote);
        }
        body.put("expectedVersion", expectedVersion);
        body.put("requestId", requestId == null ? UUID.randomUUID().toString() : requestId);
        return body;
    }

    private Map<String, Object> regenerateBody(int expectedVersion, String requestId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("expectedVersion", expectedVersion);
        body.put("requestId", requestId == null ? UUID.randomUUID().toString() : requestId);
        return body;
    }

    private Map<String, Object> handoffBody(String reason, int expectedVersion, String requestId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("reason", reason);
        body.put("expectedVersion", expectedVersion);
        body.put("requestId", requestId == null ? UUID.randomUUID().toString() : requestId);
        return body;
    }

    private Map<String, Object> writeBody(String text, int expectedVersion, String requestId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("text", text);
        body.put("expectedVersion", expectedVersion);
        body.put("requestId", requestId == null ? UUID.randomUUID().toString() : requestId);
        return body;
    }

    private Map<String, Object> versionBody(int expectedVersion, String requestId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("expectedVersion", expectedVersion);
        body.put("requestId", requestId == null ? UUID.randomUUID().toString() : requestId);
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
