-- Cache only: source references and active search entries remain authoritative.
-- FKs and the conversation epoch fence prevent a stale embedding from serving
-- after correction, branch change, rebuild or deletion.
CREATE TABLE reference_vectors (
    owner_id text NOT NULL,
    source_id text NOT NULL,
    passage_id text NOT NULL,
    model_id text NOT NULL,
    content_sha256 char(64) NOT NULL,
    embedding real[] NOT NULL,
    PRIMARY KEY(owner_id,source_id,passage_id),
    FOREIGN KEY(owner_id,source_id,passage_id)
      REFERENCES reference_passages(owner_id,source_id,id) ON DELETE CASCADE
);
CREATE TABLE history_vectors (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    source_id text NOT NULL,
    speaker text NOT NULL,
    epoch bigint NOT NULL,
    model_id text NOT NULL,
    embedding real[] NOT NULL,
    PRIMARY KEY(owner_id,conversation_id,source_id,speaker),
    FOREIGN KEY(owner_id,conversation_id,source_id,speaker)
      REFERENCES search_entries(owner_id,conversation_id,source_id,speaker) ON DELETE CASCADE
);
