-- Preserve unknown legacy/manual names. Only new placeholder conversations enter
-- the one-attempt, source-fenced automatic title workflow.
ALTER TABLE conversations ADD COLUMN title_origin text NOT NULL DEFAULT 'legacy'
    CHECK (title_origin IN ('legacy', 'placeholder', 'generated', 'manual'));
ALTER TABLE conversations ADD COLUMN title_status text NOT NULL DEFAULT 'untouched'
    CHECK (title_status IN ('untouched', 'waiting', 'pending', 'generated', 'failed', 'stale'));
ALTER TABLE conversations ADD COLUMN title_source_turn text;
ALTER TABLE conversations ADD COLUMN title_source_epoch bigint;
ALTER TABLE conversations ADD COLUMN title_source_digest text;
