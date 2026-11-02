"""Offline encrypted selected-registration handoff; no browser or provider request.

Stop the owning app first. Export from an explicit owned local fixture, then move
only the encrypted file through an approved secure channel. Import into a fresh
explicit deployment registration after authenticating the matching Kat username
on each side. A separate explicit offline command forgets only a disconnected
single-owner registration before a new transfer; it never calls the provider.
"""

import argparse
import getpass
from pathlib import Path
import sys

from m2.deletion import Tombstones
from m2.local_fixture import fixture_dsn
from m2.siwc import CredentialFiles
from m2.store import Store
from m2.web_server import deployment_dsn


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('export-local', 'import-deployment',
                                           'forget-disconnected-deployment'))
    parser.add_argument('--state-directory', required=True, type=Path)
    parser.add_argument('--handoff-file', type=Path)
    parser.add_argument('--db-password-file', type=Path)
    args = parser.parse_args(argv)
    if not args.state_directory.is_absolute():
        parser.error('State directory must be absolute')
    if args.action == 'forget-disconnected-deployment':
        if args.handoff_file is not None:
            parser.error('Forgetting a disconnected registration does not accept a handoff file')
    elif args.handoff_file is None or not args.handoff_file.is_absolute():
        parser.error('Handoff file must be absolute')
    if args.action == 'export-local' and args.db_password_file is not None:
        parser.error('Export may only use an owned local fixture')
    if args.action != 'export-local' and args.db_password_file is None:
        parser.error('Deployment recovery/import requires an explicit database password file')
    try:
        dsn = (fixture_dsn(args.state_directory) if args.action == 'export-local'
               else deployment_dsn(args.db_password_file, 'db', 'kat', 'kat'))
        owner = input('Kat account username: ')
        password = getpass.getpass('Kat account password: ')
        passphrase = (getpass.getpass('Encrypted handoff passphrase: ')
                      if args.action != 'forget-disconnected-deployment' else None)
        files = args.state_directory / 'browser-runtime/files'
        ledger = Tombstones(args.state_directory / ('browser-runtime/deletions.jsonl'
            if args.action == 'export-local' else 'browser-runtime/deletions/deletions.jsonl'))
        with Store(dsn, files, ledger) as store:
            store.authenticate(owner, password)
            credentials = CredentialFiles(args.state_directory / 'browser-runtime/siwc')
            if args.action == 'export-local':
                credentials.export_selected(owner, args.handoff_file, passphrase)
            elif args.action == 'import-deployment':
                credentials.import_selected(owner, args.handoff_file, passphrase)
            else:
                if input('Type FORGET to remove the disconnected registration: ') != 'FORGET':
                    raise ValueError('Offline recovery not confirmed')
                credentials.forget_disconnected(owner)
        print('Offline registration operation completed; no registration data shown.')
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f'Handoff failed ({type(error).__name__}); no provider request made.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
