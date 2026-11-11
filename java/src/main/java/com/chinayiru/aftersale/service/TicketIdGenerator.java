package com.chinayiru.aftersale.service;

import com.chinayiru.aftersale.mapper.SequenceMapper;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * ticketId = T + yyyyMMdd + 6 位日序号。演示为单实例，方法级同步 + 主键唯一兜底；
 * 多实例部署需改为数据库原子取号（契约允许实现自由，格式不变）。
 */
@Component
public class TicketIdGenerator {

    private static final DateTimeFormatter DAY = DateTimeFormatter.ofPattern("yyyyMMdd");

    private final SequenceMapper sequenceMapper;

    public TicketIdGenerator(SequenceMapper sequenceMapper) {
        this.sequenceMapper = sequenceMapper;
    }

    public synchronized String next(LocalDateTime now) {
        String day = now.format(DAY);
        sequenceMapper.bump(day);
        Integer value = sequenceMapper.current(day);
        int seq = value == null ? 1 : value;
        return "T" + day + String.format("%06d", seq);
    }
}
