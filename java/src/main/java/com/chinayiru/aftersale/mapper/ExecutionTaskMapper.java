package com.chinayiru.aftersale.mapper;

import com.chinayiru.aftersale.domain.ExecutionTask;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;

@Mapper
public interface ExecutionTaskMapper {

    @Insert("""
            INSERT INTO execution_task
            (task_id, ticket_id, request_id, state, attempts, last_error, created_at, updated_at)
            VALUES
            (#{taskId}, #{ticketId}, #{requestId}, #{state}, #{attempts}, #{lastError}, #{createdAt}, #{updatedAt})
            """)
    int insert(ExecutionTask task);

    @Select("""
            SELECT * FROM execution_task
            WHERE ticket_id = #{ticketId}
            ORDER BY created_at DESC, task_id DESC
            LIMIT 1
            """)
    ExecutionTask findLatestByTicket(@Param("ticketId") String ticketId);

    @Select("""
            SELECT * FROM execution_task
            WHERE ticket_id = #{ticketId} AND request_id = #{requestId}
            ORDER BY created_at DESC LIMIT 1
            """)
    ExecutionTask findByTicketAndRequest(@Param("ticketId") String ticketId,
                                         @Param("requestId") String requestId);

    @Update("""
            UPDATE execution_task
            SET state = 'DONE', attempts = attempts + 1, last_error = NULL, updated_at = #{now}
            WHERE task_id = #{taskId}
            """)
    int markDone(@Param("taskId") String taskId, @Param("now") LocalDateTime now);

    @Update("""
            UPDATE execution_task
            SET state = 'FAILED', attempts = attempts + 1, last_error = #{errorCode}, updated_at = #{now}
            WHERE task_id = #{taskId}
            """)
    int markFailed(@Param("taskId") String taskId,
                   @Param("errorCode") String errorCode,
                   @Param("now") LocalDateTime now);
}
