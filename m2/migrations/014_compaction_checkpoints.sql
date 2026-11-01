-- Routine complete turns advance search epoch but preserve eligible context checkpoints.
-- Branch/correction/profile/source changes advance this separate revision.
ALTER TABLE conversations ADD COLUMN compaction_revision bigint NOT NULL DEFAULT 0;

CREATE TABLE compaction_checkpoints (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    source_head text NOT NULL,
    compaction_revision bigint NOT NULL,
    model_provider text NOT NULL,
    model_slug text NOT NULL,
    prompt_version text NOT NULL,
    prompt_sha256 char(64) NOT NULL,
    summary_version text NOT NULL,
    summary_sha256 char(64) NOT NULL,
    selected_sha256 char(64) NOT NULL,
    model_policy_sha256 char(64) NOT NULL,
    covered_ids jsonb NOT NULL,
    first_kept_id text NOT NULL,
    source_sha256 char(64) NOT NULL,
    summary text NOT NULL CHECK (length(summary) BETWEEN 1 AND 4096),
    count_method text NOT NULL,
    input_estimate integer NOT NULL,
    output_estimate integer NOT NULL,
    usage jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (owner_id, conversation_id) REFERENCES conversations(owner_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, conversation_id, source_head)
      REFERENCES turns(owner_id, conversation_id, id) ON DELETE CASCADE
);
CREATE INDEX compaction_recent_idx ON compaction_checkpoints
    (owner_id, conversation_id, compaction_revision, id DESC);
