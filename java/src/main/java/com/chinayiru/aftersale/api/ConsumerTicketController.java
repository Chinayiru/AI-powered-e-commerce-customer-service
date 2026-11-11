package com.chinayiru.aftersale.api;

import com.chinayiru.aftersale.api.dto.ApiDtos.AddMessageRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.CancelRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.ConsumerTicketView;
import com.chinayiru.aftersale.api.dto.ApiDtos.CreateTicketRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.OrderSummary;
import com.chinayiru.aftersale.auth.AccessGuard;
import com.chinayiru.aftersale.auth.TicketTokenService;
import com.chinayiru.aftersale.service.TicketService;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 消费者入口。除创建与订单列表使用演示头身份外，工单访问一律使用 ticketToken。
 */
@RestController
@RequestMapping("/api")
public class ConsumerTicketController {

    private final AccessGuard accessGuard;
    private final TicketService ticketService;

    public ConsumerTicketController(AccessGuard accessGuard, TicketService ticketService) {
        this.accessGuard = accessGuard;
        this.ticketService = ticketService;
    }

    @PostMapping("/tickets")
    public ResponseEntity<?> create(@RequestHeader(value = "X-User-Id", required = false) String xUserId,
                                    @Valid @RequestBody CreateTicketRequest request) {
        String userId = accessGuard.requireUser(xUserId);
        return ticketService.create(request, userId);
    }

    @PostMapping("/tickets/{ticketId}/messages")
    public ResponseEntity<?> addMessage(@PathVariable String ticketId,
                                        @RequestHeader(value = "Authorization", required = false) String authorization,
                                        @Valid @RequestBody AddMessageRequest request) {
        TicketTokenService.Claims claims = accessGuard.requireTicket(ticketId, authorization);
        return ticketService.addMessage(ticketId, claims.userId(), request);
    }

    @GetMapping("/tickets/{ticketId}")
    public ConsumerTicketView get(@PathVariable String ticketId,
                                  @RequestHeader(value = "Authorization", required = false) String authorization) {
        TicketTokenService.Claims claims = accessGuard.requireTicket(ticketId, authorization);
        return ticketService.get(ticketId, claims.userId());
    }

    @PostMapping("/tickets/{ticketId}/cancel")
    public ResponseEntity<?> cancel(@PathVariable String ticketId,
                                    @RequestHeader(value = "Authorization", required = false) String authorization,
                                    @Valid @RequestBody CancelRequest request) {
        TicketTokenService.Claims claims = accessGuard.requireTicket(ticketId, authorization);
        return ticketService.cancel(ticketId, claims.userId(), request);
    }

    @GetMapping("/me/orders")
    public List<OrderSummary> orders(@RequestHeader(value = "X-User-Id", required = false) String xUserId) {
        return ticketService.orders(accessGuard.requireUser(xUserId));
    }
}
