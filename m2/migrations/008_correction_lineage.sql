-- A turn records the correction revision of its direct parent when it begins.
-- A later correction to that parent invalidates the old descendant; a new turn
-- can depend on the corrected replacement without changing archived events.
-- NULL marks pre-migration lineage, conservatively unusable after a parent correction.
ALTER TABLE turns ADD COLUMN parent_revision bigint;
ALTER TABLE corrections ADD COLUMN parent_revision bigint;
