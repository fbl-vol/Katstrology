-- The stored passages and manually curated notes are originals; search/cache
-- derivatives may be rebuilt but must never replace these records.
CREATE TABLE reference_sources (
    owner_id text NOT NULL REFERENCES accounts(id),
    id text NOT NULL,
    author text NOT NULL,
    title text NOT NULL,
    edition text NOT NULL,
    tradition text NOT NULL,
    technique text NOT NULL,
    rights_basis text NOT NULL CHECK (rights_basis='synthetic_fixture'),
    rights_evidence text NOT NULL,
    approval text NOT NULL DEFAULT 'not_kat_selected',
    provenance text NOT NULL,
    source_conversation_id text,
    source_turn_id text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id,id),
    FOREIGN KEY (owner_id,source_conversation_id,source_turn_id)
      REFERENCES turns(owner_id,conversation_id,id) ON DELETE CASCADE,
    CHECK ((source_conversation_id IS NULL) = (source_turn_id IS NULL))
);
CREATE TABLE reference_passages (
    owner_id text NOT NULL,
    source_id text NOT NULL,
    id text NOT NULL,
    section text NOT NULL,
    content text NOT NULL,
    content_sha256 char(64) NOT NULL,
    PRIMARY KEY(owner_id,source_id,id),
    FOREIGN KEY (owner_id,source_id) REFERENCES reference_sources(owner_id,id) ON DELETE CASCADE
);
CREATE INDEX reference_passages_text_idx
    ON reference_passages USING gin (to_tsvector('simple',content));
CREATE TABLE personal_entries (
    owner_id text NOT NULL,
    person_id text NOT NULL,
    id text NOT NULL,
    conversation_id text NOT NULL,
    source_turn_id text NOT NULL,
    source_event_sequence integer NOT NULL,
    statement text NOT NULL,
    epistemic_status text NOT NULL
        CHECK (epistemic_status IN ('user_reported','explicitly_confirmed','agent_inference')),
    confirmation_turn_id text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(owner_id,person_id,id),
    FOREIGN KEY(owner_id,person_id) REFERENCES people(owner_id,id) ON DELETE CASCADE,
    FOREIGN KEY(owner_id,conversation_id,source_turn_id,source_event_sequence)
        REFERENCES events(owner_id,conversation_id,turn_id,sequence) ON DELETE CASCADE,
    FOREIGN KEY(owner_id,conversation_id,confirmation_turn_id)
        REFERENCES turns(owner_id,conversation_id,id) ON DELETE CASCADE,
    CHECK ((epistemic_status='explicitly_confirmed') = (confirmation_turn_id IS NOT NULL))
);
