package com.chinayiru.aftersale.agent;

import com.chinayiru.aftersale.agent.AgentContract.AskRequest;
import com.chinayiru.aftersale.agent.AgentContract.AskResponse;
import com.chinayiru.aftersale.common.ErrorCode;
import com.chinayiru.aftersale.config.AppProperties;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.io.InterruptedIOException;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;

/**
 * 真实 Python AI 层客户端。只发一次请求、不自动重试；超时/5xx/契约不合法
 * 一律抛 AgentUnavailableException，由状态机降级为转人工。
 */
public class HttpAgentClient implements AgentClient {

    private static final Logger log = LoggerFactory.getLogger(HttpAgentClient.class);

    private final RestClient client;
    private final ObjectMapper strictMapper;
    private final AppProperties properties;

    public HttpAgentClient(AppProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(2000);
        factory.setReadTimeout(properties.getAgent().getTimeoutMs());
        this.client = RestClient.builder()
                .baseUrl(properties.getAgent().getBaseUrl())
                .requestFactory(factory)
                .build();
        this.strictMapper = objectMapper.copy()
                .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, true)
                .configure(DeserializationFeature.FAIL_ON_NULL_FOR_PRIMITIVES, true);
    }

    @Override
    public String provider() {
        return "http";
    }

    @Override
    public AskResponse ask(AskRequest request, String internalIdentity) {
        long start = System.nanoTime();
        String body;
        try {
            body = client.post()
                    .uri("/internal/agent/ask")
                    .header("X-Internal-Identity", internalIdentity)
                    .header("X-Trace-Id", request.traceId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .accept(MediaType.APPLICATION_JSON)
                    .body(request)
                    .exchange((outbound, response) -> {
                        String text = new String(response.getBody().readAllBytes(), StandardCharsets.UTF_8);
                        if (!response.getStatusCode().is2xxSuccessful()) {
                            throw new AgentUnavailableException(ErrorCode.AGENT_UNAVAILABLE,
                                    "AI 服务返回 HTTP " + response.getStatusCode().value());
                        }
                        return text;
                    });
        } catch (AgentUnavailableException e) {
            throw e;
        } catch (ResourceAccessException e) {
            long elapsed = (System.nanoTime() - start) / 1_000_000;
            if (isTimeout(e)) {
                log.warn("agent timeout after {}ms: {}", elapsed, e.getMessage());
                throw new AgentUnavailableException(ErrorCode.TOOL_TIMEOUT, "AI 服务超时", e);
            }
            log.warn("agent unavailable after {}ms: {}", elapsed, e.getMessage());
            throw new AgentUnavailableException(ErrorCode.AGENT_UNAVAILABLE, "AI 服务不可达", e);
        } catch (RestClientException e) {
            log.warn("agent call failed: {}", e.getMessage());
            throw new AgentUnavailableException(ErrorCode.AGENT_UNAVAILABLE, "AI 调用失败", e);
        }

        try {
            AskResponse response = strictMapper.readValue(body, AskResponse.class);
            AgentResponseValidator.validate(response);
            return response;
        } catch (AgentUnavailableException e) {
            throw e;
        } catch (Exception e) {
            log.warn("agent response violates contract: {}", e.getMessage());
            throw new AgentUnavailableException(ErrorCode.AGENT_UNAVAILABLE, "AI 返回不符合契约", e);
        }
    }

    private static boolean isTimeout(Throwable throwable) {
        Throwable current = throwable;
        while (current != null) {
            if (current instanceof SocketTimeoutException
                    || current instanceof InterruptedIOException) {
                return true;
            }
            current = current.getCause();
        }
        return false;
    }
}
