package com.chinayiru.aftersale.service;

import org.springframework.stereotype.Component;

/**
 * 默认的模拟执行器：无外部副作用，也不产生任何延迟。
 * 生产接入真实执行前，必须先在契约里定义幂等与对账规则。
 */
@Component
public class DefaultSimulatedExecutor implements SimulatedExecutor {

    @Override
    public void execute(String ticketId, String requestId) {
        // SIMULATED：不触达资金系统、不修改订单，仅代表执行段已完成。
    }
}
