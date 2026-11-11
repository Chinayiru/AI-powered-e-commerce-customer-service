package com.chinayiru.aftersale.mapper;

import com.chinayiru.aftersale.domain.AuditLog;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface AuditMapper {

    @Insert("""
            INSERT INTO audit_log (ticket_id, action, detail, trace_id, created_at)
            VALUES (#{ticketId}, #{action}, #{detail}, #{traceId}, #{createdAt})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id", keyColumn = "id")
    int insert(AuditLog audit);

    @Select("SELECT * FROM audit_log WHERE ticket_id = #{ticketId} ORDER BY id ASC")
    List<AuditLog> listByTicket(@Param("ticketId") String ticketId);

    @Select("SELECT * FROM audit_log ORDER BY id DESC LIMIT #{limit}")
    List<AuditLog> latest(@Param("limit") int limit);
}
