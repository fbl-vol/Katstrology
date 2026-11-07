CREATE TABLE person_links (
    owner_id TEXT NOT NULL, person_id TEXT NOT NULL, id TEXT NOT NULL,
    other_person_id TEXT NOT NULL, label TEXT NOT NULL, dates TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(owner_id,person_id,id),
    UNIQUE(owner_id,person_id,other_person_id,label),
    CHECK(person_id <> other_person_id),
    FOREIGN KEY(owner_id,person_id) REFERENCES people(owner_id,id) ON DELETE CASCADE,
    FOREIGN KEY(owner_id,other_person_id) REFERENCES people(owner_id,id) ON DELETE CASCADE
);
