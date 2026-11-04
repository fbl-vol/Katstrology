"""Owned synthetic manual23→24 lifecycle qualification, never a server installer.

Real signed admission, controller, phase engine, Docker, PostgreSQL, migration and
backup/restore. Only root file ownership and public TLS transport are substituted
with explicitly owned local fixtures; no SSH, production host or private data.
"""

import argparse
from contextlib import ExitStack
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import traceback
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import patch

from deploy import release_access as access, release_pipeline as pipeline, release_remote as remote
from deploy.smoke_local import await_session, free_port

ROOT = pipeline.ROOT
LANE = {'from': 23, 'to': 24, 'migrations': {
    '024_account_tones.sql': '523775c5caa77b398d2f8804711f12029a7c810031f66ad4505003486feb8a71'},
    'added_tables': ['account_tones'], 'added_columns': {}}


class LocalEdge:
    """Exercise public-response checks locally; not evidence of real TLS/Caddy."""
    def __init__(self, port, origin):
        self.port, self.origin = port, origin
        self.opener = build_opener(ProxyHandler({}))

    def open(self, request, timeout):
        url = urlsplit(request.full_url)
        if request.full_url == self.origin.replace('https:', 'http:') + '/':
            response = BytesIO(b'')
            response.status, response.headers = 301, {'Location': self.origin + '/'}
            return response
        if url.scheme != 'https' or url.netloc != urlsplit(self.origin).netloc:
            raise ValueError('Native fixture refuses external destination')
        headers = dict(request.header_items())
        headers.setdefault('Host', url.netloc)
        local = Request(f'http://127.0.0.1:{self.port}' + url.path, headers=headers)
        try:
            response = self.opener.open(local, timeout=timeout)
        except HTTPError as error:
            response = error
        if headers['Host'] != url.netloc:
            # The app independently denies wrong Host with403; installed Caddy
            # denies it at the edge with421. Verify the native app denial before
            # representing that separate, explicitly synthetic edge behavior.
            with response:
                if response.status != 403:
                    raise AssertionError('Native app did not deny wrong Host')
            response = BytesIO(b'')
            response.status, response.headers = 421, {}
        return response


class NativeFixture:
    def __init__(self, root, old, candidate, compose_bytes, *, ambiguous):
        self.root, self.old, self.candidate = root, old, candidate
        self.ambiguous = ambiguous
        self.project = 'kat-manual-transition-' + secrets.token_hex(6)
        self.port = free_port()
        self.base_env = {'PATH': os.environ['PATH'], 'HOME': str(root), 'LANG': 'C.UTF-8',
                         'DOCKER_HOST': 'unix:///var/run/docker.sock'}
        driver = json.loads(self.command(['docker', 'info', '--format', '{{json .DriverStatus}}']))
        self.old_image = remote.native_image_identity(old, driver)
        self.new_image = remote.native_image_identity(candidate, driver)
        self.compose_path = root / 'compose.yaml'
        # Only the fixture's loopback port changes, not the packaged source.
        self.compose_path.write_bytes(compose_bytes.replace(b'127.0.0.1:28765:8765',
                                                           f'127.0.0.1:{self.port}:8765'.encode()))
        self.password = root / 'synthetic-password'
        self.password.write_text('synthetic-' + secrets.token_hex(24) + '\n')
        self.password.chmod(0o400)
        self.ephe = root / 'empty-ephe'
        self.ephe.mkdir()
        self.snapshots = root / 'snapshots'
        self.snapshots.mkdir()
        self.envfile = root / 'release.env'
        self.source = root / 'public-source.tar'
        self.source.write_bytes(Path(old['source_offer']).read_bytes())
        self.envfile.write_text(f'KAT_APP_IMAGE={self.old_image}\nKAT_DB_PASSWORD_FILE={self.password}\n'
                                f'KAT_EPHE_DIR={self.ephe}\n')
        self.compose = ['docker', 'compose', '--env-file', str(self.envfile), '-f', str(self.compose_path),
                        '-p', self.project]
        self.migration_calls = 0
        self.phase_failures = []
        self.started = False
        self.target = None

    def command(self, argv, *, env=None, input=None, timeout=600, failed=False):
        result = subprocess.run(argv, cwd=ROOT, env=self.base_env if env is None else env,
                                input=input, text=True, capture_output=True, timeout=timeout)
        if (result.returncode == 0) == failed:
            (self.root.parent / ('command-failure-' + self.project + '.json')).write_text(json.dumps({
                'argv': argv, 'exit_code': result.returncode, 'stdout': result.stdout[-32000:],
                'stderr': result.stderr[-32000:]}, indent=2) + '\n')
            raise RuntimeError('Owned native command outcome differs; inspect retained synthetic evidence')
        return result.stdout.strip()

    def c(self, *args, **kwargs):
        return self.command([*self.compose, *args], **kwargs)

    def root_files(self, *args):
        # Limited to this freshly owned synthetic directory; never host state.
        self.command(['docker', 'run', '--rm', '--network', 'none', '--user', '0',
            '--mount', f'type=bind,src={self.root},dst=/synthetic', '--entrypoint', args[0],
            self.old_image, *args[1:]])

    def start(self):
        if self.c('ps', '-aq'):
            raise ValueError('Native fixture project already exists')
        config = json.loads(self.c('config', '--format', 'json'))
        for name, volume in config['volumes'].items():
            if volume != {'name': self.project + '_' + name}:
                raise ValueError('Native fixture contains foreign volume')
            inspected = subprocess.run(['docker', 'volume', 'inspect', volume['name']],
                                       env=self.base_env, capture_output=True)
            if inspected.returncode == 0:
                raise ValueError('Native fixture volume already exists')
        self.root_files('chown', '10001:10001', '/synthetic/synthetic-password', '/synthetic/snapshots')
        self.root_files('chmod', '0755', '/synthetic/snapshots')
        self.started = True
        self.c('up', '-d', '--wait', '--wait-timeout', '90')
        await_session(self.port)
        self.c('stop', 'app')
        self.app_python(self.old_image, '''
with Store(dsn,root/'files',Tombstones(root/'deletions/deletions.jsonl')) as store:
 store.register_local('manual_owner','synthetic-password')
 session=store.authenticate('manual_owner','synthetic-password')
 store.create_conversation(session,'kept')
 store.create_conversation(session,'deleted_after_old_snapshot')
 store.create_conversation(session,'deleted_before_snapshot')
 store.ledger.delete_conversation(store,session,'deleted_before_snapshot')
''')
        self.c('up', '-d', '--no-deps', '--wait', 'app')
        await_session(self.port)
        app = json.loads(self.command(['docker', 'inspect', self.c('ps', '-q', 'app')]))[0]
        db = json.loads(self.command(['docker', 'inspect', self.c('ps', '-q', 'db')]))[0]
        if app['Image'] != self.old_image or self.sql('SELECT max(version) FROM schema_migrations') != '23':
            raise ValueError('Old native owner/schema differs')
        (self.root / 'stages').mkdir()
        self.target = {'ssh_alias': 'owned-native-only', 'project': self.project,
            'stage_root': str(self.root / 'stages'), 'password_file': str(self.password),
            'ephemeris_dir': str(self.ephe), 'snapshot_dir': str(self.snapshots),
            'origin': 'https://katstrology.dk', 'loopback_port': self.port,
            'db_image': db['Image'], 'release_env_file': str(self.envfile), 'source_offer_file': str(self.source)}

    def sql(self, query, database='kat'):
        return self.c('exec', '-T', 'db', 'psql', '-U', 'kat', '-d', database, '-At',
                      '-v', 'ON_ERROR_STOP=1', '-c', query)

    def app(self, image, *args, **kwargs):
        env = self.base_env | {'KAT_APP_IMAGE': image, 'KAT_DB_PASSWORD_FILE': str(self.password),
                               'KAT_EPHE_DIR': str(self.ephe)}
        return self.c('run', '--rm', '--no-deps', '-T', '-v', str(self.snapshots) + ':/verification',
                      'app', *args, env=env, **kwargs)

    def app_python(self, image, script):
        prelude = """from pathlib import Path
from m2.web_server import deployment_dsn
from m2.store import Store
from m2.deletion import Tombstones
root=Path('/var/lib/kat/browser-runtime')
dsn=deployment_dsn('/run/secrets/db_password','db','kat','kat')
"""
        return self.app(image, 'python', '-c', prelude + script)

    def protected(self, path):
        path = Path(path)
        helpers = {Path(module.__file__) for module in (access, pipeline, remote)}
        if path not in helpers and self.root not in path.parents:
            raise ValueError('Native ownership adapter refuses foreign path')
        if path.is_symlink() or not path.is_file():
            raise ValueError('Native ownership adapter requires regular owned input')
        return path

    def phase_command(self, *args, env=None, input=None, timeout=120):
        value = self.command(list(args), env=env, input=input, timeout=timeout)
        if 'm2.deployment_backup' in args:
            # Root on a server can read UID10001 snapshot metadata. Give this
            # non-root harness read-only access to its synthetic snapshots only.
            self.root_files('chmod', '-R', 'a+rX', '/synthetic/snapshots')
        if 'm2.release_schema' in args:
            self.migration_calls += 1
            if self.ambiguous:
                raise subprocess.TimeoutExpired(args, timeout)  # Actual commit, lost acknowledgement.
        return value

    def execute(self, archive):
        manual = {'lane': LANE, 'old_image': self.old_image,
                  'old_source_sha256': self.old['source_offer_sha256'], 'settled_existing_work': True}
        plan = pipeline.plan(self.candidate, self.target, 24, self.compose_path.read_bytes(),
                             secrets.token_hex(16), archive.stat().st_size,
                             Path(self.candidate['source_offer']).stat().st_size, manual_transition=manual)
        key = self.root / 'synthetic-signing-key'
        self.command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)])
        allowed = self.root / 'allowed-signers'
        allowed.write_text('native-fixture ' + ' '.join(key.with_suffix('.pub').read_text().split()[:2]) + '\n')
        policy = {'contract': 4, 'target': self.target, 'schema_version': 23,
            'compose_file': str(self.compose_path), 'max_archive_bytes': 2 * 1024**3,
            'max_source_bytes': 128 * 1024**2, 'approval_principal': 'native-fixture',
            'approval_namespace': access.APPROVAL_NAMESPACE, 'allowed_signers_file': str(allowed),
            'allowed_signers_sha256': pipeline.digest(allowed), 'manual_transitions': [LANE]}
        approval = {'approved_action': 'release', 'attempt': plan['attempt'], 'plan_sha256': plan['plan_sha256']}
        signature = self.command(['ssh-keygen', '-Y', 'sign', '-f', str(key), '-n', access.APPROVAL_NAMESPACE],
                                 input=json.dumps(approval, sort_keys=True, separators=(',', ':')) + '\n')
        def transport(alias, request, upload=None, **kwargs):
            if alias != 'owned-native-only':
                raise ValueError('Native fixture has no SSH transport')
            try:
                if upload:
                    with upload.open('rb') as stream:
                        return access.dispatch(request, policy, stream)
                return access.dispatch(request, policy, BytesIO())
            except Exception as error:
                self.phase_failures.append({'action': request['action'], 'boundary': 'admission',
                    'error_class': type(error).__name__, 'message': str(error)[:1000]})
                raise
        edge = LocalEdge(self.port, self.target['origin'])
        original_phase = remote.release_phase
        def recorded_phase():
            try:
                return original_phase()
            except Exception as error:
                # All inputs are synthetic. Retain bounded discriminating evidence
                # before resource cleanup, without keys, request bodies or locals.
                self.phase_failures.append({'action': remote.REQUEST['action'],
                    'error_class': type(error).__name__, 'message': str(error)[:1000],
                    'frames': [{'file': Path(frame.filename).name, 'line': frame.lineno}
                               for frame in traceback.extract_tb(error.__traceback__)[-8:]]})
                raise
        with ExitStack() as stack:
            stack.enter_context(patch.object(access, 'protected', side_effect=self.protected))
            stack.enter_context(patch.object(remote, 'protected_file', side_effect=self.protected))
            stack.enter_context(patch.object(remote, 'SERVER_ENV', self.base_env))
            stack.enter_context(patch.object(remote, 'run', side_effect=self.phase_command))
            stack.enter_context(patch.object(remote, 'release_phase', side_effect=recorded_phase))
            stack.enter_context(patch.object(pipeline, 'remote', side_effect=transport))
            stack.enter_context(patch.object(pipeline, 'build_opener', return_value=edge))
            stack.enter_context(patch('urllib.request.build_opener', return_value=edge))
            try:
                pipeline.execute(self.candidate, archive, self.compose_path.read_bytes(), self.target,
                                 plan, approval, signature, self.root / 'controller-result.json')
            except RuntimeError:
                if not self.ambiguous:
                    raise
        stage = Path(self.target['stage_root']) / plan['attempt']
        phase = json.loads((stage / 'phase.json').read_text())['phase']
        if self.migration_calls != 1 or self.sql('SELECT max(version) FROM schema_migrations') != '24':
            raise AssertionError('Exact migration did not commit exactly once')
        snapshot = 'snapshot-' + plan['plan_sha256'][:16]
        old_manifest = json.loads((self.snapshots / snapshot / 'manifest.json').read_text())
        if old_manifest['schema_version'] != 23:
            raise AssertionError('Actual controller did not use old-image schema23 backup')
        if self.ambiguous:
            if (phase != 'migrating' or self.c('ps', '-q', 'app')
                    or not (stage.parent / 'active-attempt').exists()
                    or pipeline.digest(self.source) != self.old['source_offer_sha256']
                    or remote.selected_image(self.envfile.read_bytes()) != self.old_image):
                raise AssertionError('Ambiguous commit was not contained behind stopped old owner')
            return {'status': 'expected halt verified', 'phase': phase, 'schema': 24, 'old_snapshot_schema': 23,
                    'migration_calls': 1, 'source_and_selection': 'old retained', 'restarted_or_restored': False}
        if phase != 'completed' or (stage.parent / 'active-attempt').exists():
            raise AssertionError('Manual release did not complete/retire its attempt')
        admission = json.loads(self.c('exec', '-T', '--user', '10001:10001', 'app',
                                    'python', '-m', 'm2.release_drain', 'status', plan['attempt']))
        if admission['phase'] != 'open' or admission['attempt'] is not None:
            raise AssertionError('Completed candidate admission did not reopen')
        self.c('stop', 'app')
        self.verify_restores(snapshot)
        return {'status': 'passed', 'phase': phase, 'schema': 24, 'old_snapshot_schema': 23,
                'migration_calls': 1, 'new24_restore': 'preference retained; newer deletion reconciled',
                'old23_restore': 'old snapshot accepted; newer deletion reconciled',
                'admission': 'reopened after local and synthetic public verification'}

    def verify_restores(self, snapshot23):
        new_image = self.new_image
        self.app_python(new_image, """
with Store(dsn,root/'files',Tombstones(root/'deletions/deletions.jsonl')) as store:
 session=store.authenticate('manual_owner','synthetic-password')
 assert store.tone_preference(session)=={'tone_id':'quiet-wonder','revision':0}
 store.set_tone_preference(session,'thoughtful-wit',0)
 store.ledger.delete_conversation(store,session,'deleted_after_old_snapshot')
 store.create_conversation(session,'deleted_after_new_snapshot')
""")
        self.app(new_image, 'python', '-m', 'm2.deployment_backup', 'backup', '--state-directory',
                 '/var/lib/kat', '--snapshot', '/verification/new24', '--db-password-file', '/run/secrets/db_password')
        self.app_python(new_image, """
with Store(dsn,root/'files',Tombstones(root/'deletions/deletions.jsonl')) as store:
 session=store.authenticate('manual_owner','synthetic-password')
 store.ledger.delete_conversation(store,session,'deleted_after_new_snapshot')
import shutil
for name in ('restored23','restored24','refused23'):
 destination=Path('/verification')/name/'browser-runtime/deletions'
 destination.mkdir(parents=True,mode=0o700)
 for filename in ('deletions.jsonl','deletions.jsonl.tip'):
  shutil.copyfile(root/'deletions'/filename,destination/filename)
""")
        for schema, image, snapshot in ((23, self.old_image, snapshot23), (24, new_image, 'new24')):
            database = 'restored' + str(schema)
            self.sql('CREATE DATABASE ' + database)
            self.app(image, 'python', '-m', 'm2.deployment_backup', 'verify-restore',
                '--state-directory', '/verification/' + database, '--snapshot', '/verification/' + snapshot,
                '--db-password-file', '/run/secrets/db_password', '--db-name', database)
            if self.sql('SELECT count(*) FROM conversations', database) != '1':
                raise AssertionError('Restored snapshot revived a later independent deletion')
        if self.sql('SELECT tone_id FROM account_tones', 'restored24') != 'thoughtful-wit':
            raise AssertionError('New-format restore lost account preference')
        self.sql('CREATE DATABASE refused23')
        self.app(self.old_image, 'python', '-m', 'm2.deployment_backup', 'verify-restore',
            '--state-directory', '/verification/refused23', '--snapshot', '/verification/new24',
            '--db-password-file', '/run/secrets/db_password', '--db-name', 'refused23', failed=True)
        if self.sql("SELECT count(*) FROM pg_tables WHERE schemaname='public'", 'refused23') != '0':
            raise AssertionError('Incompatible old restore changed its empty target')

    def cleanup(self):
        if self.started:
            self.c('down', '--volumes', '--remove-orphans')
            for kind, args in (('container', ['ps', '-aq']), ('volume', ['volume', 'ls', '-q']),
                               ('network', ['network', 'ls', '-q'])):
                if self.command(['docker', *args, '--filter', 'label=com.docker.compose.project=' + self.project]):
                    raise RuntimeError('Owned native ' + kind + ' cleanup incomplete')
        self.root_files('chown', '-R', f'{os.getuid()}:{os.getgid()}', '/synthetic')


def qualify(old_path, candidate_path, output):
    old, old_archive, old_compose, old_schema = pipeline.artifact(old_path)
    candidate, archive, compose, schema = pipeline.artifact(candidate_path)
    if (old['commit'] != '094be931c8d5bde3689086fa8daa232c70c9becb'
            or (old_schema, schema) != (23, 24) or old_compose != compose
            or subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip()
            or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() != candidate['commit']):
        raise ValueError('Native qualification requires exact clean candidate and retained094')
    output.mkdir(parents=True, exist_ok=False)
    # Both archives are verified above and genuinely loaded, not substituted tags.
    for path in (old_archive, archive):
        subprocess.run(['docker', 'load', '-i', str(path)], check=True, capture_output=True, timeout=600)
    report = {'status': 'running', 'commit': candidate['commit'], 'tree': candidate['tree'],
              'archive_sha256': candidate['image_archive_sha256'], 'migration': LANE,
              'adapters': ['synthetic root ownership',
                           'synthetic edge redirect,421 and TLS-to-owned-loopback; native app403 separately checked'],
              'ssh_or_server_access': False, 'cases': []}
    try:
        for ambiguous in (False, True):
            with tempfile.TemporaryDirectory(prefix='owned-', dir=output) as directory:
                fixture = NativeFixture(Path(directory), old, candidate, compose, ambiguous=ambiguous)
                case = {'project': fixture.project, 'ambiguous_control': ambiguous, 'status': 'running'}
                report['cases'].append(case)
                try:
                    fixture.start()
                    case.update(fixture.execute(archive))
                except Exception as error:
                    case.update(status='failed', error_class=type(error).__name__)
                    raise
                finally:
                    case['phase_failures'] = fixture.phase_failures
                    receipt = fixture.root / 'controller-result.json'
                    if receipt.exists():
                        shutil.copyfile(receipt, output / (fixture.project + '-controller.json'))
                    case['phases'] = [json.loads(path.read_text()) for path in
                                      (fixture.root / 'stages').glob('*/phase.json')]
                    fixture.cleanup()
                    case['cleanup'] = 'passed'
        report['status'] = 'passed'
        report['cleanup'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error_class'] = type(error).__name__
        raise
    finally:
        (output / 'native.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-receipt', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print('Plan only: new owned native094→24 signed release and ambiguous-commit control; no server access.')
    elif not args.old_receipt or not args.receipt or not args.output:
        parser.error('Execution needs exact old/new receipts and a fresh owned output directory')
    else:
        print(json.dumps(qualify(args.old_receipt, args.receipt, args.output)))
