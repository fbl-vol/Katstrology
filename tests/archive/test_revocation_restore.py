"""Restore a real older snapshot with revocations from a subsequently enrolled owner."""
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.archive.backup import backup, restore
from m2.chat.personal_context import preference, set_preference
from m2.people.people import People
from m2.people.personal_context import ContextConflict
from m2.people.self_association import association, set_association
from tests.support.database import DatabaseCase
from tests.support.self_association import legacy_association


class RevocationRestoreTests(DatabaseCase):
    @contextmanager
    def restored(self, snapshot):
        name = 'kat_m2_restored_' + uuid4().hex[:12]
        dsn = make_conninfo(self.admin_dsn, dbname=name)
        with psycopg.connect(self.admin_dsn, autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        recovered = None
        try:
            recovered = restore(snapshot, dsn, Path(self.directory.name) / name, self.ledger)
            yield recovered
        finally:
            if recovered:
                recovered.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as db:
                db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))

    def exercise_later_owner(self, kind):
        def enable(session):
            if kind == 'self':
                People(self.store).charts.add_person(session, 'casey', 'Casey')
                set_association(self.store, session, 'casey', 0)
                self.assertFalse(preference(self.store, session)['enabled'])
            else:
                set_preference(self.store, session, True, 0)

        def revoke(session):
            if kind == 'self':
                legacy_association(self.store, session, None)
            else:
                set_preference(self.store, session, False, 1)

        def assert_revoked(store, session):
            expected = {'person_id': None, 'version': 2} if kind == 'self' else {'enabled': False, 'version': 2}
            read = association if kind == 'self' else preference
            self.assertEqual(read(store, session), expected)

        enable(self.alice)
        before = Path(self.directory.name) / 'before-enrollment'
        backup(self.store, before)
        self.store.register_local('later-owner', 'synthetic-later-password')
        later = self.store.authenticate('later-owner', 'synthetic-later-password')
        enable(later)
        after = Path(self.directory.name) / 'after-enrollment'
        backup(self.store, after)
        revoke(self.alice)
        revoke(later)
        journal = self.ledger.path.read_bytes()

        # This supported backup predates later-owner. No ghost account, person or
        # authority may be manufactured merely to satisfy a revocation's FK.
        with self.restored(before) as recovered:
            alice = recovered.authenticate('alice', 'synthetic-password-alice')
            assert_revoked(recovered, alice)
            for table in ('accounts', 'people', 'personal_context_self', 'personal_context_consent'):
                column = 'id' if table == 'accounts' else 'owner_id'
                self.assertEqual(recovered.db.execute(
                    f'SELECT count(*) AS n FROM {table} WHERE {column}=%s', ('later-owner',)).fetchone()['n'], 0)
            self.assertFalse(recovered._blocked)
            recovered.ledger.reconcile(recovered)
            assert_revoked(recovered, alice)
        self.assertEqual(self.ledger.path.read_bytes(), journal)

        # Skipping an absent owner must not consume its revocation: a different
        # valid older backup containing that owner still loses the old authority.
        with self.restored(after) as recovered:
            for owner, password in [('alice', 'synthetic-password-alice'), ('later-owner', 'synthetic-later-password')]:
                assert_revoked(recovered, recovered.authenticate(owner, password))
            recovered.ledger.reconcile(recovered)
            assert_revoked(recovered, recovered.authenticate('later-owner', 'synthetic-later-password'))
        self.assertEqual(self.ledger.path.read_bytes(), journal)

    def test_backup_before_first_choice_cannot_offer_another_identity(self):
        People(self.store).charts.add_person(self.alice, 'casey', 'Casey')
        before = Path(self.directory.name) / 'before-first-choice'
        backup(self.store, before)
        set_association(self.store, self.alice, 'casey', 0)
        journal = self.ledger.path.read_bytes()
        with self.restored(before) as recovered:
            alice = recovered.authenticate('alice', 'synthetic-password-alice')
            self.assertEqual(association(recovered, alice), {'person_id': None, 'version': 1})
            with self.assertRaises(ContextConflict):
                set_association(recovered, alice, 'casey', 1)
            self.assertFalse(recovered._blocked)
        self.assertEqual(self.ledger.path.read_bytes(), journal)

    def test_self_revocation_for_later_enrollment_survives_both_older_backups(self):
        self.exercise_later_owner('self')

    def test_consent_revocation_for_later_enrollment_survives_both_older_backups(self):
        self.exercise_later_owner('consent')
