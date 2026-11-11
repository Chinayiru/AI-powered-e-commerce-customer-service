package com.chinayiru.aftersale.mapper;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface SequenceMapper {

    @Insert("""
            INSERT INTO ticket_sequence (seq_date, next_val) VALUES (#{day}, 1)
            ON DUPLICATE KEY UPDATE next_val = next_val + 1
            """)
    int bump(@Param("day") String day);

    @Select("SELECT next_val FROM ticket_sequence WHERE seq_date = #{day}")
    Integer current(@Param("day") String day);
}
