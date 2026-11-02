"""Fixed SSH-side phases for release_pipeline.py; never invoke directly on a serving host.

REQUEST is injected by the local gated runner. No secrets or raw responses are emitted.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener


def run(*args, env=None, input=None, timeout=120):
    return subprocess.check_output(args, env=env, input=input, text=True,
                                   stderr=subprocess.DEVNULL, timeout=timeout).strip()


def expected_mounts(config, service):
    mounts = {}
    for item in config['services'][service].get('volumes', []):
        source = (config['volumes'][item['source']]['name'] if item['type'] == 'volume'
                  else os.path.realpath(item['source']))
        mounts[item['target']] = (item['type'], source, not item.get('read_only', False))
    for secret in config['services'][service].get('secrets', []):
        mounts[secret['target']] = ('bind', os.path.realpath(config['secrets'][secret['source']]['file']), False)
    return mounts


def check_existing(info, config, service, project, *, db_image=None):
    settings = config['services'][service]
    if (info['Config']['Labels'].get('com.docker.compose.project') != project
            or info['Config']['Labels'].get('com.docker.compose.service') != service
            or not info['State']['Running']):
        raise ValueError('Existing serving owner mismatch')
    actual = {item['Destination']: (item['Type'], item['Name'] if item['Type'] == 'volume'
              else os.path.realpath(item['Source']), item['RW']) for item in info['Mounts']}
    if actual != expected_mounts(config, service):
        raise ValueError('Existing serving mount differs from candidate')
    networks = {config['networks'][name]['name'] for name in settings['networks']}
    if set(info['NetworkSettings']['Networks']) != networks:
        raise ValueError('Existing serving network differs from candidate')
    if service == 'app':
        ports = {'8765/tcp': [{'HostIp': item['host_ip'], 'HostPort': str(item['published'])}]
                 for item in settings['ports']}
        if (info['Config']['Cmd'] != settings['command']
                or info['Config']['User'] != settings['user']
                or info['HostConfig']['ReadonlyRootfs'] != settings['read_only']
                or info['HostConfig']['PortBindings'] != ports):
            raise ValueError('Existing serving command, user, flags or binding differs from candidate')
        tmp = info['HostConfig'].get('Tmpfs') or {}
        options = set(tmp.get('/tmp', '').split(','))
        if (set(tmp) != {'/tmp'} or not {'rw', 'noexec', 'nosuid'} <= options
                or not {'size=64m', 'size=67108864'} & options):
            raise ValueError('Existing serving tmpfs differs from candidate')
    elif (info['Image'] != db_image or info['HostConfig'].get('PortBindings')
          or any(f'{key}={value}' not in info['Config']['Env'] for key, value in settings['environment'].items())):
        raise ValueError('Existing DB image, environment or binding differs from candidate')


def check_snapshot(target, planned, serving_mounts):
    root = Path(target['snapshot_dir'])
    if (not root.is_dir() or root.is_symlink() or root.resolve() != root
            or root.stat().st_uid != 10001
            or root.stat().st_mode & (stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR) !=
               (stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)):
        raise ValueError('Independent app-owned snapshot volume required')
    if not os.access(root, os.R_OK | os.X_OK):
        raise ValueError('SSH identity cannot inspect snapshot result')
    path = root.resolve()
    protected = [Path(target['stage']), Path(target['password_file']), Path(target['ephemeris_dir'])]
    protected += [Path(item['Source']) for item in serving_mounts if item['Type'] == 'bind']
    protected += [Path(item['Source']) for item in serving_mounts if item['Type'] == 'volume']
    if any(path == source or path in source.parents or source in path.parents for source in protected):
        raise ValueError('Snapshot cannot overlap serving state or staging')
    destination = root / ('snapshot-' + planned['plan_sha256'][:16])
    if destination.exists() or destination.is_symlink():
        raise ValueError('Snapshot target already exists; no retry')
    return root


def installed_db_override(target):
    image = target['db_image']
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
        raise ValueError('Installed DB requires an immutable config ID')
    return f'services:\n  db:\n    image: {image}\n'


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
    compose = ['docker', 'compose', '-f', str(stage / 'compose.yaml'),
               '-f', str(stage / 'runtime.yaml'), '-p', project]

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
        (stage / 'runtime.yaml').write_text(installed_db_override(target))
        (stage / 'runtime.yaml').chmod(0o600)
    elif action == 'preflight':
        if json.loads(marker.read_text()) != {'plan_sha256': planned['plan_sha256'], 'phase': 'staged'}:
            raise ValueError('Unexpected stage')
        archive = stage / 'image.tar'
        with archive.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != planned['artifact']['image_archive_sha256']:
                raise ValueError('Archive differs from approved image')
        if (hashlib.sha256((stage / 'compose.yaml').read_bytes()).hexdigest() != planned['compose_sha256']
                or (stage / 'runtime.yaml').read_text() != installed_db_override(target)):
            raise ValueError('Compose or installed DB override mismatch')
        config = json.loads(c('config', '--format', 'json'))
        if (config['name'] != project or config['services']['app']['image'] != image
                or config['services']['db']['image'] != target['db_image']):
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
        app_id, db_id = c('ps', '-q', 'app'), c('ps', '-q', 'db')
        if not app_id or not db_id:
            raise ValueError('Existing owned app and DB must be running')
        app = json.loads(run('docker', 'inspect', app_id))[0]
        db = json.loads(run('docker', 'inspect', db_id))[0]
        db_image = json.loads(run('docker', 'image', 'inspect', services['db']['image']))[0]['Id']
        check_existing(app, config, 'app', project)
        check_existing(db, config, 'db', project, db_image=db_image)
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', app['Image']):
            raise ValueError('Previous image identity invalid')
        check_snapshot(target, planned, app['Mounts'] + db['Mounts'])
        (stage / 'previous-image').write_text(app['Image'] + '\n')
        (stage / 'previous-container').write_text(app_id + '\n')
        (stage / 'previous-db-container').write_text(db_id + '\n')
        (stage / 'previous-db-image').write_text(db['Image'] + '\n')
        # No pull, tag substitution or build on the server.
        run('docker', 'load', '-i', str(archive), timeout=600)
        loaded = json.loads(run('docker', 'image', 'inspect', image))[0]
        if loaded['Id'] != image or loaded['Config']['Labels'].get('org.opencontainers.image.revision') != planned['artifact']['commit']:
            raise ValueError('Loaded image identity mismatch')
        advance('staged', 'preflight_ok')
    elif action == 'quiesce_and_snapshot':
        app_id = (stage / 'previous-container').read_text().strip()
        db_id = (stage / 'previous-db-container').read_text().strip()
        previous_image = (stage / 'previous-image').read_text().strip()
        db_image = (stage / 'previous-db-image').read_text().strip()
        if (hashlib.sha256((stage / 'compose.yaml').read_bytes()).hexdigest() != planned['compose_sha256']
                or (stage / 'runtime.yaml').read_text() != installed_db_override(target)
                or c('ps', '-q', 'app') != app_id or c('ps', '-q', 'db') != db_id):
            raise ValueError('Serving owner or Compose changed after preflight')
        config = json.loads(c('config', '--format', 'json'))
        app = json.loads(run('docker', 'inspect', app_id))[0]
        db = json.loads(run('docker', 'inspect', db_id))[0]
        check_existing(app, config, 'app', project)
        check_existing(db, config, 'db', project, db_image=db_image)
        if app['Image'] != previous_image or db['Image'] != db_image:
            raise ValueError('Serving image changed after preflight')
        check_snapshot(target, planned, app['Mounts'] + db['Mounts'])
        advance('preflight_ok', 'quiescing')  # durable before first serving mutation
        c('stop', 'app')
        # Safe recovery is only for a verified stopped original container before
        # the snapshot command begins. An ambiguous backup/activation never retries.
        try:
            if c('ps', '-q', 'app'):
                raise ValueError('App not quiesced')
            stopped = json.loads(run('docker', 'inspect', app_id))[0]
            if stopped['Image'] != previous_image or stopped['State']['Running']:
                raise ValueError('Stopped app identity changed')
            snapshot_root = check_snapshot(target, planned, stopped['Mounts'])
        except (ValueError, OSError):
            original = json.loads(run('docker', 'inspect', app_id))[0]
            if (original['Image'] != previous_image
                    or original['Config']['Labels'].get('com.docker.compose.project') != project
                    or c('ps', '-q', 'db') != db_id
                    or json.loads(run('docker', 'inspect', db_id))[0]['Image'] != db_image):
                raise
            if not original['State']['Running']:
                run('docker', 'start', app_id)
            restored = json.loads(run('docker', 'inspect', app_id))[0]
            if restored['Image'] != previous_image or not restored['State']['Running']:
                raise RuntimeError('Old app restart unconfirmed')
            advance('quiescing', 'recovered_old_app')
            print(json.dumps({'phase': action, 'status': 'recovered_old_app'}))
            return
        name = 'snapshot-' + planned['plan_sha256'][:16]
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
            with error:
                if error.code != 403:
                    raise ValueError('Wrong-host guard failed')
        else:
            raise ValueError('Wrong-host guard failed')
        # Every public file in the image is checked at loopback, then returned
        # as bounded digests for the controller's independent HTTPS verification.
        listing = "import hashlib,json,pathlib; root=pathlib.Path('/opt/kat/web/dist'); print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}))"
        assets = json.loads(c('exec', '-T', 'app', 'python', '-c', listing))
        required = {'index.html', 'manifest.webmanifest', 'icons/kat-192.png',
                    'icons/kat-512.png', 'icons/kat-512-maskable.png'}
        if (not required <= assets.keys() or len(assets) > 64
                or any(not re.fullmatch(r'[A-Za-z0-9_./-]+', name) or '..' in Path(name).parts
                       or not re.fullmatch(r'[a-f0-9]{64}', digest) for name, digest in assets.items())):
            raise ValueError('Invalid packaged asset list')
        for name, expected in assets.items():
            code, body = fetch('/' if name == 'index.html' else '/' + name)
            if code != 200 or hashlib.sha256(body).hexdigest() != expected:
                raise ValueError('Served asset differs from packaged image')
        advance('app_started', 'local_verified')
        print(json.dumps({'phase': action, 'status': 'ok', 'assets': assets}))
        return
    else:
        raise ValueError('Unsupported phase')
    print(json.dumps({'phase': action, 'status': 'ok'}))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        print('Release phase halted; inspect protected stage; do not retry automatically.', file=sys.stderr)
        raise SystemExit(1)
