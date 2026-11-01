-- Immutable user-requested advanced technique results, separate from active natal.
CREATE TABLE advanced_results (
    owner_id TEXT NOT NULL,
    id TEXT NOT NULL,
    technique TEXT NOT NULL,
    chart_a_id TEXT NOT NULL,
    chart_b_id TEXT,
    method_version TEXT NOT NULL,
    parameters JSONB NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, id),
    FOREIGN KEY (owner_id, chart_a_id) REFERENCES charts(owner_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, chart_b_id) REFERENCES charts(owner_id, id) ON DELETE CASCADE
);
CREATE INDEX advanced_results_source ON advanced_results(owner_id, chart_a_id, created_at DESC);
