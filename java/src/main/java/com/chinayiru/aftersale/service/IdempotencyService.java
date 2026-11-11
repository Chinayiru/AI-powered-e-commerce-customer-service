package com.chinayiru.aftersale.service;

import com.chinayiru.aftersale.common.ApiException;
import com.chinayiru.aftersale.common.ErrorCode;
import com.chinayiru.aftersale.common.ErrorResponse;
import com.chinayiru.aftersale.common.Hashing;
import com.chinayiru.aftersale.common.JsonCodec;
import com.chinayiru.aftersale.common.TimeUtil;
import com.chinayiru.aftersale.common.TraceFilter;
import com.chinayiru.aftersale.domain.IdemState;
import com.chinayiru.aftersale.domain.IdempotencyRecord;
import com.chinayiru.aftersale.mapper.IdempotencyMapper;
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * 幂等：作用域 (userId, endpoint, targetId, requestId) + 请求体 sha256。
 * - 同 key 同体：重放首次 2xx/4xx 结果；不同体 409；
 * - IN_PROGRESS 且租约未过期：409 IN_PROGRESS（可重试）；
 * - 5xx：删除记录，允许客户端换 requestId 重试。
 */
@Service
public class IdempotencyService {

    private final IdempotencyMapper mapper;
    private final JsonCodec json;
    private final long leaseSeconds;

    public IdempotencyService(IdempotencyMapper mapper, JsonCodec json,
                              com.chinayiru.aftersale.config.AppProperties properties) {
        this.mapper = mapper;
        this.json = json;
        this.leaseSeconds = properties.getIdempotency().getLeaseSeconds();
    }

    public String hash(Object request) {
        return Hashing.sha256Hex(json.write(request));
    }

    public ResponseEntity<?> execute(String userId, String endpoint, String targetId, String requestId,
                                     String requestHash, Supplier<ResponseEntity<?>> action) {
        IdempotencyRecord existing = find(userId, endpoint, targetId, requestId);
        if (existing != null) {
            if (!requestHash.equals(existing.getRequestHash())) {
                throw new ApiException(ErrorCode.IDEMPOTENCY_CONFLICT, "同一 requestId 携带了不同请求体");
            }
            if (existing.getState() == IdemState.DONE || existing.getState() == IdemState.FAILED) {
                return replay(existing);
            }
            if (!takeOverIfExpired(existing)) {
                throw new ApiException(ErrorCode.IN_PROGRESS, "相同请求正在处理中，请稍后重试", 1);
            }
        } else {
            IdempotencyRecord record = new IdempotencyRecord();
            record.setUserId(userId);
            record.setEndpoint(endpoint);
            record.setTargetId(targetId);
            record.setRequestId(requestId);
            record.setRequestHash(requestHash);
            record.setState(IdemState.IN_PROGRESS);
            record.setUpdatedAt(TimeUtil.now());
            record.setCreatedAt(TimeUtil.now());
            try {
                mapper.insert(record);
            } catch (DuplicateKeyException ex) {
                existing = find(userId, endpoint, targetId, requestId);
                if (existing == null) {
                    throw ex;
                }
                if (!requestHash.equals(existing.getRequestHash())) {
                    throw new ApiException(ErrorCode.IDEMPOTENCY_CONFLICT, "同一 requestId 携带了不同请求体");
                }
                if (existing.getState() == IdemState.DONE || existing.getState() == IdemState.FAILED) {
                    return replay(existing);
                }
                if (!takeOverIfExpired(existing)) {
                    throw new ApiException(ErrorCode.IN_PROGRESS, "相同请求正在处理中，请稍后重试", 1);
                }
            }
        }

        try {
            ResponseEntity<?> response = action.get();
            store(userId, endpoint, targetId, requestId, response.getStatusCode().value(), response.getBody(), null);
            return response;
        } catch (ApiException ex) {
            if (ex.getCode().httpStatus() >= 500) {
                mapper.delete(userId, endpoint, targetId, requestId);
                throw ex;
            }
            ErrorResponse error = new ErrorResponse(ex.getCode().name(), ex.getMessage(),
                    TraceFilter.currentTraceId(), ex.getCode().retryable());
            store(userId, endpoint, targetId, requestId, ex.getCode().httpStatus(), error, ex.getCode().name());
            return ResponseEntity.status(ex.getCode().httpStatus()).body(error);
        } catch (RuntimeException ex) {
            mapper.delete(userId, endpoint, targetId, requestId);
            throw ex;
        }
    }

    private IdempotencyRecord find(String userId, String endpoint, String targetId, String requestId) {
        return mapper.find(userId, endpoint, targetId, requestId);
    }

    private boolean takeOverIfExpired(IdempotencyRecord record) {
        LocalDateTime cutoff = TimeUtil.now().minusSeconds(leaseSeconds);
        if (record.getUpdatedAt() != null && record.getUpdatedAt().isAfter(cutoff)) {
            return false;
        }
        return mapper.takeover(record.getUserId(), record.getEndpoint(), record.getTargetId(),
                record.getRequestId(), cutoff, TimeUtil.now()) == 1;
    }

    private void store(String userId, String endpoint, String targetId, String requestId,
                       int status, Object body, String errorCode) {
        Map<String, Object> stored = new LinkedHashMap<>();
        stored.put("status", status);
        stored.put("body", body);
        String value = json.write(stored);
        if (errorCode == null) {
            mapper.markDone(userId, endpoint, targetId, requestId, value, TimeUtil.now());
        } else {
            mapper.markFailed(userId, endpoint, targetId, requestId, errorCode, value, TimeUtil.now());
        }
    }

    private ResponseEntity<?> replay(IdempotencyRecord record) {
        JsonNode node = json.readTree(record.getResponse());
        if (node == null) {
            throw new ApiException(ErrorCode.IN_PROGRESS, "首次请求结果尚未就绪", 1);
        }
        int status = node.path("status").asInt(200);
        JsonNode body = node.get("body");
        return ResponseEntity.status(status).body(body);
    }
}
