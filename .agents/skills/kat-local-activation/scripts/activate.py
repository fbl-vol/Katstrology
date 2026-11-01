#!/usr/bin/env python3
"""Plan an exact-tip local activation; execute only after a separately scoped user approval."""
import argparse
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[4]
TABLES = ('accounts', 'people', 'charts', 'conversations', 'turns')


def run(argv, *, capture=True):
    if capture:
        return subprocess.check_output(argv, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    subprocess.run(argv, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def exact_tip(commit):
    return (re.fullmatch('[0-9a-f]{40}', commit) is not None and
            run(['git', 'rev-parse', 'HEAD']) == commit and
            not run(['git', 'status', '--porcelain']))


def origin_parts(origin):
    parsed = urlsplit(origin)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or
            parsed.username or parsed.password or parsed.path not in ('', '/') or
            parsed.query or parsed.fragment or parsed.port is None):
        raise ValueError('Activation origin must be an exact 127.0.0.1 HTTP origin with a port')
    return parsed.port


def service_identity(unit, port):
    if not re.fullmatch(r'[a-zA-Z0-9_.@-]+\.service', unit):
        raise ValueError('Invalid named service')
    show = lambda field: run(['systemctl', '--user', 'show', unit,
                              '--property=' + field, '--value'])
    pid = int(show('MainPID'))
    if show('WorkingDirectory') != str(ROOT) or show('ActiveState') != 'active' or pid < 1:
        raise ValueError('Named service is not the active Kat checkout service')
    argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    if not any(b'm2.web_server' in part for part in argv):
        raise ValueError('Named process is not Kat web server')
    if b'--port' in argv:
        index = argv.index(b'--port')
        if index + 1 >= len(argv) or argv[index + 1] != str(port).encode():
            raise ValueError('Named service port differs from configured origin')
    elif port != 8765:  # existing Kat server default; never infer a non-default port
        raise ValueError('Named service port is not explicit')
    return pid


def metadata(dsn):
    import psycopg
    with psycopg.connect(dsn, options='-c default_transaction_read_only=on') as db:
        counts = tuple(db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                       for table in TABLES)
        version = db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
    if version is None:
        raise ValueError('Schema version is unavailable')
    return counts, version


def latest_migration():
    files = sorted((ROOT / 'm2/migrations').glob('[0-9]*.sql'))
    if not files:
        raise ValueError('No tracked migrations')
    return int(files[-1].name.split('_', 1)[0])


def http_bytes(port, path):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        content = response.read(2_000_001)
        if response.status != 200 or len(content) > 2_000_000:
            raise RuntimeError('Local asset verification failed')
        return content
    finally:
        connection.close()


def verify_assets(port, dist):
    index = (dist / 'index.html').read_bytes()
    if http_bytes(port, '/') != index:
        raise RuntimeError('Served HTML differs from exact-tip build')
    # At least one built asset must match; no private page/record/API payload read.
    match = re.search(rb'(?:src|href)="(/assets/[a-zA-Z0-9_.-]+)"', index)
    if not match:
        raise RuntimeError('No built asset found')
    relative = match.group(1).decode().lstrip('/')
    if http_bytes(port, '/' + relative) != (dist / relative).read_bytes():
        raise RuntimeError('Served asset differs from exact-tip build')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True, help='Exact 40-character commit SHA')
    parser.add_argument('--service', required=True, help='Named systemd user service, never a wildcard')
    parser.add_argument('--origin', required=True, help='Exact http://127.0.0.1:<port>')
    parser.add_argument('--dsn-env', default='KAT_LOCAL_ACTIVATION_DSN',
                        help='Environment variable containing DB connection; never echoed')
    parser.add_argument('--dist', default='web/dist', help='Configured Kat service asset directory')
    parser.add_argument('--execute', action='store_true', help='Mutates service/assets; NOT an approval')
    parser.add_argument('--approval-file', help='Private scoped user approval receipt for execute')
    args = parser.parse_args()
    report = {'action': 'execute' if args.execute else 'plan', 'status': 'stopped',
              'commit': args.commit, 'checks': [], 'service_restarted': False}
    try:
        port = origin_parts(args.origin)
        dist = (ROOT / args.dist).resolve()
        if dist != ROOT / 'web/dist':
            raise ValueError('Configured Kat service serves only web/dist')
        if not exact_tip(args.commit):
            raise ValueError('Checkout is not clean at the exact commit')
        report['checks'].append('clean-exact-tip')
        latest = latest_migration()
        report['migration_target'] = latest
        if not args.execute:
            report['status'] = 'planned'  # no DB, service, provider or browser accessed
        else:
            if not args.approval_file or not Path(args.approval_file).is_file():
                raise ValueError('A separately granted exact-scope approval receipt is required')
            approval = json.loads(Path(args.approval_file).read_text())
            if approval != {'action': 'activate-local', 'commit': args.commit,
                            'service': args.service, 'origin': args.origin,
                            'allow_migrations': approval.get('allow_migrations')} or not isinstance(
                                approval.get('allow_migrations'), bool):
                raise ValueError('Activation approval scope mismatch')
            dsn = os.environ.get(args.dsn_env)
            if not dsn:
                raise ValueError('Configured database access is missing')
            before, schema = metadata(dsn)
            if schema > latest or schema < latest and not approval['allow_migrations']:
                raise ValueError('Migration state requires separate explicit approval')
            original_pid = service_identity(args.service, port)
            report['schema_before'] = schema
            report['checks'].extend(['read-only-aggregate-before', 'named-service-identity'])
            # This is the only action allowed to write served assets, and only with approval.
            run(['npm', '--prefix', 'web', 'run', 'build', '--', '--outDir', str(dist)], capture=False)
            if not exact_tip(args.commit) or service_identity(args.service, port) != original_pid:
                raise RuntimeError('Checkout or service identity changed during build')
            run(['systemctl', '--user', 'restart', args.service], capture=False)
            report['service_restarted'] = True
            import time
            for _ in range(40):
                try:
                    service_identity(args.service, port)
                    verify_assets(port, dist)
                    break
                except (OSError, ValueError, RuntimeError, http.client.HTTPException):
                    time.sleep(0.5)
            else:
                raise RuntimeError('Named service or exact assets did not become ready')
            after, new_schema = metadata(dsn)
            if before != after or new_schema != latest:
                raise RuntimeError('Read-only aggregate or schema check changed unexpectedly')
            report['checks'].extend(['exact-assets-served', 'read-only-aggregate-preserved'])
            report['schema_after'] = new_schema
            report['status'] = 'activated-local'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, http.client.HTTPException, json.JSONDecodeError) as exc:
        report['error_type'] = type(exc).__name__  # no DSN, record, HTML or raw exception
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] in ('planned', 'activated-local') else 1


if __name__ == '__main__':
    sys.exit(main())
