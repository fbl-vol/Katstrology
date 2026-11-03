"""Plan an immutable app-only release; execute only against an exact approved plan.

No network or server access in plan mode. The operator supplies a protected target
file (see README); neither that file nor the approval is a source artifact.
"""

import argparse
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from tempfile import TemporaryFile
from time import monotonic
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
HEX = re.compile(r'[0-9a-f]{64}\Z')
GIT_ID = re.compile(r'[0-9a-f]{40}\Z')
IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
ALIAS = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,79}\Z')
PROJECT = re.compile(r'[a-z][a-z0-9_-]{1,62}\Z')
ATTEMPT = re.compile(r'[0-9a-f]{32}\Z')
UPLOAD_TIMEOUT = 600
PHASE_TIMEOUT = 180


def digest(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def artifact(receipt_path):
    receipt = json.loads(receipt_path.read_text())
    for key in ('commit', 'tree'):
        if not GIT_ID.fullmatch(receipt[key]):
            raise ValueError('Invalid source identity')
    for key in ('image_archive_sha256', 'source_offer_sha256'):
        if not HEX.fullmatch(receipt[key]):
            raise ValueError('Invalid artifact identity')
    if not IMAGE.fullmatch(receipt['image_id']) or not IMAGE.fullmatch(receipt['config_digest']):
        raise ValueError('Invalid image identity')
    if receipt['architecture'] != 'linux/amd64':
        raise ValueError('Unsupported artifact architecture')
    archive, offer = Path(receipt['image_archive']), Path(receipt['source_offer'])
    if digest(archive) != receipt['image_archive_sha256'] or digest(offer) != receipt['source_offer_sha256']:
        raise ValueError('Artifact hash mismatch')
    with tarfile.open(archive) as image:
        config_name = 'blobs/sha256/' + receipt['config_digest'][7:]
        config_bytes = image.extractfile(config_name).read()
        if sha256(config_bytes).hexdigest() != receipt['config_digest'][7:]:
            raise ValueError('Image config digest mismatch')
        config = json.loads(config_bytes)
        if (config['architecture'], config['os']) != ('amd64', 'linux') or config['config']['Labels'].get('org.opencontainers.image.revision') != receipt['commit']:
            raise ValueError('Image revision/platform mismatch')
        index = json.load(image.extractfile('index.json'))
        if not any(item.get('digest') == receipt['image_id'] for item in index['manifests']):
            raise ValueError('Image index mismatch')
        image_index_bytes = image.extractfile('blobs/sha256/' + receipt['image_id'][7:]).read()
        if sha256(image_index_bytes).hexdigest() != receipt['image_id'][7:]:
            raise ValueError('Image index digest mismatch')
        image_index = json.loads(image_index_bytes)
        platform = next((entry for entry in image_index['manifests'] if entry.get('platform') == {
            'os': 'linux', 'architecture': 'amd64'}), None)
        if platform is None:
            raise ValueError('No amd64 application manifest')
        manifest_digest = platform['digest']
        manifest_bytes = image.extractfile('blobs/sha256/' + manifest_digest[7:]).read()
        if sha256(manifest_bytes).hexdigest() != manifest_digest[7:] or json.loads(manifest_bytes)['config']['digest'] != receipt['config_digest']:
            raise ValueError('Image manifest/config mismatch')
    if not 0 < offer.stat().st_size <= 128 * 1024**2:
        raise ValueError('Source archive size exceeds release bound')
    with tarfile.open(offer, mode='r:') as source:
        members = source.getmembers()
        if (len(members) > 10000 or sum(m.size for m in members) > 128 * 1024**2
                or len({m.name for m in members}) != len(members)
                or any(not (m.isfile() or m.isdir()) or Path(m.name).is_absolute()
                       or '..' in Path(m.name).parts for m in members)):
            raise ValueError('Unsafe source offer')
        tree = subprocess.check_output(['git', 'rev-parse', receipt['commit'] + '^{tree}'],
                                       cwd=ROOT, text=True).strip()
        if tree != receipt['tree']:
            raise ValueError('Source commit/tree mismatch')
        for member in members:
            if member.isfile():
                committed = subprocess.check_output(['git', 'show', receipt['commit'] + ':' + member.name], cwd=ROOT)
                if source.extractfile(member).read() != committed:
                    raise ValueError('Source offer differs from committed tree')
        compose = source.extractfile('deploy/compose.yaml').read()
        migrations = sorted(int(Path(m.name).name.split('_', 1)[0]) for m in members
                            if re.fullmatch(r'm2/migrations/[0-9]+_[^/]+\.sql', m.name))
        if not migrations or migrations != list(range(1, max(migrations) + 1)):
            raise ValueError('Unrecognized migration set')
    return receipt, archive, compose, max(migrations)


def target_config(path):
    target = json.loads(path.read_text())
    if set(target) != {'ssh_alias', 'project', 'stage_root', 'password_file', 'ephemeris_dir', 'snapshot_dir', 'origin', 'loopback_port', 'db_image', 'release_env_file', 'source_offer_file'}:
        raise ValueError('Target fields differ from release contract')
    if not ALIAS.fullmatch(target['ssh_alias']) or not PROJECT.fullmatch(target['project']):
        raise ValueError('SSH alias/project invalid')
    for field in ('stage_root', 'password_file', 'ephemeris_dir', 'snapshot_dir', 'release_env_file', 'source_offer_file'):
        value = target[field]
        if not isinstance(value, str) or not Path(value).is_absolute() or '..' in Path(value).parts or not value.startswith('/srv/'):
            raise ValueError('Target path must be an absolute /srv path without traversal')
    if target['stage_root'] == target['snapshot_dir'] or target['stage_root'].startswith(target['snapshot_dir'] + '/') or target['snapshot_dir'].startswith(target['stage_root'] + '/'):
        raise ValueError('Snapshot must be independent of release staging')
    if not IMAGE.fullmatch(target['db_image']):
        raise ValueError('Installed DB image must be an immutable runtime config ID')
    if not re.fullmatch(r'https://[a-z0-9.-]+', target['origin']) or target['loopback_port'] not in range(1024, 65536):
        raise ValueError('Invalid public origin or loopback port')
    return target


def plan(receipt, target, schema, compose, attempt, archive_bytes, source_bytes):
    if not ATTEMPT.fullmatch(attempt):
        raise ValueError('Attempt must be a fresh 32-character lowercase hex ID')
    if not isinstance(archive_bytes, int) or isinstance(archive_bytes, bool) or not 0 < archive_bytes <= 2 * 1024**3:
        raise ValueError('Archive size exceeds release bound')
    if not isinstance(source_bytes, int) or isinstance(source_bytes, bool) or not 0 < source_bytes <= 128 * 1024**2:
        raise ValueError('Source archive size exceeds release bound')
    # No credential paths in the portable approval/receipt; target file remains private.
    scope = {'project': target['project'],
             'origin': target['origin'], 'loopback_port': target['loopback_port'],
             'target_sha256': sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()}
    identity = {key: receipt[key] for key in ('commit', 'tree', 'image_id', 'config_digest',
                'image_archive_sha256', 'source_offer_sha256')}
    content = {'contract': 4, 'attempt': attempt, 'archive_bytes': archive_bytes,
               'source_bytes': source_bytes,
               'target': scope, 'artifact': identity, 'schema_version': schema,
               'compose_sha256': sha256(compose).hexdigest(),
               'runner_sha256': digest(Path(__file__)),
               'remote_runner_sha256': digest(Path(__file__).with_name('release_remote.py')),
               'access_helper_sha256': digest(Path(__file__).with_name('release_access.py')),
               'steps': ['stage', 'upload', 'upload_source', 'compose', 'preflight', 'quiesce_and_snapshot',
                         'promote_release', 'activate_app_only', 'verify_serving_path', 'complete'],
               'on_ambiguity': 'halt_without_retry_or_database_restore'}
    content['plan_sha256'] = sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return content


def remote(alias, request, upload=None, *, ssh_config=None):
    """Only the fixed OpenSSH command; stdin is JSON followed by bounded archive bytes."""
    command = ['ssh', *(['-F', str(ssh_config)] if ssh_config is not None else []),
               '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=10', alias, 'kat-release-v1']
    header = json.dumps(request, separators=(',', ':')).encode() + b'\n'
    if len(header) > 16 * 1024:
        raise ValueError('Release request exceeds helper header bound')
    # Native tempfile stdin is unlinked/owned locally. Python never writes to a
    # network pipe before the child timeout starts, even when the peer stops reading.
    with TemporaryFile(mode='w+b') as framed:
        framed.write(header)
        if upload is not None:
            size = upload.stat().st_size
            if size != request.get('bytes') or not 0 < size <= 2 * 1024**3:
                raise ValueError('Archive framing length differs or exceeds bound')
            with upload.open('rb') as archive:
                while block := archive.read(1024 * 1024):
                    framed.write(block)
        framed.flush()
        framed.seek(0)
        try:
            result = subprocess.run(command, stdin=framed, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=UPLOAD_TIMEOUT if upload is not None else
                {'preflight': 720, 'quiesce_and_snapshot': 600, 'activate_app_only': 600,
                 'verify_serving_path': 900}.get(request['action'], PHASE_TIMEOUT))
        except subprocess.TimeoutExpired:
            raise RuntimeError('Restricted remote phase failed; timed out without retry') from None
        if result.returncode or len(result.stdout) > 16384:
            raise RuntimeError('Restricted remote phase failed; inspect protected stage before another attempt')
    return json.loads(result.stdout)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def verify_public(origin, assets, opener=None):
    """No proxy, redirected content, unverified TLS or session-bearing requests."""
    opener = opener or build_opener(ProxyHandler({}), NoRedirect())

    def get(url, headers=None):
        request = Request(url, headers=headers or {}, method='GET')
        try:
            response = opener.open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise ValueError('Public response exceeds bound')
            return response.status, response.headers, body

    status, headers, _ = get('http://' + origin.removeprefix('https://') + '/')
    if status not in (301, 308) or headers.get('Location') != origin + '/':
        raise ValueError('Public HTTP redirect differs from exact HTTPS origin')
    if get(origin + '/api/session')[0] != 401:
        raise ValueError('Public anonymous session boundary differs')
    if get(origin + '/api/session', {'Host': 'wrong.invalid'})[0] != 421:
        raise ValueError('Public edge wrong-Host denial differs')
    for headers in ({'Origin': 'https://wrong.invalid'}, {'Sec-Fetch-Site': 'cross-site'}):
        if get(origin + '/api/session', headers)[0] != 403:
            raise ValueError('Public Origin/fetch-site guard differs')
    for name, expected in assets.items():
        path = '/' if name == 'index.html' else '/' + name
        status, _, body = get(origin + path)
        if status != 200 or sha256(body).hexdigest() != expected:
            raise ValueError('Public HTTPS asset differs from packaged image')


def execute(receipt, archive, compose, target, planned, approval, signature, receipt_path, *, ssh_config=None):
    if approval != {'approved_action': 'release', 'attempt': planned['attempt'],
                    'plan_sha256': planned['plan_sha256']}:
        raise ValueError('Exact-target release approval missing or mismatched')
    if not signature.startswith('-----BEGIN SSH SIGNATURE-----\n') or len(signature) > 8192:
        raise ValueError('Signed per-release approval missing or exceeds bound')
    if receipt_path.exists():
        raise ValueError('Receipt already exists; never replay an ambiguous attempt')
    if archive.stat().st_size != planned['archive_bytes']:
        raise ValueError('Approved archive length changed')
    source = Path(receipt['source_offer'])
    if source.stat().st_size != planned['source_bytes']:
        raise ValueError('Approved source archive length changed')
    # Durable guard precedes the first network action. Never overwrite on retry.
    with open(receipt_path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        json.dump({'plan_sha256': planned['plan_sha256'], 'status': 'started; inspect before retry'}, output)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    directory = os.open(receipt_path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    alias = target['ssh_alias']
    signed = {'plan': planned, 'approval': approval, 'signature': signature}
    result = {'plan_sha256': planned['plan_sha256'], 'artifact': planned['artifact'],
              'target': planned['target'], 'status': 'started', 'timings': []}

    def record():
        # Never dump commands, target paths, environment or remote diagnostics.
        temporary = receipt_path.with_name(receipt_path.name + '.next')
        with open(temporary, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
            json.dump(result, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, receipt_path)
        descriptor = os.open(receipt_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def phase(name, *, upload=None):
        result['phase'] = name
        record()
        start = monotonic()
        status = 'failed'
        try:
            request = {'action': name, **signed}
            if upload is not None:
                request['bytes'] = upload.stat().st_size
            options = {'ssh_config': ssh_config} if ssh_config is not None else {}
            observed = remote(alias, request, upload=upload, **options)
            status = observed['status']
            if status != 'ok':
                result['remote'] = observed
                raise RuntimeError('Remote release halted')
            return observed
        finally:
            result['timings'].append({'phase': name, 'seconds': round(monotonic() - start, 3), 'status': status})
            record()

    try:
        phase('stage')
        phase('upload', upload=archive)
        phase('upload_source', upload=source)
        phase('compose')
        for name in ('preflight', 'quiesce_and_snapshot', 'promote_release', 'activate_app_only'):
            phase(name)
        observed = phase('verify_serving_path')
        result['packaged_asset_sha256'] = observed['assets']
        if 'readiness' in observed:
            result['readiness'] = observed['readiness']
        result['status'] = 'app_activated_local_verified_public_incomplete'
        result['phase'] = 'verify_public'
        record()
        start = monotonic()
        public_status = 'failed'
        try:
            verify_public(target['origin'], observed['assets'])
            public_status = 'ok'
        finally:
            result['timings'].append({'phase': 'verify_public', 'seconds': round(monotonic() - start, 3),
                                      'status': public_status})
        phase('complete')
    except (Exception, KeyboardInterrupt):
        failed_phase = result['phase']
        result['status'] = 'halted; serving state unknown'
        # A signed containment request is NOT a retry of upload/promotion/activation.
        try:
            result['containment'] = remote(alias, {'action': 'quarantine', **signed},
                **({'ssh_config': ssh_config} if ssh_config is not None else {}))
            result['status'] = 'halted; ' + result['containment']['serving']
        except (Exception, KeyboardInterrupt):
            result['containment'] = {'serving': 'unknown', 'status': 'unconfirmed'}
        result['failed_phase'] = failed_phase
        record()
        raise RuntimeError('Release halted; inspect receipt and serving state, do not retry deployment or restore database.') from None
    result['status'] = 'verified'
    result['snapshot'] = 'quiesced; independently retained'
    result['serving_path'] = 'loopback and public TLS assets, redirects and authority verified'
    record()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-receipt', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--attempt', required=True, help='fresh 32-character hex attempt ID; retain for execution')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--signature', type=Path)
    parser.add_argument('--result', type=Path)
    parser.add_argument('--prepare-dir', type=Path, help='create private plan and unsigned approval; no SSH or signing')
    parser.add_argument('--ssh-config', type=Path, help='existing dedicated OpenSSH client profile; execution only')
    args = parser.parse_args(argv)
    receipt, archive, compose, schema = artifact(args.artifact_receipt)
    target = target_config(args.target)
    planned = plan(receipt, target, schema, compose, args.attempt, archive.stat().st_size,
                   Path(receipt['source_offer']).stat().st_size)
    if args.prepare_dir:
        if args.execute or args.approval or args.signature or args.result or args.ssh_config:
            parser.error('--prepare-dir cannot execute, sign or consume an approval')
        args.prepare_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        approval = {'approved_action': 'release', 'attempt': planned['attempt'],
                    'plan_sha256': planned['plan_sha256']}
        for name, value in (('plan.json', planned), ('approval.json', approval)):
            path = args.prepare_dir / name
            with open(path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
                output.write(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
        print(json.dumps({'status': 'prepared; user signature required', 'plan_sha256': planned['plan_sha256'],
                          'contract': 4, 'schema_version': schema, 'server_access': False}))
        return
    if not args.execute:
        if args.approval or args.signature or args.result or args.ssh_config:
            parser.error('Approval and result apply only to --execute')
        print(json.dumps(planned, indent=2))
        return
    if not args.approval or not args.signature or not args.result:
        parser.error('--execute requires --approval, --signature and --result')
    execute(receipt, archive, compose, target, planned, json.loads(args.approval.read_text()),
            args.signature.read_text(), args.result, ssh_config=args.ssh_config)
    print(json.dumps({'status': 'verified', 'plan_sha256': planned['plan_sha256']}))


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f'Release refused or halted ({type(error).__name__}); never retry blindly.', file=sys.stderr)
        raise SystemExit(1)
