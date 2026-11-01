-- Explicitly consented per-turn person file selection, distinct from chart versions.
-- A referenced file cannot be deleted before the dependent conversation is removed.
ALTER TABLE turn_people ADD COLUMN attachment_id text;
ALTER TABLE turn_people ADD CONSTRAINT turn_people_selected_attachment_fk
    FOREIGN KEY (owner_id,person_id,attachment_id)
    REFERENCES person_attachments(owner_id,person_id,id);
CREATE INDEX turn_people_attachment_idx
    ON turn_people(owner_id,person_id,attachment_id)
    WHERE attachment_id IS NOT NULL;
