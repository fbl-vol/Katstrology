CREATE TABLE account_tones (
    owner_id text PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    tone_id text NOT NULL,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0)
);
