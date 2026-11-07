CREATE TABLE personal_context_actions (
    owner_id TEXT NOT NULL, person_id TEXT NOT NULL, entry_id TEXT NOT NULL,
    id TEXT NOT NULL, expected_version INTEGER NOT NULL, content JSONB NOT NULL,
    source JSONB NOT NULL, version INTEGER NOT NULL,
    PRIMARY KEY(owner_id,person_id,id),
    FOREIGN KEY(owner_id,person_id,entry_id) REFERENCES personal_context(owner_id,person_id,id) ON DELETE CASCADE
);
