package com.chinayiru.aftersale.service;

import com.chinayiru.aftersale.api.dto.ApiDtos.TicketCreated;
import com.chinayiru.aftersale.domain.Ticket;

/**
 * 一次生成的果：ticket 是当前工单（咨询转售后时是原咨询单），
 * createdTicket 仅在“咨询转售后”新建/复用关联单时非空。
 */
public record GenerationOutcome(Ticket ticket, TicketCreated createdTicket) {
}
