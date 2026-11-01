-- Every application lookup and FK carries the authenticated owner identity.
CREATE TABLE people (
    owner_id text NOT NULL REFERENCES accounts(id),
    id text NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, id)
);
CREATE TABLE birth_records (
    owner_id text NOT NULL,
    person_id text NOT NULL,
    id text NOT NULL,
    wall_time text,
    zone_name text NOT NULL,
    fold smallint,
    instant_utc timestamptz,
    earliest_utc timestamptz,
    latest_utc timestamptz,
    latitude double precision,
    longitude double precision,
    provenance text NOT NULL,
    source_conversation_id text,
    source_turn_id text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, person_id, id),
    FOREIGN KEY (owner_id, person_id) REFERENCES people(owner_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, source_conversation_id, source_turn_id)
        REFERENCES turns(owner_id, conversation_id, id) ON DELETE CASCADE,
    CHECK ((instant_utc IS NOT NULL AND earliest_utc IS NULL AND latest_utc IS NULL)
        OR (instant_utc IS NULL AND earliest_utc IS NOT NULL AND latest_utc IS NOT NULL)),
    CHECK ((source_conversation_id IS NULL) = (source_turn_id IS NULL))
);
CREATE TABLE calculation_profiles (
    owner_id text NOT NULL REFERENCES accounts(id),
    id text NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    settings jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, id, revision)
);
CREATE TABLE charts (
    owner_id text NOT NULL,
    id text NOT NULL,
    person_id text NOT NULL,
    birth_id text NOT NULL,
    profile_id text NOT NULL,
    profile_revision integer NOT NULL,
    result jsonb NOT NULL,
    engine_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, id),
    FOREIGN KEY (owner_id, person_id, birth_id)
        REFERENCES birth_records(owner_id, person_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, profile_id, profile_revision)
        REFERENCES calculation_profiles(owner_id, id, revision)
);
CREATE TABLE chart_evidence (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    turn_id text NOT NULL,
    chart_id text NOT NULL,
    event_sequence integer NOT NULL,
    PRIMARY KEY (owner_id, conversation_id, turn_id, chart_id, event_sequence),
    FOREIGN KEY (owner_id, conversation_id, turn_id, event_sequence)
        REFERENCES events(owner_id, conversation_id, turn_id, sequence) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, chart_id) REFERENCES charts(owner_id, id) ON DELETE CASCADE
);
