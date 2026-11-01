-- A preflight prevents new deletion of a reference with live successor editions.
-- An older, already-durable tombstone still has to replay across old backups.
-- Preserve the surviving edition's historical predecessor identity when the
-- predecessor is erased, without retaining a dangling live-source FK.
ALTER TABLE reference_sources ADD COLUMN supersedes_deleted_source_id text;
ALTER TABLE reference_sources ADD CONSTRAINT reference_sources_one_previous_check
  CHECK (supersedes_source_id IS NULL OR supersedes_deleted_source_id IS NULL);
