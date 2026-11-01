-- One conversation may be related to many people, including no one. Membership
-- is cumulative; each turn snapshots the exact selected versions separately.
ALTER TABLE conversations ADD COLUMN title text NOT NULL DEFAULT '';
CREATE TABLE conversation_people (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    person_id text NOT NULL,
    PRIMARY KEY (owner_id,conversation_id,person_id),
    FOREIGN KEY (owner_id,conversation_id) REFERENCES conversations(owner_id,id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id,person_id) REFERENCES people(owner_id,id)
);
ALTER TABLE charts ADD CONSTRAINT chart_person_identity UNIQUE (owner_id,person_id,id);
CREATE TABLE turn_people (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    turn_id text NOT NULL,
    person_id text NOT NULL,
    draft_revision integer,
    chart_id text,
    birth_id text,
    profile_id text,
    profile_revision integer,
    PRIMARY KEY (owner_id,conversation_id,turn_id,person_id),
    FOREIGN KEY (owner_id,conversation_id,turn_id)
        REFERENCES turns(owner_id,conversation_id,id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id,person_id) REFERENCES people(owner_id,id),
    FOREIGN KEY (owner_id,person_id,draft_revision)
        REFERENCES person_drafts(owner_id,person_id,revision),
    FOREIGN KEY (owner_id,person_id,chart_id)
        REFERENCES charts(owner_id,person_id,id),
    FOREIGN KEY (owner_id,person_id,birth_id)
        REFERENCES birth_records(owner_id,person_id,id),
    FOREIGN KEY (owner_id,profile_id,profile_revision)
        REFERENCES calculation_profiles(owner_id,id,revision)
);
CREATE INDEX conversation_people_person_idx ON conversation_people(owner_id,person_id,conversation_id);
