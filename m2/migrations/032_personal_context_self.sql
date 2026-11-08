CREATE TABLE personal_context_self (
    owner_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    person_id TEXT,
    version INTEGER NOT NULL CHECK (version > 0),
    FOREIGN KEY (owner_id, person_id) REFERENCES people(owner_id, id)
        ON DELETE SET NULL (person_id)
);
