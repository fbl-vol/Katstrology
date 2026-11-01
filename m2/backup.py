"""Quiesced single-owner PostgreSQL + referenced-file snapshot and gated restore.

An independently retained, newer Tombstones journal MUST be supplied on restore.
No restored Store is returned until reconciliation and blob checks succeed.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from m2.deletion import Tombstones
from m2.store import Store


DIGEST = re.compile(r'[a-f0-9]{64}\Z')


def current_schema_version():
    return max(int(path.name.split('_', 1)[0]) for path in
               (Path(__file__).parent / 'migrations').glob('[0-9]*.sql'))


@dataclass(frozen=True)
class SnapshotSource:
    """Read-only, exclusively owned backup input; never runs Store recovery."""

    _dsn: str = field(repr=False)
    db: psycopg.Connection
    files: Path
    ledger: Tombstones


@contextmanager
def deployment_snapshot_source(dsn, files, journal_path):
    """Reject stale/missing state before any Store migration or journal creation."""
    files, journal_path = Path(files), Path(journal_path)
    tip = journal_path.with_name(journal_path.name + '.tip')
    if not files.is_dir() or not journal_path.is_file() or not tip.is_file():
        raise ValueError('Existing files and independent deletion journal/tip required')
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as db:
        db.execute('SET default_transaction_read_only = on')
        acquired = db.execute('''
            SELECT pg_try_advisory_lock(hashtext(current_database()), 20261028) AS acquired
        ''').fetchone()['acquired']
        if not acquired:
            raise RuntimeError('Conversation owner already active')
        versions = [row['version'] for row in db.execute(
            'SELECT version FROM schema_migrations ORDER BY version')]
        expected = [int(path.name.split('_', 1)[0]) for path in sorted(
            (Path(__file__).parent / 'migrations').glob('[0-9]*.sql'))]
        if versions != expected:
            raise RuntimeError('Backup requires the current migrated schema')
        ledger = Tombstones(journal_path)  # Both files existed; constructor cannot mint authority.
        ledger.verify()
        yield SnapshotSource(dsn, db, files, ledger)


def digest_file(path):
    with Path(path).open('rb') as file:
        return file_digest(file, 'sha256').hexdigest()


def owned_pg_command(dsn):
    """Use the PG16 tools *inside* the exact owned container, never host PG18."""
    settings = conninfo_to_dict(dsn)
    name = (Path(__file__).resolve().parents[1] / '.local/m2-pg-name').read_text().strip()
    if (not name.startswith('kat-m2-') or settings.get('host') != '127.0.0.1'
            or settings.get('user') != 'kat_fixture'
            or not re.fullmatch(r'[A-Za-z0-9_]{1,80}', settings['dbname'])):
        raise ValueError('Backup/restore requires the owned local PG16 fixture')
    port = subprocess.check_output(['docker', 'port', name, '5432/tcp'], text=True).strip()
    if port != f"127.0.0.1:{settings.get('port')}":
        raise ValueError('PostgreSQL target is not the owned fixture')
    return name, settings['user'], settings['dbname']


def dump_owned(dsn, path):
    name, user, database = owned_pg_command(dsn)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as output:
        result = subprocess.run(['docker', 'exec', name, 'pg_dump', '-U', user, '-d', database,
                                 '--format=custom', '--no-owner', '--no-acl'],
                                stdout=output, stderr=subprocess.DEVNULL, timeout=90)
    if result.returncode:
        raise RuntimeError('Owned pg_dump failed; backup incomplete')


def restore_owned(dsn, path):
    name, user, database = owned_pg_command(dsn)
    with Path(path).open('rb') as source:
        result = subprocess.run(['docker', 'exec', '-i', name, 'pg_restore', '-U', user,
                                 '-d', database, '--no-owner', '--no-acl', '--exit-on-error'],
                                stdin=source, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=90)
    if result.returncode:
        raise RuntimeError('Owned pg_restore failed; target remains quarantined')


def deployment_pg_command(dsn, path, restore_mode=False):
    """Private Compose DB only; ephemeral pgpass never enters args, logs or image."""
    settings = conninfo_to_dict(dsn)
    if (settings.get('host') != 'db' or settings.get('port') != '5432' or
            not re.fullmatch(r'[A-Za-z0-9_]{1,80}', settings.get('dbname', '')) or
            not re.fullmatch(r'[A-Za-z0-9_]{1,80}', settings.get('user', '')) or
            not settings.get('password')):
        raise ValueError('Explicit private deployment database required')
    with tempfile.TemporaryDirectory(prefix='kat-pgpass-') as directory:
        passfile = Path(directory) / 'pass'
        # Database/user names are deliberately restricted above; escape password
        # according to libpq pgpass rules. The temp directory is mode 0700.
        password = settings['password'].replace('\\', '\\\\').replace(':', '\\:')
        fd = os.open(passfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(f"db:5432:{settings['dbname']}:{settings['user']}:{password}\n")
        command = (['pg_restore', '--no-owner', '--no-acl', '--exit-on-error'] if restore_mode
                   else ['pg_dump', '--format=custom', '--no-owner', '--no-acl'])
        command += ['--no-password', '-h', 'db', '-p', '5432', '-U', settings['user'],
                    '-d', settings['dbname']]
        env = {'PATH': os.environ.get('PATH', os.defpath),
               'PGPASSFILE': str(passfile)}
        with Path(path).open('rb' if restore_mode else 'wb') as stream:
            channels = ({'stdin': stream, 'stdout': subprocess.DEVNULL} if restore_mode
                        else {'stdout': stream})
            result = subprocess.run(command, **channels, stderr=subprocess.DEVNULL,
                                    env=env, timeout=90)
        if result.returncode:
            raise RuntimeError('Deployment database dump/restore failed; target remains quarantined')


def verify_reference_contents(store):
    # Reference originals and passages are inline DB text, not filesystem blobs.
    for table, content, digest in (('reference_originals', 'original_text', 'content_sha256'),
                                   ('reference_passages', 'content', 'content_sha256')):
        for row in store.db.execute(f'SELECT {content}, {digest} FROM {table}'):
            if sha256(row[content].encode('utf-8')).hexdigest() != row[digest]:
                raise RuntimeError('Stored reference checksum mismatch')


def backup(store, destination, dump_database=dump_owned):
    """Caller has quiesced this sole local owner; never snapshots active writes."""
    target = Path(destination)
    verify_reference_contents(store)
    if store.db.execute('SELECT max(version) AS version FROM schema_migrations').fetchone()['version'] != current_schema_version():
        raise RuntimeError('Backup requires the current migrated schema')
    target.mkdir(parents=True, mode=0o700, exist_ok=False)
    (target / 'blobs').mkdir(mode=0o700)
    rows = store.db.execute('''
        SELECT digest FROM attachments UNION SELECT digest FROM person_attachments
        ORDER BY digest
    ''').fetchall()
    expected = [row['digest'] for row in rows]
    for digest in expected:
        if not DIGEST.fullmatch(digest):
            raise RuntimeError('Invalid stored blob digest')
        source = store.files / 'blobs' / digest
        if digest_file(source) != digest:
            raise RuntimeError('Blob checksum mismatch before backup')
        shutil.copyfile(source, target / 'blobs' / digest)
        os.chmod(target / 'blobs' / digest, 0o600)
    dump = target / 'database.dump'
    dump_database(store._dsn, dump)
    after = [row['digest'] for row in store.db.execute('''
        SELECT digest FROM attachments UNION SELECT digest FROM person_attachments
        ORDER BY digest
    ''').fetchall()]
    if after != expected:
        raise RuntimeError('Attachment references changed during backup; discard snapshot')
    store.ledger.verify()
    journal_snapshot = store.ledger.path.read_bytes()
    manifest = {'format': 1, 'schema_version': current_schema_version(),
                'database_sha256': digest_file(dump), 'blobs': expected,
                'journal_id': store.ledger.journal_id,
                'journal_prefix_bytes': len(journal_snapshot),
                'journal_prefix_sha256': sha256(journal_snapshot).hexdigest()}
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    os.chmod(target / 'manifest.json', 0o600)
    return manifest


def restore(backup_dir, target_dsn, target_files, newer_ledger,
            restore_dump=restore_owned, require_current_schema=False):
    """Empty owned target DB/files only; caller must never expose raw restore."""
    source = Path(backup_dir)
    manifest = json.loads((source / 'manifest.json').read_text())
    version = manifest.get('schema_version')
    if (manifest.get('format') != 1 or not isinstance(manifest.get('blobs'), list)
            or version not in (None, current_schema_version())
            or (require_current_schema and version != current_schema_version())):
        raise ValueError('Unsupported backup manifest')
    newer_ledger.verify()  # independent tip must attest the complete newer journal
    journal = newer_ledger.path.read_bytes()  # independently retained, never the backup's copy
    prefix = manifest['journal_prefix_bytes']
    if (newer_ledger.journal_id != manifest['journal_id'] or len(journal) < prefix
            or sha256(journal[:prefix]).hexdigest() != manifest['journal_prefix_sha256']):
        raise RuntimeError('Independent newer deletion journal is missing or diverged')
    if digest_file(source / 'database.dump') != manifest['database_sha256']:
        raise RuntimeError('Backup dump checksum mismatch')
    for digest in manifest['blobs']:
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError('Invalid backup blob name')
        if digest_file(source / 'blobs' / digest) != digest:
            raise RuntimeError('Backup blob checksum mismatch')
    with psycopg.connect(target_dsn) as db:
        existing = db.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0]
        if existing:
            raise ValueError('Restore target database must be empty')
    files = Path(target_files)
    files.mkdir(parents=True, mode=0o700, exist_ok=False)
    (files / 'blobs').mkdir(mode=0o700)
    for digest in manifest['blobs']:
        shutil.copyfile(source / 'blobs' / digest, files / 'blobs' / digest)
        os.chmod(files / 'blobs' / digest, 0o600)
    restore_dump(target_dsn, source / 'database.dump')
    # The ledger is independently retained after this backup. Store startup
    # replays tombstones before any authenticated read can be served.
    recovered = Store(target_dsn, files, newer_ledger)
    try:
        verify_reference_contents(recovered)
    except BaseException:
        recovered.close()
        raise
    return recovered
