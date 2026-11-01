"""Explicit branch selection, source-linked corrections and original-preserving export."""

from base64 import b64encode
import json
import os
from pathlib import Path

from m2.attachments import Attachments
from m2.charts import Charts
from m2.references import References


def select_branch(store, session, conv_id, head_id):
    owner = store.owner(session)
    if head_id is not None:
        store.ancestry(session, conv_id, head_id)  # complete and same owned conversation
    with store.db.transaction():
        current = store._conversation(owner, conv_id, lock=True)
        if current['active_head'] != head_id:
            store._changed(owner, conv_id, head_id)
    return head_id


def correct(store, session, conv_id, correction_id, source_turn, action, replacement=None):
    owner = store.owner(session)
    store._id(correction_id)
    store._id(source_turn)
    if action not in ('correct', 'withdraw'):
        raise ValueError('Unsupported correction action')
    if action == 'correct':
        store._text(replacement)
    elif replacement is not None:
        raise ValueError('Withdrawal cannot supply a replacement')
    with store.db.transaction():
        store._conversation(owner, conv_id, lock=True)
        existing = store.db.execute('''
            SELECT source_turn_id, action, replacement FROM corrections
            WHERE owner_id=%s AND conversation_id=%s AND id=%s
        ''', (owner, conv_id, correction_id)).fetchone()
        expected = {'source_turn_id': source_turn, 'action': action, 'replacement': replacement}
        if existing:
            if existing != expected:
                raise ValueError('Correction ID reused with changed content')
            return False
        source = store.db.execute('''
            SELECT status,parent_id FROM turns WHERE owner_id=%s AND conversation_id=%s AND id=%s
        ''', (owner, conv_id, source_turn)).fetchone()
        if not source or source['status'] != 'complete':
            raise ValueError('Correction source must be a complete owned turn')
        parent_revision = 0
        if source['parent_id']:
            parent_revision = store.db.execute('''
                SELECT COALESCE(MAX(sequence), 0) AS revision FROM corrections
                WHERE owner_id=%s AND conversation_id=%s AND source_turn_id=%s
            ''', (owner, conv_id, source['parent_id'])).fetchone()['revision']
        count = store.db.execute('''
            SELECT count(*) AS value FROM corrections
            WHERE owner_id=%s AND conversation_id=%s AND source_turn_id=%s
        ''', (owner, conv_id, source_turn)).fetchone()['value']
        if count >= 16:
            raise ValueError('Correction limit for source turn reached')
        store.db.execute('''
            INSERT INTO corrections(owner_id, conversation_id, id, source_turn_id,
                                    action, replacement, parent_revision)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (owner, conv_id, correction_id, source_turn, action,
              replacement, parent_revision))
        store._changed(owner, conv_id)
    return True


def export_conversation(store, session, conv_id, destination):
    """Write an owner-scoped JSONL original export; never overwrite a local file."""
    owner = store.owner(session)
    conversation = store._conversation(owner, conv_id)
    files = Attachments(store)
    turns = store.db.execute('''
        SELECT id FROM turns WHERE owner_id=%s AND conversation_id=%s ORDER BY created_at, id
    ''', (owner, conv_id)).fetchall()
    attachments = store.db.execute('''
        SELECT id, filename, digest, byte_count, created_at FROM attachments
        WHERE owner_id=%s AND conversation_id=%s ORDER BY created_at, id
    ''', (owner, conv_id)).fetchall()
    path = Path(destination)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        def line(value):
            output.write(json.dumps(value, default=str, ensure_ascii=False) + '\n')
        line({'type': 'conversation', 'id': conv_id, 'active_head': conversation['active_head'],
              'created_at': conversation['created_at'], 'owner_id': owner,
              'people': store.db.execute('''
                  SELECT person_id FROM conversation_people
                  WHERE owner_id=%s AND conversation_id=%s ORDER BY person_id
              ''', (owner, conv_id)).fetchall()})
        for item in turns:
            offset = 0
            while True:
                page = store.read_turn(session, conv_id, item['id'], event_offset=offset)
                if offset == 0:
                    line({'type': 'turn', 'id': page['id'], 'parent_id': page['parent_id'],
                          'parent_revision': page['parent_revision'],
                          'status': page['status'], 'source': page['source'],
                          'revision_kind': page['revision_kind'],
                          'replaces_turn_id': page['replaces_turn_id'],
                          'created_at': page['created_at'], 'corrections': page['corrections'],
                          'selected_people': page['selected_people']})
                for event in page['events']:
                    line({'type': 'event', 'turn_id': item['id'], **event})
                if page['next_event_offset'] is None:
                    break
                offset = page['next_event_offset']
        for attachment in attachments:
            line({'type': 'attachment', **attachment,
                  'base64_content': b64encode(files.read(session, conv_id, attachment['id'])).decode('ascii')})
        # Versioned records referred to by this conversation retain their
        # exact settings and source passage metadata; no detached global account
        # collection is accidentally exported.
        chart_rows = store.db.execute('''
            SELECT e.turn_id,e.event_sequence,c.id AS chart_id,c.result,c.engine_version,
                   p.name AS person_name
            FROM chart_evidence e JOIN charts c ON (c.owner_id=e.owner_id AND c.id=e.chart_id)
            JOIN people p ON (p.owner_id=c.owner_id AND p.id=c.person_id)
            WHERE e.owner_id=%s AND e.conversation_id=%s
            ORDER BY e.turn_id,e.event_sequence
        ''', (owner, conv_id)).fetchall()
        for chart in chart_rows:
            status = Charts(store).get_chart(session, chart['chart_id'])['source_status']
            line({'type': 'chart_evidence', **chart, 'source_status': status})
        selected_people = store.db.execute('''
            SELECT DISTINCT tp.person_id,p.name,tp.draft_revision,d.details AS draft
            FROM turn_people tp JOIN people p ON p.owner_id=tp.owner_id AND p.id=tp.person_id
            LEFT JOIN person_drafts d ON d.owner_id=tp.owner_id AND d.person_id=tp.person_id
              AND d.revision=tp.draft_revision
            WHERE tp.owner_id=%s AND tp.conversation_id=%s
            ORDER BY tp.person_id,tp.draft_revision
        ''', (owner, conv_id)).fetchall()
        for selected in selected_people:
            line({'type': 'selected_person_version', **selected})
        selected_charts = store.db.execute('''
            SELECT DISTINCT c.id FROM turn_people tp JOIN charts c
              ON c.owner_id=tp.owner_id AND c.id=tp.chart_id
            WHERE tp.owner_id=%s AND tp.conversation_id=%s
            ORDER BY c.id
        ''', (owner, conv_id)).fetchall()
        for selected in selected_charts:
            line({'type': 'selected_chart',
                  **Charts(store).get_chart(session, selected['id'])})
        notes = store.db.execute('''
            SELECT person_id,id,source_turn_id,source_event_sequence,statement,
                   epistemic_status,confirmation_turn_id,created_at FROM personal_entries
            WHERE owner_id=%s AND conversation_id=%s ORDER BY person_id,id
        ''', (owner, conv_id)).fetchall()
        for note in notes:
            line({'type': 'personal_entry', **note})
        sources = store.db.execute('''
            SELECT DISTINCT s.* FROM reference_sources s
            WHERE s.owner_id=%s AND (s.source_conversation_id=%s OR EXISTS (
                SELECT 1 FROM reference_evidence e WHERE e.owner_id=s.owner_id
                AND e.source_id=s.id AND e.conversation_id=%s)) ORDER BY s.id
        ''', (owner, conv_id, conv_id)).fetchall()
        for source in sources:
            line({'type': 'reference_source', **source})
            passages = store.db.execute('''
                SELECT id,section,content,content_sha256 FROM reference_passages
                WHERE owner_id=%s AND source_id=%s ORDER BY id
            ''', (owner, source['id'])).fetchall()
            for passage in passages:
                provenance = References(store).get_passage(session, source['id'], passage['id'])
                line({'type': 'reference_passage', 'source_id': source['id'],
                      **passage, 'source_status': provenance['source_status'],
                      'source_corrections': provenance.get('source_corrections', [])})
    return {'turns': len(turns), 'attachments': len(attachments), 'path': str(path),
            'chart_evidence': len(chart_rows), 'personal_entries': len(notes),
            'reference_sources': len(sources)}
