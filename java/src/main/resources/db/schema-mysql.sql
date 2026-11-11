-- MySQL 8 schema（生产口径）。
-- 生成列 active_order_key 是「同一订单唯一未结束售后单」的兜底；H2 通过不代表 MySQL 通过。

CREATE TABLE IF NOT EXISTS `aftersale_ticket` (
  `ticket_id` VARCHAR(32) NOT NULL,
  `category` VARCHAR(16) NOT NULL,
  `parent_consult_ticket_id` VARCHAR(32) DEFAULT NULL,
  `user_id` VARCHAR(32) NOT NULL,
  `order_no` VARCHAR(32) DEFAULT NULL,
  `state` VARCHAR(24) NOT NULL,
  `version` INT NOT NULL,
  `task_epoch` INT NOT NULL,
  `current_attempt` INT NOT NULL,
  `stalled_rounds` INT NOT NULL,
  `execution_mode` VARCHAR(16) NOT NULL,
  `transfer_reason` VARCHAR(32) DEFAULT NULL,
  `generation_task_id` VARCHAR(64) DEFAULT NULL,
  `active_order_key` VARCHAR(80) GENERATED ALWAYS AS (
      CASE
        WHEN `category` = 'CONSULT' OR `state` IN ('CLOSED', 'CANCELLED') OR `order_no` IS NULL
          THEN NULL
        ELSE CONCAT(`user_id`, ':', `order_no`)
      END
  ) STORED,
  `created_at` DATETIME(3) NOT NULL,
  `updated_at` DATETIME(3) NOT NULL,
  `closed_at` DATETIME(3) DEFAULT NULL,
  PRIMARY KEY (`ticket_id`),
  UNIQUE KEY `uk_ticket_active_order` (`active_order_key`),
  KEY `idx_ticket_user` (`user_id`),
  KEY `idx_ticket_parent` (`parent_consult_ticket_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `ticket_message` (
  `message_id` BIGINT NOT NULL AUTO_INCREMENT,
  `ticket_id` VARCHAR(32) NOT NULL,
  `role` VARCHAR(16) NOT NULL,
  `text` VARCHAR(1000) NOT NULL,
  `created_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`message_id`),
  KEY `idx_message_ticket` (`ticket_id`, `message_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `draft` (
  `draft_id` VARCHAR(36) NOT NULL,
  `ticket_id` VARCHAR(32) NOT NULL,
  `draft_version` INT NOT NULL,
  `generation_task_id` VARCHAR(64) NOT NULL,
  `intent` VARCHAR(32) NOT NULL,
  `confidence` DECIMAL(4,3) NOT NULL,
  `reply_type` VARCHAR(16) NOT NULL,
  `reply_draft` VARCHAR(200) NOT NULL,
  `suggested_action_json` JSON DEFAULT NULL,
  `citations_json` JSON DEFAULT NULL,
  `policy_check_json` JSON DEFAULT NULL,
  `policy_version` VARCHAR(16) DEFAULT NULL,
  `need_human_review` TINYINT(1) NOT NULL,
  `superseded` TINYINT(1) NOT NULL,
  `created_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`draft_id`),
  UNIQUE KEY `uk_draft_task` (`generation_task_id`),
  UNIQUE KEY `uk_draft_version` (`ticket_id`, `draft_version`),
  KEY `idx_draft_ticket` (`ticket_id`, `draft_version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `tool_call` (
  `call_id` BIGINT NOT NULL AUTO_INCREMENT,
  `ticket_id` VARCHAR(32) NOT NULL,
  `step` INT NOT NULL,
  `name` VARCHAR(64) NOT NULL,
  `ok` TINYINT(1) NOT NULL,
  `latency_ms` INT NOT NULL,
  `error_code` VARCHAR(32) DEFAULT NULL,
  `request_hash` CHAR(64) DEFAULT NULL,
  `response_hash` CHAR(64) DEFAULT NULL,
  `summary` VARCHAR(200) DEFAULT NULL,
  `created_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`call_id`),
  KEY `idx_tool_ticket` (`ticket_id`, `step`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `idempotency_record` (
  `user_id` VARCHAR(32) NOT NULL,
  `endpoint` VARCHAR(64) NOT NULL,
  `target_id` VARCHAR(64) NOT NULL,
  `request_id` VARCHAR(36) NOT NULL,
  `request_hash` CHAR(64) NOT NULL,
  `state` VARCHAR(16) NOT NULL,
  `response` JSON DEFAULT NULL,
  `error_code` VARCHAR(32) DEFAULT NULL,
  `updated_at` DATETIME(3) NOT NULL,
  `created_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`user_id`, `endpoint`, `target_id`, `request_id`),
  KEY `idx_idem_updated` (`state`, `updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `execution_task` (
  `task_id` VARCHAR(64) NOT NULL,
  `ticket_id` VARCHAR(32) NOT NULL,
  `request_id` VARCHAR(36) NOT NULL,
  `state` VARCHAR(16) NOT NULL,
  `attempts` INT NOT NULL,
  `last_error` VARCHAR(32) DEFAULT NULL,
  `created_at` DATETIME(3) NOT NULL,
  `updated_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`task_id`),
  KEY `idx_execution_ticket` (`ticket_id`),
  KEY `idx_execution_request` (`ticket_id`, `request_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `audit_log` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `ticket_id` VARCHAR(32) DEFAULT NULL,
  `action` VARCHAR(64) NOT NULL,
  `detail` TEXT,
  `trace_id` VARCHAR(64) DEFAULT NULL,
  `created_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_audit_ticket` (`ticket_id`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `ticket_sequence` (
  `seq_date` CHAR(8) NOT NULL,
  `next_val` INT NOT NULL,
  PRIMARY KEY (`seq_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
