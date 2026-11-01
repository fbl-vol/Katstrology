"""Owned synthetic PostgreSQL fixture; never connects to an existing shared DB."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
from time import perf_counter
from uuid import uuid4
import unittest
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from m2.deletion import Tombstones
from m2.local_fixture import ROOT, fixture_dsn
from m2.store import Session, Store
from m2.test_template import TEMPLATE_NAME


def test_fixture_dsn():
    """An explicit, isolated test server bypasses the user's owned fixture metadata."""
    return os.environ.get('KAT_ISOLATED_TEST_DSN') or fixture_dsn()


def isolated_backup_target(dsn):
    """Test-only pg_dump target; never replace the production ownership guard."""
    settings = conninfo_to_dict(dsn)
    admin = conninfo_to_dict(os.environ['KAT_ISOLATED_TEST_DSN'])
    name = os.environ['KAT_ISOLATED_TEST_CONTAINER']
    if (not name.startswith('kat-origin-isolated-') or
            not re.fullmatch(r'kat_(m2_test|m2_restored|person_restore)_[a-f0-9]{12}',
                             settings.get('dbname', '')) or
            any(settings.get(key) != admin.get(key) for key in ('host', 'port', 'user'))):
        raise ValueError('Not an isolated test backup target')
    label = subprocess.check_output(['docker', 'inspect', '-f',
                                     '{{index .Config.Labels "kat.siwc.test"}}', name],
                                    text=True).strip()
    port = subprocess.check_output(['docker', 'port', name, '5432/tcp'], text=True).strip()
    if label != 'isolated' or port != f"127.0.0.1:{admin['port']}":
        raise ValueError('Isolated test container does not match test DSN')
    return name, settings['user'], settings['dbname']


def synthetic_web_dist(directory):
    """Give HTTP API tests an owned static root, never the served web/dist."""
    dist = Path(directory) / 'synthetic-dist'
    dist.mkdir()
    (dist / 'index.html').write_text('<!doctype html><title>synthetic HTTP fixture</title>', encoding='utf-8')
    return dist


def seeded_session(store, owner):
    """Bind a synthetic, existing account to this Store only; not a login path."""
    if not store.db.execute('SELECT 1 FROM accounts WHERE id=%s', (owner,)).fetchone():
        raise AssertionError('Missing seeded test account')
    session = Session(owner)
    store.sessions[id(session)] = session
    return session


class DatabaseCase(unittest.TestCase):
    fixture_requires_fresh_migration = False

    def _drop_database(self):
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(self.database)))

    def setUp(self):
        started = perf_counter()
        self.admin_dsn = test_fixture_dsn()
        if os.environ.get('KAT_ISOLATED_TEST_DSN'):
            backup_patch = patch('m2.backup.owned_pg_command',
                                 side_effect=isolated_backup_target)
            backup_patch.start()
            self.addCleanup(backup_patch.stop)
        template = os.environ.get('KAT_ISOLATED_TEST_TEMPLATE')
        if template and (not os.environ.get('KAT_ISOLATED_TEST_DSN') or
                         not TEMPLATE_NAME.fullmatch(template)):
            raise ValueError('Owned isolated template required')
        self.database = f'kat_m2_test_{uuid4().hex[:12]}'
        seeded = bool(template and not self.fixture_requires_fresh_migration)
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            create = sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                sql.Identifier(self.database), sql.Identifier(template)) if seeded else sql.SQL(
                'CREATE DATABASE {}').format(sql.Identifier(self.database))
            admin.execute(create)
        self.addCleanup(self._drop_database)
        self.dsn = make_conninfo(self.admin_dsn, dbname=self.database)
        self.directory = tempfile.TemporaryDirectory(prefix='kat-m2-test-', dir=ROOT / '.local')
        self.addCleanup(self.directory.cleanup)
        self.ledger = Tombstones(Path(self.directory.name) / 'deletions.jsonl')
        self.store = Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)
        self.addCleanup(lambda: self.store.close())
        if seeded:
            self.alice = seeded_session(self.store, 'alice')
            self.bob = seeded_session(self.store, 'bob')
        else:
            self.store.register_local('alice', 'synthetic-password-alice')
            self.store.register_local('bob', 'synthetic-password-bob')
            self.alice = self.store.authenticate('alice', 'synthetic-password-alice')
            self.bob = self.store.authenticate('bob', 'synthetic-password-bob')
        self._fixture_setup_seconds = perf_counter() - started
