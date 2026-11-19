package com.chinayiru.aftersale.service;

/**
 * 模拟执行器：一期 {@code app.execution.mode=SIMULATED}，只代表"执行流程已走完"，
 * 绝不调用任何真实资金系统。
 *
 * <p>抽成接口而不是内联在 {@link AgentService} 里，是为了让测试能注入失败实现，
 * 从而覆盖"执行失败返回 202 并可重试"这条分支——否则该分支永远测不到，
 * 工单卡死在 CONFIRMED 的缺陷也就无法被回归测试发现。
 */
public interface SimulatedExecutor {

    /**
     * 执行一次已确认的动作。抛出 {@link RuntimeException} 表示执行失败，
     * 调用方据此返回 202 并保留可重试的 CONFIRMED 状态。
     */
    void execute(String ticketId, String requestId);
}
