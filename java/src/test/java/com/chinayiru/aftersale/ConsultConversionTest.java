package com.chinayiru.aftersale;

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
 * AC20「咨询转售后」的两条入口回归。
 *
 * <p>两条入口历史上行为不一致：{@code POST /messages} 会用 {@code createdTicket} 回传新单凭据，
 * 而 {@code POST /api/tickets} 建单时就转单的场景把新单凭据丢掉了——客户端拿到的是原咨询单
 * 的凭据，原单此时是「已回复」但没有任何回复文案，新单则完全不可达。这里同时钉住两条入口。
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class ConsultConversionTest {

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;
    @Autowired
    private JdbcTemplate jdbc;

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
    void consultCreateWithRefundIntentReturnsAssociatedAftersaleTicket() throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("category", "CONSULT");
        body.put("text", "我要把 O1005 这笔退掉，不想要了");
        body.put("orderNo", "O1005");
        body.put("requestId", UUID.randomUUID().toString());

        MvcResult created = postJson("/api/tickets", body, null);
        assertThat(created.getResponse().getStatus()).isEqualTo(201);
        JsonNode ticket = json(created);
        assertThat(ticket.path("category").asText()).isEqualTo("AFTERSALE");
        assertThat(ticket.path("ticketToken").asText()).isNotBlank();

        // 回传的凭据必须直指新售后单：用它查单能看到复制过来的客户诉求。
        MvcResult view = mockMvc.perform(get("/api/tickets/" + ticket.path("ticketId").asText())
                .header("Authorization", "Bearer " + ticket.path("ticketToken").asText())).andReturn();
        assertThat(view.getResponse().getStatus()).isEqualTo(200);
        JsonNode viewed = json(view);
        assertThat(viewed.path("displayState").asText()).isEqualTo("处理中");
        assertThat(viewed.path("messages").toString()).contains("我要把 O1005 这笔退掉");

        Integer converted = jdbc.queryForObject(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'CONSULT_TO_AFTERSALE'", Integer.class);
        Integer shell = jdbc.queryForObject(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'ASSOCIATED_TICKET_CREATED'", Integer.class);
        assertThat(converted).isEqualTo(1);
        assertThat(shell).isEqualTo(1);
        Integer consultCount = jdbc.queryForObject(
                "SELECT COUNT(*) FROM aftersale_ticket WHERE category = 'CONSULT'", Integer.class);
        Integer aftersaleCount = jdbc.queryForObject(
                "SELECT COUNT(*) FROM aftersale_ticket WHERE category = 'AFTERSALE'", Integer.class);
        assertThat(consultCount).isEqualTo(1);
        assertThat(aftersaleCount).isEqualTo(1);
        String parent = jdbc.queryForObject(
                "SELECT parent_consult_ticket_id FROM aftersale_ticket WHERE category = 'AFTERSALE'", String.class);
        assertThat(parent).isNotBlank();
    }

    @Test
    void consultFollowUpRefundMessageReturnsCreatedTicket() throws Exception {
        Map<String, Object> consult = new LinkedHashMap<>();
        consult.put("category", "CONSULT");
        consult.put("text", "退货运费谁承担？");
        consult.put("orderNo", "O1001");
        consult.put("requestId", UUID.randomUUID().toString());
        MvcResult created = postJson("/api/tickets", consult, null);
        JsonNode ticket = json(created);
        assertThat(created.getResponse().getStatus()).isEqualTo(201);
        assertThat(ticket.path("category").asText()).isEqualTo("CONSULT");
        assertThat(ticket.path("displayState").asText()).isEqualTo("已回复");

        String ticketId = ticket.path("ticketId").asText();
        String token = ticket.path("ticketToken").asText();
        Map<String, Object> message = new LinkedHashMap<>();
        message.put("text", "那我直接退款吧，帮我退掉");
        message.put("requestId", UUID.randomUUID().toString());

        MvcResult replied = mockMvc.perform(post("/api/tickets/" + ticketId + "/messages")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsBytes(message))).andReturn();
        assertThat(replied.getResponse().getStatus()).isEqualTo(200);
        JsonNode result = json(replied);
        assertThat(result.path("displayState").asText()).isEqualTo("已回复");
        JsonNode createdTicket = result.path("createdTicket");
        assertThat(createdTicket.isMissingNode()).isFalse();
        assertThat(createdTicket.path("category").asText()).isEqualTo("AFTERSALE");
        assertThat(createdTicket.path("ticketToken").asText()).isNotBlank();

        MvcResult view = mockMvc.perform(get("/api/tickets/" + createdTicket.path("ticketId").asText())
                .header("Authorization", "Bearer " + createdTicket.path("ticketToken").asText())).andReturn();
        assertThat(view.getResponse().getStatus()).isEqualTo(200);
        assertThat(json(view).path("displayState").asText()).isEqualTo("处理中");
    }

    private MvcResult postJson(String path, Object body, String bearer) throws Exception {
        var builder = org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post(path)
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsBytes(body));
        if (bearer == null) {
            builder.header("X-User-Id", "U001");
        } else {
            builder.header("Authorization", "Bearer " + bearer);
        }
        return mockMvc.perform(builder).andReturn();
    }

    private JsonNode json(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsByteArray());
    }
}
