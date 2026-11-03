"""One-time local-root adoption bridge, never an SSH operation or CI bypass.

Default prints a plan only. Execution additionally requires a root-enrolled exact
permit, fresh native keyless provenance and separately approved one-time settled
maintenance. The permit is consumed before effects; interruption is not retried.
"""

import argparse
import fcntl
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import sys

if __package__:
    from deploy import release_ci_access as ci
else:
    # -I ignores CWD/PYTHONPATH. Check every imported file before adding this
    # fixed installed directory; no client-selected code enters this root path.
    directory = Path(__file__).absolute().parent
    for path in (Path(__file__).absolute(), directory / 'release_ci_access.py'):
        for entry in (path, *path.parents):
            info = entry.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise SystemExit('Unprotected bootstrap installation')
    sys.path.insert(0, str(directory))
    import release_ci_access as ci

PERMIT = Path('/etc/kat-release/bootstrap.json')


def execute(package, *, permit_path=PERMIT):
    if os.geteuid() != 0 or os.environ.get('SSH_ORIGINAL_COMMAND'):
        raise ValueError('Bootstrap is local-root adoption only, never transport authority')
    ci.protected(__file__)
    access = ci.shared_access()
    manual, policy = access.read_policy(), ci.read_policy(enrollment=True)
    if policy['enabled'] is not False:
        raise ValueError('Bootstrap requires disabled routine CI transport')
    permit = json.loads(ci.protected(permit_path).read_text())
    if (set(permit) != {'plan_sha256', 'old_image', 'old_source_sha256', 'settled_existing_work'}
            or permit['settled_existing_work'] is not True):
        raise ValueError('Exact one-time maintenance permit required')
    manifest_path = ci.protected(package / 'manifest.json')
    manifest = json.loads(manifest_path.read_text())
    ci.validate_manifest(manifest)
    plan = manifest['plan']
    access.validate_plan(plan, manual)
    if (manifest_path.read_bytes() != ci.canonical(manifest)
            or plan['plan_sha256'] != permit['plan_sha256'] or plan['schema_version'] != 23):
        raise ValueError('Bootstrap plan/same-schema source differs')
    bundle = ci.protected(package / 'bundle.json').read_bytes()
    if not 0 < len(bundle) <= ci.BUNDLE_LIMIT:
        raise ValueError('Bootstrap bundle bound exceeded')
    for name, size, digest in (
            ('kat-production-amd64.tar', plan['archive_bytes'], plan['artifact']['image_archive_sha256']),
            ('kat-public-source.tar', plan['source_bytes'], plan['artifact']['source_offer_sha256'])):
        path = ci.protected(package / name)
        if path.stat().st_size != size:
            raise ValueError('Bootstrap artifact size changed')
        from hashlib import file_digest
        with path.open('rb') as stream:
            if file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('Bootstrap artifact changed')
    witness = ci.verify(manifest, bundle, policy) | {'mode': 'bootstrap', 'transitions': []}
    root = Path(manual['target']['stage_root'])
    fd = os.open(root / 'release.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (root / 'active-attempt').exists() or (root / plan['attempt']).exists():
            raise ValueError('Existing release attempt; no bootstrap replay')
        if (root / 'ci-run-number').exists() and witness['run_number'] <= int((root / 'ci-run-number').read_text()):
            raise ValueError('Historical CI run cannot bootstrap')
        # Hard-link consumption is exclusive and durable; never replace a used permit.
        used = permit_path.with_name('bootstrap.used.json')
        os.link(permit_path, used, follow_symlinks=False)
        phase = access.phase_module()
        phase.sync_directory(used.parent)
        permit_path.unlink()
        phase.sync_directory(used.parent)
        temporary = root / ('ci-run-' + plan['attempt'])
        phase.durable_text(temporary, str(witness['run_number']) + '\n')
        os.replace(temporary, root / 'ci-run-number')
        phase.sync_directory(root)
        stage = root / plan['attempt']
        target = manual['target'] | {'stage': str(stage)}
        phase.REQUEST = {'target': target, 'plan': plan, 'ci_admission': witness,
                         'bootstrap_permit': permit}

        def dispatch(action, stream=None, size=None):
            request = {'action': action}
            if size is not None:
                request['bytes'] = size
            result = access.dispatch_locked(request, manual, stream or BytesIO(), action, plan,
                                           ci_admission=witness, bootstrap_permit=permit)
            if result['status'] != 'ok':
                raise ValueError('Bootstrap phase halted')
            return result

        try:
            dispatch('stage')
            phase.durable_text(stage / 'ci-admission.json', json.dumps(witness | {
                'manifest_sha256': sha256(ci.canonical(manifest)).hexdigest(),
                'policy_sha256': sha256(ci.canonical(policy)).hexdigest()}))
            for action, name, size in (('upload', 'kat-production-amd64.tar', plan['archive_bytes']),
                                       ('upload_source', 'kat-public-source.tar', plan['source_bytes'])):
                with (package / name).open('rb') as stream:
                    dispatch(action, stream, size)
            for action in ('compose', 'preflight', 'quiesce_and_snapshot', 'promote_release', 'activate_app_only'):
                dispatch(action)
            observed = dispatch('verify_serving_path')
            path = ci.protected(Path(__file__).with_name('release_pipeline.py'))
            if ci.file_hash(path) != plan['runner_sha256']:
                raise ValueError('Public verifier changed')
            spec = ci.spec_from_file_location('_kat_bootstrap_controller', path)
            controller = ci.module_from_spec(spec)
            spec.loader.exec_module(controller)
            controller.verify_public(target['origin'], observed['assets'])
            dispatch('complete')
            phase.durable_text(stage / 'bootstrap-completed.json', json.dumps({'status': 'verified', 'plan_sha256': plan['plan_sha256']}))
        except (Exception, KeyboardInterrupt):
            if stage.exists():
                phase.quarantine(target, plan)
            raise
    return {'status': 'verified bootstrap; not unattended release proof', 'plan_sha256': plan['plan_sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print('Plan only: root-enrolled one-time exact permit + fresh CI provenance + settled old owner; shared native phases; no SSH bootstrap route.')
    elif not args.package:
        parser.error('Exact root-owned attested package required')
    else:
        try:
            print(json.dumps(execute(args.package)))
        except (Exception, KeyboardInterrupt):
            print('Bootstrap refused/halted; retain permit/attempt evidence, never replay.', file=sys.stderr)
            raise SystemExit(1)
