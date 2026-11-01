CREATE TABLE reference_evidence (
    owner_id text NOT NULL,
    conversation_id text NOT NULL,
    turn_id text NOT NULL,
    event_sequence integer NOT NULL,
    source_id text NOT NULL,
    passage_id text NOT NULL,
    PRIMARY KEY(owner_id,conversation_id,turn_id,event_sequence,source_id,passage_id),
    FOREIGN KEY(owner_id,conversation_id,turn_id,event_sequence)
        REFERENCES events(owner_id,conversation_id,turn_id,sequence) ON DELETE CASCADE,
    FOREIGN KEY(owner_id,source_id,passage_id)
        REFERENCES reference_passages(owner_id,source_id,id) ON DELETE CASCADE
);
