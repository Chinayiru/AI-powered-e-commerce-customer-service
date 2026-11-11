package com.chinayiru.aftersale.api;

import com.chinayiru.aftersale.api.dto.ApiDtos.LogisticsQueryRequest;
import com.chinayiru.aftersale.api.dto.ApiDtos.OrderQueryRequest;
import com.chinayiru.aftersale.auth.InternalIdentityService;
import com.chinayiru.aftersale.tool.OrderModels.Order;
import com.chinayiru.aftersale.tool.OrderModels.Shipment;
import com.chinayiru.aftersale.tool.OrderToolService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Java 提供给 Python 的工具入口。内部身份带 userId，因此仍做归属校验，
 * 越权订单统一 404 ORDER_NOT_FOUND。
 */
@RestController
@RequestMapping("/internal/tools")
public class InternalToolController {

    private static final String QUERY_ORDER_PATH = "/internal/tools/queryOrder";
    private static final String LOGISTICS_PATH = "/internal/tools/getLogistics";

    private final InternalIdentityService internalIdentity;
    private final OrderToolService orderTools;

    public InternalToolController(InternalIdentityService internalIdentity, OrderToolService orderTools) {
        this.internalIdentity = internalIdentity;
        this.orderTools = orderTools;
    }

    @PostMapping("/queryOrder")
    public Order queryOrder(@RequestHeader(value = "X-Internal-Identity", required = false) String identity,
                            @Valid @RequestBody OrderQueryRequest request) {
        InternalIdentityService.Identity caller = internalIdentity.verify(identity, QUERY_ORDER_PATH);
        return orderTools.requireOwned(caller.userId(), request.orderNo());
    }

    @PostMapping("/getLogistics")
    public Shipment getLogistics(@RequestHeader(value = "X-Internal-Identity", required = false) String identity,
                                 @Valid @RequestBody LogisticsQueryRequest request) {
        InternalIdentityService.Identity caller = internalIdentity.verify(identity, LOGISTICS_PATH);
        return orderTools.shipmentFor(caller.userId(), request.orderNo());
    }
}
