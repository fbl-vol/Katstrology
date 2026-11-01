-- Deliberate saved timing and private self-reported notes. No model/recall index.
CREATE TABLE watch_items (
    owner_id TEXT NOT NULL, person_id TEXT NOT NULL, id TEXT NOT NULL,
    result_id TEXT NOT NULL, event_index INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, person_id, id),
    FOREIGN KEY (owner_id, person_id) REFERENCES people(owner_id,id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, result_id) REFERENCES advanced_results(owner_id,id) ON DELETE CASCADE,
    CHECK (event_index IS NULL OR event_index >= 0)
);
CREATE TABLE watch_actions (
    owner_id TEXT NOT NULL, person_id TEXT NOT NULL, item_id TEXT NOT NULL,
    id TEXT NOT NULL, version INTEGER NOT NULL, note TEXT NOT NULL,
    reminder JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, person_id, item_id, id),
    UNIQUE (owner_id, person_id, item_id, version),
    FOREIGN KEY (owner_id, person_id, item_id)
      REFERENCES watch_items(owner_id,person_id,id) ON DELETE CASCADE
);
CREATE TABLE journal_entries (
    owner_id TEXT NOT NULL, person_id TEXT NOT NULL, id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('date','instant','uncertain')),
    local_date DATE NOT NULL, instant_utc TIMESTAMPTZ,
    zone_name TEXT, linked_result_id TEXT,
    attribution TEXT NOT NULL DEFAULT 'voluntary_self_report',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,person_id,id),
    FOREIGN KEY(owner_id,person_id) REFERENCES people(owner_id,id) ON DELETE CASCADE,
    FOREIGN KEY(owner_id,linked_result_id) REFERENCES advanced_results(owner_id,id)
      ON DELETE SET NULL (linked_result_id),
    CHECK ((kind='instant' AND instant_utc IS NOT NULL AND zone_name IS NOT NULL)
           OR (kind IN ('date','uncertain') AND instant_utc IS NULL AND zone_name IS NULL))
);
CREATE TABLE journal_actions (
    owner_id TEXT NOT NULL, person_id TEXT NOT NULL, entry_id TEXT NOT NULL,
    id TEXT NOT NULL, version INTEGER NOT NULL, text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,person_id,entry_id,id),
    UNIQUE(owner_id,person_id,entry_id,version),
    FOREIGN KEY(owner_id,person_id,entry_id)
      REFERENCES journal_entries(owner_id,person_id,id) ON DELETE CASCADE
);
