-- One current generated natal per owned person; immutable chart/birth history stays intact.
-- Request IDs are the idempotency keys. A deliberate later action may repeat inputs
-- without an earlier lost-ACK replay unexpectedly reactivating an old chart.
ALTER TABLE birth_generation_requests
    DROP CONSTRAINT birth_generation_requests_owner_id_person_id_input_digest_key;

ALTER TABLE charts ADD CONSTRAINT charts_owner_person_id_unique
    UNIQUE (owner_id, person_id, id);
ALTER TABLE birth_generation_requests ADD CONSTRAINT birth_generation_chart_unique
    UNIQUE (owner_id, person_id, chart_id);
CREATE TABLE person_active_charts (
    owner_id text NOT NULL,
    person_id text NOT NULL,
    chart_id text NOT NULL,
    PRIMARY KEY (owner_id, person_id),
    FOREIGN KEY (owner_id, person_id) REFERENCES people(owner_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, person_id, chart_id)
        REFERENCES charts(owner_id, person_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, person_id, chart_id)
        REFERENCES birth_generation_requests(owner_id, person_id, chart_id) ON DELETE CASCADE
);

-- Only outcomes of the established birth-generation action are eligible. Older
-- arbitrary/imported/solar charts are not guessed to be the active natal.
INSERT INTO person_active_charts(owner_id, person_id, chart_id)
SELECT DISTINCT ON (g.owner_id, g.person_id) g.owner_id, g.person_id, g.chart_id
FROM birth_generation_requests g
ORDER BY g.owner_id, g.person_id, g.created_at DESC, g.request_id DESC;
