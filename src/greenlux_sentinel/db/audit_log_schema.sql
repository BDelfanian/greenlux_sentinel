-- Audit log table (docs/RESPONSIBLE_AI.md#audit-log-schema-see-srcgreenlux_sentineldbaudit_log_schemasql)
-- Append-only. Every agent tool call writes one row here, cross-referenced with its
-- LangSmith trace ID so either log can reconstruct a decision after the fact.

CREATE TABLE IF NOT EXISTS audit_log (
    id                      BIGSERIAL PRIMARY KEY,
    "timestamp"             TIMESTAMPTZ NOT NULL DEFAULT now(),
    agent_name              TEXT NOT NULL,
    tool_name               TEXT NOT NULL,
    input_summary           TEXT,
    output_summary          TEXT,
    langsmith_trace_id      TEXT,
    required_approval       BOOLEAN NOT NULL DEFAULT false,
    approval_status         TEXT,          -- NULL | 'pending' | 'approved' | 'rejected'
    approved_by             TEXT,
    approved_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_audit_log_agent ON audit_log (agent_name, "timestamp");
CREATE INDEX IF NOT EXISTS idx_audit_log_pending_approval ON audit_log (approval_status)
    WHERE approval_status = 'pending';
