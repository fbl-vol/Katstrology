"""Future exact CI-lane append. Default is OFFLINE; --execute is not approval.

No DDL, restart, trust replacement or retry. Execute only under a separately
scoped root enrollment instruction with independently inspected expected pins.
"""
import argparse
import fcntl
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

from deploy.release_access import validate_transition_lane

POLICY = Path('/etc/kat-release/ci-policy.json')
HELPERS = Path('/usr/local/libexec/kat-release/deploy')
HELPER_NAMES = {'release_access.py', 'release_remote.py', 'release_pipeline.py', 'release_ci_access.py'}
HEX = re.compile(r'[a-f0-9]{64}\Z')


def inputs(lane_bytes, expected_bytes, expected_sha256):
    if sha256(expected_bytes).hexdigest() != expected_sha256:
        raise ValueError('Approved expectations bytes differ')
    expected = json.loads(expected_bytes)
    if (set(expected) != {'request', 'hostname', 'lane_sha256', 'policy_sha256',
                         'native_policy_sha256', 'helper_sha256'}
            or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', expected['request'])
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', expected['hostname'])
            or set(expected['helper_sha256']) != HELPER_NAMES
            or any(not isinstance(value, str) or not HEX.fullmatch(value) for value in
                   [expected['lane_sha256'], expected['policy_sha256'], expected['native_policy_sha256'],
                    *expected['helper_sha256'].values()])
            or sha256(lane_bytes).hexdigest() != expected['lane_sha256']):
        raise ValueError('Exact lane, host, native policy and helper pins required')
    lane = json.loads(lane_bytes)
    validate_transition_lane(lane)
    return lane, expected


def candidate_policy(before_bytes, lane):
    before = json.loads(before_bytes)
    if (len(before['transitions']) >= 8 or any(
            item['from'] == lane['from'] for item in before['transitions'])):
        raise ValueError('Existing/conflicting lane or full allowlist; no replay')
    return (json.dumps(before | {'transitions': before['transitions'] + [lane]}, indent=2) + '\n').encode()


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_bytes(path, content, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def installed_guards(expected):
    from deploy.release_ci_access import protected
    # Verify every imported/used installed helper before executing its validator.
    for name, digest in expected['helper_sha256'].items():
        if sha256(protected(HELPERS / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Installed helper differs')
    spec = spec_from_file_location('_kat_enrollment_guard', HELPERS / 'release_ci_access.py')
    ci = module_from_spec(spec)
    spec.loader.exec_module(ci)
    ci.read_policy()
    manual = ci.shared_access()
    if sha256(ci.protected(manual.POLICY).read_bytes()).hexdigest() != expected['native_policy_sha256']:
        raise ValueError('Inspected native policy changed')
    return ci, manual, manual.read_policy()


def running_schema(target):
    # Target comes only from the unchanged installed native policy, never CLI paths.
    ids = subprocess.check_output(['docker', 'ps', '--filter',
        'label=com.docker.compose.project=' + target['project'], '--filter',
        'label=com.docker.compose.service=db', '--format', '{{.ID}}'], text=True, timeout=10).split()
    if len(ids) != 1:
        raise ValueError('Expected one running owned DB')
    image = subprocess.check_output(['docker', 'inspect', '--format', '{{.Image}}', ids[0]],
                                    text=True, timeout=10).strip()
    if image != target['db_image']:
        raise ValueError('Native DB image differs')
    return int(subprocess.check_output(['docker', 'exec', ids[0], 'psql', '-U', 'kat', '-d', 'kat',
        '-At', '-c', 'SELECT max(version) FROM schema_migrations'], text=True, timeout=10).strip())


def enroll(lane_bytes, expected_bytes, expected_sha256, *, execute=False):
    lane, expected = inputs(lane_bytes, expected_bytes, expected_sha256)
    result = {'contract': 1, 'request': expected['request'], 'lane_sha256': expected['lane_sha256'],
              'expectations_sha256': expected_sha256, 'schema': lane['from'],
              'status': 'offline-plan-not-installed', 'database_written': False, 'service_restarted': False}
    if not execute:
        return result  # No installed files, lock, hostname, Docker or credentials inspected.
    if os.geteuid() != 0 or socket.gethostname() != expected['hostname']:
        raise ValueError('Expected separately authorized root session on exact host')
    ci, manual, native = installed_guards(expected)
    root = Path(native['target']['stage_root'])
    lock_path = ci.protected(root / 'release.lock')
    with os.fdopen(os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW), 'r+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = root / 'active-attempt'
        if active.exists() or active.is_symlink():
            raise ValueError('Native release owns the target')
        before = ci.protected(POLICY).read_bytes()
        if sha256(before).hexdigest() != expected['policy_sha256']:
            raise ValueError('Inspected CI policy changed')
        if running_schema(native['target']) != lane['from']:
            raise ValueError('Running schema differs')
        ci.read_policy()
        manual.validate_transition_lane(lane)
        after = candidate_policy(before, lane)
        backup = POLICY.parent / ('migration-enrollment-' + expected['request'])
        backup.mkdir(mode=0o700, exist_ok=False)  # Also fences ambiguous interrupted replay.
        sync_directory(backup.parent)
        durable_bytes(backup / 'policy.before.json', before)
        durable_bytes(backup / 'lane.json', lane_bytes)
        durable_bytes(backup / 'expectations.json', expected_bytes)
        durable_bytes(backup / 'policy.expected.json', after)
        pending = backup / 'policy.pending.json'
        durable_bytes(pending, after, POLICY.stat().st_mode & 0o777)
        ci.read_policy(pending)
        # Recheck native/schema/ownership and helpers immediately before replacing policy.
        installed_guards(expected)
        if (ci.protected(POLICY).read_bytes() != before or active.exists() or active.is_symlink()
                or running_schema(native['target']) != lane['from']):
            raise ValueError('Protected state changed before commit; preserve backup')
        result.update(policy_before_sha256=expected['policy_sha256'],
                      policy_after_sha256=sha256(after).hexdigest(), no_active_attempt=True,
                      other_policy_fields_preserved=True, status='prepared-not-installed')
        durable_bytes(backup / 'prepared.json', (json.dumps(result, sort_keys=True) + '\n').encode())
        os.replace(pending, POLICY)
        sync_directory(POLICY.parent)
        sync_directory(backup)
        if ci.protected(POLICY).read_bytes() != after or ci.read_policy() != json.loads(after):
            raise ValueError('Ambiguous enrollment; preserve evidence, no retry or restore')
        result['status'] = 'enrolled-independent-readback-required'
        durable_bytes(backup / 'receipt.json', (json.dumps(result, sort_keys=True) + '\n').encode())
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lane', required=True, type=Path)
    parser.add_argument('--expectations', required=True, type=Path,
                        help='Supplied exact request/host/policy/helper pins, not approval itself')
    parser.add_argument('--expectations-sha256', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    print(json.dumps(enroll(args.lane.read_bytes(), args.expectations.read_bytes(),
                           args.expectations_sha256, execute=args.execute), indent=2))


if __name__ == '__main__':
    main()
