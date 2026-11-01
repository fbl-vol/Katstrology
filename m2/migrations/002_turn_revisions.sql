ALTER TABLE turns
    ADD COLUMN revision_kind text NOT NULL DEFAULT 'normal'
      CHECK (revision_kind IN ('normal', 'edit', 'regenerate')),
    ADD COLUMN replaces_turn_id text,
    ADD CONSTRAINT turns_replaces_fk
      FOREIGN KEY (owner_id, conversation_id, replaces_turn_id)
      REFERENCES turns(owner_id, conversation_id, id);
