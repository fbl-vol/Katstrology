"""Root-owned OpenSSH forced command. Install only under a separately approved scope.

The client sends one bounded JSON line and, for upload only, exactly the declared
archive bytes. Neither client-supplied code, paths, Compose, environment nor Docker
arguments cross this boundary. All effects are delegated to the root-owned,
versioned release_remote module after validating a root-owned release policy.
"""

from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from tempfile import NamedTemporaryFile

if __package__:
    from deploy import release_remote
else:
    release_remote = None  # Isolated script: load only the adjacent protected file after the guard.

POLICY = Path('/etc/kat-release/policy.json')
REQUEST_LIMIT = 16 * 1024
HEX = re.compile(r'[0-9a-f]{64}\Z')
IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
ATTEMPT = re.compile(r'[0-9a-f]{32}\Z')
APPROVAL_NAMESPACE = 'kat-release-approval-v1'
ACTIONS = {'stage', 'upload', 'upload_source', 'compose', 'preflight', 'quiesce_and_snapshot',
           'promote_release', 'activate_app_only', 'verify_serving_path', 'complete', 'quarantine'}
STEPS = ['stage', 'upload', 'upload_source', 'compose', 'preflight', 'quiesce_and_snapshot',
         'promote_release', 'activate_app_only', 'verify_serving_path', 'complete']
PLAN_FIELDS = {'contract', 'attempt', 'archive_bytes', 'source_bytes', 'target', 'artifact', 'schema_version', 'compose_sha256',
               'runner_sha256', 'remote_runner_sha256', 'access_helper_sha256',
               'steps', 'on_ambiguity', 'plan_sha256'}
ARTIFACT_FIELDS = {'commit', 'tree', 'image_id', 'config_digest',
                   'image_archive_sha256', 'source_offer_sha256'}


def phase_module():
    adjacent = protected(Path(__file__).with_name('release_remote.py'))
    if release_remote is not None:
        if Path(release_remote.__file__) != adjacent:
            raise ValueError('Phase module is not adjacent to the fixed helper')
        return release_remote
    spec = spec_from_file_location('_kat_root_protected_release_phase', adjacent)
    if spec is None or spec.loader is None:
        raise ValueError('Protected phase module unavailable')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def protected(path):
    """The policy and installed code/template must not be writable by the key holder."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('Protected path must be absolute')
    for parent in (path, *path.parents):
        info = parent.lstat()
        if (stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                or (parent == path and not stat.S_ISREG(info.st_mode))):
            raise ValueError('Release policy or installed code is not root protected')
    return path


def read_policy(path=POLICY):
    policy = json.loads(protected(path).read_text())
    if set(policy) != {'contract', 'target', 'schema_version', 'compose_file', 'max_archive_bytes', 'max_source_bytes',
                       'approval_principal', 'approval_namespace', 'allowed_signers_file',
                       'allowed_signers_sha256'}:
        raise ValueError('Policy fields differ')
    target = policy['target']
    if set(target) != {'ssh_alias', 'project', 'stage_root', 'password_file', 'ephemeris_dir',
                       'snapshot_dir', 'origin', 'loopback_port', 'db_image', 'release_env_file', 'source_offer_file'}:
        raise ValueError('Protected target fields differ')
    for key in ('stage_root', 'password_file', 'ephemeris_dir', 'snapshot_dir', 'release_env_file', 'source_offer_file'):
        path_value = target[key]
        if (not isinstance(path_value, str) or not path_value.startswith('/srv/')
                or '..' in Path(path_value).parts or os.path.realpath(path_value) != path_value):
            raise ValueError('Protected target path invalid')
    if (policy['contract'] != 4 or not IMAGE.fullmatch(target['db_image'])
            or not isinstance(policy['schema_version'], int) or isinstance(policy['schema_version'], bool)
            or policy['schema_version'] < 1
            or not isinstance(policy['max_archive_bytes'], int) or isinstance(policy['max_archive_bytes'], bool)
            or not 0 < policy['max_archive_bytes'] <= 2 * 1024**3
            or not isinstance(policy['max_source_bytes'], int) or isinstance(policy['max_source_bytes'], bool)
            or not 0 < policy['max_source_bytes'] <= 128 * 1024**2
            or policy['approval_namespace'] != APPROVAL_NAMESPACE
            or not re.fullmatch(r'[a-z][a-z0-9-]{1,63}', policy['approval_principal'])
            or not HEX.fullmatch(policy['allowed_signers_sha256'])):
        raise ValueError('Protected identity or archive bound invalid')
    protected(policy['compose_file'])
    signers = protected(policy['allowed_signers_file'])
    if sha256(signers.read_bytes()).hexdigest() != policy['allowed_signers_sha256']:
        raise ValueError('Protected signer identity changed')
    lines = signers.read_text().splitlines()
    if (len(lines) != 1 or not re.fullmatch(
            re.escape(policy['approval_principal']) + r' ssh-ed25519 [A-Za-z0-9+/]+={0,2}', lines[0])):
        raise ValueError('Protected signer entry differs')
    stage_root = Path(target['stage_root'])
    for parent in (stage_root, *stage_root.parents):
        info = parent.lstat()
        if (stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                or (parent == stage_root and not stat.S_ISDIR(info.st_mode))):
            raise ValueError('Stage root must be root protected')
    destinations = [protected(target[key]) for key in ('release_env_file', 'source_offer_file')]
    if len(set(destinations + [Path(target['password_file']), Path(policy['compose_file']), signers, Path(path)])) != 6:
        raise ValueError('Release destinations overlap')
    snapshot = Path(target['snapshot_dir'])
    if any(stage_root in path.parents or snapshot in path.parents for path in destinations):
        raise ValueError('Release destination overlaps staging or snapshots')
    if stage_root == snapshot or stage_root in snapshot.parents or snapshot in stage_root.parents:
        raise ValueError('Staging and snapshot must be independent')
    return policy


def validate(request, policy):
    if not isinstance(request, dict) or set(request) not in (
            {'action', 'plan', 'approval', 'signature'},
            {'action', 'plan', 'approval', 'signature', 'bytes'}):
        raise ValueError('Unsupported request fields')
    action, plan = request['action'], request['plan']
    if action not in ACTIONS or ('bytes' in request) != (action in ('upload', 'upload_source')):
        raise ValueError('Unsupported release action')
    if not isinstance(plan, dict) or set(plan) != PLAN_FIELDS or set(plan['artifact']) != ARTIFACT_FIELDS:
        raise ValueError('Plan fields differ')
    identity = plan['artifact']
    if (not all(HEX.fullmatch(identity[key]) for key in ('image_archive_sha256', 'source_offer_sha256'))
            or not all(IMAGE.fullmatch(identity[key]) for key in ('image_id', 'config_digest'))
            or not all(re.fullmatch(r'[a-f0-9]{40}', identity[key]) for key in ('commit', 'tree'))
            or not HEX.fullmatch(plan['compose_sha256'])):
        raise ValueError('Invalid immutable artifact identity')
    expected_target = policy['target']
    target_scope = {'project': expected_target['project'], 'origin': expected_target['origin'],
                    'loopback_port': expected_target['loopback_port'],
                    'target_sha256': sha256(json.dumps(expected_target, sort_keys=True).encode()).hexdigest()}
    content = {key: value for key, value in plan.items() if key != 'plan_sha256'}
    digest = sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (policy['contract'] != 4 or plan['contract'] != 4 or plan['steps'] != STEPS
            or not ATTEMPT.fullmatch(plan['attempt'])
            or not isinstance(plan['archive_bytes'], int) or isinstance(plan['archive_bytes'], bool)
            or not 0 < plan['archive_bytes'] <= policy['max_archive_bytes']
            or not isinstance(plan['source_bytes'], int) or isinstance(plan['source_bytes'], bool)
            or not 0 < plan['source_bytes'] <= policy['max_source_bytes']
            or plan['target'] != target_scope
            or plan['schema_version'] != policy['schema_version']
            or digest != plan['plan_sha256']
            or sha256(protected(__file__).read_bytes()).hexdigest() != plan['access_helper_sha256']
            or sha256(protected(phase_module().__file__).read_bytes()).hexdigest() != plan['remote_runner_sha256']
            or sha256(protected(policy['compose_file']).read_bytes()).hexdigest() != plan['compose_sha256']):
        raise ValueError('Protected approval, target or template differs')
    if action in ('upload', 'upload_source') and (not isinstance(request['bytes'], int) or isinstance(request['bytes'], bool)
            or request['bytes'] != plan['archive_bytes' if action == 'upload' else 'source_bytes']):
        raise ValueError('Archive length exceeds policy')
    approval = request['approval']
    if (not isinstance(approval, dict) or approval != {'approved_action': 'release',
            'attempt': plan['attempt'], 'plan_sha256': digest}):
        raise ValueError('Unsigned, stale or mismatched release approval')
    verify_signature(approval, request['signature'], policy)
    return action, plan


def verify_signature(approval, signature, policy):
    if (not isinstance(signature, str) or len(signature) > 8192
            or not signature.startswith('-----BEGIN SSH SIGNATURE-----\n')
            or not signature.rstrip().endswith('-----END SSH SIGNATURE-----')):
        raise ValueError('Signed release approval missing or malformed')
    payload = (json.dumps(approval, sort_keys=True, separators=(',', ':')) + '\n').encode()
    # OpenSSH verifies the pinned signer, principal and namespace, not the client.
    with NamedTemporaryFile(mode='w', encoding='ascii', prefix='kat-approval-', suffix='.sig') as file:
        file.write(signature)
        file.flush()
        result = subprocess.run(['/usr/bin/ssh-keygen', '-Y', 'verify',
                '-f', str(protected(policy['allowed_signers_file'])),
                '-I', policy['approval_principal'], '-n', policy['approval_namespace'],
                '-s', file.name], input=payload, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=10,
                env={'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LANG': 'C'})
    if result.returncode:
        raise ValueError('Release approval signature differs')


def upload(stage, plan, size, input_stream, *, source=False):
    filename = 'source.tar' if source else 'image.tar'
    expected, next_phase = ('image_uploaded', 'uploaded') if source else ('staged', 'image_uploaded')
    marker = json.loads((stage / 'phase.json').read_text())
    if marker != {'plan_sha256': plan['plan_sha256'], 'phase': expected}:
        raise ValueError('Archive upload requires an exclusive fresh stage')
    # Exclusive O_NOFOLLOW prevents a staged symlink or ambiguous replay.
    fd = os.open(stage / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as output:
        remaining = size
        while remaining:
            block = input_stream.read(min(1024 * 1024, remaining))
            if not block:
                raise ValueError('Truncated archive; attempt must not be retried')
            output.write(block)
            remaining -= len(block)
        if input_stream.read(1):
            raise ValueError('Trailing archive bytes refused')
        output.flush()
        os.fsync(output.fileno())
    with (stage / filename).open('rb') as archive:
        from hashlib import file_digest
        if file_digest(archive, 'sha256').hexdigest() != plan['artifact']['source_offer_sha256' if source else 'image_archive_sha256']:
            raise ValueError('Archive differs from approved hash')
    temporary = stage / 'phase.next'
    with temporary.open('x') as marker:
        json.dump({'plan_sha256': plan['plan_sha256'], 'phase': next_phase}, marker)
        marker.write('\n')
        marker.flush()
        os.fsync(marker.fileno())
    os.replace(temporary, stage / 'phase.json')
    phase_module().sync_directory(stage)


def dispatch(request, policy, input_stream):
    # Serialize phases and pin one active attempt across separate SSH processes.
    # Interrupted attempts retain ownership: no second deployment can race recovery.
    action, plan = validate(request, policy)
    root = Path(policy['target']['stage_root'])
    fd = os.open(root / 'release.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return dispatch_locked(request, policy, input_stream, action, plan)


def dispatch_locked(request, policy, input_stream, action, plan):
    target = policy['target'] | {'stage': str(Path(policy['target']['stage_root']) / plan['attempt'])}
    stage = Path(target['stage'])
    owner = Path(target['stage_root']) / 'active-attempt'
    if action == 'stage':
        if stage.exists() or stage.is_symlink():
            raise ValueError('Stage exists; no retry')
        with owner.open('x') as output:
            output.write(plan['attempt'] + '\n')
            output.flush()
            os.fsync(output.fileno())
        phase_module().sync_directory(owner.parent)
    elif owner.read_text().strip() != plan['attempt']:
        raise ValueError('Another release owns this target')
    if action in ('upload', 'upload_source'):
        upload(stage, plan, request['bytes'], input_stream, source=action == 'upload_source')
        return {'phase': action, 'status': 'ok'}
    if input_stream.read(1):
        raise ValueError('Unexpected request body')
    # Only trusted policy, code and template enter the actual lifecycle.
    phase = phase_module()
    phase.REQUEST = {'action': action, 'target': target, 'plan': plan}
    if action == 'compose':
        phase.REQUEST['compose'] = protected(policy['compose_file']).read_text()
    return phase.main()


def main(input_stream=None, original_command=None, policy_path=POLICY):
    if original_command != 'kat-release-v1':
        raise ValueError('Unsupported SSH command (no shell, SCP, SFTP or PTY)')
    os.umask(0o077)
    input_stream = input_stream or sys.stdin.buffer
    header = input_stream.readline(REQUEST_LIMIT + 1)
    if not header.endswith(b'\n') or len(header) > REQUEST_LIMIT:
        raise ValueError('Release request exceeds header bound')
    protected(__file__)
    phase_module()
    request = json.loads(header)
    result = dispatch(request, read_policy(policy_path), input_stream)
    if result is not None:
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main(original_command=os.environ.get('SSH_ORIGINAL_COMMAND'))
    except (Exception, KeyboardInterrupt):
        print('Restricted release refused; inspect protected stage before any new attempt.', file=sys.stderr)
        raise SystemExit(1)
