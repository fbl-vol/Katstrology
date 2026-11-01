-- Workspace login is separate from any model-provider authorization.
-- Only a digest of the random opaque session cookie is retained.
CREATE TABLE web_sessions (
    token_digest char(64) PRIMARY KEY,
    owner_id text NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    csrf_token char(64) NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX web_sessions_owner_idx ON web_sessions(owner_id, expires_at);
