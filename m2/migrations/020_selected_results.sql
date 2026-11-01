-- The exact saved result and optional crossing chosen for a committed message.
-- Original result/chart rows cannot disappear while a referenced turn survives.
CREATE TABLE turn_selected_results (
    owner_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    result_id TEXT NOT NULL,
    event_index INTEGER,
    chart_a_id TEXT NOT NULL,
    chart_b_id TEXT,
    source_status_at_ack TEXT NOT NULL CHECK (source_status_at_ack IN ('current','historical')),
    PRIMARY KEY (owner_id, conversation_id, turn_id),
    FOREIGN KEY (owner_id, conversation_id, turn_id)
      REFERENCES turns(owner_id, conversation_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, result_id) REFERENCES advanced_results(owner_id, id),
    CHECK (event_index IS NULL OR event_index >= 0)
);
