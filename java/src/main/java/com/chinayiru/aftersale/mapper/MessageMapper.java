package com.chinayiru.aftersale.mapper;

import com.chinayiru.aftersale.domain.TicketMessage;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface MessageMapper {

    @Insert("""
            INSERT INTO ticket_message (ticket_id, role, `text`, created_at)
            VALUES (#{ticketId}, #{role}, #{text}, #{createdAt})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "messageId", keyColumn = "message_id")
    int insert(TicketMessage message);

    @Select("SELECT * FROM ticket_message WHERE ticket_id = #{ticketId} ORDER BY message_id ASC")
    List<TicketMessage> listByTicket(@Param("ticketId") String ticketId);

    @Select("""
            SELECT * FROM (
                SELECT * FROM ticket_message
                WHERE ticket_id = #{ticketId}
                ORDER BY message_id DESC
                LIMIT #{limit}
            ) recent
            ORDER BY message_id ASC
            """)
    List<TicketMessage> listRecent(@Param("ticketId") String ticketId, @Param("limit") int limit);

    @Select("SELECT COUNT(*) FROM ticket_message WHERE ticket_id = #{ticketId}")
    int countByTicket(@Param("ticketId") String ticketId);
}
