package com.chinayiru.aftersale.mapper;

import com.chinayiru.aftersale.domain.IdempotencyRecord;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;

@Mapper
public interface IdempotencyMapper {

    @Select("""
            SELECT * FROM idempotency_record
            WHERE user_id = #{userId} AND endpoint = #{endpoint}
              AND target_id = #{targetId} AND request_id = #{requestId}
            """)
    IdempotencyRecord find(@Param("userId") String userId,
                           @Param("endpoint") String endpoint,
                           @Param("targetId") String targetId,
                           @Param("requestId") String requestId);

    @Insert("""
            INSERT INTO idempotency_record
            (user_id, endpoint, target_id, request_id, request_hash, state, response, error_code, updated_at, created_at)
            VALUES
            (#{userId}, #{endpoint}, #{targetId}, #{requestId}, #{requestHash}, #{state}, #{response},
             #{errorCode}, #{updatedAt}, #{createdAt})
            """)
    int insert(IdempotencyRecord record);

    @Update("""
            UPDATE idempotency_record
            SET state = 'DONE', response = #{response}, error_code = NULL, updated_at = #{now}
            WHERE user_id = #{userId} AND endpoint = #{endpoint}
              AND target_id = #{targetId} AND request_id = #{requestId}
            """)
    int markDone(@Param("userId") String userId,
                 @Param("endpoint") String endpoint,
                 @Param("targetId") String targetId,
                 @Param("requestId") String requestId,
                 @Param("response") String response,
                 @Param("now") LocalDateTime now);

    @Update("""
            UPDATE idempotency_record
            SET state = 'FAILED', response = #{response}, error_code = #{errorCode}, updated_at = #{now}
            WHERE user_id = #{userId} AND endpoint = #{endpoint}
              AND target_id = #{targetId} AND request_id = #{requestId}
            """)
    int markFailed(@Param("userId") String userId,
                   @Param("endpoint") String endpoint,
                   @Param("targetId") String targetId,
                   @Param("requestId") String requestId,
                   @Param("errorCode") String errorCode,
                   @Param("response") String response,
                   @Param("now") LocalDateTime now);

    @Update("""
            UPDATE idempotency_record
            SET updated_at = #{now}
            WHERE user_id = #{userId} AND endpoint = #{endpoint}
              AND target_id = #{targetId} AND request_id = #{requestId}
              AND state = 'IN_PROGRESS' AND updated_at < #{cutoff}
            """)
    int takeover(@Param("userId") String userId,
                 @Param("endpoint") String endpoint,
                 @Param("targetId") String targetId,
                 @Param("requestId") String requestId,
                 @Param("cutoff") LocalDateTime cutoff,
                 @Param("now") LocalDateTime now);

    @Delete("""
            DELETE FROM idempotency_record
            WHERE user_id = #{userId} AND endpoint = #{endpoint}
              AND target_id = #{targetId} AND request_id = #{requestId}
            """)
    int delete(@Param("userId") String userId,
               @Param("endpoint") String endpoint,
               @Param("targetId") String targetId,
               @Param("requestId") String requestId);
}
