-- Optional immutable full-book package details; old reference rows remain unchanged.
-- All rows cascade with their owner-scoped source and external deletion journal.
CREATE TABLE reference_book_sources (
    owner_id text NOT NULL,
    source_id text NOT NULL,
    raw_source bytea NOT NULL,
    transcript bytea NOT NULL,
    raw_sha256 char(64) NOT NULL,
    transcript_sha256 char(64) NOT NULL,
    processing_sha256 char(64) NOT NULL,
    normalized_sha256 char(64) NOT NULL,
    package_version integer NOT NULL CHECK (package_version=1),
    manifest jsonb NOT NULL,
    PRIMARY KEY (owner_id,source_id),
    FOREIGN KEY (owner_id,source_id) REFERENCES reference_sources(owner_id,id) ON DELETE CASCADE
);
CREATE TABLE reference_book_locations (
    owner_id text NOT NULL,
    source_id text NOT NULL,
    passage_id text NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal>=0 AND ordinal<512),
    start_offset integer NOT NULL CHECK (start_offset>=0),
    end_offset integer NOT NULL CHECK (end_offset>start_offset),
    page_start integer NOT NULL,
    page_end integer NOT NULL CHECK (page_end>=page_start),
    printed_page_start integer,
    printed_page_end integer,
    source_locator_start text NOT NULL,
    source_locator_end text NOT NULL,
    CHECK (printed_page_start IS NULL OR printed_page_start>0),
    CHECK (printed_page_end IS NULL OR printed_page_end>=printed_page_start),
    parent_section text NOT NULL,
    extraction_status text NOT NULL,
    review_status text NOT NULL,
    PRIMARY KEY (owner_id,source_id,passage_id),
    UNIQUE (owner_id,source_id,ordinal),
    FOREIGN KEY (owner_id,source_id,passage_id)
      REFERENCES reference_passages(owner_id,source_id,id) ON DELETE CASCADE
);
