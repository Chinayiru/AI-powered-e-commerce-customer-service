-- H2 dev/test schema (MySQL compatibility mode).
-- 生产以 db/schema-mysql.sql 为准；H2 的生成列/唯一索引行为不能替代 MySQL 8 验证。

CREATE TABLE IF NOT EXISTS aftersale_ticket (
    ticket_id               VARCHAR(32) PRIMARY KEY,
    category                VARCHAR(16) NOT NULL,
    parent_consult_ticket_id VARCHAR(32),
    user_id                 VARCHAR(32) NOT NULL,
    order_no                VARCHAR(32),
    state                   VARCHAR(24) NOT NULL,
    version                 INT NOT NULL,
    task_epoch              INT NOT NULL,
    current_attempt         INT NOT NULL,
    stalled_rounds          INT NOT NULL,
    execution_mode          VARCHAR(16) NOT NULL,
    transfer_reason         VARCHAR(32),
    generation_task_id      VARCHAR(64),
    active_order_key        VARCHAR(80) GENERATED ALWAYS AS (
        CASE
            WHEN category = 'CONSULT' OR state IN ('CLOSED', 'CANCELLED') OR order_no IS NULL
                THEN NULL
            ELSE CONCAT(user_id, ':', order_no)
        END),
    created_at              TIMESTAMP NOT NULL,
    updated_at              TIMESTAMP NOT NULL,
    closed_at               TIMESTAMP,
    CONSTRAINT uk_ticket_active_order UNIQUE (active_order_key)
);

CREATE INDEX IF NOT EXISTS idx_ticket_user ON aftersale_ticket (user_id);
CREATE INDEX IF NOT EXISTS idx_ticket_parent ON aftersale_ticket (parent_consult_ticket_id);

CREATE TABLE IF NOT EXISTS ticket_message (
    message_id  BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticket_id   VARCHAR(32) NOT NULL,
    role        VARCHAR(16) NOT NULL,
    `text`      VARCHAR(1000) NOT NULL,
    created_at  TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_message_ticket ON ticket_message (ticket_id, message_id);

CREATE TABLE IF NOT EXISTS draft (
    draft_id             VARCHAR(36) PRIMARY KEY,
    ticket_id            VARCHAR(32) NOT NULL,
    draft_version        INT NOT NULL,
    generation_task_id   VARCHAR(64) NOT NULL,
    intent               VARCHAR(32) NOT NULL,
    confidence           DECIMAL(4, 3) NOT NULL,
    reply_type           VARCHAR(16) NOT NULL,
    reply_draft          VARCHAR(200) NOT NULL,
    suggested_action_json CLOB,
    citations_json       CLOB,
    policy_check_json    CLOB,
    policy_version       VARCHAR(16),
    need_human_review    BOOLEAN NOT NULL,
    superseded           BOOLEAN NOT NULL,
    created_at           TIMESTAMP NOT NULL,
    CONSTRAINT uk_draft_task UNIQUE (generation_task_id),
    CONSTRAINT uk_draft_version UNIQUE (ticket_id, draft_version)
);

CREATE INDEX IF NOT EXISTS idx_draft_ticket ON draft (ticket_id, draft_version);

CREATE TABLE IF NOT EXISTS tool_call (
    call_id       BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticket_id     VARCHAR(32) NOT NULL,
    step          INT NOT NULL,
    name          VARCHAR(64) NOT NULL,
    ok            BOOLEAN NOT NULL,
    latency_ms    INT NOT NULL,
    error_code    VARCHAR(32),
    request_hash  CHAR(64),
    response_hash CHAR(64),
    summary       VARCHAR(200),
    created_at    TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_ticket ON tool_call (ticket_id, step);

CREATE TABLE IF NOT EXISTS idempotency_record (
    user_id      VARCHAR(32) NOT NULL,
    endpoint     VARCHAR(64) NOT NULL,
    target_id    VARCHAR(64) NOT NULL,
    request_id   VARCHAR(36) NOT NULL,
    request_hash CHAR(64) NOT NULL,
    state        VARCHAR(16) NOT NULL,
    response     CLOB,
    error_code   VARCHAR(32),
    updated_at   TIMESTAMP NOT NULL,
    created_at   TIMESTAMP NOT NULL,
    PRIMARY KEY (user_id, endpoint, target_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_idem_updated ON idempotency_record (state, updated_at);

CREATE TABLE IF NOT EXISTS execution_task (
    task_id     VARCHAR(64) PRIMARY KEY,
    ticket_id   VARCHAR(32) NOT NULL,
    request_id  VARCHAR(36) NOT NULL,
    state       VARCHAR(16) NOT NULL,
    attempts    INT NOT NULL,
    last_error  VARCHAR(32),
    created_at  TIMESTAMP NOT NULL,
    updated_at  TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_ticket ON execution_task (ticket_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticket_id   VARCHAR(32),
    action      VARCHAR(64) NOT NULL,
    detail      CLOB,
    trace_id    VARCHAR(64),
    created_at  TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_ticket ON audit_log (ticket_id, id);

CREATE TABLE IF NOT EXISTS ticket_sequence (
    seq_date  CHAR(8) PRIMARY KEY,
    next_val  INT NOT NULL
);
