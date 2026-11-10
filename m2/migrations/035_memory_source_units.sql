CREATE TABLE memory_source_units (
    id BIGSERIAL UNIQUE NOT NULL,
    owner_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    PRIMARY KEY(owner_id,conversation_id,turn_id),
    FOREIGN KEY(owner_id,conversation_id,turn_id)
        REFERENCES turns(owner_id,conversation_id,id) ON DELETE CASCADE
);
