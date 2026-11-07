CREATE TABLE personal_context (
    owner_id TEXT NOT NULL, person_id TEXT NOT NULL, id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0), content JSONB NOT NULL,
    lifecycle TEXT NOT NULL DEFAULT 'active' CHECK(lifecycle IN ('active','source_invalidated')),
    source JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,person_id,id),
    FOREIGN KEY(owner_id,person_id) REFERENCES people(owner_id,id) ON DELETE CASCADE
);
