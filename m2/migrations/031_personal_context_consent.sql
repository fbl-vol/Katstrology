CREATE TABLE personal_context_consent (
    owner_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT false, version INTEGER NOT NULL
);
