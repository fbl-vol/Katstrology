CREATE TABLE memory_source_suppressions (
    owner_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    source_before BIGINT NOT NULL,
    PRIMARY KEY(owner_id,person_id),
    FOREIGN KEY(owner_id,person_id) REFERENCES people(owner_id,id) ON DELETE CASCADE
);
