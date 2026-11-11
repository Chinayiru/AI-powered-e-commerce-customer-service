package com.chinayiru.aftersale.mapper;

import com.chinayiru.aftersale.domain.Draft;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;

@Mapper
public interface DraftMapper {

    @Insert("""
            INSERT INTO draft
            (draft_id, ticket_id, draft_version, generation_task_id, intent, confidence, reply_type,
             reply_draft, suggested_action_json, citations_json, policy_check_json, policy_version,
             need_human_review, superseded, created_at)
            VALUES
            (#{draftId}, #{ticketId}, #{draftVersion}, #{generationTaskId}, #{intent}, #{confidence}, #{replyType},
             #{replyDraft}, #{suggestedActionJson}, #{citationsJson}, #{policyCheckJson}, #{policyVersion},
             #{needHumanReview}, #{superseded}, #{createdAt})
            """)
    int insert(Draft draft);

    @Select("SELECT * FROM draft WHERE ticket_id = #{ticketId} ORDER BY draft_version DESC LIMIT 1")
    Draft findLatest(@Param("ticketId") String ticketId);

    @Select("""
            SELECT * FROM draft
            WHERE ticket_id = #{ticketId} AND superseded = FALSE
            ORDER BY draft_version DESC LIMIT 1
            """)
    Draft findLatestActive(@Param("ticketId") String ticketId);

    @Select("SELECT * FROM draft WHERE generation_task_id = #{taskId} LIMIT 1")
    Draft findByTaskId(@Param("taskId") String taskId);

    @Select("SELECT COALESCE(MAX(draft_version), 0) FROM draft WHERE ticket_id = #{ticketId}")
    int maxVersion(@Param("ticketId") String ticketId);

    @Update("UPDATE draft SET superseded = TRUE WHERE ticket_id = #{ticketId} AND superseded = FALSE")
    int supersedeAll(@Param("ticketId") String ticketId);

    @Update("""
            UPDATE draft SET superseded = TRUE
            WHERE ticket_id = #{ticketId} AND superseded = FALSE AND draft_id <> #{keepDraftId}
            """)
    int supersedeOthers(@Param("ticketId") String ticketId, @Param("keepDraftId") String keepDraftId);

    @Update("UPDATE draft SET superseded = TRUE WHERE ticket_id = #{ticketId} AND draft_version < #{version}")
    int supersedeOlder(@Param("ticketId") String ticketId, @Param("version") int version);

    @Select("SELECT COUNT(*) FROM draft WHERE ticket_id = #{ticketId}")
    int countByTicket(@Param("ticketId") String ticketId);

    @Select("SELECT COUNT(*) FROM draft WHERE generation_task_id = #{taskId}")
    int countByTask(@Param("taskId") String taskId);

    @Update("UPDATE draft SET created_at = #{now} WHERE draft_id = #{draftId}")
    int touch(@Param("draftId") String draftId, @Param("now") LocalDateTime now);
}
