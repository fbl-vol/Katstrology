CREATE TABLE memory_work (
    owner_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    consent_version INTEGER NOT NULL,
    session_digest TEXT NOT NULL,
    account_binding TEXT NOT NULL,
    model_slug TEXT NOT NULL,
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
