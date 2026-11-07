CREATE TABLE personal_profile_actions (
    owner_id TEXT NOT NULL, person_id TEXT NOT NULL, id TEXT NOT NULL,
    request JSONB NOT NULL, result JSONB NOT NULL,
    PRIMARY KEY(owner_id,person_id,id),
    FOREIGN KEY(owner_id,person_id) REFERENCES people(owner_id,id) ON DELETE CASCADE
);
