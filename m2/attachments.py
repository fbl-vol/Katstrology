"""Content-addressed local synthetic attachments with database-scoped references.

Blobs may be shared by digest; no physical deletion while any reference remains.
DB/file atomicity is not claimed: backup quiesces writes and orphan cleanup is
explicit. All reads authorize the reference before resolving a digest path.
"""

from hashlib import sha256
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


MAX_ATTACHMENT = 1024 * 1024


def _filename(value):
    if (not isinstance(value, str) or not value or len(value) > 100
            or value in ('.', '..') or '/' in value or '\\' in value
            or any(ord(c) < 32 for c in value)):
        raise ValueError('Invalid attachment filename')
    return value


def _media_type(content):
    # This is a type gate, not a parser or a claim about file contents.
    if content.startswith(b'%PDF-'):
        return 'application/pdf'
    if content.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if content.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if content[:4] == b'RIFF' and content[8:12] == b'WEBP':
        return 'image/webp'
    raise ValueError('Only PDF, PNG, JPEG or WebP reference files are accepted')


class Attachments:
    def __init__(self, store):
        self.store = store
        self.directory = store.files / 'blobs'
        self.directory.mkdir(mode=0o700, exist_ok=True)

    def add(self, session, conv_id, attachment_id, filename, content):
        owner = self.store.owner(session)
        self.store._id(attachment_id)
        _filename(filename)
        self._size(content)
        self.store._conversation(owner, conv_id)
        if self.store.ledger.contains(owner, conv_id, attachment_id):
            raise ValueError('Deleted attachment identity cannot be reused')
        digest = self._store_blob(content)
        with self.store.db.transaction():
            row = self.store.db.execute('''
                SELECT filename, digest FROM attachments
                WHERE owner_id=%s AND conversation_id=%s AND id=%s
            ''', (owner, conv_id, attachment_id)).fetchone()
            if row:
                if row != {'filename': filename, 'digest': digest}:
                    raise ValueError('Attachment ID reused with changed content')
                return digest
            self.store.db.execute('''
                INSERT INTO attachments(owner_id, conversation_id, id, filename, digest, byte_count)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (owner, conv_id, attachment_id, filename, digest, len(content)))
        return digest

    @staticmethod
    def _size(content):
        if not isinstance(content, bytes) or len(content) > MAX_ATTACHMENT:
            raise ValueError('Attachment exceeds 1 MiB limit')

    def _store_blob(self, content):
        digest = sha256(content).hexdigest()
        target = self.directory / digest
        if not target.exists():
            with NamedTemporaryFile(dir=self.directory, prefix='.pending-', delete=False) as temp:
                pending = Path(temp.name)
                os.chmod(temp.name, 0o600)
                try:
                    temp.write(content)
                    temp.flush()
                    os.fsync(temp.fileno())
                except BaseException:
                    pending.unlink(missing_ok=True)
                    raise
            try:
                os.replace(pending, target)
                directory_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                pending.unlink(missing_ok=True)
        return digest

    def add_person(self, session, person_id, attachment_id, filename, content):
        owner = self.store.owner(session)
        self.store._id(person_id)
        self.store._id(attachment_id)
        _filename(filename)
        self._size(content)
        person = self.store.db.execute('SELECT 1 FROM people WHERE owner_id=%s AND id=%s',
                                       (owner, person_id)).fetchone()
        if not person:
            raise KeyError('Person not found')
        if self.store.ledger.contains_person_attachment(owner, person_id, attachment_id):
            raise ValueError('Deleted person attachment identity cannot be reused')
        media_type = _media_type(content)
        digest = self._store_blob(content)
        with self.store.db.transaction():
            row = self.store.db.execute('''
                SELECT filename,digest,media_type FROM person_attachments
                WHERE owner_id=%s AND person_id=%s AND id=%s
            ''', (owner, person_id, attachment_id)).fetchone()
            expected = {'filename': filename, 'digest': digest, 'media_type': media_type}
            if row:
                if row != expected:
                    raise ValueError('Person attachment ID reused with different bytes')
                return row
            self.store.db.execute('''
                INSERT INTO person_attachments(owner_id,person_id,id,filename,media_type,digest,byte_count)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            ''', (owner, person_id, attachment_id, filename, media_type, digest, len(content)))
        return expected

    def read_person(self, session, person_id, attachment_id):
        owner = self.store.owner(session)
        row = self.store.db.execute('''
            SELECT filename,media_type,digest FROM person_attachments
            WHERE owner_id=%s AND person_id=%s AND id=%s
        ''', (owner, self.store._id(person_id), self.store._id(attachment_id))).fetchone()
        if not row:
            raise KeyError('Person attachment not found')
        return row, self._content(row['digest'])

    def list(self, session, conv_id, limit=20):
        owner = self.store.owner(session)
        self.store._conversation(owner, conv_id)
        if not 1 <= limit <= 20:
            raise ValueError('Attachment list limit 1..20')
        return self.store.db.execute('''
            SELECT id, filename, digest, byte_count, created_at FROM attachments
            WHERE owner_id=%s AND conversation_id=%s ORDER BY created_at, id LIMIT %s
        ''', (owner, conv_id, limit)).fetchall()

    def read(self, session, conv_id, attachment_id):
        owner = self.store.owner(session)
        row = self.store.db.execute('''
            SELECT digest FROM attachments WHERE owner_id=%s AND conversation_id=%s AND id=%s
        ''', (owner, self.store._id(conv_id), self.store._id(attachment_id))).fetchone()
        if not row:
            raise KeyError('Attachment not found')
        return self._content(row['digest'])

    def _content(self, digest):
        content = (self.directory / digest).read_bytes()
        if sha256(content).hexdigest() != digest:
            raise RuntimeError('Attachment checksum mismatch')
        return content

    def _retained_digests(self):
        return {row['digest'] for row in self.store.db.execute('''
            SELECT digest FROM attachments UNION SELECT digest FROM person_attachments
        ''')}

    def verify_references(self):
        """Do not serve an apparently complete archive with missing blob bytes."""
        for digest in self._retained_digests():
            path = self.directory / digest
            if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError('Referenced attachment bytes are missing or corrupt')

    def prune_unreferenced(self):
        """Only with exclusive application ownership; repairs orphan writes/deletes."""
        retained = self._retained_digests()
        removed = 0
        for path in self.directory.iterdir():
            if path.is_file() and path.name not in retained:
                path.unlink()
                removed += 1
        return removed
