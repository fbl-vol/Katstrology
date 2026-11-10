CREATE TABLE memory_budget (
    owner_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    next_attempt_at TIMESTAMPTZ NOT NULL,
    context_revision BIGINT NOT NULL DEFAULT 0
);
