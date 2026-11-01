"""Run-local, empty migrated schema for owned synthetic validation only.

Only schema and two synthetic account hashes are cloned. File blobs and deletion
journals live outside PostgreSQL and must be created independently per test.
"""

import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.deletion import Tombstones
from m2.store import Store


TEMPLATE_NAME = re.compile(r'kat_m2_template_[a-f0-9]{12}\Z')


def create_run_template():
    admin_dsn = os.environ['KAT_ISOLATED_TEST_DSN']
    name = os.environ['KAT_ISOLATED_TEST_TEMPLATE']
    run_dir = Path(os.environ['KAT_ISOLATED_TEST_RUN_DIR'])
    if not TEMPLATE_NAME.fullmatch(name) or not run_dir.is_dir() or not os.environ.get('KAT_ISOLATED_TEST_CONTAINER', '').startswith('kat-origin-isolated-'):
        raise ValueError('Owned isolated template environment required')

    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            with TemporaryDirectory(prefix='template-init-', dir=run_dir) as directory:
                with Store(make_conninfo(admin_dsn, dbname=name), Path(directory) / 'files',
                           Tombstones(Path(directory) / 'deletions.jsonl')) as store:
                    store.register_local('alice', 'synthetic-password-alice')
                    store.register_local('bob', 'synthetic-password-bob')
                    # Recovery/archived data cannot become a shared test starting state.
                    for table in ('conversations', 'turns', 'people', 'attachments'):
                        count = store.db.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(
                            sql.Identifier(table))).fetchone()['n']
                        if count:
                            raise RuntimeError('Template contains archived data')
            admin.execute(sql.SQL('ALTER DATABASE {} WITH ALLOW_CONNECTIONS false').format(sql.Identifier(name)))
        except BaseException:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            raise


if __name__ == '__main__':
    create_run_template()
