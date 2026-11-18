package com.chinayiru.aftersale.api;

import java.net.URI;
import java.util.Collections;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.Set;

import javax.servlet.http.HttpServletRequest;

import org.apache.http.client.config.RequestConfig;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClients;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.ResponseErrorHandler;
import org.springframework.web.client.RestTemplate;

/**
 * 把 /api/** 原样转给 Python 服务。
 *
 * <p>为什么是反代而不是重写：前端只认一套 API（app/api/server.py），Java 侧再实现
 * 一份就是第二套规则（NG-6 明令禁止）。这里连响应码、响应体、错误结构都原样透传，
 * 前端看到的 422/503 与直连 Python 时完全一致。
 */
@RestController
public class ApiProxyController {

    /** 逐跳头：不能跨代理转发，其中 content-length 交给 RestTemplate 重算。 */
    private static final Set<String> HOP_BY_HOP = new HashSet<String>();

    static {
        Collections.addAll(HOP_BY_HOP,
            "host", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
            "te", "trailer", "transfer-encoding", "upgrade", "content-length", "accept-encoding");
    }

    private final RestTemplate restTemplate;
    private final String apiBase;
    private static final org.slf4j.Logger logger =
        org.slf4j.LoggerFactory.getLogger(ApiProxyController.class);

    public ApiProxyController(@Value("${aftersale.api-base:http://127.0.0.1:8000}") String apiBase) {
        this.apiBase = apiBase.replaceAll("/+$", "");
        // 真实模型单次跑单可能几十秒；给足读超时，但绝不无限等
        RequestConfig config = RequestConfig.custom()
            .setConnectTimeout(5000)
            .setConnectionRequestTimeout(5000)
            .setSocketTimeout(120000)
            .build();
        CloseableHttpClient client = HttpClients.custom()
            .setDefaultRequestConfig(config)
            .disableAutomaticRetries()
            .build();
        this.restTemplate = new RestTemplate(new HttpComponentsClientHttpRequestFactory(client));
        // 4xx/5xx 是业务结果（404 无记录、422 参数错、503 未配操作人），必须透传而不是抛异常
        this.restTemplate.setErrorHandler(new ResponseErrorHandler() {
            @Override
            public boolean hasError(org.springframework.http.client.ClientHttpResponse response) {
                return false;
            }

            @Override
            public void handleError(org.springframework.http.client.ClientHttpResponse response) {
                // no-op
            }
        });
    }

    @RequestMapping("/api/**")
    public ResponseEntity<byte[]> proxy(HttpServletRequest request,
                                        @RequestBody(required = false) byte[] body) {
        String path = request.getRequestURI();
        String query = request.getQueryString();
        URI target = URI.create(apiBase + path + (query == null || query.isEmpty() ? "" : "?" + query));

        HttpHeaders headers = new HttpHeaders();
        Enumeration<String> names = request.getHeaderNames();
        while (names != null && names.hasMoreElements()) {
            String name = names.nextElement();
            if (HOP_BY_HOP.contains(name.toLowerCase())) {
                continue;
            }
            // 操作人身份头 X-Operator-Id / X-Operator-Token 必须原样过去，否则 Java 入口会把鉴权吃掉
            for (String value : Collections.list(request.getHeaders(name))) {
                headers.add(name, value);
            }
        }

        HttpMethod method = HttpMethod.valueOf(request.getMethod());
        HttpEntity<byte[]> entity = new HttpEntity<byte[]>(body, headers);
        try {
            ResponseEntity<byte[]> upstream = restTemplate.exchange(target, method, entity, byte[].class);
            HttpHeaders out = new HttpHeaders();
            for (String name : upstream.getHeaders().keySet()) {
                if (HOP_BY_HOP.contains(name.toLowerCase())) {
                    continue;
                }
                out.put(name, upstream.getHeaders().get(name));
            }
            return new ResponseEntity<byte[]>(upstream.getBody(), out, upstream.getStatusCode());
        } catch (ResourceAccessException exc) {
            logger.warn("proxy failed: {} {} -> {}", request.getMethod(), target, exc.toString());
            // Python 服务没起来：给前端的错误要和直连时同一形状（code/message/hint）
            HttpHeaders out = new HttpHeaders();
            out.set(HttpHeaders.CONTENT_TYPE, "application/json;charset=UTF-8");
            byte[] payload = ("{\"code\":\"E_API_UNREACHABLE\",\"message\":\"Python API 不可达："
                + apiBase + "\",\"hint\":\"先启动 python -m app.api.server（默认 127.0.0.1:8000）\"}")
                .getBytes(java.nio.charset.StandardCharsets.UTF_8);
            return new ResponseEntity<byte[]>(payload, out, org.springframework.http.HttpStatus.BAD_GATEWAY);
        }
    }
}
