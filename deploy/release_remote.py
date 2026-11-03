"""Fixed app-only phases, callable solely by installed release_access forced command.

The trusted server policy supplies REQUEST after forced-command validation; never
execute this module with client-provided Python or a writable Compose template.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener


SERVER_ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/root', 'LANG': 'C.UTF-8',
              'DOCKER_HOST': 'unix:///var/run/docker.sock'}


def run(*args, env=None, input=None, timeout=120):
    return subprocess.check_output(args, env=SERVER_ENV if env is None else env,
                                   input=input, text=True,
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


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_text(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    sync_directory(path.parent)


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def protected_file(path):
    path = Path(path)
    for item in (path, *path.parents):
        info = item.lstat()
        if (stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                or (item == path and not stat.S_ISREG(info.st_mode))):
            raise ValueError('Canonical release file is not root protected')
    return path


def selected_image(content):
    matches = re.findall(rb'^KAT_APP_IMAGE=(sha256:[a-f0-9]{64})$', content, re.MULTILINE)
    assignments = re.findall(rb'^\s*(?:export\s+)?KAT_APP_IMAGE\s*=', content, re.MULTILINE)
    if len(matches) != 1 or len(assignments) != 1:
        raise ValueError('Canonical image selection is ambiguous')
    return matches[0].decode()


def replace_file(path, content, attempt):
    path = protected_file(path)
    temporary = path.with_name(path.name + '.kat-' + attempt)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 stat.S_IMODE(path.stat().st_mode))
    with os.fdopen(fd, 'wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def source_archive(path, planned):
    if path.stat().st_size != planned['source_bytes'] or file_hash(path) != planned['artifact']['source_offer_sha256']:
        raise ValueError('Source archive differs from signed identity')
    with tarfile.open(path, mode='r:') as archive:
        members = archive.getmembers()
        if (not members or len(members) > 10000 or len({m.name for m in members}) != len(members)
                or sum(m.size for m in members) > 128 * 1024**2
                or any(not (m.isfile() or m.isdir()) or Path(m.name).is_absolute()
                       or '..' in Path(m.name).parts for m in members)):
            raise ValueError('Unsafe source archive')


def release_files(target):
    env = protected_file(target['release_env_file'])
    source = protected_file(target['source_offer_file'])
    return {'selected_image': selected_image(env.read_bytes()),
            'env_sha256': file_hash(env), 'source_sha256': file_hash(source)}


# Fixed server-local read: emit only aggregate/hash identities, never rows,
# filenames, credentials or provider requests. SIWC credential contents stay unread.
STATE_FINGERPRINT = '''from pathlib import Path
from hashlib import sha256,file_digest
import json,os
root=Path('/var/lib/kat/browser-runtime')
for name in ('files','deletions','siwc'):
    directory=root/name
    if (not directory.is_dir() or directory.is_symlink() or directory.stat().st_uid!=os.getuid()
            or directory.stat().st_mode&0o777!=0o700): raise ValueError('Unsafe state directory')
def digest(path):
    if path.is_symlink() or not path.is_file(): raise ValueError('Unsafe state file')
    with path.open('rb') as stream: return file_digest(stream,'sha256').hexdigest()
files=sha256()
for path in sorted((root/'files').rglob('*')):
    if path.is_symlink(): raise ValueError('Unsafe attachment')
    if path.is_file(): files.update(str(path.relative_to(root/'files')).encode()+b'\\0'+digest(path).encode()+b'\\n')
print(json.dumps({'files_sha256':files.hexdigest(),
    'host_sha256':digest(root/'siwc/host.json'),
    'journal_sha256':digest(root/'deletions/deletions.jsonl'),
    'journal_bytes':(root/'deletions/deletions.jsonl').stat().st_size,
    'tip_sha256':digest(root/'deletions/deletions.jsonl.tip')}))
'''


RETAIN_AUTHORITY = '''from pathlib import Path
from hashlib import file_digest
import os,shutil
from m2.deletion import Tombstones
journal=Path('/var/lib/kat/browser-runtime/deletions/deletions.jsonl')
for path in (journal,journal.with_name(journal.name+'.tip')):
    if not path.is_file() or path.is_symlink(): raise ValueError('Existing deletion authority required')
Tombstones(journal).verify()
destination=Path('/verification/authority-ATTEMPT')
destination.mkdir(mode=0o700)
for source in (journal,journal.with_name(journal.name+'.tip')):
    target=destination/source.name
    with source.open('rb') as original,target.open('xb') as retained:
        shutil.copyfileobj(original,retained)
        retained.flush()
        os.fsync(retained.fileno())
    target.chmod(0o600)
    with source.open('rb') as original,target.open('rb') as retained:
        if file_digest(original,'sha256').hexdigest()!=file_digest(retained,'sha256').hexdigest():
            raise ValueError('Independent deletion authority copy differs')
for directory in (destination,destination.parent):
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
'''


def preservation(c, *, running):
    tables = c('exec', '-T', 'db', 'psql', '-U', 'kat', '-d', 'kat', '-At', '-c',
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
    aggregates = {}
    for table in tables:
        if not re.fullmatch('[a-z_0-9]+', table):
            raise ValueError('Unsupported table identity')
        query = ("SET statement_timeout='10s'; SELECT count(*),md5(COALESCE("
                 "string_agg(md5(to_jsonb(t)::text),'' ORDER BY md5(to_jsonb(t)::text)),'')) "
                 'FROM public."' + table + '" t')
        aggregates[table] = c('exec', '-T', 'db', 'psql', '-U', 'kat', '-d', 'kat', '-At', '-c', query).splitlines()[-1]
    command = ('exec', '-T', 'app') if running else ('run', '--rm', '--no-deps', '-T', 'app')
    return {'database': aggregates, 'state': json.loads(c(*command, 'python', '-c', STATE_FINGERPRINT))}


POST_START_INTEGRITY = '''from pathlib import Path
from hashlib import sha256,file_digest
root=Path('/var/lib/kat/browser-runtime')
baseline_journal_bytes=BASELINE_BYTES
host=root/'siwc/host.json'
journal=root/'deletions/deletions.jsonl'
for path in (host,journal,journal.with_name(journal.name+'.tip')):
    if not path.is_file() or path.is_symlink(): raise ValueError('Required identity/authority file missing')
with host.open('rb') as stream:
    if file_digest(stream,'sha256').hexdigest()!='BASELINE_HOST': raise ValueError('Host identity changed')
# Active users may append deletions and atomically advance the tip. Compare only
# the retained, immutable prefix; never equate a new tip or new rows with damage.
with journal.open('rb') as stream:
    remaining=baseline_journal_bytes
    digest=sha256()
    while remaining:
        block=stream.read(min(remaining,1024*1024))
        if not block: raise ValueError('Retained authority prefix truncated')
        digest.update(block)
        remaining-=len(block)
    if digest.hexdigest()!='BASELINE_HASH': raise ValueError('Retained authority prefix changed')
'''


def post_start_integrity(c, baseline):
    size = baseline['journal_bytes']
    if (not isinstance(size, int) or isinstance(size, bool) or size <= 0
            or any(not re.fullmatch('[a-f0-9]{64}', baseline[key])
                   for key in ('journal_sha256', 'host_sha256'))):
        raise ValueError('Invalid retained identity/authority baseline')
    script = POST_START_INTEGRITY.replace('BASELINE_BYTES', str(size)).replace(
        'BASELINE_HASH', baseline['journal_sha256']).replace('BASELINE_HOST', baseline['host_sha256'])
    c('exec', '-T', 'app', 'python', '-c', script)


def check_canonical_config(compose, target, expected):
    # Evaluate the persisted file as a future fresh Compose process would. Policy
    # overrides must NOT mask missing/wrong canonical secret or ephemeris paths.
    observed = json.loads(run(*compose[:2], '--env-file', target['release_env_file'],
                              *compose[2:], 'config', '--format', 'json', env=SERVER_ENV))
    if observed != expected:
        raise ValueError('Canonical effective Compose config differs from policy')


def quarantine(target, planned):
    """Contain only this exact owned deployment; never restore data or guess an owner."""
    stage = Path(target['stage'])
    marker = json.loads((stage / 'phase.json').read_text())
    if marker['plan_sha256'] != planned['plan_sha256']:
        raise ValueError('Containment attempt differs')
    phase = marker['phase']
    outcome = {'status': 'halted', 'phase': phase, 'serving': 'unknown'}
    try:
        outcome['files'] = release_files(target)
    except (Exception, KeyboardInterrupt):
        outcome['files'] = 'unavailable; inspect protected originals'
    try:
        if phase in ('staged', 'image_uploaded', 'uploaded', 'composed', 'preflight_ok', 'recovered_old_app'):
            outcome['serving'] = 'unchanged; no activation attempted'
        elif phase == 'completed':
            outcome['serving'] = 'verified release already completed'
        else:
            env = {**SERVER_ENV, 'KAT_APP_IMAGE': planned['artifact']['config_digest'],
                   'KAT_DB_PASSWORD_FILE': target['password_file'], 'KAT_EPHE_DIR': target['ephemeris_dir']}
            command = ['docker', 'compose', '-f', str(stage / 'compose.yaml'),
                       '-f', str(stage / 'runtime.yaml'), '-p', target['project']]
            if (file_hash(stage / 'compose.yaml') != planned['compose_sha256']
                    or (stage / 'runtime.yaml').read_text() != installed_db_override(target)):
                raise ValueError('Containment config drift')
            config = json.loads(run(*command, 'config', '--format', 'json', env=env))
            container = run(*command, 'ps', '-aq', 'app', env=env)
            if container:
                info = json.loads(run('docker', 'inspect', container))[0]
                previous = (stage / 'previous-image').read_text().strip()
                if info['Image'] not in (previous, planned['artifact']['config_digest']):
                    raise ValueError('Containment image drift')
                # Validate all runtime/mount/route identities even if already stopped.
                inspected = info | {'State': info['State'] | {'Running': True}}
                check_existing(inspected, config, 'app', target['project'])
                if info['State']['Running']:
                    run('docker', 'stop', container)
                if json.loads(run('docker', 'inspect', container))[0]['State']['Running']:
                    raise ValueError('Containment stop unconfirmed')
                outcome['serving'] = 'stopped; exact owned app quarantined'
            else:
                outcome['serving'] = 'no app container found; inspection required'
    except (Exception, KeyboardInterrupt):
        outcome['serving'] = 'unknown; containment unconfirmed'
    # Retain the active-attempt fence on every halt, including confirmed quarantine.
    # Recovery/adoption must reconcile files and serving state before retiring it.
    with (stage / 'failure.json').open('w') as output:
        json.dump(outcome, output)
        output.flush()
        os.fsync(output.fileno())
    return outcome


def main():
    try:
        return release_phase()
    except (Exception, KeyboardInterrupt):
        if REQUEST['action'] not in ('quiesce_and_snapshot', 'promote_release',
                'activate_app_only', 'verify_serving_path', 'complete'):
            raise
        return quarantine(REQUEST['target'], REQUEST['plan'])


def release_phase():
    target, planned, action = REQUEST['target'], REQUEST['plan'], REQUEST['action']
    stage = Path(target['stage'])
    marker = stage / 'phase.json'
    # OCI index identity is not the Docker runtime image ID; Compose pins config.
    image = planned['artifact']['config_digest']
    project = target['project']
    environment = {**SERVER_ENV, 'KAT_APP_IMAGE': image,
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
        sync_directory(stage)

    if action == 'quarantine':
        return quarantine(target, planned)
    if action not in ('stage', 'compose'):
        if (file_hash(stage / 'compose.yaml') != planned['compose_sha256']
                or (stage / 'runtime.yaml').read_text() != installed_db_override(target)):
            raise ValueError('Staged Compose drift')
    if action == 'stage':
        if stage.exists() or stage.is_symlink():
            raise ValueError('Stage exists; no retry')
        stage.mkdir(mode=0o700)
        durable_text(marker, json.dumps({'plan_sha256': planned['plan_sha256'], 'phase': 'staged'}) + '\n')
        sync_directory(stage.parent)
    elif action == 'compose':
        if json.loads(marker.read_text()) != {'plan_sha256': planned['plan_sha256'], 'phase': 'uploaded'}:
            raise ValueError('Unexpected stage; no retry')
        with (stage / 'compose.yaml').open('x') as output:
            output.write(REQUEST['compose'])
        (stage / 'compose.yaml').chmod(0o600)
        with (stage / 'runtime.yaml').open('x') as output:
            output.write(installed_db_override(target))
        (stage / 'runtime.yaml').chmod(0o600)
        advance('uploaded', 'composed')
    elif action == 'preflight':
        if json.loads(marker.read_text()) != {'plan_sha256': planned['plan_sha256'], 'phase': 'composed'}:
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
        schema = c('exec', '-T', 'db', 'psql', '-U', 'kat', '-d', 'kat', '-At', '-c',
                   'SELECT max(version) FROM schema_migrations')
        if schema != str(planned['schema_version']):
            raise ValueError('Routine release cannot migrate schema')
        files = release_files(target)
        if files['selected_image'] != app['Image']:
            raise ValueError('Canonical selection differs from running app')
        canonical_expected = config | {'services': config['services'] | {
            'app': services['app'] | {'image': app['Image']}}}
        check_canonical_config(compose, target, canonical_expected)
        source_archive(stage / 'source.tar', planned)
        durable_text(stage / 'files.before.json', json.dumps(files))
        for key, name in (('release_env_file', 'env.before'), ('source_offer_file', 'source.before.tar')):
            with (stage / name).open('xb') as output:
                output.write(Path(target[key]).read_bytes())
                output.flush()
                os.fsync(output.fileno())
        if (file_hash(stage / 'env.before') != files['env_sha256']
                or file_hash(stage / 'source.before.tar') != files['source_sha256']):
            raise ValueError('Original release files changed while retaining them')
        durable_text(stage / 'previous-image', app['Image'] + '\n')
        durable_text(stage / 'previous-container', app_id + '\n')
        durable_text(stage / 'previous-db-container', db_id + '\n')
        durable_text(stage / 'previous-db-image', db['Image'] + '\n')
        # No pull, tag substitution or build on the server.
        run('docker', 'load', '-i', str(archive), timeout=600)
        loaded = json.loads(run('docker', 'image', 'inspect', image))[0]
        if loaded['Id'] != image or loaded['Config']['Labels'].get('org.opencontainers.image.revision') != planned['artifact']['commit']:
            raise ValueError('Loaded image identity mismatch')
        advance('composed', 'preflight_ok')
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
        if release_files(target) != json.loads((stage / 'files.before.json').read_text()):
            raise ValueError('Canonical release files drifted after preflight')
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
            return {'phase': action, 'status': 'recovered_old_app'}
        with (stage / 'state.before.json').open('x') as output:
            json.dump(preservation(c, running=False), output)
            output.flush()
            os.fsync(output.fileno())
        name = 'snapshot-' + planned['plan_sha256'][:16]
        run(*compose, 'run', '--rm', '--no-deps', '-T', '-v',
            str(snapshot_root) + ':/verification', 'app',
            'python', '-m', 'm2.deployment_backup', 'backup',
            '--state-directory', '/var/lib/kat', '--snapshot', '/verification/' + name,
            '--db-password-file', '/run/secrets/db_password', env=environment, timeout=180)
        manifest = json.loads((snapshot_root / name / 'manifest.json').read_text())
        if manifest['schema_version'] != planned['schema_version'] or not manifest['journal_prefix_sha256']:
            raise ValueError('Snapshot schema or deletion authority mismatch')
        c('run', '--rm', '--no-deps', '-T', '-v', str(snapshot_root) + ':/verification',
          'app', 'python', '-c', RETAIN_AUTHORITY.replace('ATTEMPT', planned['attempt']))
        advance('quiescing', 'snapshot_ok')
    elif action == 'promote_release':
        if release_files(target) != json.loads((stage / 'files.before.json').read_text()):
            raise ValueError('Canonical release files drifted before promotion')
        if c('ps', '-q', 'app'):
            raise ValueError('App must remain quiesced for promotion')
        source_archive(stage / 'source.tar', planned)
        advance('snapshot_ok', 'promoting')
        old = (stage / 'env.before').read_bytes()
        selected_image(old)  # Exactly one canonical assignment; comments are unrelated bytes.
        replacement = re.sub(rb'^KAT_APP_IMAGE=sha256:[a-f0-9]{64}$',
                             ('KAT_APP_IMAGE=' + image).encode(), old, count=1, flags=re.MULTILINE)
        # These are distinct filesystem/Docker effects, not an atomic transaction.
        # A failure leaves the exact owned app stopped, originals and backup retained.
        replace_file(target['source_offer_file'], (stage / 'source.tar').read_bytes(), planned['attempt'])
        replace_file(target['release_env_file'], replacement, planned['attempt'])
        expected = {'selected_image': image, 'env_sha256': hashlib.sha256(replacement).hexdigest(),
                    'source_sha256': planned['artifact']['source_offer_sha256']}
        if release_files(target) != expected:
            raise ValueError('Promotion did not commit exact source/config')
        check_canonical_config(compose, target, json.loads(c('config', '--format', 'json')))
        with (stage / 'files.promoted.json').open('x') as output:
            json.dump(expected, output)
            output.flush()
            os.fsync(output.fileno())
        advance('promoting', 'promoted')
    elif action == 'activate_app_only':
        if release_files(target) != json.loads((stage / 'files.promoted.json').read_text()):
            raise ValueError('Promoted source/selection mismatch')
        if c('ps', '-q', 'app'):
            raise ValueError('Preservation equality requires the app to remain quiesced')
        # Last full equality boundary BEFORE public traffic can write rows/files.
        # No new proxy/maintenance authority is needed for this app-only release.
        if preservation(c, running=False) != json.loads((stage / 'state.before.json').read_text()):
            raise ValueError('Quiesced archive/files/host/deletion authority changed')
        advance('promoted', 'activating')
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
        return {'phase': action, 'status': 'ok', 'assets': assets}
    elif action == 'complete':
        if release_files(target) != json.loads((stage / 'files.promoted.json').read_text()):
            raise ValueError('Final source/selection drift')
        container = c('ps', '-q', 'app')
        info = json.loads(run('docker', 'inspect', container))[0]
        if info['Image'] != image:
            raise ValueError('Final running image drift')
        check_existing(info, json.loads(c('config', '--format', 'json')), 'app', project)
        if c('ps', '-q', 'db') != (stage / 'previous-db-container').read_text().strip():
            raise ValueError('Database container changed during app-only release')
        owner = Path(target['stage_root']) / 'active-attempt'
        if owner.read_text().strip() != planned['attempt']:
            raise ValueError('Active release ownership changed')
        post_start_integrity(c, json.loads((stage / 'state.before.json').read_text())['state'])
        advance('local_verified', 'completed')
        owner.unlink()
        sync_directory(owner.parent)
    else:
        raise ValueError('Unsupported phase')
    return {'phase': action, 'status': 'ok'}
