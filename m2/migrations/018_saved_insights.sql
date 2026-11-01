-- Explicit user curation of an attributed personal passage. The original entry
-- and source event are immutable; note edits and removal are append-only actions.
ALTER TABLE personal_entries DROP CONSTRAINT personal_entries_epistemic_status_check;
ALTER TABLE personal_entries ADD CONSTRAINT personal_entries_epistemic_status_check
    CHECK (epistemic_status IN ('user_reported','explicitly_confirmed','agent_inference','saved_user_passage','saved_assistant_passage'));

CREATE TABLE personal_entry_actions (
    owner_id text NOT NULL,
    person_id text NOT NULL,
    entry_id text NOT NULL,
    id text NOT NULL,
    action text NOT NULL CHECK (action IN ('save','edit','remove')),
    note text NOT NULL CHECK (char_length(note) <= 512),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id,person_id,entry_id,id),
    FOREIGN KEY (owner_id,person_id,entry_id)
        REFERENCES personal_entries(owner_id,person_id,id) ON DELETE CASCADE
);
