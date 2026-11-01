CREATE TABLE accounts (
    id text PRIMARY KEY,
    password_hash text NOT NULL
);
CREATE TABLE conversations (
    owner_id text NOT NULL REFERENCES accounts(id),
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    active_head text,
    epoch bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (owner_id, id)
);
CREATE TABLE turns (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    id text NOT NULL,
    parent_id text,
    prompt text NOT NULL,
    source text NOT NULL,
    status text NOT NULL CHECK (status IN ('open', 'complete', 'interrupted', 'error')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, conversation_id, id),
    FOREIGN KEY (owner_id, conversation_id) REFERENCES conversations(owner_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, conversation_id, parent_id)
      REFERENCES turns(owner_id, conversation_id, id)
);
CREATE TABLE events (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    turn_id text NOT NULL,
    sequence integer NOT NULL,
    kind text NOT NULL,
    payload jsonb NOT NULL,
    stored_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, conversation_id, turn_id, sequence),
    FOREIGN KEY (owner_id, conversation_id, turn_id)
      REFERENCES turns(owner_id, conversation_id, id) ON DELETE CASCADE
);
CREATE TABLE attachments (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    id text NOT NULL,
    filename text NOT NULL,
    digest char(64) NOT NULL,
    byte_count integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, conversation_id, id),
    FOREIGN KEY (owner_id, conversation_id)
      REFERENCES conversations(owner_id, id) ON DELETE CASCADE
);
CREATE TABLE corrections (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    id text NOT NULL,
    source_turn_id text NOT NULL,
    action text NOT NULL CHECK (action IN ('correct', 'withdraw')),
    replacement text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, conversation_id, id),
    FOREIGN KEY (owner_id, conversation_id, source_turn_id)
      REFERENCES turns(owner_id, conversation_id, id) ON DELETE CASCADE
);
CREATE TABLE summaries (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    head_id text NOT NULL,
    epoch bigint NOT NULL,
    covered_ids jsonb NOT NULL,
    omitted_older integer NOT NULL,
    content text NOT NULL,
    PRIMARY KEY (owner_id, conversation_id, head_id),
    FOREIGN KEY (owner_id, conversation_id) REFERENCES conversations(owner_id, id) ON DELETE CASCADE
);
CREATE TABLE search_entries (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    source_id text NOT NULL,
    epoch bigint NOT NULL,
    speaker text NOT NULL,
    content text NOT NULL,
    PRIMARY KEY (owner_id, conversation_id, source_id, speaker),
    FOREIGN KEY (owner_id, conversation_id) REFERENCES conversations(owner_id, id) ON DELETE CASCADE
);
CREATE INDEX search_text_idx ON search_entries USING gin (to_tsvector('simple', content));
CREATE TABLE rebuild_queue (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    epoch bigint NOT NULL,
    PRIMARY KEY (owner_id, conversation_id),
    FOREIGN KEY (owner_id, conversation_id) REFERENCES conversations(owner_id, id) ON DELETE CASCADE
);
