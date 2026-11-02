"""Root-owned OpenSSH forced command. Install only under a separately approved scope.

The client sends one bounded JSON line and, for upload only, exactly the declared
archive bytes. Neither client-supplied code, paths, Compose, environment nor Docker
arguments cross this boundary. All effects are delegated to the root-owned,
versioned release_remote module after validating a root-owned release policy.
"""

from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import re
import stat
import sys

if __package__:
    from deploy import release_remote
else:
    release_remote = None  # Isolated script: load only the adjacent protected file after the guard.

POLICY = Path('/etc/kat-release/policy.json')
REQUEST_LIMIT = 16 * 1024
HEX = re.compile(r'[0-9a-f]{64}\Z')
IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
ACTIONS = {'stage', 'upload', 'compose', 'preflight', 'quiesce_and_snapshot',
           'activate_app_only', 'verify_serving_path'}
PLAN_FIELDS = {'contract', 'target', 'artifact', 'schema_version', 'compose_sha256',
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
    if set(policy) != {'target', 'approved_plan_sha256', 'schema_version',
                       'compose_file', 'max_archive_bytes'}:
        raise ValueError('Policy fields differ')
    target = policy['target']
    if set(target) != {'ssh_alias', 'project', 'stage', 'password_file', 'ephemeris_dir',
                       'snapshot_dir', 'origin', 'loopback_port', 'db_image'}:
        raise ValueError('Protected target fields differ')
    for key in ('stage', 'password_file', 'ephemeris_dir', 'snapshot_dir'):
        path_value = target[key]
        if (not isinstance(path_value, str) or not path_value.startswith('/srv/')
                or '..' in Path(path_value).parts or os.path.realpath(path_value) != path_value):
            raise ValueError('Protected target path invalid')
    if (not IMAGE.fullmatch(target['db_image']) or not HEX.fullmatch(policy['approved_plan_sha256'])
            or not isinstance(policy['schema_version'], int) or policy['schema_version'] < 1
            or not isinstance(policy['max_archive_bytes'], int)
            or not 0 < policy['max_archive_bytes'] <= 2 * 1024**3):
        raise ValueError('Protected identity or archive bound invalid')
    protected(policy['compose_file'])
    stage_parent = Path(target['stage']).parent
    for parent in (stage_parent, *stage_parent.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Stage parent must be root protected')
    return policy


def validate(request, policy):
    if not isinstance(request, dict) or set(request) not in ({'action', 'plan'}, {'action', 'plan', 'bytes'}):
        raise ValueError('Unsupported request fields')
    action, plan = request['action'], request['plan']
    if action not in ACTIONS or ('bytes' in request) != (action == 'upload'):
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
    if (plan['contract'] != 2 or plan['target'] != target_scope
            or plan['schema_version'] != policy['schema_version']
            or digest != plan['plan_sha256'] or digest != policy['approved_plan_sha256']
            or sha256(protected(__file__).read_bytes()).hexdigest() != plan['access_helper_sha256']
            or sha256(protected(phase_module().__file__).read_bytes()).hexdigest() != plan['remote_runner_sha256']
            or sha256(protected(policy['compose_file']).read_bytes()).hexdigest() != plan['compose_sha256']):
        raise ValueError('Protected approval, target or template differs')
    if action == 'upload' and (not isinstance(request['bytes'], int) or isinstance(request['bytes'], bool)
            or not 0 < request['bytes'] <= policy['max_archive_bytes']):
        raise ValueError('Archive length exceeds policy')
    return action, plan


def upload(stage, plan, size, input_stream):
    marker = json.loads((stage / 'phase.json').read_text())
    if marker != {'plan_sha256': plan['plan_sha256'], 'phase': 'staged'}:
        raise ValueError('Archive upload requires an exclusive fresh stage')
    # Exclusive O_NOFOLLOW prevents a staged symlink or ambiguous replay.
    fd = os.open(stage / 'image.tar', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
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
    with (stage / 'image.tar').open('rb') as archive:
        from hashlib import file_digest
        if file_digest(archive, 'sha256').hexdigest() != plan['artifact']['image_archive_sha256']:
            raise ValueError('Archive differs from approved hash')


def dispatch(request, policy, input_stream):
    action, plan = validate(request, policy)
    target = policy['target']
    stage = Path(target['stage'])
    if action == 'upload':
        upload(stage, plan, request['bytes'], input_stream)
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
