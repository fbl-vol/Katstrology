-- References and fencing only: no duplicate conversation text or provider secrets.
CREATE TABLE memory_work (
    owner_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    consent_version INTEGER NOT NULL,
    session_digest TEXT NOT NULL,
    account_binding TEXT NOT NULL,
    capacity JSONB NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'idle')),
    attempted_generation INTEGER,
    outcome TEXT,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, conversation_id),
    FOREIGN KEY (owner_id, conversation_id, turn_id)
        REFERENCES turns(owner_id, conversation_id, id) ON DELETE CASCADE
);
CREATE TABLE memory_budget (
    owner_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    next_attempt_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX people_memory_name ON people(owner_id, lower(name));
