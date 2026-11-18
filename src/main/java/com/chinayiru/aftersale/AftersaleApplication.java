package com.chinayiru.aftersale;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 售后工单处置台 Java 入口。
 *
 * <p>职责边界（ADR-011）：这里只是"静态页 + 反向代理"，不承载任何售后业务规则。
 * 托盘/打款/策略判定仍然在 Python（app.core.pipeline），Java 侧改错规则会同时踩坏
 * CONTRACT NG-6 与 AC 证据链。
 */
@SpringBootApplication
public class AftersaleApplication {

    public static void main(String[] args) {
        SpringApplication.run(AftersaleApplication.class, args);
    }
}
