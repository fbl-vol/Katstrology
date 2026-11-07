"""External minimal deletion journal: replay tombstones before serving.

The journal contains identifiers only. Its separately retained tip detects an
isolated truncation or rollback of the journal; neither copy belongs in a DB
snapshot. Losing both copies together is not recoverable from an older backup.
"""

from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

from m2.archive.attachments import Attachments


class ReferencedPersonAttachment(ValueError):
    """Owner-scoped where-used details for a refused file deletion."""

    def __init__(self, conversations, more):
        super().__init__('An archived turn still references this file')
        self.conversations = conversations
        self.more = more


class Tombstones:
    def __init__(self, path):
        self.path = Path(path)
        self.tip_path = self.path.with_name(self.path.name + '.tip')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.path.exists():
            if self.tip_path.exists():
                raise RuntimeError('Deletion journal is missing while its tip exists')
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            self.journal_id = uuid4().hex
            self._append_raw({'journal_id': self.journal_id})
            self._write_tip()
        else:
            # An existing pre-tip journal cannot be attested by inventing a tip
            # during restore. Supply independently retained evidence instead.
            if not self.tip_path.is_file():
                raise RuntimeError('Independent deletion-journal tip is missing')
            with self.path.open(encoding='utf-8') as journal:
                header = json.loads(journal.readline())
            if (set(header) != {'journal_id'} or not isinstance(header['journal_id'], str)
                    or len(header['journal_id']) != 32):
                raise RuntimeError('Missing independent deletion-journal identity')
            self.journal_id = header['journal_id']
            self.verify()

    def _append_raw(self, record):
        payload = (json.dumps(record, separators=(',', ':')) + '\n').encode('utf-8')
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND)
        try:
            if os.write(fd, payload) != len(payload):
                raise OSError('Short deletion-journal write')
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write_tip(self):
        journal = self.path.read_bytes()
        tip = {'journal_id': self.journal_id, 'size': len(journal),
               'sha256': sha256(journal).hexdigest()}
        temporary = self.tip_path.with_name(self.tip_path.name + '.' + uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump(tip, output)
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.tip_path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def verify(self):
        if not self.tip_path.is_file():
            raise RuntimeError('Independent deletion-journal tip is missing')
        tip = json.loads(self.tip_path.read_text())
        journal = self.path.read_bytes()
        if (not isinstance(tip, dict) or set(tip) != {'journal_id', 'size', 'sha256'}
                or tip['journal_id'] != self.journal_id or tip['size'] != len(journal)
                or tip['sha256'] != sha256(journal).hexdigest()):
            raise RuntimeError('Independent deletion-journal tip disagrees with journal')

    def _append(self, record):
        self.verify()
        self._append_raw(record)
        self._write_tip()

    def _records(self):
        self.verify()
        with self.path.open(encoding='utf-8') as journal:
            if json.loads(journal.readline()) != {'journal_id': self.journal_id}:
                raise RuntimeError('Deletion journal identity changed')
            for line in journal:
                if len(line) > 2048:
                    raise RuntimeError('Invalid deletion journal')
                record = json.loads(line)
                single = ({'owner', 'conversation'}, {'owner', 'conversation', 'attachment'},
                          {'owner', 'person'}, {'owner', 'person', 'person_attachment'},
                          {'owner', 'reference'}, {'owner', 'reference_revoked'},
                          {'owner', 'person', 'watch_item'},
                          {'owner', 'person', 'journal_entry'},
                          {'owner', 'person', 'context_entry'},
                          {'owner', 'person', 'person_link'},
                          {'owner', 'context_consent_revoked'})
                if not isinstance(record, dict) or (set(record) not in single and
                    (set(record) != {'owner', 'conversations'} or
                     not isinstance(record['conversations'], list) or
                     not 2 <= len(record['conversations']) <= 20 or
                     any(not isinstance(item, str) for item in record['conversations']) or
                     len(set(record['conversations'])) != len(record['conversations']))):
                    raise RuntimeError('Invalid deletion journal')
                yield record

    def contains(self, owner, conversation, attachment=None):
        for record in self._records():
            if record['owner'] != owner:
                continue
            if conversation in record.get('conversations', ()) and attachment is None:
                return True
            if (record.get('conversation') == conversation and
                    ('attachment' not in record or record['attachment'] == attachment)):
                return True
        return False

    def contains_person(self, owner, person_id):
        return any(record['owner'] == owner and record.get('person') == person_id
                   for record in self._records())

    def contains_person_attachment(self, owner, person_id, attachment_id):
        return any(record['owner'] == owner and record.get('person') == person_id
                   and record.get('person_attachment') == attachment_id
                   for record in self._records())

    def contains_person_record(self, owner, person_id, record_id, kind):
        return any(record['owner'] == owner and record.get('person') == person_id
                   and record.get(kind) == record_id for record in self._records())

    def contains_reference(self, owner, source_id):
        return any(record['owner'] == owner and record.get('reference') == source_id
                   for record in self._records())

    def reconcile(self, store):
        """Only with exclusive store ownership; failure must prevent any serving."""
        for record in self._records():
            owner = store._id(record['owner'])
            with store.db.transaction():
                if 'context_consent_revoked' in record:
                    version = record['context_consent_revoked']
                    if not isinstance(version, str) or not version.isdigit() or not 1 <= int(version) <= 2147483647:
                        raise RuntimeError('Invalid context consent revocation')
                    store.db.execute('''INSERT INTO personal_context_consent VALUES (%s,false,%s)
                        ON CONFLICT(owner_id) DO UPDATE SET enabled=false,version=excluded.version
                        WHERE personal_context_consent.version < excluded.version''', (owner, int(version)))
                elif 'conversations' in record:
                    ids = [store._id(item) for item in record['conversations']]
                    store.db.execute('DELETE FROM conversations WHERE owner_id=%s AND id=ANY(%s)',
                                     (owner, ids))
                elif 'person_link' in record:
                    store.db.execute('DELETE FROM person_links WHERE owner_id=%s AND person_id=%s AND id=%s',
                                     (owner, store._id(record['person']), store._id(record['person_link'])))
                elif 'context_entry' in record:
                    store.db.execute('''
                        DELETE FROM personal_context WHERE owner_id=%s AND person_id=%s AND id=%s
                    ''', (owner, store._id(record['person']), store._id(record['context_entry'])))
                    for conversation in store.db.execute('SELECT id FROM conversations WHERE owner_id=%s', (owner,)).fetchall():
                        store._changed(owner, conversation['id'])
                elif 'watch_item' in record:
                    store.db.execute('''
                        DELETE FROM watch_items WHERE owner_id=%s AND person_id=%s AND id=%s
                    ''', (owner, store._id(record['person']), store._id(record['watch_item'])))
                elif 'journal_entry' in record:
                    store.db.execute('''
                        DELETE FROM journal_entries WHERE owner_id=%s AND person_id=%s AND id=%s
                    ''', (owner, store._id(record['person']), store._id(record['journal_entry'])))
                elif 'person_attachment' in record:
                    store.db.execute('''
                        DELETE FROM person_attachments
                        WHERE owner_id=%s AND person_id=%s AND id=%s
                    ''', (owner, store._id(record['person']),
                          store._id(record['person_attachment'])))
                elif 'person' in record:
                    store.db.execute('DELETE FROM people WHERE owner_id=%s AND id=%s',
                                     (owner, store._id(record['person'])))
                elif 'reference_revoked' in record:
                    source_id = store._id(record['reference_revoked'])
                    revived = store.db.execute('''
                        UPDATE reference_sources SET approval='revoked'
                        WHERE owner_id=%s AND id=%s AND approval<>'revoked' RETURNING id
                    ''', (owner, source_id)).fetchone()
                    store.db.execute('DELETE FROM reference_vectors WHERE owner_id=%s AND source_id=%s',
                                     (owner, source_id))
                    if revived:
                        dependents = store.db.execute('''
                            SELECT DISTINCT conversation_id FROM reference_evidence
                            WHERE owner_id=%s AND source_id=%s
                        ''', (owner, source_id)).fetchall()
                        for item in dependents:
                            store._changed(owner, item['conversation_id'])
                elif 'reference' in record:
                    source_id = store._id(record['reference'])
                    # Only a previously journaled, now-inadmissible deletion reaches
                    # here with descendants. Keep those editions and their predecessor
                    # identity while replaying the authoritative erasure on every backup.
                    store.db.execute('''
                        UPDATE reference_sources
                        SET supersedes_deleted_source_id=supersedes_source_id,
                            supersedes_source_id=NULL
                        WHERE owner_id=%s AND supersedes_source_id=%s
                    ''', (owner, source_id))
                    store.db.execute('DELETE FROM reference_sources WHERE owner_id=%s AND id=%s',
                                     (owner, source_id))
                elif 'attachment' in record:
                    store.db.execute('''
                        DELETE FROM attachments WHERE owner_id=%s AND conversation_id=%s AND id=%s
                    ''', (owner, store._id(record['conversation']), store._id(record['attachment'])))
                else:
                    store.db.execute('DELETE FROM conversations WHERE owner_id=%s AND id=%s',
                                     (owner, store._id(record['conversation'])))
        from m2.chat.personal_context import invalidate_sources
        for source in store.db.execute("SELECT DISTINCT owner_id,source->>'conversation_id' AS conversation_id FROM personal_context WHERE source->>'kind'='conversation'").fetchall():
            invalidate_sources(store, source['owner_id'], source['conversation_id'])
        files = Attachments(store)
        files.prune_unreferenced()
        files.verify_references()
        store._blocked = False

    def delete_conversations(self, store, session, conversation_ids):
        """Delete an explicitly selected dependency group in one journal record."""
        owner = store.owner(session)
        ids = [store._id(item) for item in conversation_ids]
        if not 1 <= len(ids) <= 20 or len(set(ids)) != len(ids):
            raise ValueError('Select 1..20 distinct owned conversations')
        for conv_id in ids:
            store._conversation(owner, conv_id)
        dependent = store.db.execute('''
            SELECT e.conversation_id FROM chart_evidence e
            JOIN charts c ON (c.owner_id=e.owner_id AND c.id=e.chart_id)
            JOIN birth_records b ON (b.owner_id=c.owner_id AND b.person_id=c.person_id
                                     AND b.id=c.birth_id)
            WHERE e.owner_id=%s AND b.source_conversation_id=ANY(%s)
              AND NOT (e.conversation_id=ANY(%s))
            UNION
            SELECT e.conversation_id FROM reference_evidence e
            JOIN reference_sources s ON (s.owner_id=e.owner_id AND s.id=e.source_id)
            WHERE e.owner_id=%s AND s.source_conversation_id=ANY(%s)
              AND NOT (e.conversation_id=ANY(%s))
        ''', (owner, ids, ids, owner, ids, ids)).fetchall()
        if dependent:
            raise ValueError('Delete dependent conversations using this source first')
        record = ({'owner': owner, 'conversation': ids[0]} if len(ids) == 1 else
                  {'owner': owner, 'conversations': sorted(ids)})
        store._blocked = True
        self._append(record)
        self.reconcile(store)

    def delete_conversation(self, store, session, conv_id):
        self.delete_conversations(store, session, [conv_id])

    def delete_person(self, store, session, person_id):
        owner = store.owner(session)
        store._id(person_id)
        if not store.db.execute('SELECT 1 FROM people WHERE owner_id=%s AND id=%s',
                                (owner, person_id)).fetchone():
            raise KeyError('Person not found')
        if (store.db.execute('''
                SELECT 1 FROM conversation_people
                WHERE owner_id=%s AND person_id=%s LIMIT 1
            ''', (owner, person_id)).fetchone() or store.db.execute('''
                SELECT 1 FROM chart_evidence e JOIN charts c
                  ON c.owner_id=e.owner_id AND c.id=e.chart_id
                WHERE c.owner_id=%s AND c.person_id=%s LIMIT 1
            ''', (owner, person_id)).fetchone() or store.db.execute('''
                SELECT 1 FROM personal_entries WHERE owner_id=%s AND person_id=%s LIMIT 1
            ''', (owner, person_id)).fetchone()):
            raise ValueError('Delete conversations containing this person selection or evidence first')
        store._blocked = True
        self._append({'owner': owner, 'person': person_id})
        self.reconcile(store)

    def revoke_context_consent(self, store, session, version):
        owner = store.owner(session)
        if type(version) is not int or not 1 <= version <= 2147483647:
            raise ValueError('Invalid consent version')
        store._blocked = True
        self._append({'owner': owner, 'context_consent_revoked': str(version)})
        self.reconcile(store)

    def delete_person_record(self, store, session, person_id, record_id, kind):
        """Retain an independent deletion authority across older DB snapshots."""
        if kind not in ('watch_item', 'journal_entry', 'context_entry', 'person_link'):
            raise ValueError('Unsupported person record')
        owner = store.owner(session)
        store._id(person_id); store._id(record_id)
        table = {'watch_item': 'watch_items', 'journal_entry': 'journal_entries',
                 'context_entry': 'personal_context', 'person_link': 'person_links'}[kind]
        if not store.db.execute(f'''
            SELECT 1 FROM {table} WHERE owner_id=%s AND person_id=%s AND id=%s
        ''', (owner, person_id, record_id)).fetchone():
            raise KeyError('Person record not found')
        store._blocked = True
        self._append({'owner': owner, 'person': person_id, kind: record_id})
        self.reconcile(store)

    def delete_person_attachment(self, store, session, person_id, attachment_id):
        owner = store.owner(session)
        store._id(person_id)
        store._id(attachment_id)
        if not store.db.execute('''
            SELECT 1 FROM person_attachments
            WHERE owner_id=%s AND person_id=%s AND id=%s
        ''', (owner, person_id, attachment_id)).fetchone():
            raise KeyError('Person attachment not found')
        if store.db.execute('''
            SELECT 1 FROM turn_people WHERE owner_id=%s AND person_id=%s
              AND attachment_id=%s LIMIT 1
        ''', (owner, person_id, attachment_id)).fetchone():
            used = store.db.execute('''
                SELECT DISTINCT c.id, c.title FROM turn_people tp
                JOIN conversations c ON c.owner_id=tp.owner_id AND c.id=tp.conversation_id
                WHERE tp.owner_id=%s AND tp.person_id=%s AND tp.attachment_id=%s
                ORDER BY c.title, c.id LIMIT 21
            ''', (owner, person_id, attachment_id)).fetchall()
            raise ReferencedPersonAttachment([dict(row) for row in used[:20]], len(used) > 20)
        store._blocked = True
        self._append({'owner': owner, 'person': person_id,
                      'person_attachment': attachment_id})
        self.reconcile(store)

    def revoke_reference(self, store, session, source_id):
        """Journal revocation so restoring an older snapshot cannot re-enable passages."""
        owner = store.owner(session)
        source = store.db.execute('''
            SELECT approval FROM reference_sources WHERE owner_id=%s AND id=%s
        ''', (owner, store._id(source_id))).fetchone()
        if not source:
            raise KeyError('Source not found')
        if source['approval'] == 'revoked':
            return
        store._blocked = True
        self._append({'owner': owner, 'reference_revoked': source_id})
        self.reconcile(store)

    def delete_reference(self, store, session, source_id):
        owner = store.owner(session)
        store._id(source_id)
        source = store.db.execute('''
            SELECT source_conversation_id FROM reference_sources WHERE owner_id=%s AND id=%s
        ''', (owner, source_id)).fetchone()
        if not source:
            raise KeyError('Reference source not found')
        if (source['source_conversation_id'] or store.db.execute('''
            SELECT 1 FROM reference_evidence WHERE owner_id=%s AND source_id=%s LIMIT 1
        ''', (owner, source_id)).fetchone()):
            raise ValueError('Delete linked conversations before deleting their reference source')
        if store.db.execute('''
            SELECT 1 FROM reference_sources
            WHERE owner_id=%s AND supersedes_source_id=%s LIMIT 1
        ''', (owner, source_id)).fetchone():
            raise ValueError('Delete successor reference editions before their predecessor')
        store._blocked = True
        self._append({'owner': owner, 'reference': source_id})
        self.reconcile(store)

    def delete_attachment(self, store, session, conv_id, attachment_id):
        owner = store.owner(session)
        store._conversation(owner, conv_id)
        store._id(attachment_id)
        if not store.db.execute('''
            SELECT 1 FROM attachments WHERE owner_id=%s AND conversation_id=%s AND id=%s
        ''', (owner, conv_id, attachment_id)).fetchone():
            raise KeyError('Attachment not found')
        store._blocked = True
        self._append({'owner': owner, 'conversation': conv_id,
                      'attachment': attachment_id})
        self.reconcile(store)
