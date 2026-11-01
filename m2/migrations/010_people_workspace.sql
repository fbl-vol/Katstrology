-- A person can exist before verified chart inputs. Drafts are labelled, immutable
-- versions of supplied details, not sources of calculated astrological values.
CREATE TABLE person_drafts (
    owner_id text NOT NULL,
    person_id text NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    details jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, person_id, revision),
    FOREIGN KEY (owner_id, person_id) REFERENCES people(owner_id, id) ON DELETE CASCADE
);
-- A chart reference belongs to a person, independently of any conversation.
CREATE TABLE person_attachments (
    owner_id text NOT NULL,
    person_id text NOT NULL,
    id text NOT NULL,
    filename text NOT NULL,
    media_type text NOT NULL,
    digest char(64) NOT NULL,
    byte_count integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, person_id, id),
    FOREIGN KEY (owner_id, person_id) REFERENCES people(owner_id, id) ON DELETE CASCADE
);
