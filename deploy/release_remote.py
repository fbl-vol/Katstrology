"""Fixed SSH-side phases for release_pipeline.py; never invoke directly on a serving host.

REQUEST is injected by the local gated runner. No secrets or raw responses are emitted.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener


def run(*args, env=None, input=None, timeout=120):
    return subprocess.check_output(args, env=env, input=input, text=True,
                                   stderr=subprocess.DEVNULL, timeout=timeout).strip()


def main():
    target, planned, action = REQUEST['target'], REQUEST['plan'], REQUEST['action']
    stage = Path(target['stage'])
    marker = stage / 'phase.json'
    # OCI index identity is not the Docker runtime image ID; Compose pins config.
    image = planned['artifact']['config_digest']
    project = target['project']
    environment = {**os.environ, 'KAT_APP_IMAGE': image,
                   'KAT_DB_PASSWORD_FILE': target['password_file'],
                   'KAT_EPHE_DIR': target['ephemeris_dir']}
    compose = ['docker', 'compose', '-f', str(stage / 'compose.yaml'), '-p', project]

    def c(*args, timeout=120):
        return run(*compose, *args, env=environment, timeout=timeout)

    def advance(expected, next_phase):
        if json.loads(marker.read_text()) != {'plan_sha256': planned['plan_sha256'], 'phase': expected}:
            raise ValueError('Unexpected phase; no retry')
        temporary = stage / 'phase.next'
        with temporary.open('x') as output:
            json.dump({'plan_sha256': planned['plan_sha256'], 'phase': next_phase}, output)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, marker)

    if action == 'stage':
        if stage.exists() or stage.is_symlink():
            raise ValueError('Stage exists; no retry')
        stage.mkdir(mode=0o700)
        marker.write_text(json.dumps({'plan_sha256': planned['plan_sha256'], 'phase': 'staged'}) + '\n')
        marker.chmod(0o600)
    elif action == 'compose':
        if json.loads(marker.read_text())['phase'] != 'staged':
            raise ValueError('Unexpected stage')
        (stage / 'compose.yaml').write_text(REQUEST['compose'])
        (stage / 'compose.yaml').chmod(0o600)
    elif action == 'preflight':
        if json.loads(marker.read_text()) != {'plan_sha256': planned['plan_sha256'], 'phase': 'staged'}:
            raise ValueError('Unexpected stage')
        archive = stage / 'image.tar'
        with archive.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != planned['artifact']['image_archive_sha256']:
                raise ValueError('Archive differs from approved image')
        if hashlib.sha256((stage / 'compose.yaml').read_bytes()).hexdigest() != planned['compose_sha256']:
            raise ValueError('Compose mismatch')
        config = json.loads(c('config', '--format', 'json'))
        if config['name'] != project or config['services']['app']['image'] != image:
            raise ValueError('Effective project/image mismatch')
        services = config['services']
        command = services['app']['command']
        if ('--deployment-origin' not in command or command[command.index('--deployment-origin') + 1] != target['origin']
                or '--db-password-file' not in command or '--state-directory' not in command):
            raise ValueError('Deployment origin/state command mismatch')
        if services['db'].get('ports') or services['app'].get('ports') != [{
            'mode': 'ingress', 'host_ip': '127.0.0.1', 'target': 8765,
            'published': str(target['loopback_port']), 'protocol': 'tcp'}]:
            raise ValueError('Effective network exposure mismatch')
        if services['app'].get('tmpfs') != ['/tmp:rw,noexec,nosuid,size=64m']:
            raise ValueError('Effective tmpfs mismatch')
        if config['volumes'] and any(value.get('name') != f'{project}_{key}' for key, value in config['volumes'].items()):
            raise ValueError('External volume mapping requires separate review')
        existing = c('ps', '-q', 'app')
        if not existing or not c('ps', '-q', 'db'):
            raise ValueError('Existing owned app and DB must be running')
        info = json.loads(run('docker', 'inspect', existing))[0]
        if (info['Config']['Labels'].get('com.docker.compose.project') != project
                or info['Config']['Labels'].get('com.docker.compose.service') != 'app'
                or not info['State']['Running']):
            raise ValueError('Serving owner mismatch')
        (stage / 'previous-image').write_text(info['Image'] + '\n')
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', info['Image']):
            raise ValueError('Previous image identity invalid')
        # No pull, tag substitution or build on the server.
        run('docker', 'load', '-i', str(archive), timeout=600)
        loaded = json.loads(run('docker', 'image', 'inspect', image))[0]
        if loaded['Id'] != image or loaded['Config']['Labels'].get('org.opencontainers.image.revision') != planned['artifact']['commit']:
            raise ValueError('Loaded image identity mismatch')
        advance('staged', 'preflight_ok')
    elif action == 'quiesce_and_snapshot':
        advance('preflight_ok', 'quiescing')  # durable before first serving mutation
        c('stop', 'app')
        if c('ps', '-q', 'app'):
            raise ValueError('App not quiesced')
        snapshot_root = Path(target['snapshot_dir'])
        if not snapshot_root.is_dir() or snapshot_root.is_symlink() or snapshot_root.stat().st_uid != 10001:
            raise ValueError('Independent app-owned snapshot volume required')
        name = 'snapshot-' + planned['plan_sha256'][:16]
        if (snapshot_root / name).exists():
            raise ValueError('Snapshot already exists; no retry')
        run(*compose, 'run', '--rm', '--no-deps', '-T', '-v',
            str(snapshot_root) + ':/verification', 'app',
            'python', '-m', 'm2.deployment_backup', 'backup',
            '--state-directory', '/var/lib/kat', '--snapshot', '/verification/' + name,
            '--db-password-file', '/run/secrets/db_password', env=environment, timeout=180)
        manifest = json.loads((snapshot_root / name / 'manifest.json').read_text())
        if manifest['schema_version'] != planned['schema_version'] or not manifest['journal_prefix_sha256']:
            raise ValueError('Snapshot schema or deletion authority mismatch')
        advance('quiescing', 'snapshot_ok')
    elif action == 'activate_app_only':
        advance('snapshot_ok', 'activating')
        c('up', '--no-deps', '-d', '--wait', '--wait-timeout', '90', 'app')
        container = c('ps', '-q', 'app')
        info = json.loads(run('docker', 'inspect', container))[0]
        if info['Image'] != image or info['Config']['Labels'].get('com.docker.compose.project') != project:
            raise ValueError('Activated image/owner differs')
        advance('activating', 'app_started')
    elif action == 'verify_serving_path':
        if json.loads(marker.read_text()) != {'plan_sha256': planned['plan_sha256'], 'phase': 'app_started'}:
            raise ValueError('Not activated')
        from urllib.parse import urlsplit
        host = urlsplit(target['origin']).netloc
        opener = build_opener(ProxyHandler({}))

        def fetch(path):
            request = Request(f"http://127.0.0.1:{target['loopback_port']}{path}", headers={'Host': host})
            try:
                response = opener.open(request, timeout=8)
            except HTTPError as error:
                response = error
            with response:
                return response.status, response.read()

        if fetch('/api/session')[0] != 401:
            raise ValueError('Session path unavailable')
        wrong = Request(f"http://127.0.0.1:{target['loopback_port']}/api/session",
                        headers={'Host': 'wrong.invalid'})
        try:
            opener.open(wrong, timeout=8)
        except HTTPError as error:
            if error.code != 403:
                raise ValueError('Wrong-host guard failed')
        else:
            raise ValueError('Wrong-host guard failed')
        code, html = fetch('/')
        expected = c('exec', '-T', 'app', 'sha256sum', '/opt/kat/web/dist/index.html').split()[0]
        if code != 200 or hashlib.sha256(html).hexdigest() != expected:
            raise ValueError('Served asset differs from packaged image')
        advance('app_started', 'verified')
    else:
        raise ValueError('Unsupported phase')
    print(json.dumps({'phase': action, 'status': 'ok'}))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        print('Release phase halted; inspect protected stage; do not retry automatically.', file=sys.stderr)
        raise SystemExit(1)
