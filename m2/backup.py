"""Quiesced single-owner PostgreSQL + referenced-file snapshot and gated restore.

An independently retained, newer Tombstones journal MUST be supplied on restore.
No restored Store is returned until reconciliation and blob checks succeed.
"""

from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import psycopg
from psycopg.conninfo import conninfo_to_dict

from m2.store import Store


DIGEST = re.compile(r'[a-f0-9]{64}\Z')


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


def backup(store, destination):
    """Caller has quiesced this sole local owner; never snapshots active writes."""
    target = Path(destination)
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
    dump_owned(store._dsn, dump)
    after = [row['digest'] for row in store.db.execute('''
        SELECT digest FROM attachments UNION SELECT digest FROM person_attachments
        ORDER BY digest
    ''').fetchall()]
    if after != expected:
        raise RuntimeError('Attachment references changed during backup; discard snapshot')
    store.ledger.verify()
    journal_snapshot = store.ledger.path.read_bytes()
    manifest = {'format': 1, 'database_sha256': digest_file(dump), 'blobs': expected,
                'journal_id': store.ledger.journal_id,
                'journal_prefix_bytes': len(journal_snapshot),
                'journal_prefix_sha256': sha256(journal_snapshot).hexdigest()}
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    os.chmod(target / 'manifest.json', 0o600)
    return manifest


def restore(backup_dir, target_dsn, target_files, newer_ledger):
    """Empty owned target DB/files only; caller must never expose raw restore."""
    source = Path(backup_dir)
    manifest = json.loads((source / 'manifest.json').read_text())
    if manifest.get('format') != 1 or not isinstance(manifest.get('blobs'), list):
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
    restore_owned(target_dsn, source / 'database.dump')
    # The ledger is independently retained after this backup. Store startup
    # replays tombstones before any authenticated read can be served.
    return Store(target_dsn, files, newer_ledger)
