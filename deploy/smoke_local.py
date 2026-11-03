"""Opt-in, disposable Compose smoke for an identified *local* package.

No external traffic, real credentials, host app, or production Compose project.
The default only prints a plan; --execute uses a unique project and deletes only
its newly created containers and named volumes, including on failure.
"""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from m2.backup import current_schema_version


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / 'deploy/compose.yaml'


def command(argv, *, env=None):
    return subprocess.check_output(argv, cwd=ROOT, env=env, text=True).strip()


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    if port == 8765:
        return free_port()
    return port


def response(port, host, path):
    request = Request(f'http://127.0.0.1:{port}{path}', headers={'Host': host})
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=2) as result:
            return result.status, result.read()
    except HTTPError as error:
        return error.code, error.read()


def await_session(port):
    until = time.monotonic() + 70
    while time.monotonic() < until:
        try:
            status, body = response(port, 'katstrology.dk', '/api/session')
            if status == 401 and json.loads(body) == {'error': 'authentication_required'}:
                return
            if status != 503:
                raise RuntimeError(f'Expected unauthenticated Host session 401, got {status}')
            time.sleep(0.5)
        except (URLError, ConnectionError, TimeoutError):
            time.sleep(0.5)
    raise RuntimeError('Packaged app did not serve the expected Host session 401')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True, help='Exact clean-tip local build receipt')
    parser.add_argument('--execute', action='store_true', help='Start and remove owned synthetic containers')
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text())
    tip = command(['git', 'rev-parse', 'HEAD'])
    if (receipt['commit'] != tip or receipt['tree'] != command(['git', 'rev-parse', 'HEAD^{tree}'])
            or command(['git', 'status', '--porcelain', '--untracked-files=all'])):
        raise RuntimeError('Smoke requires the clean committed receipt tip')
    image = receipt['image_id']
    if not image.startswith('sha256:') or len(image) != 71:
        raise ValueError('Invalid local image identity')
    if not args.execute:
        print(json.dumps({'status': 'plan', 'commit': tip, 'image_id': image,
                          'scope': 'new disposable Compose project, dynamic loopback port, fake DB secret; no activation'}))
        return
    if command(['docker', 'image', 'inspect', image, '--format', '{{.Id}}']) != image:
        raise RuntimeError('The exact receipt image is not local')
    project = 'kat-acceptance-' + secrets.token_hex(6)
    port = free_port()
    with tempfile.TemporaryDirectory(prefix=project + '-', dir=ROOT / '.local') as directory:
        stage = Path(directory)
        password = stage / 'synthetic-db-password'
        password.write_text('synthetic-' + secrets.token_urlsafe(30) + '\n')
        password.chmod(0o400)
        ephe = stage / 'empty-ephe'
        ephe.mkdir()
        override = stage / 'override.yaml'
        override.write_text(f'name: {project}\nservices:\n  app:\n    ports: !override\n'
                            f'      - "127.0.0.1:{port}:8765"\n'
                            '    volumes:\n      - release_verification:/verification\n'
                            'volumes:\n  release_verification:\n')
        env = {**os.environ, 'KAT_APP_IMAGE': image,
               'KAT_DB_PASSWORD_FILE': str(password), 'KAT_EPHE_DIR': str(ephe)}
        compose = ['docker', 'compose', '-f', str(COMPOSE), '-f', str(override),
                   '--project-name', project]
        config = json.loads(command([*compose, 'config', '--format', 'json'], env=env))
        volumes = config['volumes']
        if (config['name'] != project or config['services']['app']['image'] != image or
                config['services']['app']['tmpfs'] != ['/tmp:rw,noexec,nosuid,size=64m'] or
                config['services']['app']['ports'] != [
                    {'mode': 'ingress', 'host_ip': '127.0.0.1', 'target': 8765,
                     'published': str(port), 'protocol': 'tcp'}] or
                not all(value == {'name': f'{project}_{key}'} for key, value in volumes.items()) or
                config['services']['app']['command'].count('/opt/kat/web/dist') != 1):
            raise RuntimeError('Effective smoke Compose config differs from isolated template')
        assert not command(['docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={project}'])
        for volume in volumes.values():
            if subprocess.run(['docker', 'volume', 'inspect', volume['name']],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                raise RuntimeError('Smoke project unexpectedly has an existing volume')
        # A cold hosted BuildKit cache need not register the DB base as a local
        # runnable image. Pull only this source-template digest before Compose.
        db_image = config['services']['db']['image']
        if '@sha256:' not in db_image:
            raise ValueError('Synthetic DB must retain the pinned source image')
        if subprocess.run(['docker', 'image', 'inspect', db_image], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode:
            command(['docker', 'pull', db_image])
        # Synthetic-only file: owner UID matches the read-only app bind mount.
        command(['docker', 'run', '--rm', '--network', 'none', '--user', '0',
                 '--mount', f'type=bind,src={stage},dst=/synthetic',
                 '--entrypoint', 'chown', image, '10001:10001', '/synthetic/synthetic-db-password'])
        started = False
        try:
            started = True  # up may have created partial resources before failing.
            command([*compose, 'up', '-d', '--wait', '--wait-timeout', '90'], env=env)
            await_session(port)
            if response(port, 'wrong.invalid', '/api/session')[0] != 403:
                raise RuntimeError('Incorrect Host was not denied')
            status, body = response(port, 'katstrology.dk', '/')
            if status != 200 or b'<html' not in body.lower():
                raise RuntimeError('Packaged static home was not served')
            asset = command([*compose, 'exec', '-T', 'app', 'sha256sum',
                             '/opt/kat/web/dist/index.html'], env=env).split()[0]
            if sha256(body).hexdigest() != asset:
                raise RuntimeError('Served home does not match packaged dist')
            for name in ('manifest.webmanifest', 'icons/kat-192.png',
                         'icons/kat-512.png', 'icons/kat-512-maskable.png'):
                status, delivered = response(port, 'katstrology.dk', '/' + name)
                packaged = command([*compose, 'exec', '-T', 'app', 'sha256sum',
                                    '/opt/kat/web/dist/' + name], env=env).split()[0]
                if status != 200 or sha256(delivered).hexdigest() != packaged:
                    raise RuntimeError('Packaged install asset not served exactly')
                if response(port, 'wrong.invalid', '/' + name)[0] != 403:
                    raise RuntimeError('Install asset bypassed Host boundary')
            query = ("SELECT max(version), (SELECT count(*) FROM accounts), "
                     "(SELECT count(*) FROM web_sessions) FROM schema_migrations")
            def state():
                return command([*compose, 'exec', '-T', 'db', 'psql', '-U', 'kat', '-d', 'kat',
                                '-At', '-c', query], env=env)
            expected = f'{current_schema_version()}|0|0'
            if state() != expected:
                raise RuntimeError('Fresh Compose DB did not have current empty schema')
            command([*compose, 'restart', 'app'], env=env)
            await_session(port)
            if state() != expected:
                raise RuntimeError('Restart changed the current empty schema')
            from deploy.smoke_state import verify
            state_checks = verify(command, compose, env, image, volumes['release_verification']['name'])
        finally:
            if started:
                command([*compose, 'down', '--volumes', '--remove-orphans'], env=env)
        if command(['docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={project}']):
            raise RuntimeError('Owned smoke containers survived cleanup')
        for volume in volumes.values():
            if subprocess.run(['docker', 'volume', 'inspect', volume['name']],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                raise RuntimeError('Owned smoke volume survived cleanup')
    print(json.dumps({'status': 'passed', 'commit': tip, 'image_id': image,
                      'project': project, 'host_port': port, 'schema': current_schema_version(),
                      'empty_accounts': True, 'unauthenticated_401': True,
                      'invalid_host_403': True, 'packaged_dist_matched': True,
                      'restart': 'passed', 'state_checks': state_checks, 'cleanup': 'passed'}))


if __name__ == '__main__':
    main()
