"""Owner-scoped, immutable rights-attributed editions and personal statements.

Reference originals are retained text, not generated summaries or embedding indexes.
Selection is an explicit local editorial act, never a model-issued permission.
"""

from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlparse


from m2 import book_package
from m2.provenance import source_turn_current


class References:
    def __init__(self, store):
        self.store = store

    def add_source(self, session, source_id, author, title, edition, tradition,
                   technique, provenance, rights_evidence, source=None, *,
                   rights_basis='synthetic_fixture', language='en', source_url=None,
                   original_text=None, extraction_note=None, supersedes_source_id=None,
                   book_source=False):
        owner = self.store.owner(session)
        self.store._id(source_id)
        metadata = (author, title, edition, tradition, technique,
                    provenance, rights_evidence)
        for value in metadata:
            self.store._text(value, 512)
        if rights_basis not in ('synthetic_fixture', 'public_domain_edition',
                                'open_license', 'user_permitted_private'):
            raise ValueError('Unsupported source rights basis')
        if not isinstance(language, str) or not 2 <= len(language) <= 12 or not language.isascii():
            raise ValueError('Invalid source language')
        if source_url is not None:
            self.store._text(source_url, 512)
            parsed = urlparse(source_url)
            if (parsed.scheme != 'https' or not parsed.hostname or
                    parsed.username or parsed.password):
                raise ValueError('Source URL must be HTTPS without credentials')
        if rights_basis != 'synthetic_fixture' and original_text is None:
            raise ValueError('Non-fixture source requires a preserved original')
        if original_text is not None:
            self.store._text(original_text, book_package.MAX_TEXT if book_source else 128 * 1024)
            self.store._text(extraction_note, 512)
        elif extraction_note is not None:
            raise ValueError('Extraction note without source original')
        if supersedes_source_id is not None:
            self.store._id(supersedes_source_id)
            if supersedes_source_id == source_id:
                raise ValueError('Source revision requires a distinct identity')
        if self.store.ledger.contains_reference(owner, source_id):
            raise ValueError('Deleted reference identity cannot be reused')
        if source is not None:
            conv_id, turn_id = source
            if self.store.read_turn(session, conv_id, turn_id)['status'] != 'complete':
                raise ValueError('Source turn must be complete')
        else:
            conv_id = turn_id = None
        with self.store.db.transaction():
            self.store.db.execute('''
                INSERT INTO reference_sources(owner_id,id,author,title,edition,tradition,
                    technique,rights_basis,rights_evidence,provenance,source_conversation_id,
                    source_turn_id,language,source_url,supersedes_source_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ''', (owner, source_id, author, title, edition, tradition, technique,
                  rights_basis, rights_evidence, provenance, conv_id, turn_id,
                  language, source_url, supersedes_source_id))
            if original_text is not None:
                self.store.db.execute('''
                    INSERT INTO reference_originals VALUES (%s,%s,%s,%s,%s)
                ''', (owner, source_id, original_text,
                      sha256(original_text.encode()).hexdigest(), extraction_note))
        return source_id

    def add_passage(self, session, source_id, passage_id, section, content):
        owner = self.store.owner(session)
        self.store._id(source_id)
        self.store._id(passage_id)
        self.store._text(section, 256)
        self.store._text(content, 4096)
        digest = sha256(content.encode('utf-8')).hexdigest()
        source = self.store.db.execute('''
            SELECT approval FROM reference_sources WHERE owner_id=%s AND id=%s
        ''', (owner, source_id)).fetchone()
        if not source or source['approval'] != 'not_kat_selected':
            raise ValueError('Passages can only be added to an unselected source edition')
        original = self.store.db.execute('''
            SELECT original_text FROM reference_originals WHERE owner_id=%s AND source_id=%s
        ''', (owner, source_id)).fetchone()
        if original is not None and content not in original['original_text']:
            raise ValueError('Passage must occur exactly in the preserved original')
        self.store.db.execute('''
            INSERT INTO reference_passages(owner_id,source_id,id,section,content,content_sha256)
            VALUES (%s,%s,%s,%s,%s,%s)
        ''', (owner, source_id, passage_id, section, content, digest))
        return digest

    def get_passage(self, session, source_id, passage_id):
        owner = self.store.owner(session)
        row = self.store.db.execute('''
            SELECT p.id,p.section,p.content,p.content_sha256,
                   l.ordinal,l.start_offset,l.end_offset,l.page_start,l.page_end,
                   l.printed_page_start,l.printed_page_end,
                   l.source_locator_start,l.source_locator_end,l.parent_section,l.extraction_status,l.review_status,
                   b.raw_sha256,b.transcript_sha256,b.processing_sha256,b.normalized_sha256,
                   s.author,s.title,s.edition,
                   s.tradition,s.technique,s.provenance,s.rights_basis,s.rights_evidence,
                   s.approval,s.language,s.source_url,
                   COALESCE(s.supersedes_source_id,s.supersedes_deleted_source_id) AS supersedes_source_id,
                   s.supersedes_deleted_source_id IS NOT NULL AS supersedes_source_deleted,
                   s.source_conversation_id,s.source_turn_id
            FROM reference_passages p JOIN reference_sources s
              ON (s.owner_id=p.owner_id AND s.id=p.source_id)
            LEFT JOIN reference_book_locations l ON (l.owner_id=p.owner_id
                AND l.source_id=p.source_id AND l.passage_id=p.id)
            LEFT JOIN reference_book_sources b ON (b.owner_id=p.owner_id AND b.source_id=p.source_id)
            WHERE p.owner_id=%s AND p.source_id=%s AND p.id=%s
        ''', (owner, self.store._id(source_id), self.store._id(passage_id))).fetchone()
        if not row:
            raise KeyError('Passage not found')
        row['neighbors'] = {'previous': None, 'next': None}
        if row['ordinal'] is not None and row['parent_section'] != 'mixed_sections':
            neighbors = self.store.db.execute('''
                SELECT p.id,l.ordinal FROM reference_book_locations l JOIN reference_passages p
                  ON (p.owner_id=l.owner_id AND p.source_id=l.source_id AND p.id=l.passage_id)
                WHERE l.owner_id=%s AND l.source_id=%s AND l.parent_section=%s
                  AND p.section=%s AND l.ordinal IN (%s,%s)
            ''', (owner, source_id, row['parent_section'], row['section'],
                  row['ordinal'] - 1, row['ordinal'] + 1)).fetchall()
            for neighbor in neighbors:
                row['neighbors']['previous' if neighbor['ordinal'] < row['ordinal'] else 'next'] = neighbor['id']
        conv_id, turn_id = row['source_conversation_id'], row['source_turn_id']
        row['source_status'] = ('independent_synthetic_fixture' if row['rights_basis'] == 'synthetic_fixture'
                                else 'independent_attributed_edition')
        if conv_id:
            head = self.store.active_head(session, conv_id)
            ancestry = self.store.ancestry(session, conv_id, head) if head else []
            turn = self.store.read_turn(session, conv_id, turn_id)
            row['source_status'] = ('superseded' if turn['corrections'] else
                                    'abandoned_branch' if turn_id not in ancestry else
                                    'active' if source_turn_current(self.store, session,
                                                                    conv_id, turn_id) else
                                    'superseded')
            row['source_corrections'] = turn['corrections']
        return row

    def select(self, session, source_id):
        """Explicitly select a reviewed rights-bearing edition; never a model tool."""
        owner = self.store.owner(session)
        source = self.store.db.execute('''
            SELECT rights_basis,rights_evidence FROM reference_sources
            WHERE owner_id=%s AND id=%s AND approval='not_kat_selected'
        ''', (owner, self.store._id(source_id))).fetchone()
        if not source:
            raise KeyError('Unselected source not found')
        if source['rights_basis'] != 'synthetic_fixture' and not self.store.db.execute('''
            SELECT 1 FROM reference_originals WHERE owner_id=%s AND source_id=%s
        ''', (owner, source_id)).fetchone():
            raise ValueError('Preserved source original required')
        if not self.store.db.execute('''
            SELECT 1 FROM reference_passages WHERE owner_id=%s AND source_id=%s LIMIT 1
        ''', (owner, source_id)).fetchone():
            raise ValueError('Cannot select an empty source edition')
        self.store.db.execute('''
            UPDATE reference_sources SET approval='selected'
            WHERE owner_id=%s AND id=%s
        ''', (owner, source_id))

    def revoke(self, session, source_id):
        """Exclude revoked content immediately, including after an older-backup restore."""
        self.store.ledger.revoke_reference(self.store, session, source_id)

    def readable_passage(self, session, source_id, passage_id):
        """Single eligibility boundary for CLI, MCP and model passage reads."""
        row = self.get_passage(session, source_id, passage_id)
        if row['approval'] == 'revoked' or (row['approval'] != 'selected' and
                                            row['rights_basis'] != 'synthetic_fixture') or row['source_status'] in (
                                                'superseded', 'abandoned_branch'):
            raise PermissionError('Source edition is not eligible for retrieval')
        return row

    def import_text_file(self, session, manifest_path, original_path):
        """Import a bounded UTF-8 original with exact located spans; no OCR or network I/O.

        A same-ID retry is accepted only for the same original AND manifest. Revisions
        require a new ID. File paths are explicit operator input, never model input.
        """
        with Path(original_path).open('rb') as source:
            raw = source.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError('Source original exceeds 128 KiB')
        text = raw.decode('utf-8')
        if text.startswith('\ufeff'):
            raise ValueError('UTF-8 BOM is not supported for exact original-byte identity')
        with Path(manifest_path).open('rb') as source:
            manifest_bytes = source.read(32 * 1024 + 1)
        if len(manifest_bytes) > 32 * 1024:
            raise ValueError('Source manifest exceeds 32 KiB')
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict) or set(manifest) != {
                'source_id', 'author', 'title', 'edition', 'tradition', 'technique',
                'provenance', 'rights_evidence', 'rights_basis', 'language',
                'source_url', 'extraction_note', 'passages'} and set(manifest) != {
                'source_id', 'author', 'title', 'edition', 'tradition', 'technique',
                'provenance', 'rights_evidence', 'rights_basis', 'language',
                'source_url', 'extraction_note', 'supersedes_source_id', 'passages'}:
            raise ValueError('Invalid source manifest fields')
        passages = manifest.pop('passages')
        if not isinstance(passages, list) or any(not isinstance(item, dict) or
                set(item) != {'id', 'section', 'content'} for item in passages):
            raise ValueError('Invalid located passages')
        source_id = self.store._id(manifest['source_id'])
        owner = self.store.owner(session)
        existing = self.store.db.execute('''
            SELECT s.author,s.title,s.edition,s.tradition,s.technique,s.provenance,
                   s.rights_evidence,s.rights_basis,s.language,s.source_url,
                   COALESCE(s.supersedes_source_id,s.supersedes_deleted_source_id) AS supersedes_source_id,
                   o.extraction_note,o.original_text,o.content_sha256
            FROM reference_sources s JOIN reference_originals o
              ON (s.owner_id=o.owner_id AND s.id=o.source_id)
            WHERE s.owner_id=%s AND s.id=%s
        ''', (owner, source_id)).fetchone()
        if existing:
            fields = {key: value for key, value in manifest.items() if key != 'source_id'}
            rows = self.store.db.execute('''
                SELECT id,section,content FROM reference_passages
                WHERE owner_id=%s AND source_id=%s ORDER BY id
            ''', (owner, source_id)).fetchall()
            if (all(existing[key] == value for key, value in fields.items()) and
                    existing['original_text'] == text and
                    existing['content_sha256'] == sha256(text.encode()).hexdigest() and
                    sorted(passages, key=lambda item: item['id']) == [
                        {key: row[key] for key in ('id', 'section', 'content')} for row in rows]):
                return {'source_id': source_id, 'already_imported': True}
            raise ValueError('Edition ID already exists with different content or metadata')
        self.ingest_edition(session, manifest, text, passages)
        return {'source_id': source_id, 'already_imported': False}

    def ingest_edition(self, session, metadata, original_text, passages):
        """Atomic text ingest; revisions use new immutable source IDs."""
        if not isinstance(passages, list) or not 1 <= len(passages) <= 64:
            raise ValueError('Select 1..64 located passages')
        with self.store.db.transaction():
            source_id = self.add_source(session, original_text=original_text, **metadata)
            for item in passages:
                if not isinstance(item, dict) or set(item) != {'id', 'section', 'content'}:
                    raise ValueError('Invalid located passage')
                self.add_passage(session, source_id, item['id'], item['section'], item['content'])
        return source_id

    def import_book_package(self, session, path):
        """Validate all package bytes before an atomic, unselected owner import."""
        package = book_package.validated_snapshot(path)
        manifest, raw, transcript, text = package
        owner = self.store.owner(session)
        source_id = self.store._id(manifest['source_id'])
        existing = self.store.db.execute('''
            SELECT b.manifest,b.raw_source,b.transcript,b.raw_sha256,o.original_text,o.content_sha256
            FROM reference_book_sources b JOIN reference_originals o
              ON (o.owner_id=b.owner_id AND o.source_id=b.source_id)
            WHERE b.owner_id=%s AND b.source_id=%s
        ''', (owner, source_id)).fetchone()
        if existing:
            if (existing['manifest'] != manifest or bytes(existing['raw_source']) != raw or
                    bytes(existing['transcript']) != transcript or
                    existing['raw_sha256'] != book_package.digest(raw) or
                    existing['original_text'] != text or
                    existing['content_sha256'] != book_package.digest(text.encode()) or
                    self.store.db.execute('''
                        SELECT count(*) AS n FROM reference_book_locations
                        WHERE owner_id=%s AND source_id=%s
                    ''', (owner, source_id)).fetchone()['n'] != len(manifest['passages'])):
                raise ValueError('Imported edition identity differs from package')
            return {'source_id': source_id, 'already_imported': True}
        if self.store.db.execute('SELECT 1 FROM reference_sources WHERE owner_id=%s AND id=%s',
                                 (owner, source_id)).fetchone():
            raise ValueError('Edition ID already exists')
        metadata = dict(manifest['metadata'], source_id=source_id)
        metadata.pop('processing_revision')
        passages = manifest['passages']
        with self.store.db.transaction():
            self.add_source(session, original_text=text, book_source=True,
                            **metadata)
            self.store.db.execute('''
                INSERT INTO reference_book_sources
                  (owner_id,source_id,raw_source,transcript,raw_sha256,transcript_sha256,
                   processing_sha256,normalized_sha256,package_version,manifest)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ''', (owner, source_id, raw, transcript, manifest['source_sha256'],
                  manifest['transcript_sha256'], manifest['processing_sha256'],
                  manifest['normalized_sha256'],
                  manifest['package_version'], json.dumps(manifest)))
            for item in passages:
                self.add_passage(session, source_id, item['id'], item['section'], item['content'])
                self.store.db.execute('''
                    INSERT INTO reference_book_locations
                      (owner_id,source_id,passage_id,ordinal,start_offset,end_offset,page_start,
                       page_end,printed_page_start,printed_page_end,source_locator_start,
                       source_locator_end,parent_section,extraction_status,review_status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ''', (owner, source_id, item['id'], item['ordinal'], item['start'], item['end'],
                      item['page_start'], item['page_end'], item['printed_page_start'],
                      item['printed_page_end'], item['source_locator_start'],
                      item['source_locator_end'], item['parent_section'],
                      item['extraction_status'], item['review_status']))
        return {'source_id': source_id, 'already_imported': False}


class PersonalContext:
    def __init__(self, store):
        self.store = store

    def add(self, session, person_id, entry_id, conversation_id, source_turn_id,
            statement, epistemic_status='user_reported', source_event_sequence=0,
            confirmation_turn_id=None):
        owner = self.store.owner(session)
        for value in (person_id, entry_id, conversation_id, source_turn_id):
            self.store._id(value)
        self.store._text(statement, 512)
        if epistemic_status not in {'user_reported', 'explicitly_confirmed', 'agent_inference', 'saved_user_passage', 'saved_assistant_passage'}:
            raise ValueError('Unsupported epistemic status')
        if not self.store.db.execute('SELECT 1 FROM people WHERE owner_id=%s AND id=%s',
                                     (owner, person_id)).fetchone():
            raise KeyError('Person not found')
        if self.store.read_turn(session, conversation_id, source_turn_id)['status'] != 'complete':
            raise ValueError('Source turn must be complete')
        event = self.store.read_event(session, conversation_id, source_turn_id, source_event_sequence)
        kind = 'assistant_chunk' if epistemic_status in ('agent_inference', 'saved_assistant_passage') else 'user'
        if event['kind'] != kind or (kind == 'user' and statement not in event['payload']['content']):
            raise ValueError('Statement must be extracted from its attributed source event')
        if epistemic_status == 'explicitly_confirmed':
            self.store._id(confirmation_turn_id)
            if confirmation_turn_id == source_turn_id:
                raise ValueError('Confirmation requires a separate user turn')
            confirmation = self.store.read_turn(session, conversation_id, confirmation_turn_id)
            if (confirmation['status'] != 'complete' or confirmation['events'][0]['payload']['content']
                    != f'confirm: {statement}'):
                raise ValueError('Explicit source confirmation required')
        elif confirmation_turn_id is not None:
            raise ValueError('Only confirmed entries may name a confirmation turn')
        self.store.db.execute('''
            INSERT INTO personal_entries(owner_id,person_id,id,conversation_id,source_turn_id,
                source_event_sequence,statement,epistemic_status,confirmation_turn_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ''', (owner, person_id, entry_id, conversation_id, source_turn_id,
              source_event_sequence, statement, epistemic_status, confirmation_turn_id))
        return entry_id
