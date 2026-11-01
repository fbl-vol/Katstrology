"""Quiesced deployment snapshot and independent-journal restore verification.

No serving process may own either database. Restore requires a newly provisioned,
empty, disposable DB and absent file directory; never use a serving target.
"""

import argparse
from pathlib import Path
import sys

from m2.backup import backup, deployment_pg_command, deployment_snapshot_source, restore
from m2.deletion import Tombstones
from m2.web_server import deployment_dsn


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('backup', 'verify-restore'))
    parser.add_argument('--state-directory', required=True, type=Path)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--db-password-file', required=True, type=Path)
    parser.add_argument('--db-name', default='kat')
    parser.add_argument('--db-user', default='kat')
    args = parser.parse_args(argv)
    if not all(path.is_absolute() for path in (args.state_directory, args.snapshot,
                                               args.db_password_file)):
        parser.error('All paths must be absolute')
    if args.state_directory == args.snapshot or args.state_directory in args.snapshot.parents:
        parser.error('Snapshot must be independent of serving state and deletion authority')
    try:
        dsn = deployment_dsn(args.db_password_file, 'db', args.db_name, args.db_user)
        ledger_path = args.state_directory / 'browser-runtime/deletions/deletions.jsonl'
        files = args.state_directory / 'browser-runtime/files'
        if args.action == 'backup':
            with deployment_snapshot_source(dsn, files, ledger_path) as source:
                backup(source, args.snapshot, dump_database=deployment_pg_command)
        else:
            if (not ledger_path.is_file() or
                    not ledger_path.with_name(ledger_path.name + '.tip').is_file()):
                raise ValueError('Independent newer deletion journal and tip required')
            ledger = Tombstones(ledger_path)
            restored = restore(args.snapshot, dsn, files, ledger,
                               restore_dump=lambda target, path: deployment_pg_command(
                                   target, path, restore_mode=True),
                               require_current_schema=True)
            restored.close()
        print('Snapshot completed.' if args.action == 'backup' else
              'Restore reconciled and verified on the disposable target.')
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f'Snapshot operation failed ({type(error).__name__}); do not serve this target.',
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
