"""Owned local PostgreSQL fixture backup/restore only; no shared environment."""

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.archive.backup import backup, restore
from m2.archive.deletion import Tombstones
from m2.operations.local_fixture import fixture_dsn
from m2.archive.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    save = commands.add_parser('backup')
    save.add_argument('destination', type=Path)
    load = commands.add_parser('restore')
    load.add_argument('snapshot', type=Path)
    for command in (save, load):
        command.add_argument('--files', type=Path, required=True,
                             help='source files for backup; destination files for restore')
        command.add_argument('--ledger', type=Path, required=True,
                             help='independent retained deletion journal (never in snapshot)')
    args = parser.parse_args(argv)
    try:
        dsn = fixture_dsn()
        if args.command == 'backup':
            ledger = Tombstones(args.ledger)
            with Store(dsn, args.files, ledger) as store:
                store.recover_open()  # no generation during quiesced snapshot
                manifest = backup(store, args.destination)
            print(json.dumps({'snapshot': str(args.destination), 'format': manifest['format'],
                              'blob_count': len(manifest['blobs'])}))
        else:
            if not args.ledger.is_file():
                raise ValueError('Independent deletion journal must already exist')
            ledger = Tombstones(args.ledger)
            database = 'kat_m2_restored_' + uuid4().hex[:12]
            target_dsn = make_conninfo(dsn, dbname=database)
            with psycopg.connect(dsn, autocommit=True) as admin:
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
            try:
                with restore(args.snapshot, target_dsn, args.files, ledger) as store:
                    count = store.db.execute('SELECT count(*) AS value FROM conversations').fetchone()['value']
                print(json.dumps({'restored_database': database, 'restored_conversations': count,
                                  'files': str(args.files), 'ledger': str(args.ledger)}))
            except BaseException:
                # Quarantine on failure: never expose an unreconciled restored DB.
                # The newly created target is ours and no client was handed out.
                with psycopg.connect(dsn, autocommit=True) as admin:
                    admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
                raise
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Owned local maintenance failed ({type(exc).__name__}); do not serve a partial restore.',
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
