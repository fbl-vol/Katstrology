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
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
HEX = re.compile(r'[0-9a-f]{64}\Z')
GIT_ID = re.compile(r'[0-9a-f]{40}\Z')
IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
ALIAS = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,79}\Z')
PROJECT = re.compile(r'[a-z][a-z0-9_-]{1,62}\Z')


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
    with tarfile.open(offer) as source:
        members = source.getmembers()
        if any(m.issym() or m.islnk() or Path(m.name).is_absolute() or '..' in Path(m.name).parts for m in members):
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
    if set(target) != {'ssh_alias', 'project', 'stage', 'password_file', 'ephemeris_dir', 'snapshot_dir', 'origin', 'loopback_port'}:
        raise ValueError('Target fields differ from release contract')
    if not ALIAS.fullmatch(target['ssh_alias']) or not PROJECT.fullmatch(target['project']):
        raise ValueError('SSH alias/project invalid')
    for field in ('stage', 'password_file', 'ephemeris_dir', 'snapshot_dir'):
        value = target[field]
        if not isinstance(value, str) or not Path(value).is_absolute() or '..' in Path(value).parts or not value.startswith('/srv/'):
            raise ValueError('Target path must be an absolute /srv path without traversal')
    if target['stage'] == target['snapshot_dir'] or target['stage'].startswith(target['snapshot_dir'] + '/') or target['snapshot_dir'].startswith(target['stage'] + '/'):
        raise ValueError('Snapshot must be independent of release staging')
    if not re.fullmatch(r'https://[a-z0-9.-]+', target['origin']) or target['loopback_port'] not in range(1024, 65536):
        raise ValueError('Invalid public origin or loopback port')
    return target


def plan(receipt, target, schema, compose):
    # No credential paths in the portable approval/receipt; target file remains private.
    scope = {'project': target['project'],
             'origin': target['origin'], 'loopback_port': target['loopback_port'],
             'target_sha256': sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()}
    identity = {key: receipt[key] for key in ('commit', 'tree', 'image_id', 'config_digest',
                'image_archive_sha256', 'source_offer_sha256')}
    content = {'contract': 1, 'target': scope, 'artifact': identity, 'schema_version': schema,
               'compose_sha256': sha256(compose).hexdigest(),
               'runner_sha256': digest(Path(__file__)),
               'remote_runner_sha256': digest(Path(__file__).with_name('release_remote.py')),
               'steps': ['stage', 'preflight', 'quiesce_and_snapshot', 'activate_app_only', 'verify_serving_path'],
               'on_ambiguity': 'halt_without_retry_or_database_restore'}
    content['plan_sha256'] = sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return content


def remote(alias, request):
    # Run only fixed, versioned remote code. The request has no secret values.
    source = (Path(__file__).with_name('release_remote.py')).read_text()
    program = 'REQUEST = ' + repr(request) + '\n' + source
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                             '-o', 'ConnectTimeout=10', alias, 'python3', '-'], input=program, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=180)
    if result.returncode:
        raise RuntimeError('Remote phase failed; inspect server-side state before any new attempt')
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
    for headers in ({'Host': 'wrong.invalid'}, {'Origin': 'https://wrong.invalid'},
                    {'Sec-Fetch-Site': 'cross-site'}):
        if get(origin + '/api/session', headers)[0] != 403:
            raise ValueError('Public Host/Origin/fetch-site guard differs')
    for name, expected in assets.items():
        path = '/' if name == 'index.html' else '/' + name
        status, _, body = get(origin + path)
        if status != 200 or sha256(body).hexdigest() != expected:
            raise ValueError('Public HTTPS asset differs from packaged image')


def execute(receipt, archive, compose, target, planned, approval, receipt_path):
    if approval != {'approved_action': 'release', 'plan_sha256': planned['plan_sha256']}:
        raise ValueError('Exact-target release approval missing or mismatched')
    if receipt_path.exists():
        raise ValueError('Receipt already exists; never replay an ambiguous attempt')
    # Durable guard precedes the first network action. Never overwrite on retry.
    with receipt_path.open('x') as output:
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
    try:
        remote(alias, {'action': 'stage', 'target': target, 'plan': planned})
        stage = target['stage']
        for source, name in ((archive, 'image.tar'),):
            subprocess.run(['scp', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                            str(source), f'{alias}:{stage}/{name}'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
        # Compose is from the verified immutable source offer, not this mutable checkout.
        remote(alias, {'action': 'compose', 'target': target, 'plan': planned, 'compose': compose.decode()})
        for phase in ('preflight', 'quiesce_and_snapshot', 'activate_app_only', 'verify_serving_path'):
            observed = remote(alias, {'action': phase, 'target': target, 'plan': planned})
            if observed['status'] == 'recovered_old_app':
                receipt_path.write_text(json.dumps({'plan_sha256': planned['plan_sha256'],
                    'status': 'recovered_old_app; release not activated'}) + '\n')
                raise RuntimeError('Original app restarted before snapshot; release halted')
            if observed['status'] != 'ok':
                raise RuntimeError('Unexpected remote phase')
        assets = observed['assets']
        receipt_path.write_text(json.dumps({'plan_sha256': planned['plan_sha256'],
            'artifact': planned['artifact'], 'target': planned['target'],
            'status': 'app_activated_local_verified_public_incomplete',
            'packaged_asset_sha256': assets}, indent=2) + '\n')
        verify_public(target['origin'], assets)
    except (Exception, KeyboardInterrupt):
        raise RuntimeError('Release halted; inspect receipt and serving state, do not retry deployment or restore database.') from None
    # Public check completed without login or provider calls. No paths/secrets in receipt.
    receipt_path.write_text(json.dumps({'plan_sha256': planned['plan_sha256'],
                                        'artifact': planned['artifact'], 'target': planned['target'],
                                        'status': 'verified', 'snapshot': 'quiesced; independently retained',
                                        'packaged_asset_sha256': assets,
                                        'serving_path': 'loopback and public TLS assets, redirects and authority verified'}, indent=2) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-receipt', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--result', type=Path)
    args = parser.parse_args(argv)
    receipt, archive, compose, schema = artifact(args.artifact_receipt)
    target = target_config(args.target)
    planned = plan(receipt, target, schema, compose)
    if not args.execute:
        if args.approval or args.result:
            parser.error('Approval and result apply only to --execute')
        print(json.dumps(planned, indent=2))
        return
    if not args.approval or not args.result:
        parser.error('--execute requires --approval and --result')
    execute(receipt, archive, compose, target, planned, json.loads(args.approval.read_text()), args.result)
    print(json.dumps({'status': 'verified', 'plan_sha256': planned['plan_sha256']}))


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f'Release refused or halted ({type(error).__name__}); never retry blindly.', file=sys.stderr)
        raise SystemExit(1)
