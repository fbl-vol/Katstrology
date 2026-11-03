"""Synthetic full-sized book package and owner-scoped reference acceptance."""

from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.backup import dump_owned, restore_owned, verify_reference_contents
from m2.store import Store

from m2.gateway import run_turn
from m2.provider_model import ResponsesModel
from m2.test_agent_reads import FakeBridge, ScriptedTransport
from m2.tool_evidence import MAX_MODEL_EVIDENCE_BYTES

from m2 import book_package
from m2.book_package import prepare, validate
from m2.references import References
from m2.evidence import search_evidence
from m2.agent_reads import execute
from m2.test_support import DatabaseCase


def fixture(root):
    root = Path(root)
    raw = root / 'source.dat'
    raw.write_bytes(b'private-format synthetic original\n' * 8000)  # >128 KiB
    leaves = root / 'leaves.json'
    rows = [dict(text=f'Synthetic leaf {i:03d}: ' + ('café Δ motif ' * 240) +
                 (' farendtoken ' if i == 210 else ' '),
                 page=i + 1, printed_page=i + 1, source_locator=f'synthetic leaf {i + 1}',
                 section=f'Chapter {i // 20 + 1}',
                 parent_section='Synthetic observations',
                 extraction_status='unverified_transcription', review_status='not_reviewed')
            for i in range(211)]
    leaves.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    metadata = root / 'metadata.json'
    record = dict(author='Synthetic author', title='Synthetic full-book test', edition='Unverified edition',
                  tradition='invented_fixture', technique='natal', provenance='Local synthetic original',
                  rights_basis='user_permitted_private', rights_evidence='Synthetic test operator permission for authored fixture',
                  language='en', source_url=None, extraction_note='Unverified transcription',
                  supersedes_source_id=None, processing_revision='transcript-v1')
    metadata.write_text(json.dumps(record), encoding='utf-8')
    return raw, leaves, metadata, rows, record


class PackageTests(DatabaseCase):
    fixture_requires_fresh_migration = True

    def test_full_book_import_navigation_lifecycle(self):
        root = Path(self.directory.name)
        raw, leaves, metadata, rows, _ = fixture(root)
        package = prepare(raw, leaves, metadata, root / 'packages')
        manifest = validate(package)
        text = ''.join(row['text'] + '\n\n' for row in rows)
        self.assertGreater(len(text.encode()), 128 * 1024)
        self.assertGreater(len(manifest['passages']), 195)
        self.assertEqual(manifest['normalized_sha256'], sha256(text.encode()).hexdigest())
        self.assertEqual(''.join(p['content'] for p in manifest['passages']), text)
        self.assertTrue(any(p['page_start'] != p['page_end'] for p in manifest['passages']))
        self.assertEqual(prepare(raw, leaves, metadata, root / 'packages'), package)
        refs = References(self.store)
        source = refs.import_book_package(self.alice, package)['source_id']
        self.assertTrue(refs.import_book_package(self.alice, package)['already_imported'])
        self.assertEqual(self.store.db.execute('''SELECT count(*) AS n FROM reference_book_locations
            WHERE owner_id='alice' AND source_id=%s''', (source,)).fetchone()['n'], len(manifest['passages']))
        self.assertEqual(self.store.db.execute('''SELECT octet_length(raw_source) AS n FROM reference_book_sources
            WHERE owner_id='alice' AND source_id=%s''', (source,)).fetchone()['n'], len(raw.read_bytes()))
        self.assertEqual(search_evidence(self.store, self.alice, 'farendtoken')['results'], [])
        with self.assertRaises(PermissionError):
            refs.readable_passage(self.alice, source, manifest['passages'][-1]['id'])
        refs.select(self.alice, source)
        found = search_evidence(self.store, self.alice, 'farendtoken', include_history=False)
        self.assertEqual(found['results'][0]['passage_id'], manifest['passages'][-1]['id'])
        self.assertEqual(found['results'][0]['source_id'], source)
        self.assertEqual(found['results'][0]['page_end'], 211)
        self.assertEqual(found['results'][0]['printed_page_end'], 211)
        self.assertEqual(found['results'][0]['review_status'], 'not_reviewed')
        self.assertFalse(found['semantic_available'])
        last = manifest['passages'][-1]
        read = execute(self.store, self.alice, 'get_reference_passage', {
            'source_id': source, 'passage_id': last['id']}, set())
        self.assertEqual(read['content'], last['content'])
        self.assertEqual(read['start_offset'], last['start'])
        self.assertEqual(read['end_offset'], last['end'])
        self.assertEqual(read['neighbors']['previous'], manifest['passages'][-2]['id'])
        crossing = next(p for p in manifest['passages'] if p['page_end'] > p['page_start'])
        self.assertEqual(crossing['parent_section'], 'Synthetic observations')
        self.assertEqual(refs.get_passage(self.alice, source, crossing['id'])['content'],
                         text[crossing['start']:crossing['end']])
        with self.assertRaises(KeyError):
            refs.readable_passage(self.bob, source, manifest['passages'][-1]['id'])
        refs.revoke(self.alice, source)
        self.assertEqual(search_evidence(self.store, self.alice, 'farendtoken')['results'], [])
        self.ledger.delete_reference(self.store, self.alice, source)
        self.assertEqual(self.store.db.execute('''SELECT count(*) AS n FROM reference_book_sources
            WHERE owner_id='alice' AND source_id=%s''', (source,)).fetchone()['n'], 0)

    def test_invalid_package_revision_and_rollback(self):
        root = Path(self.directory.name)
        raw, leaves, metadata, rows, record = fixture(root)
        package = prepare(raw, leaves, metadata, root / 'packages')
        refs = References(self.store)
        original_id = refs.import_book_package(self.alice, package)['source_id']
        broken = root / 'broken'
        broken.mkdir()
        for member in package.iterdir():
            (broken / member.name).write_bytes(member.read_bytes())
        (broken / 'normalized.txt').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            refs.import_book_package(self.alice, broken)
        (broken / 'normalized.txt').write_bytes((package / 'normalized.txt').read_bytes())
        tampered = json.loads((broken / 'manifest.json').read_text())
        tampered['passages'][-1]['page_start'] = 1
        (broken / 'manifest.json').write_text(json.dumps(tampered))
        with self.assertRaises(ValueError):
            refs.import_book_package(self.alice, broken)
        record['processing_revision'] = 'interrupted'
        metadata.write_text(json.dumps(record))
        with patch('m2.book_package.os.rename', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                prepare(raw, leaves, metadata, root / 'packages')
        self.assertEqual(validate(package)['source_id'], original_id)
        self.assertEqual(len(list((root / 'packages').iterdir())), 1)
        self.assertEqual(refs.import_book_package(self.alice, package)['source_id'], original_id)
        record['processing_revision'] = 'transcript-v2'
        metadata.write_text(json.dumps(record))
        newer = prepare(raw, leaves, metadata, root / 'packages')
        self.assertNotEqual(newer, package)
        self.assertEqual(validate(package)['source_id'], original_id)
        # A failed DB insert must not leave either the source or partially inserted passages.
        newer_manifest = validate(newer)
        self.assertEqual(refs.import_book_package(self.alice, newer)['source_id'],
                         newer_manifest['source_id'])
        self.assertEqual(refs.get_passage(self.alice, original_id, 'p-0000000')['approval'],
                         'not_kat_selected')
        record['processing_revision'] = 'transcript-v3'
        metadata.write_text(json.dumps(record))
        interrupted = prepare(raw, leaves, metadata, root / 'packages')
        interrupted_id = validate(interrupted)['source_id']
        real_add = refs.add_passage
        calls = 0

        def fail_mid_import(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('synthetic interrupted import')
            return real_add(*args)

        with patch.object(refs, 'add_passage', side_effect=fail_mid_import):
            with self.assertRaises(RuntimeError):
                refs.import_book_package(self.alice, interrupted)
        self.assertIsNone(self.store.db.execute('''SELECT 1 FROM reference_sources
            WHERE owner_id='alice' AND id=%s''', (interrupted_id,)).fetchone())
        self.assertFalse(refs.import_book_package(self.alice, interrupted)['already_imported'])
        raw.write_bytes(raw.read_bytes() + b'corrected source byte')
        source_revision = prepare(raw, leaves, metadata, root / 'packages')
        self.assertNotEqual(source_revision, interrupted)
        adjusted = json.loads(leaves.read_text())
        adjusted[-1]['text'] += ' corrected transcript'
        leaves.write_text(json.dumps(adjusted, ensure_ascii=False))
        transcript_revision = prepare(raw, leaves, metadata, root / 'packages')
        self.assertNotEqual(transcript_revision, source_revision)
        self.assertEqual(validate(package)['source_id'], original_id)
        record['source_url'] = 'http://unsafe.invalid/not-https'
        metadata.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            prepare(raw, leaves, metadata, root / 'packages')
        self.assertEqual(validate(package)['source_id'], original_id)

    def test_noncanonical_transcript_rejected_before_any_db_write(self):
        root = Path(self.directory.name)
        package = prepare(*fixture(root)[:3], root / 'packages')
        transcript = package / 'transcript.json'
        transcript.write_text(json.dumps(json.loads(transcript.read_text()),
                                         ensure_ascii=False, indent=2), encoding='utf-8')
        source_id = json.loads((package / 'manifest.json').read_text())['source_id']
        with self.assertRaisesRegex(ValueError, 'canonical'):
            References(self.store).import_book_package(self.alice, package)
        self.assertIsNone(self.store.db.execute('''SELECT 1 FROM reference_sources
            WHERE owner_id='alice' AND id=%s''', (source_id,)).fetchone())

    def test_import_uses_validated_bytes_even_if_input_changes_during_read(self):
        root = Path(self.directory.name)
        package = prepare(*fixture(root)[:3], root / 'packages')
        original = (package / 'source.bin').read_bytes()
        bounded_file = book_package.bounded_file
        changed = False

        def replace_after_first_read(path, limit):
            nonlocal changed
            content = bounded_file(path, limit)
            if not changed and Path(path) == package / 'source.bin':
                changed = True
                (package / 'source.bin').write_bytes(b'controlled changed raw')
            return content

        with patch.object(book_package, 'bounded_file', side_effect=replace_after_first_read):
            source_id = References(self.store).import_book_package(self.alice, package)['source_id']
        self.assertTrue(changed)
        saved = self.store.db.execute('''SELECT raw_source FROM reference_book_sources
            WHERE owner_id='alice' AND source_id=%s''', (source_id,)).fetchone()
        self.assertEqual(bytes(saved['raw_source']), original)
        verify_reference_contents(self.store)

    def test_transcript_and_normalized_changes_cannot_escape_validated_snapshot(self):
        root = Path(self.directory.name)
        raw, leaves, metadata, _, record = fixture(root)
        refs = References(self.store)
        for filename, column in (('transcript.json', 'transcript'),
                                 ('normalized.txt', 'original_text')):
            with self.subTest(filename=filename):
                record['processing_revision'] = filename
                metadata.write_text(json.dumps(record))
                package = prepare(raw, leaves, metadata, root / 'packages')
                original = (package / filename).read_bytes()
                bounded_file = book_package.bounded_file
                changed = False

                def replace_after_read(path, limit):
                    nonlocal changed
                    content = bounded_file(path, limit)
                    if not changed and Path(path) == package / filename:
                        changed = True
                        (package / filename).write_bytes(b'changed after validated read')
                    return content

                with patch.object(book_package, 'bounded_file', side_effect=replace_after_read):
                    source_id = refs.import_book_package(self.alice, package)['source_id']
                self.assertTrue(changed)
                saved = self.store.db.execute('''
                    SELECT b.transcript,o.original_text FROM reference_book_sources b
                    JOIN reference_originals o USING (owner_id,source_id)
                    WHERE b.owner_id='alice' AND b.source_id=%s
                ''', (source_id,)).fetchone()
                self.assertEqual(bytes(saved[column]) if column == 'transcript' else
                                 saved[column].encode('utf-8'), original)
                verify_reference_contents(self.store)

    def test_mixed_parent_leaves_never_advertise_false_neighbors(self):
        root = Path(self.directory.name)
        raw, leaves, metadata, _, _ = fixture(root)
        rows = [dict(text=chr(65 + i) * 900, page=i + 1, printed_page=i + 1,
                     source_locator=f'leaf {i}', section=f'section-{i}',
                     parent_section=f'parent-{i}', extraction_status='unverified_transcription',
                     review_status='not_reviewed') for i in range(8)]
        leaves.write_text(json.dumps(rows))
        package = prepare(raw, leaves, metadata, root / 'packages')
        manifest = validate(package)
        self.assertEqual(''.join(item['content'] for item in manifest['passages']),
                         ''.join(leaf['text'] + '\n\n' for leaf in rows))
        refs = References(self.store)
        source = refs.import_book_package(self.alice, package)['source_id']
        refs.select(self.alice, source)
        for passage in manifest['passages']:
            self.assertNotEqual(passage['parent_section'], 'mixed_sections')
            self.assertEqual(refs.readable_passage(self.alice, source, passage['id'])['neighbors'],
                             {'previous': None, 'next': None})
        for leaf in rows:
            leaf['parent_section'] = 'shared-parent'
        leaves.write_text(json.dumps(rows))
        same_parent = prepare(raw, leaves, metadata, root / 'packages')
        new_manifest = validate(same_parent)
        new_source = refs.import_book_package(self.alice, same_parent)['source_id']
        refs.select(self.alice, new_source)
        for passage in new_manifest['passages']:
            self.assertEqual(refs.readable_passage(self.alice, new_source, passage['id'])['neighbors'],
                             {'previous': None, 'next': None})

    def test_legacy_file_import_retains_64_passage_admission(self):
        root = Path(self.directory.name)
        _, _, _, _, metadata = fixture(root)
        metadata.pop('processing_revision')
        metadata['source_id'] = 'synthetic-legacy-cap'
        original = root / 'small-original.txt'
        original.write_text('sample')
        path = root / 'small-manifest.json'
        refs = References(self.store)
        metadata['passages'] = [{'id': f'p-{i}', 'section': 'Synthetic', 'content': 'sample'}
                                for i in range(64)]
        path.write_text(json.dumps(metadata))
        self.assertFalse(refs.import_text_file(self.alice, path, original)['already_imported'])
        metadata['source_id'] = 'synthetic-over-legacy-cap'
        metadata['passages'].append({'id': 'p-64', 'section': 'Synthetic', 'content': 'sample'})
        path.write_text(json.dumps(metadata))
        self.assertLess(path.stat().st_size, 32768)
        with self.assertRaisesRegex(ValueError, '1..64'):
            refs.import_text_file(self.alice, path, original)
        self.assertIsNone(self.store.db.execute('''SELECT 1 FROM reference_sources
            WHERE owner_id='alice' AND id=%s''', (metadata['source_id'],)).fetchone())

    def test_symbol_rich_and_four_byte_book_passages_import_and_read(self):
        root = Path(self.directory.name)
        raw, leaves, metadata, _, record = fixture(root)
        refs = References(self.store)
        for label, text in (
                ('symbols', 'Synthetic planetary table\n' + '☉ ♄ ♃ ♀ ' * 350),
                ('four-byte', '🌙' * 3000)):
            with self.subTest(label=label):
                record['processing_revision'] = label
                metadata.write_text(json.dumps(record))
                leaves.write_text(json.dumps([dict(
                    text=text, page=1, printed_page=1, source_locator=label,
                    section='Synthetic symbols', parent_section='Synthetic observations',
                    extraction_status='unverified_transcription', review_status='not_reviewed')],
                    ensure_ascii=False))
                package = prepare(raw, leaves, metadata, root / 'packages')
                manifest = validate(package)
                first = manifest['passages'][0]
                self.assertLessEqual(len(first['content']), 3000)
                self.assertGreater(len(first['content'].encode('utf-8')), 4096)
                self.assertLessEqual(len(first['content'].encode('utf-8')), 16384)
                self.assertEqual(''.join(p['content'] for p in manifest['passages']), text + '\n\n')
                source = refs.import_book_package(self.alice, package)['source_id']
                self.assertTrue(refs.import_book_package(self.alice, package)['already_imported'])
                self.assertEqual(refs.get_passage(self.alice, source, first['id'])['approval'],
                                 'not_kat_selected')
                verify_reference_contents(self.store)
                with self.assertRaises(PermissionError):
                    refs.readable_passage(self.alice, source, first['id'])
                with self.assertRaises(KeyError):
                    refs.get_passage(self.bob, source, first['id'])
                refs.select(self.alice, source)  # synthetic only; no real corpus selected
                read = execute(self.store, self.alice, 'get_reference_passage', {
                    'source_id': source, 'passage_id': first['id']}, set())
                self.assertEqual(read['content'], first['content'])
                self.assertIsNone(read['next_offset'])  # every admitted book chunk is <=3000 characters
                following = execute(self.store, self.alice, 'get_reference_passage', {
                    'source_id': source, 'passage_id': first['id'], 'offset': 1800}, set())
                self.assertEqual(read['content'][:1800] + following['content'], first['content'])
                self.assertEqual(read['content_sha256'], sha256(first['content'].encode()).hexdigest())

    def test_book_only_byte_ceiling_and_legacy_four_kib_remain(self):
        root = Path(self.directory.name)
        raw, leaves, metadata, _, _ = fixture(root)
        leaves.write_text(json.dumps([dict(
            text='🌙' * 4096, page=1, printed_page=1,
            source_locator='fixture', section='Symbols', parent_section='Fixture',
            extraction_status='unverified_transcription', review_status='not_reviewed')]))
        refs = References(self.store)
        source = refs.import_book_package(self.alice, prepare(raw, leaves, metadata,
                                                               root / 'packages'))['source_id']
        before = self.store.db.execute('''SELECT count(*) AS n FROM reference_passages
            WHERE owner_id='alice' AND source_id=%s''', (source,)).fetchone()['n']
        # Probe the service byte boundary with a contiguous source span, then
        # remove the synthetic probe row; normal packages still chunk at 3000 chars.
        with self.store.db.transaction():
            refs.add_passage(self.alice, source, 'exact-book-ceiling', 'Symbols', '🌙' * 4096)
            self.assertEqual(refs.get_passage(self.alice, source, 'exact-book-ceiling')['content'],
                             '🌙' * 4096)
            self.store.db.execute('''DELETE FROM reference_passages
                WHERE owner_id='alice' AND source_id=%s AND id='exact-book-ceiling' ''', (source,))
        with self.assertRaisesRegex(ValueError, 'Invalid or oversized text'):
            refs.add_passage(self.alice, source, 'too-large-book', 'Symbols', '🌙' * 4097)
        self.assertEqual(self.store.db.execute('''SELECT count(*) AS n FROM reference_passages
            WHERE owner_id='alice' AND source_id=%s''', (source,)).fetchone()['n'], before)
        verify_reference_contents(self.store)
        legacy = dict(source_id='legacy-four-kib', author='Synthetic author', title='Synthetic text',
                      edition='Unverified', tradition='fixture', technique='text',
                      provenance='Local authored fixture', rights_evidence='Synthetic fixture',
                      rights_basis='synthetic_fixture', language='en', source_url=None,
                      extraction_note='No OCR', supersedes_source_id=None)
        exactly_four_kib = '🌙' * 1024
        refs.ingest_edition(self.alice, legacy, exactly_four_kib,
            [{'id': 'p', 'section': 'Synthetic', 'content': exactly_four_kib}])
        self.assertEqual(refs.get_passage(self.alice, 'legacy-four-kib', 'p')['content'],
                         exactly_four_kib)
        legacy['source_id'] = 'legacy-exceeds-four-kib'
        with self.assertRaisesRegex(ValueError, 'Invalid or oversized text'):
            refs.ingest_edition(self.alice, legacy, exactly_four_kib + '🌙',
                [{'id': 'p', 'section': 'Synthetic', 'content': exactly_four_kib + '🌙'}])
        self.assertIsNone(self.store.db.execute('''SELECT 1 FROM reference_sources
            WHERE owner_id='alice' AND id=%s''', (legacy['source_id'],)).fetchone())

    def test_book_bytes_and_old_backup_remain_revoked(self):
        root = Path(self.directory.name)
        raw, leaves, metadata, _, _ = fixture(root)
        package = prepare(raw, leaves, metadata, root / 'packages')
        refs = References(self.store)
        source = refs.import_book_package(self.alice, package)['source_id']
        refs.select(self.alice, source)
        verify_reference_contents(self.store)
        snapshot = root / 'book-before-revocation.dump'
        dump_owned(self.dsn, snapshot)
        refs.revoke(self.alice, source)
        name = 'kat_m2_restored_' + uuid4().hex[:12]
        dsn = make_conninfo(self.admin_dsn, dbname=name)
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        restored = None
        try:
            restore_owned(dsn, snapshot)
            restored = Store(dsn, root / 'restored-files', self.ledger)
            alice = restored.authenticate('alice', 'synthetic-password-alice')
            verify_reference_contents(restored)
            with self.assertRaises(PermissionError):
                References(restored).readable_passage(alice, source, 'p-0000000')
            self.assertEqual(search_evidence(restored, alice, 'farendtoken')['results'], [])
            saved = restored.db.execute('''SELECT raw_source FROM reference_book_sources
                WHERE owner_id='alice' AND source_id=%s''', (source,)).fetchone()
            self.assertEqual(bytes(saved['raw_source']), raw.read_bytes())
        finally:
            if restored:
                restored.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))

    def test_real_read_rounds_archive_then_replay_without_resend(self):
        root = Path(self.directory.name)
        package = prepare(*fixture(root)[:3], root / 'packages')
        manifest = validate(package)
        refs = References(self.store)
        source = refs.import_book_package(self.alice, package)['source_id']
        refs.select(self.alice, source)
        self.store.create_conversation(self.alice, 'book-reader')

        def call(index, name, arguments):
            return {'type': 'function_call', 'id': f'fc_{index}', 'call_id': f'call_{index}',
                    'name': name, 'arguments': json.dumps(arguments)}

        search_args = {'query': 'farendtoken', 'author': None, 'tradition': None,
                       'technique': None, 'language': None}
        last_id = manifest['passages'][-1]['id']
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [call(1, 'search_references', search_args)]}}, 'fixture')],
            [({'type': 'response.completed', 'response': {'output': [call(2, 'get_reference_passage',
                {'source_id': source, 'passage_id': last_id, 'offset': 0})]}}, 'fixture')],
            [({'type': 'response.output_text.delta', 'delta': 'Synthetic citation only.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        with patch('m2.agent_reads.LocalEmbedder', side_effect=RuntimeError('offline cache unavailable')):
            self.assertEqual(run_turn(self.store, self.alice, 'book-reader', 'read',
                'Find the synthetic token at the end', model, lambda _: None,
                model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'complete')
        found = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertEqual(found['results'][0]['passage_id'], last_id)
        self.assertFalse(found['semantic_available'])
        passage = json.loads(transport.calls[2]['input'][-1]['output'])
        self.assertEqual(passage['page_end'], 211)
        self.assertEqual(passage['source_locator_end'], 'synthetic leaf 211')
        self.assertEqual(passage['neighbors']['previous'], manifest['passages'][-2]['id'])
        self.assertLess(sum(len(json.loads(body['input'][-1]['output']).get('content', ''))
                            for body in transport.calls[1:]), MAX_MODEL_EVIDENCE_BYTES)
        events = self.store.read_turn(self.alice, 'book-reader', 'read')['events']
        self.assertEqual([e['kind'] for e in events if e['kind'] == 'tool_result'],
                         ['tool_result', 'tool_result'])
        self.assertEqual(run_turn(self.store, self.alice, 'book-reader', 'read',
            'Find the synthetic token at the end', model, lambda _: None,
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'complete')
        self.assertEqual(len(transport.calls), 3)
