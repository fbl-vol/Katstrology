-- One user action retains its exact selected inputs and immutable outcome across lost HTTP ACKs.
CREATE TABLE birth_generation_requests (
    owner_id text NOT NULL,
    person_id text NOT NULL,
    request_id text NOT NULL,
    input_digest char(64) NOT NULL,
    provisional boolean NOT NULL,
    place_id text,
    draft_revision integer NOT NULL,
    birth_id text NOT NULL,
    chart_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, person_id, request_id),
    UNIQUE (owner_id, person_id, input_digest),
    FOREIGN KEY (owner_id, person_id) REFERENCES people(owner_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, person_id, draft_revision) REFERENCES person_drafts(owner_id, person_id, revision),
    FOREIGN KEY (owner_id, person_id, birth_id) REFERENCES birth_records(owner_id, person_id, id),
    FOREIGN KEY (owner_id, chart_id) REFERENCES charts(owner_id, id)
);
