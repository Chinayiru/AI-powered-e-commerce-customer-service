package com.chinayiru.aftersale.api;

import com.chinayiru.aftersale.api.dto.ApiDtos.AgentTicketView;
import com.chinayiru.aftersale.api.dto.ApiDtos.CloseRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.HandoffRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.RegenerateRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.ReplyRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.SendRequest;
import com.chinayiru.aftersale.auth.AccessGuard;
import com.chinayiru.aftersale.service.AgentService;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 坐席入口。只认 X-Agent-Token，不接受消费者 ticketToken。
 */
@RestController
@RequestMapping("/api/agent/tickets")
public class AgentTicketController {

    private final AccessGuard accessGuard;
    private final AgentService agentService;

    public AgentTicketController(AccessGuard accessGuard, AgentService agentService) {
        this.accessGuard = accessGuard;
        this.agentService = agentService;
    }

    @GetMapping("/{ticketId}")
    public AgentTicketView view(@PathVariable String ticketId,
                                @RequestHeader(value = "X-Agent-Token", required = false) String token) {
        accessGuard.requireAgent(token);
        return agentService.view(ticketId);
    }

    @PostMapping("/{ticketId}/send")
    public ResponseEntity<?> send(@PathVariable String ticketId,
                                  @RequestHeader(value = "X-Agent-Token", required = false) String token,
                                  @Valid @RequestBody SendRequest request) {
        accessGuard.requireAgent(token);
        return agentService.send(ticketId, request);
    }

    @PostMapping("/{ticketId}/regenerate")
    public ResponseEntity<?> regenerate(@PathVariable String ticketId,
                                        @RequestHeader(value = "X-Agent-Token", required = false) String token,
                                        @Valid @RequestBody RegenerateRequest request) {
        accessGuard.requireAgent(token);
        return agentService.regenerate(ticketId, request);
    }

    @PostMapping("/{ticketId}/handoff")
    public ResponseEntity<?> handoff(@PathVariable String ticketId,
                                     @RequestHeader(value = "X-Agent-Token", required = false) String token,
                                     @Valid @RequestBody HandoffRequest request) {
        accessGuard.requireAgent(token);
        return agentService.handoff(ticketId, request);
    }

    @PostMapping("/{ticketId}/reply")
    public ResponseEntity<?> reply(@PathVariable String ticketId,
                                   @RequestHeader(value = "X-Agent-Token", required = false) String token,
                                   @Valid @RequestBody ReplyRequest request) {
        accessGuard.requireAgent(token);
        return agentService.reply(ticketId, request);
    }

    @PostMapping("/{ticketId}/close")
    public ResponseEntity<?> close(@PathVariable String ticketId,
                                   @RequestHeader(value = "X-Agent-Token", required = false) String token,
                                   @Valid @RequestBody CloseRequest request) {
        accessGuard.requireAgent(token);
        return agentService.close(ticketId, request);
    }
}
