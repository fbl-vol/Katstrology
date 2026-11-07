CREATE TABLE context_update_stages (
    owner_id TEXT NOT NULL, conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL,
    id TEXT NOT NULL, person_id TEXT NOT NULL, entry_id TEXT NOT NULL,
    expected_version INTEGER NOT NULL, content JSONB NOT NULL, source JSONB NOT NULL,
    consent_version INTEGER NOT NULL, outcome TEXT NOT NULL DEFAULT 'staged',
    PRIMARY KEY(owner_id,conversation_id,turn_id,id),
    FOREIGN KEY(owner_id,conversation_id,turn_id) REFERENCES turns(owner_id,conversation_id,id) ON DELETE CASCADE
);
