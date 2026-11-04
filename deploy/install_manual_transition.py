"""Pinned manual-helper installation. Default: describe only, no root reads/writes.

Executing requires a separate root-install instruction. This is not a release
entry point: no app stop, SQL, key, transport, CI policy or service action exists.
Run the prepared bundle with python3 -I; pin both installer and manifest externally.
"""

import argparse
import fcntl
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import stat

POLICY = Path('/etc/kat-release/policy.json')
HELPERS = {'release_access.py', 'release_remote.py', 'release_pipeline.py'}
OLD_CONTROLLER = '794ac225f69302b5b74d3e0a4910fb1ab5a2183184c56122fabccc8fb66fb84c'


def protected(path, *, directory=False):
    if not path.is_absolute():
        raise ValueError('Absolute protected destination required')
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Root-protected destination required')
        if item == path and not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise ValueError('Protected destination type differs')
    return path


def sync(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def retain(path, body, mode=0o600):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    sync(path.parent)


def install(bundle, manifest_hash, directory, *, execute=False):
    manifest_body = (bundle / 'install-manifest.json').read_bytes()
    if sha256(manifest_body).hexdigest() != manifest_hash:
        raise ValueError('Installer manifest pin differs')
    manifest = json.loads(manifest_body)
    if (manifest['contract'] != 1 or set(manifest['new_helpers']) != HELPERS
            or set(manifest['expected_old_helpers']) != HELPERS - {'release_pipeline.py'}
            or (manifest['manual_transition_lane']['from'], manifest['manual_transition_lane']['to']) != (23, 24)):
        raise ValueError('Installer exceeds bounded manual transition scope')
    helpers = {name: (bundle / name).read_bytes() for name in HELPERS}
    if any(sha256(body).hexdigest() != manifest['new_helpers'][name] for name, body in helpers.items()):
        raise ValueError('Prepared helper pin differs')
    if not execute:
        return {'status': 'plan-only', 'manifest_sha256': manifest_hash, 'helper_directory': str(directory),
                'policy': str(POLICY), 'scope': manifest['writes'], 'root_access': False}
    if os.geteuid() != 0:
        raise ValueError('Explicit root installation required')
    protected(directory, directory=True)
    policy_body = protected(POLICY).read_bytes()
    if sha256(policy_body).hexdigest() != manifest['expected_policy_sha256']:
        raise ValueError('Installed policy changed; do not reuse this handoff')
    policy = json.loads(policy_body)
    if policy['contract'] != 4 or policy['schema_version'] != 23 or policy.get('manual_transitions'):
        raise ValueError('Existing baseline/allowlist differs')
    if sha256(protected(Path(policy['compose_file'])).read_bytes()).hexdigest() != manifest['compose_sha256']:
        raise ValueError('Installed Compose differs; no replacement is authorized')
    stage_root = protected(Path(policy['target']['stage_root']), directory=True)
    lock_path = stage_root / 'release.lock'
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'r+') as lock:
        protected(lock_path)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (stage_root / 'active-attempt').exists() or (stage_root / 'active-attempt').is_symlink():
            raise ValueError('Existing release attempt; no installation')
        if protected(POLICY).read_bytes() != policy_body:
            raise ValueError('Policy changed while acquiring release lock')
        originals = {}
        for name, digest in manifest['expected_old_helpers'].items():
            body = protected(directory / name).read_bytes()
            if sha256(body).hexdigest() != digest:
                raise ValueError('Installed helper changed; no retry or overwrite')
            originals[name] = body
        controller = directory / 'release_pipeline.py'
        if controller.exists() or controller.is_symlink():
            body = protected(controller).read_bytes()
            if sha256(body).hexdigest() != OLD_CONTROLLER:
                raise ValueError('Unexpected existing protected controller')
            originals[controller.name] = body
        backup = directory / ('manual-transition-before-' + manifest_hash[:16])
        backup.mkdir(mode=0o700)  # Exclusive: any uncertain installation is stop-only.
        sync(directory)
        for name, body in originals.items():
            retain(backup / name, body)
        retain(backup / 'policy.json', policy_body)
        retain(backup / 'install-manifest.json', manifest_body)
        policy_after = policy | {'manual_transitions': [manifest['manual_transition_lane']]}
        policy_after_body = (json.dumps(policy_after, indent=2, sort_keys=True) + '\n').encode()
        replacements = [(directory / name, helpers[name]) for name in
                        ('release_remote.py', 'release_pipeline.py', 'release_access.py')]
        replacements.append((POLICY, policy_after_body))
        for destination, body in replacements:
            temporary = destination.with_name(destination.name + '.manual-' + manifest_hash[:16] + '.next')
            retain(temporary, body, 0o600 if destination == POLICY else 0o644)
            os.replace(temporary, destination)
            sync(destination.parent)
        spec = spec_from_file_location('_installed_manual_access', directory / 'release_access.py')
        helper = module_from_spec(spec)
        spec.loader.exec_module(helper)
        if helper.read_policy(POLICY) != policy_after:
            raise ValueError('Installed policy verification failed; preserve partial evidence, do not retry')
        if any(sha256(protected(directory / name).read_bytes()).hexdigest() != digest
               for name, digest in manifest['new_helpers'].items()):
            raise ValueError('Installed helpers changed during verification')
        result = {'status': 'installed-not-released', 'manifest_sha256': manifest_hash,
                  'policy_sha256': sha256(policy_after_body).hexdigest(), 'retained_before': str(backup),
                  'schema_baseline': 23, 'target_signer_and_keys': 'unchanged', 'app_or_database_actions': False}
        retain(backup / 'INSTALLED.json', (json.dumps(result, indent=2) + '\n').encode())
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--helper-directory', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(Path(__file__).resolve().parent, args.manifest_sha256,
                             args.helper_directory, execute=args.execute)))
