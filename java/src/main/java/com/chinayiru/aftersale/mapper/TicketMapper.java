package com.chinayiru.aftersale.mapper;

import com.chinayiru.aftersale.domain.Ticket;
import com.chinayiru.aftersale.domain.TicketState;
import com.chinayiru.aftersale.domain.TransferReason;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;
import java.util.Collection;

@Mapper
public interface TicketMapper {

    @Insert("""
            INSERT INTO aftersale_ticket
            (ticket_id, category, parent_consult_ticket_id, user_id, order_no, state, version,
             task_epoch, current_attempt, stalled_rounds, execution_mode, transfer_reason,
             generation_task_id, created_at, updated_at)
            VALUES
            (#{ticketId}, #{category}, #{parentConsultTicketId}, #{userId}, #{orderNo}, #{state}, #{version},
             #{taskEpoch}, #{currentAttempt}, #{stalledRounds}, #{executionMode}, #{transferReason},
             #{generationTaskId}, #{createdAt}, #{updatedAt})
            """)
    int insert(Ticket ticket);

    @Select("SELECT * FROM aftersale_ticket WHERE ticket_id = #{ticketId}")
    Ticket findById(@Param("ticketId") String ticketId);

    @Select("SELECT * FROM aftersale_ticket WHERE active_order_key = #{key} LIMIT 1")
    Ticket findByActiveOrderKey(@Param("key") String key);

    @Update("""
            <script>
            UPDATE aftersale_ticket
            SET state = #{to}, updated_at = #{now}, version = version + 1
            <if test="epochIncrement">, task_epoch = task_epoch + 1</if>
            <if test="reason != null">, transfer_reason = #{reason}</if>
            <if test="clearReason">, transfer_reason = NULL</if>
            <if test="closed">, closed_at = #{now}</if>
            <if test="stalledRounds != null">, stalled_rounds = #{stalledRounds}</if>
            <if test="orderNo != null">, order_no = #{orderNo}</if>
            WHERE ticket_id = #{ticketId}
              AND version = #{version}
              AND state IN
              <foreach collection="fromStates" item="s" open="(" separator="," close=")">#{s}</foreach>
            </script>
            """)
    int transition(@Param("ticketId") String ticketId,
                   @Param("version") int version,
                   @Param("fromStates") Collection<String> fromStates,
                   @Param("to") TicketState to,
                   @Param("reason") TransferReason reason,
                   @Param("clearReason") boolean clearReason,
                   @Param("epochIncrement") boolean epochIncrement,
                   @Param("stalledRounds") Integer stalledRounds,
                   @Param("orderNo") String orderNo,
                   @Param("closed") boolean closed,
                   @Param("now") LocalDateTime now);

    @Update("""
            UPDATE aftersale_ticket
            SET order_no = #{orderNo}, updated_at = #{now}
            WHERE ticket_id = #{ticketId}
            """)
    int updateOrderNo(@Param("ticketId") String ticketId,
                      @Param("orderNo") String orderNo,
                      @Param("now") LocalDateTime now);

    @Update("""
            UPDATE aftersale_ticket
            SET generation_task_id = #{taskId}, current_attempt = #{attempt}, updated_at = #{now}
            WHERE ticket_id = #{ticketId}
            """)
    int updateGeneration(@Param("ticketId") String ticketId,
                         @Param("taskId") String taskId,
                         @Param("attempt") int attempt,
                         @Param("now") LocalDateTime now);

    @Update("""
            UPDATE aftersale_ticket
            SET current_attempt = #{attempt}, updated_at = #{now}
            WHERE ticket_id = #{ticketId}
            """)
    int updateAttempt(@Param("ticketId") String ticketId,
                      @Param("attempt") int attempt,
                      @Param("now") LocalDateTime now);

    @Update("""
            UPDATE aftersale_ticket
            SET stalled_rounds = stalled_rounds + 1, updated_at = #{now}
            WHERE ticket_id = #{ticketId}
            """)
    int incrementStalled(@Param("ticketId") String ticketId, @Param("now") LocalDateTime now);

    @Update("""
            UPDATE aftersale_ticket
            SET transfer_reason = NULL, updated_at = #{now}
            WHERE ticket_id = #{ticketId}
            """)
    int clearTransferReason(@Param("ticketId") String ticketId, @Param("now") LocalDateTime now);
}
