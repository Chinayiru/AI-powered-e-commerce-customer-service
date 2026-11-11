package com.chinayiru.aftersale.common;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

/**
 * 草稿里的结构化字段（suggestedAction/citations/policyCheck）以 JSON 落库，
 * 读取时再还原。集中在这里，避免各服务各写一套。
 */
@Component
public class JsonCodec {

    private final ObjectMapper mapper;

    public JsonCodec(ObjectMapper mapper) {
        this.mapper = mapper;
    }

    public String write(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return mapper.writeValueAsString(value);
        } catch (Exception ex) {
            throw new IllegalStateException("JSON 序列化失败", ex);
        }
    }

    public <T> T read(String json, Class<T> type) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return mapper.readValue(json, type);
        } catch (Exception ex) {
            throw new IllegalStateException("JSON 反序列化失败", ex);
        }
    }

    public JsonNode tree(Object value) {
        return mapper.valueToTree(value);
    }

    public JsonNode readTree(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return mapper.readTree(json);
        } catch (Exception ex) {
            throw new IllegalStateException("JSON 解析失败", ex);
        }
    }
}
