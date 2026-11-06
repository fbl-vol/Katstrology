"""Opaque browser sessions, resolved into the existing owner-scoped Store boundary."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import secrets

from m2.archive.store import Session


SESSION_HOURS = 8


class WebAuth:
    def __init__(self, store):
        self.store = store
        self.owners = {}

    def login(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str):
            raise PermissionError('Invalid credentials')
        session = self.store.authenticate(username, password)
        self.owners[session.owner_id] = session
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_hex(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
        self.store.db.execute('''
            INSERT INTO web_sessions(token_digest, owner_id, csrf_token, expires_at)
            VALUES (%s, %s, %s, %s)
        ''', (sha256(token.encode()).hexdigest(), session.owner_id, csrf, expires))
        return token, csrf, session, expires

    def resolve(self, token):
        if not token or not isinstance(token, str) or len(token) > 128:
            raise PermissionError('Authentication required')
        row = self.store.db.execute('''
            SELECT owner_id, csrf_token, expires_at FROM web_sessions
            WHERE token_digest=%s AND expires_at > clock_timestamp()
        ''', (sha256(token.encode()).hexdigest(),)).fetchone()
        if not row:
            raise PermissionError('Authentication required')
        session = self.owners.get(row['owner_id'])
        if session is None:
            # Only the validated server-side web session may establish the
            # in-process identity that Store requires after a process restart.
            session = Session(row['owner_id'])
            self.store.sessions[id(session)] = session
            self.owners[row['owner_id']] = session
        self.store.owner(session)
        return session, row['csrf_token'], row['expires_at']

    @staticmethod
    def check_csrf(expected, supplied):
        if not isinstance(supplied, str) or not hmac.compare_digest(expected, supplied):
            raise PermissionError('Invalid request verification token')

    def logout(self, token):
        self.store.db.execute('DELETE FROM web_sessions WHERE token_digest=%s',
                              (sha256(token.encode()).hexdigest(),))
