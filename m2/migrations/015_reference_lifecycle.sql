-- Existing synthetic sources retain their default not-selected state. No real
-- source is imported or promoted by this migration.
ALTER TABLE reference_sources DROP CONSTRAINT reference_sources_rights_basis_check;
ALTER TABLE reference_sources ADD CONSTRAINT reference_sources_rights_basis_check
  CHECK (rights_basis IN ('synthetic_fixture', 'public_domain_edition',
                          'open_license', 'user_permitted_private'));
ALTER TABLE reference_sources ADD CONSTRAINT reference_sources_approval_check
  CHECK (approval IN ('not_kat_selected', 'selected', 'revoked'));
ALTER TABLE reference_sources ADD COLUMN language text NOT NULL DEFAULT 'en';
ALTER TABLE reference_sources ADD COLUMN source_url text;
ALTER TABLE reference_sources ADD COLUMN supersedes_source_id text;
ALTER TABLE reference_sources ADD CONSTRAINT reference_sources_previous_fk
  FOREIGN KEY(owner_id,supersedes_source_id)
  REFERENCES reference_sources(owner_id,id) ON DELETE RESTRICT;
CREATE TABLE reference_originals (
    owner_id text NOT NULL,
    source_id text NOT NULL,
    original_text text NOT NULL,
    content_sha256 char(64) NOT NULL,
    extraction_note text NOT NULL,
    PRIMARY KEY(owner_id,source_id),
    FOREIGN KEY(owner_id,source_id) REFERENCES reference_sources(owner_id,id) ON DELETE CASCADE
);
