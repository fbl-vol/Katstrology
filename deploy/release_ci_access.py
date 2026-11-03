"""Keyless CI authorization adapter for the existing constrained release engine.

Install only with separately scoped adoption. No shell, client-selected paths,
verifier arguments or signing key. A verified admission is frozen before drain;
subsequent phases use its root-owned witness, never a new network authorization.
"""

import fcntl
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import time
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener, HTTPRedirectHandler

POLICY = Path('/etc/kat-release/ci-policy.json')
BUNDLE_LIMIT = 256 * 1024
REPOSITORY = 'fbl-vol/Katstrology'
REPOSITORY_ID = '1437147047'


def protected(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('Protected absolute path required')
    for parent in (path, *path.parents):
        info = parent.lstat()
        if (stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                or (parent == path and not stat.S_ISREG(info.st_mode))):
            raise ValueError('Unprotected CI trust material')
    return path


def shared_access():
    path = protected(Path(__file__).with_name('release_access.py'))
    spec = spec_from_file_location('_kat_manual_access', path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read_policy(path=POLICY):
    policy = json.loads(protected(path).read_text())
    fields = {'contract', 'enabled', 'repository', 'repository_id', 'signer_workflow',
              'signer_sha', 'caller_workflow', 'qualification_job', 'verifier',
              'verifier_sha256', 'trusted_root', 'trusted_root_sha256', 'helper_sha256',
              'max_age_seconds', 'transitions'}
    if (set(policy) != fields or policy['contract'] != 1 or policy['enabled'] is not True
            or policy['repository'] != REPOSITORY or policy['repository_id'] != REPOSITORY_ID
            or not re.fullmatch(r'[a-f0-9]{40}', policy['signer_sha'])
            or not 60 <= policy['max_age_seconds'] <= 86400):
        raise ValueError('CI trust disabled or invalid')
    for key in ('signer_workflow', 'caller_workflow'):
        if not re.fullmatch(r'\.github/workflows/[a-z0-9_-]+\.yml', policy[key]):
            raise ValueError('Fixed workflow identity required')
    for key in ('verifier', 'trusted_root'):
        if file_hash(protected(policy[key])) != policy[key + '_sha256']:
            raise ValueError('CI verifier/trust root changed')
    if file_hash(protected(__file__)) != policy['helper_sha256']:
        raise ValueError('CI helper changed')
    if not isinstance(policy['transitions'], list) or len(policy['transitions']) > 8:
        raise ValueError('Transition allowlist exceeds bound')
    for transition in policy['transitions']:
        if (set(transition) != {'from', 'to', 'migrations', 'added_tables', 'added_columns'}
                or type(transition['from']) is not int or type(transition['to']) is not int
                or not 0 < transition['from'] < transition['to']
                or not isinstance(transition['migrations'], dict)
                or not transition['migrations']
                or any(not re.fullmatch(r'[0-9]+_[a-z0-9_]+\.sql', name)
                       or not re.fullmatch(r'[a-f0-9]{64}', digest)
                       for name, digest in transition['migrations'].items())):
            raise ValueError('Invalid explicit migration lane')
    return policy


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def github(path):
    # Only fixed paths assembled from verified numeric IDs reach this method.
    opener = build_opener(ProxyHandler({}), HTTPSHandler(), NoRedirect())
    request = Request('https://api.github.com/repos/' + REPOSITORY + path,
                      headers={'Accept': 'application/vnd.github+json',
                               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'kat-release-admission'})
    with opener.open(request, timeout=10) as response:
        content = response.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError('GitHub admission response exceeds bound')
    return json.loads(content)


def verified_identity(results, manifest, policy, now):
    plan = manifest['plan']
    source = plan['artifact']['commit']
    run_id, attempt = manifest['run_id'], manifest['run_attempt']
    expected = {
        'issuer': 'https://token.actions.githubusercontent.com',
        'sourceRepositoryURI': 'https://github.com/' + REPOSITORY,
        'sourceRepositoryIdentifier': REPOSITORY_ID,
        'sourceRepositoryDigest': source, 'sourceRepositoryRef': 'refs/heads/main',
        'runnerEnvironment': 'github-hosted', 'buildTrigger': 'push',
        'buildSignerURI': f"https://github.com/{REPOSITORY}/{policy['signer_workflow']}@{policy['signer_sha']}",
        'buildSignerDigest': policy['signer_sha'],
        'buildConfigURI': f"https://github.com/{REPOSITORY}/{policy['caller_workflow']}@refs/heads/main",
        'buildConfigDigest': source,
        'runInvocationURI': f'https://github.com/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}',
    }
    from datetime import datetime
    for result in results:
        verified = result['verificationResult']
        cert = verified['signature']['certificate']
        if any(cert[key] != value for key, value in expected.items()):
            continue
        subjects = verified['statement']['subject']
        if (len(subjects) != 1 or subjects[0]['digest'] != {'sha256': sha256(canonical(manifest)).hexdigest()}):
            continue
        timestamps = [datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00')).timestamp()
                      for item in verified['verifiedTimestamps']]
        if not timestamps or any(not 0 <= now - stamp <= policy['max_age_seconds'] for stamp in timestamps):
            continue
        return expected
    raise ValueError('No exact fresh verified CI identity/subject')


def verify(manifest, bundle, policy):
    source = manifest['plan']['artifact']['commit']
    identity = f"https://github.com/{REPOSITORY}/{policy['signer_workflow']}@{policy['signer_sha']}"
    with TemporaryDirectory(prefix='kat-ci-verify-') as directory:
        root = Path(directory)
        subject = root / 'manifest.json'
        subject.write_bytes(canonical(manifest))
        bundle_path = root / 'bundle.json'
        bundle_path.write_bytes(bundle)
        with (root / 'verified.json').open('wb') as output:
            result = subprocess.run([policy['verifier'], 'attestation', 'verify', str(subject),
                '--bundle', str(bundle_path), '--repo', REPOSITORY,
                '--cert-identity', identity, '--signer-digest', policy['signer_sha'],
                '--source-ref', 'refs/heads/main', '--source-digest', source,
                '--cert-oidc-issuer', 'https://token.actions.githubusercontent.com',
                '--deny-self-hosted-runners', '--custom-trusted-root', policy['trusted_root'],
                '--format', 'json'], stdout=output, stderr=subprocess.DEVNULL, timeout=45,
                env={'PATH': '/usr/bin:/bin', 'HOME': directory, 'LANG': 'C', 'GH_PROMPT_DISABLED': '1'},
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024)))
        if result.returncode or (root / 'verified.json').stat().st_size > 1024 * 1024:
            raise ValueError('Native attestation verification refused')
        identity = verified_identity(json.loads((root / 'verified.json').read_text()), manifest, policy, time())
    return eligible_run(manifest, policy, identity)


def eligible_run(manifest, policy, identity):
    source = manifest['plan']['artifact']['commit']
    repo = github('')
    branch = github('/branches/main')
    run = github(f"/actions/runs/{manifest['run_id']}/attempts/1")
    jobs = github(f"/actions/runs/{manifest['run_id']}/attempts/1/jobs?per_page=100")
    if (str(repo['id']) != REPOSITORY_ID or repo['full_name'] != REPOSITORY
            or repo['default_branch'] != 'main' or repo['archived']
            or not branch['protected'] or branch['commit']['sha'] != source
            or str(run['repository']['id']) != REPOSITORY_ID
            or run['head_sha'] != source or run['head_branch'] != 'main'
            or run['event'] != 'push' or run['run_attempt'] != 1
            or run['path'] != policy['caller_workflow']
            or run['status'] not in ('in_progress', 'completed')
            or (run['status'] == 'completed' and run['conclusion'] != 'success')
            or jobs['total_count'] > 100):
        raise ValueError('Current repository/source/run eligibility differs')
    qualified = [job for job in jobs['jobs'] if job['name'] == policy['qualification_job']]
    if len(qualified) != 1 or qualified[0]['status'] != 'completed' or qualified[0]['conclusion'] != 'success':
        raise ValueError('Mandatory qualification did not succeed')
    return {'identity': identity, 'run_number': run['run_number'], 'admitted_at': time()}


def validate_manifest(manifest):
    if (not isinstance(manifest, dict) or set(manifest) != {'contract', 'plan', 'run_id', 'run_attempt'}
            or manifest['contract'] != 1 or manifest['run_attempt'] != 1
            or type(manifest['run_id']) is not int or manifest['run_id'] < 1):
        raise ValueError('Invalid CI manifest; reruns are not fresh releases')


def dispatch(request, policy, manual, access, input_stream):
    if set(request) not in ({'action', 'manifest'}, {'action', 'manifest', 'bytes'}):
        raise ValueError('Unsupported CI request')
    manifest, action = request['manifest'], request['action']
    validate_manifest(manifest)
    plan = manifest['plan']
    schemas = {manual['schema_version']} | {item['to'] for item in policy.get('transitions', [])}
    if plan['schema_version'] not in schemas:
        raise ValueError('Candidate schema has no installed compatibility lane')
    access.validate_plan(plan, manual | {'schema_version': plan['schema_version']})
    if action not in access.ACTIONS:
        raise ValueError('Unsupported CI phase')
    if action in ('stage', 'upload', 'upload_source'):
        expected = (None if action == 'stage' else plan['archive_bytes' if action == 'upload' else 'source_bytes'])
        size = request.get('bytes')
        if type(size) is not int or (not 0 < size <= BUNDLE_LIMIT if action == 'stage' else size != expected):
            raise ValueError('CI payload bound differs')
    elif 'bytes' in request:
        raise ValueError('Unexpected CI body')
    root = Path(manual['target']['stage_root'])
    stage = root / plan['attempt']
    digest = sha256(canonical(manifest)).hexdigest()
    policy_digest = sha256(canonical(policy)).hexdigest()
    fd = os.open(root / 'release.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if action == 'stage':
            bundle = input_stream.read(request['bytes'] + 1)
            if len(bundle) != request['bytes']:
                raise ValueError('Truncated/trailing CI bundle')
            if stage.exists() or (root / 'active-attempt').exists():
                raise ValueError('Existing attempt; no replay')
            witness = verify(manifest, bundle, policy) | {'transitions': policy.get('transitions', [])}
            highwater = root / 'ci-run-number'
            if highwater.exists() and witness['run_number'] <= int(highwater.read_text()):
                raise ValueError('Duplicate/out-of-order CI run')
            phase = access.phase_module()
            temporary = root / ('ci-run-' + plan['attempt'])
            phase.durable_text(temporary, str(witness['run_number']) + '\n')
            os.replace(temporary, highwater)
            phase.sync_directory(root)
            from io import BytesIO
            result = access.dispatch_locked(request, manual, BytesIO(), action, plan)
            phase.durable_text(stage / 'ci-admission.json', json.dumps(witness | {
                'manifest_sha256': digest, 'policy_sha256': policy_digest}))
            return result
        witness = json.loads(protected(stage / 'ci-admission.json').read_text())
        if witness['manifest_sha256'] != digest or witness['policy_sha256'] != policy_digest:
            raise ValueError('CI admission witness differs')
        # The common target lock, active-attempt and durable phases fence both modes.
        if action == 'complete':
            # The transport holder cannot skip public verification and assert success.
            path = protected(Path(__file__).with_name('release_pipeline.py'))
            if file_hash(path) != plan['runner_sha256']:
                raise ValueError('Protected public verifier changed')
            spec = spec_from_file_location('_kat_public_verification', path)
            controller = module_from_spec(spec)
            spec.loader.exec_module(controller)
            controller.verify_public(manual['target']['origin'],
                                     json.loads(protected(stage / 'assets.json').read_text()))
        return access.dispatch_locked(request, manual, input_stream, action, plan, ci_admission=witness)


def main():
    if os.environ.get('SSH_ORIGINAL_COMMAND') != 'kat-release-ci-v1':
        raise ValueError('Only fixed CI gateway command permitted')
    os.umask(0o077)
    protected(__file__)
    access = shared_access()
    policy, manual = read_policy(), access.read_policy()
    line = sys.stdin.buffer.readline(access.REQUEST_LIMIT + 1)
    if len(line) > access.REQUEST_LIMIT or not line.endswith(b'\n'):
        raise ValueError('CI request header exceeds bound')
    request = json.loads(line)
    if request.get('action') == 'stage':
        signal.alarm(100)  # Includes bundle framing, verifier and all eligibility reads.
    result = dispatch(request, policy, manual, access, sys.stdin.buffer)
    signal.alarm(0)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt):
        print('Restricted CI release refused; inspect protected attempt, never replay.', file=sys.stderr)
        raise SystemExit(1)
