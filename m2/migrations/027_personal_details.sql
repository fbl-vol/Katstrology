CREATE TABLE personal_details (
    owner_id TEXT NOT NULL, person_id TEXT NOT NULL, version INTEGER NOT NULL,
    details JSONB NOT NULL,
    PRIMARY KEY(owner_id,person_id),
    FOREIGN KEY(owner_id,person_id) REFERENCES people(owner_id,id) ON DELETE CASCADE
);
