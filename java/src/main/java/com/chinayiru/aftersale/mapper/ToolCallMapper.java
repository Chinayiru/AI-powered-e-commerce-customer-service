package com.chinayiru.aftersale.mapper;

import com.chinayiru.aftersale.domain.ToolCall;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ToolCallMapper {

    @Select("SELECT COALESCE(MAX(step), 0) + 1 FROM tool_call WHERE ticket_id = #{ticketId}")
    int nextStep(@Param("ticketId") String ticketId);

    @Insert("""
            INSERT INTO tool_call
            (ticket_id, step, name, ok, latency_ms, error_code, request_hash, response_hash, summary, created_at)
            VALUES
            (#{ticketId}, #{step}, #{name}, #{ok}, #{latencyMs}, #{errorCode}, #{requestHash}, #{responseHash},
             #{summary}, #{createdAt})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "callId", keyColumn = "call_id")
    int insert(ToolCall call);

    @Select("SELECT * FROM tool_call WHERE ticket_id = #{ticketId} ORDER BY step ASC, call_id ASC")
    List<ToolCall> listByTicket(@Param("ticketId") String ticketId);
}
