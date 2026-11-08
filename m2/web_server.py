"""Single-process browser entry: loopback local mode or explicit HTTPS deployment.

HTTP composition and security live in m2.http_boundary; this module owns the CLI.
"""
import argparse
import getpass
import os
from pathlib import Path

import uvicorn

from m2.archive.deletion import Tombstones
from m2.http_boundary.app import create_app
from m2.http_boundary.config import deployment_dsn, deployment_origin
from m2.http_boundary.signup import SignupPolicy
from m2.http_boundary.signup_socket import serve_with_signup
from m2.operations.local_fixture import ROOT, fixture_dsn
from m2.archive.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('serve', 'enroll'), nargs='?', default='serve')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--deployment-origin', help='Enable deployment at this exact HTTPS origin')
    parser.add_argument('--db-password-file', type=Path)
    parser.add_argument('--signup-policy', type=Path,
                        help='Opt-in root-owned LAN policy and restricted Unix edge listener; disabled by default')
    parser.add_argument('--db-name', default='kat')
    parser.add_argument('--db-user', default='kat')
    parser.add_argument('--enable-siwc', action='store_true',
                        help='Allow only offline-enrolled ChatGPT registration in deployment')
    parser.add_argument('--state-directory', type=Path, default=ROOT / '.local',
                        help='Absolute directory containing the existing owned fixture and browser-runtime')
    parser.add_argument('--served-dist', type=Path,
                        help='Absolute path to the verified static build')
    args = parser.parse_args()
    served_dist = args.served_dist if args.served_dist is not None else ROOT / 'web/dist'
    if not 1 <= args.port <= 65535:
        parser.error('Port must be 1..65535')
    if not args.state_directory.is_absolute() or not served_dist.is_absolute():
        parser.error('State directory and served dist must be absolute paths')
    deployment = args.deployment_origin is not None
    signup_policy = None
    if args.signup_policy is not None:
        if not deployment or args.action != 'serve':
            parser.error('Signup policy requires explicit deployment serving mode')
        signup_policy = SignupPolicy.load(args.signup_policy)
    if deployment:
        # Reject incomplete deployment input before any Store or fixture access.
        origin = deployment_origin(args.deployment_origin)
        if (args.db_password_file is None or args.state_directory == ROOT / '.local'
                or args.served_dist is None):
            parser.error('Deployment requires explicit private state, build and database password paths')
        dsn = deployment_dsn(args.db_password_file, 'db', args.db_name, args.db_user)
    else:
        if args.db_password_file is not None:
            parser.error('Database password file requires deployment origin')
        origin = None
        dsn = fixture_dsn(args.state_directory)
    state = args.state_directory
    files = state / 'browser-runtime/files'
    ledger = (state / 'browser-runtime/deletions/deletions.jsonl' if deployment else
              state / 'browser-runtime/deletions.jsonl')
    if args.action == 'enroll':
        username = input('Kat workspace username: ')
        password = getpass.getpass('Kat workspace password (12+ characters): ')
        with Store(dsn, files, Tombstones(ledger)) as store:
            store.register_local(username, password)
        return
    siwc_factory = None
    if args.enable_siwc or (not deployment and os.environ.get('KAT_ENABLE_SIWC') == '1'):
        from m2.provider.siwc import ProviderBridge
        siwc_factory = ProviderBridge
    app = create_app(dsn, files, ledger, served_dist, port=args.port,
                     siwc_factory=siwc_factory, origin=origin, deployment=deployment,
                     signup_policy=signup_policy)
    if signup_policy is not None:
        serve_with_signup(app, signup_policy, '0.0.0.0', args.port)
        return
    uvicorn.run(app, host='0.0.0.0' if deployment else '127.0.0.1',
                port=args.port, proxy_headers=False, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
