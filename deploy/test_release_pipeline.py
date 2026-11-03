"""Offline release control tests: never contact an SSH host or serving state."""

from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deploy import release_pipeline as pipeline
from deploy import release_access
from deploy import release_remote

ROOT = Path(__file__).resolve().parents[1]


def synthetic_package(directory):
    root = Path(directory)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip()
    offer = root / 'source.tar'
    with offer.open('wb') as output:
        subprocess.run(['git', 'archive', 'HEAD'], cwd=ROOT, stdout=output, check=True)
    config = json.dumps({'os': 'linux', 'architecture': 'amd64',
                         'config': {'Labels': {'org.opencontainers.image.revision': commit}}}).encode()
    config_hash = sha256(config).hexdigest()
    manifest = json.dumps({'config': {'digest': 'sha256:' + config_hash}}).encode()
    manifest_hash = sha256(manifest).hexdigest()
    index = json.dumps({'manifests': [{'digest': 'sha256:' + manifest_hash,
                                      'platform': {'os': 'linux', 'architecture': 'amd64'}}]}).encode()
    index_hash = sha256(index).hexdigest()
    archive = root / 'image.tar'
    with tarfile.open(archive, 'w') as tar:
        for name, content in [('blobs/sha256/' + config_hash, config),
                              ('blobs/sha256/' + manifest_hash, manifest),
                              ('blobs/sha256/' + index_hash, index),
                              ('index.json', json.dumps({'manifests': [{'digest': 'sha256:' + index_hash}]}).encode())]:
            item = tarfile.TarInfo(name)
            item.size = len(content)
            tar.addfile(item, BytesIO(content))
    receipt = {'commit': commit, 'tree': tree, 'architecture': 'linux/amd64',
               'image_id': 'sha256:' + index_hash, 'config_digest': 'sha256:' + config_hash,
               'image_archive_sha256': pipeline.digest(archive),
               'source_offer_sha256': pipeline.digest(offer),
               'image_archive': str(archive), 'source_offer': str(offer)}
    path = root / 'receipt.json'
    path.write_text(json.dumps(receipt))
    return path


def effective_config(target, image):
    project = target['project']
    return {'name': project, 'services': {
        'app': {'image': image, 'command': ['python', '-m', 'm2.web_server', 'serve',
             '--deployment-origin', target['origin'], '--db-password-file', '/run/secrets/db_password',
             '--state-directory', '/var/lib/kat', '--served-dist', '/opt/kat/web/dist', '--enable-siwc'],
             'user': '10001:10001', 'read_only': True,
             'tmpfs': ['/tmp:rw,noexec,nosuid,size=64m'],
             'ports': [{'mode': 'ingress', 'host_ip': '127.0.0.1', 'target': 8765,
                        'published': str(target['loopback_port']), 'protocol': 'tcp'}],
             'volumes': [
                 {'type': 'bind', 'source': target['password_file'], 'target': '/run/secrets/db_password', 'read_only': True},
                 {'type': 'volume', 'source': 'kat_state', 'target': '/var/lib/kat'},
                 {'type': 'volume', 'source': 'deletion_authority', 'target': '/var/lib/kat/browser-runtime/deletions'},
                 {'type': 'volume', 'source': 'siwc_credentials', 'target': '/var/lib/kat/browser-runtime/siwc'},
                 {'type': 'bind', 'source': target['ephemeris_dir'], 'target': '/opt/kat/.local/ephe', 'read_only': True},
             ], 'networks': {'private': None, 'outbound': None}},
        'db': {'image': target['db_image'], 'ports': None, 'volumes': [
            {'type': 'volume', 'source': 'pgdata', 'target': '/var/lib/postgresql/data'}],
            'secrets': [{'source': 'db_password', 'target': '/run/secrets/db_password'}],
            'environment': {'POSTGRES_DB': 'kat', 'POSTGRES_USER': 'kat',
                            'POSTGRES_PASSWORD_FILE': '/run/secrets/db_password'},
            'networks': {'private': None}},
    }, 'volumes': {name: {'name': project + '_' + name} for name in
                   ('kat_state', 'deletion_authority', 'siwc_credentials', 'pgdata')},
            'networks': {'private': {'name': project + '_private'},
                         'outbound': {'name': project + '_outbound'}},
            'secrets': {'db_password': {'file': target['password_file']}}}


def runtime_inspect(config, target, *, app=True):
    service = 'app' if app else 'db'
    project = target['project']
    mounts = []
    for item in config['services'][service]['volumes']:
        source = (config['volumes'][item['source']]['name'] if item['type'] == 'volume'
                  else item['source'])
        mounts.append({'Type': item['type'], 'Name': source if item['type'] == 'volume' else '',
                       'Source': source, 'Destination': item['target'], 'RW': not item.get('read_only', False)})
    if not app:
        mounts.append({'Type': 'bind', 'Source': target['password_file'],
                       'Destination': '/run/secrets/db_password', 'RW': False})
    return {'Id': 'existing-app' if app else 'existing-db',
            'Image': 'sha256:' + 'd' * 64 if app else 'sha256:' + 'e' * 64,
            'Config': {'Labels': {'com.docker.compose.project': project,
                                  'com.docker.compose.service': service},
                       'Cmd': config['services'][service].get('command'),
                       'User': config['services'][service].get('user') or '',
                       'Env': [f'{k}={v}' for k, v in config['services'][service].get('environment', {}).items()]},
            'State': {'Running': True}, 'Mounts': mounts,
            'HostConfig': {'PortBindings': {'8765/tcp': [{'HostIp': '127.0.0.1',
                         'HostPort': str(target['loopback_port'])}]} if app else {},
                           'ReadonlyRootfs': bool(config['services'][service].get('read_only')),
                           'Tmpfs': {'/tmp': 'rw,noexec,nosuid,size=64m'} if app else {}},
            'NetworkSettings': {'Networks': {project + '_' + network: {}
                for network in config['services'][service]['networks']}}}


def source_payload():
    stream = BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        item = tarfile.TarInfo('README.md')
        item.size = 6
        archive.addfile(item, BytesIO(b'source'))
    return stream.getvalue()


def synthetic_target():
    return {'ssh_alias': 'synthetic-alias', 'project': 'kat-synthetic',
            'stage_root': '/srv/synthetic-release', 'password_file': '/srv/synthetic-secret',
            'ephemeris_dir': '/srv/synthetic-ephe', 'snapshot_dir': '/srv/synthetic-snapshot',
            'origin': 'https://example.invalid', 'loopback_port': 28765,
            'db_image': 'sha256:' + 'e' * 64,
            'release_env_file': '/srv/kat-synthetic/.env', 'source_offer_file': '/srv/kat-synthetic/source.tar'}


class ReleasePlanTests(unittest.TestCase):
    def test_immutable_existing_package_and_nonmutating_plan(self):
        with TemporaryDirectory() as directory:
            receipt, archive, compose, schema = pipeline.artifact(synthetic_package(directory))
            self.assertTrue(archive.is_file())
            self.assertEqual(schema, 23)
            target = Path(directory) / 'target.json'
            target.write_text(json.dumps(synthetic_target()))
            with patch('deploy.release_pipeline.remote') as remote:
                planned = pipeline.plan(receipt, pipeline.target_config(target), schema, compose, '1' * 32, archive.stat().st_size, Path(receipt['source_offer']).stat().st_size)
            remote.assert_not_called()
            self.assertEqual(planned['artifact']['commit'], receipt['commit'])
            self.assertNotIn('/srv/', json.dumps(planned))
            self.assertNotIn('synthetic-secret', json.dumps(planned))

    def test_tampered_archive_is_rejected_before_transport(self):
        with TemporaryDirectory() as directory:
            path = synthetic_package(directory)
            receipt = json.loads(path.read_text())
            Path(receipt['image_archive']).write_bytes(b'corrupt archive')
            with patch('deploy.release_pipeline.remote') as remote:
                with self.assertRaisesRegex(ValueError, 'Artifact hash mismatch'):
                    pipeline.artifact(path)
                remote.assert_not_called()

    def test_target_changes_invalidate_exact_approval_and_no_side_effects(self):
        receipt = {key: 'a' * 64 for key in ('commit', 'tree', 'image_archive_sha256', 'source_offer_sha256')}
        receipt.update(image_id='sha256:' + 'b' * 64, config_digest='sha256:' + 'c' * 64)
        target = synthetic_target()
        approved = pipeline.plan(receipt, target, 22, b'compose', '1' * 32, 7, 7)
        target['password_file'] = '/srv/other-secret'
        changed = pipeline.plan(receipt, target, 22, b'compose', '1' * 32, 7, 7)
        self.assertNotEqual(approved['plan_sha256'], changed['plan_sha256'])
        with TemporaryDirectory() as directory:
            result = Path(directory) / 'receipt.json'
            with patch('deploy.release_pipeline.remote') as remote:
                with self.assertRaisesRegex(ValueError, 'approval'):
                    pipeline.execute(receipt, Path('/nonexistent'), b'compose', target, changed,
                                     {'approved_action': 'release', 'attempt': approved['attempt'], 'plan_sha256': approved['plan_sha256']}, 'synthetic', result)
            remote.assert_not_called()
            self.assertFalse(result.exists())

    def test_guard_prevents_ambiguous_replay_and_records_halt(self):
        receipt = {key: 'a' * 64 for key in ('commit', 'tree', 'image_archive_sha256', 'source_offer_sha256')}
        receipt.update(image_id='sha256:' + 'b' * 64, config_digest='sha256:' + 'c' * 64)
        target = synthetic_target()
        planned = pipeline.plan(receipt, target, 22, b'compose', '1' * 32, 7, 7)
        approval = {'approved_action': 'release', 'attempt': planned['attempt'], 'plan_sha256': planned['plan_sha256']}
        with TemporaryDirectory() as directory:
            result = Path(directory) / 'receipt.json'
            archive = Path(directory) / 'image.tar'
            archive.write_bytes(b'archive')
            receipt['source_offer'] = str(archive)
            with patch('deploy.release_pipeline.remote', side_effect=RuntimeError('synthetic failure')) as remote:
                with self.assertRaisesRegex(RuntimeError, 'halted'):
                    pipeline.execute(receipt, archive, b'compose', target, planned, approval, '-----BEGIN SSH SIGNATURE-----\nsynthetic\n-----END SSH SIGNATURE-----', result)
                self.assertEqual(remote.call_count, 2)  # stage failure then signed containment, never activation retry
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    pipeline.execute(receipt, archive, b'compose', target, planned, approval, '-----BEGIN SSH SIGNATURE-----\nsynthetic\n-----END SSH SIGNATURE-----', result)
                self.assertEqual(remote.call_count, 2)
            self.assertEqual(json.loads(result.read_text())['status'], 'halted; serving state unknown')

    def test_remote_stage_is_exclusive_before_any_docker_action(self):
        with TemporaryDirectory() as directory:
            stage = Path(directory) / 'new-stage'
            target = synthetic_target()
            target['stage'] = str(stage)
            planned = {'plan_sha256': 'a' * 64, 'artifact': {'config_digest': 'sha256:' + 'b' * 64}}
            request = {'action': 'stage', 'target': target, 'plan': planned}
            with patch.object(release_remote, 'REQUEST', request, create=True), \
                 patch.object(release_remote, 'run') as docker:
                release_remote.main()
                self.assertEqual(json.loads((stage / 'phase.json').read_text()),
                                 {'plan_sha256': planned['plan_sha256'], 'phase': 'staged'})
                with self.assertRaisesRegex(ValueError, 'no retry'):
                    release_remote.main()
                docker.assert_not_called()

    def test_mismatched_existing_state_and_port_refuse_before_loading_or_stop(self):
        with TemporaryDirectory() as directory:
            stage = Path(directory) / 'stage'
            stage.mkdir()
            payload = b'synthetic image archive'
            (stage / 'image.tar').write_bytes(payload)
            (stage / 'compose.yaml').write_text('synthetic compose')
            target = synthetic_target() | {'stage': str(stage), 'snapshot_dir': directory}
            (stage / 'runtime.yaml').write_text(release_remote.installed_db_override(target))
            plan = {'plan_sha256': 'a' * 64, 'compose_sha256': sha256(b'synthetic compose').hexdigest(),
                    'artifact': {'config_digest': 'sha256:' + 'b' * 64,
                                 'image_archive_sha256': sha256(payload).hexdigest(), 'commit': 'c' * 40}}
            (stage / 'phase.json').write_text(json.dumps({'plan_sha256': plan['plan_sha256'], 'phase': 'composed'}))
            config = effective_config(target, plan['artifact']['config_digest'])
            for mismatch in ('state-volume', 'port', 'db-volume'):
                with self.subTest(mismatch=mismatch):
                    existing = runtime_inspect(config, target)
                    database = runtime_inspect(config, target, app=False)
                    if mismatch == 'state-volume':
                        existing['Mounts'][1]['Name'] = 'synthetic-retained-archive'
                    elif mismatch == 'port':
                        existing['HostConfig']['PortBindings']['8765/tcp'][0]['HostPort'] = '28766'
                    else:
                        database['Mounts'][0]['Name'] = 'synthetic-retained-db'
                    calls = []

                    def docker(*argv, **_kwargs):
                        calls.append(argv)
                        if 'config' in argv: return json.dumps(config)
                        if 'ps' in argv: return 'existing-app' if argv[-1] == 'app' else 'existing-db'
                        if argv[:3] == ('docker', 'inspect', 'existing-app'): return json.dumps([existing])
                        if argv[:3] == ('docker', 'inspect', 'existing-db'): return json.dumps([database])
                        if argv[:3] == ('docker', 'image', 'inspect'):
                            return json.dumps([{'Id': argv[-1] if argv[-1].startswith('sha256:') else 'sha256:' + 'e' * 64,
                                                'Config': {'Labels': {'org.opencontainers.image.revision': 'c' * 40}}}])
                        if argv[:2] == ('docker', 'load'): return ''
                        raise AssertionError(argv)

                    with patch.object(release_remote, 'REQUEST', {'action': 'preflight', 'plan': plan,
                              'target': target}, create=True), patch.object(release_remote, 'run', side_effect=docker):
                        with self.assertRaisesRegex(ValueError, 'serving|mount|binding|runtime'):
                            release_remote.main()
                    self.assertFalse(any('load' in call or 'stop' in call for call in calls))
                    self.assertEqual(json.loads((stage / 'phase.json').read_text())['phase'], 'composed')

    def test_installed_db_override_resolves_in_real_compose_config(self):
        with TemporaryDirectory() as directory:
            target = synthetic_target()
            override = Path(directory) / 'runtime.yaml'
            override.write_text(release_remote.installed_db_override(target))
            env = {**os.environ, 'KAT_APP_IMAGE': 'sha256:' + 'b' * 64,
                   'KAT_DB_PASSWORD_FILE': target['password_file'],
                   'KAT_EPHE_DIR': target['ephemeris_dir']}
            output = subprocess.check_output(['docker', 'compose', '-f', str(ROOT / 'deploy/compose.yaml'),
                '-f', str(override), '-p', target['project'], 'config', '--format', 'json'],
                env=env, text=True)
            config = json.loads(output)
            self.assertEqual(config['services']['db']['image'], target['db_image'])
            self.assertEqual(config['services']['app']['image'], env['KAT_APP_IMAGE'])
            self.assertEqual(config['services']['app']['ports'][0]['published'],
                             str(target['loopback_port']))

    def test_installed_db_config_pin_works_without_source_registry_alias(self):
        with TemporaryDirectory() as directory:
            stage = Path(directory) / 'stage'
            stage.mkdir()
            target = synthetic_target() | {'stage': str(stage), 'snapshot_dir': directory}
            image = 'sha256:' + 'b' * 64
            payload = b'synthetic archive'
            plan = {'plan_sha256': 'a' * 64, 'compose_sha256': sha256(b'synthetic compose').hexdigest(),
                    'schema_version': 22,
                    'artifact': {'config_digest': image, 'image_archive_sha256': sha256(payload).hexdigest(),
                                 'commit': 'c' * 40}}
            (stage / 'phase.json').write_text(json.dumps({'plan_sha256': plan['plan_sha256'], 'phase': 'uploaded'}))
            (stage / 'image.tar').write_bytes(payload)
            config = effective_config(target, image)
            commands = []
            def docker(*argv, **_kwargs):
                commands.append(argv)
                if 'config' in argv:
                    effective = json.loads(json.dumps(config))
                    if str(stage / 'runtime.yaml') not in argv:
                        effective['services']['db']['image'] = 'postgres:16-bookworm@sha256:' + 'f' * 64
                    return json.dumps(effective)
                if 'ps' in argv: return 'existing-app' if argv[-1] == 'app' else 'existing-db'
                if argv[:3] == ('docker', 'inspect', 'existing-app'):
                    return json.dumps([runtime_inspect(config, target)])
                if argv[:3] == ('docker', 'inspect', 'existing-db'):
                    return json.dumps([runtime_inspect(config, target, app=False)])
                if argv[:3] == ('docker', 'image', 'inspect'):
                    if not argv[-1].startswith('sha256:'):
                        raise subprocess.CalledProcessError(1, argv)  # Alias absent; never pull/retag.
                    return json.dumps([{'Id': argv[-1], 'Config': {
                        'Labels': {'org.opencontainers.image.revision': 'c' * 40}}}])
                if argv[:2] == ('docker', 'load'): return ''
                raise AssertionError(argv)
            for field, name in (('release_env_file', 'env'), ('source_offer_file', 'source')):
                target[field] = str(Path(directory) / name)
                Path(target[field]).write_bytes(b'original')
            with patch.object(release_remote, 'run', side_effect=lambda *args, **kwargs: '22' if 'psql' in args else docker(*args, **kwargs)), \
                 patch.object(release_remote, 'release_files', return_value={'selected_image': 'sha256:' + 'd' * 64,
                     'env_sha256': sha256(b'original').hexdigest(), 'source_sha256': sha256(b'original').hexdigest()}), \
                 patch.object(release_remote, 'source_archive'), \
                 patch.object(release_remote, 'check_snapshot', return_value=Path(directory)):
                for action in ('compose', 'preflight'):
                    with patch.object(release_remote, 'REQUEST', {'action': action, 'target': target,
                          'plan': plan, **({'compose': 'synthetic compose'} if action == 'compose' else {})}, create=True):
                        release_remote.main()
            self.assertEqual(json.loads((stage / 'phase.json').read_text())['phase'], 'preflight_ok')
            self.assertTrue(any(str(stage / 'runtime.yaml') in argv for argv in commands))
            self.assertFalse(any('stop' in argv or 'pull' in argv or 'tag' in argv for argv in commands))

    def test_missing_snapshot_refuses_while_old_app_is_running(self):
        with TemporaryDirectory() as directory:
            stage = Path(directory) / 'stage'
            stage.mkdir()
            payload = b'synthetic image archive'
            (stage / 'image.tar').write_bytes(payload)
            (stage / 'compose.yaml').write_text('synthetic compose')
            target = synthetic_target() | {'stage': str(stage),
                                          'snapshot_dir': str(Path(directory) / 'missing')}
            (stage / 'runtime.yaml').write_text(release_remote.installed_db_override(target))
            plan = {'plan_sha256': 'a' * 64, 'compose_sha256': sha256(b'synthetic compose').hexdigest(),
                    'artifact': {'config_digest': 'sha256:' + 'b' * 64,
                                 'image_archive_sha256': sha256(payload).hexdigest(), 'commit': 'c' * 40}}
            (stage / 'phase.json').write_text(json.dumps({'plan_sha256': plan['plan_sha256'], 'phase': 'composed'}))
            config = effective_config(target, plan['artifact']['config_digest'])
            calls = []

            def docker(*argv, **_kwargs):
                calls.append(argv)
                if 'config' in argv: return json.dumps(config)
                if 'ps' in argv: return 'existing-app' if argv[-1] == 'app' else 'existing-db'
                if argv[:3] == ('docker', 'inspect', 'existing-app'): return json.dumps([runtime_inspect(config, target)])
                if argv[:3] == ('docker', 'inspect', 'existing-db'): return json.dumps([runtime_inspect(config, target, app=False)])
                if argv[:3] == ('docker', 'image', 'inspect'):
                    return json.dumps([{'Id': argv[-1] if argv[-1].startswith('sha256:') else 'sha256:' + 'e' * 64,
                                        'Config': {'Labels': {'org.opencontainers.image.revision': 'c' * 40}}}])
                if argv[:2] == ('docker', 'load'): return ''
                raise AssertionError(argv)

            with patch.object(release_remote, 'REQUEST', {'action': 'preflight', 'plan': plan,
                      'target': target}, create=True), patch.object(release_remote, 'run', side_effect=docker):
                with self.assertRaisesRegex(ValueError, 'snapshot'):
                    release_remote.main()
            self.assertFalse(any('stop' in call for call in calls))
            self.assertEqual(json.loads((stage / 'phase.json').read_text())['phase'], 'composed')

    def test_snapshot_prerequisite_rejects_owner_and_existing_target_but_accepts_empty(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / 'independent'
            root.mkdir()
            target = synthetic_target() | {'stage': str(Path(directory) / 'stage'), 'snapshot_dir': str(root)}
            plan = {'plan_sha256': 'a' * 64}
            with self.assertRaisesRegex(ValueError, 'app-owned'):
                release_remote.check_snapshot(target, plan, [])
            real_stat = Path.stat
            def app_owned(path, *args, **kwargs):
                info = real_stat(path, *args, **kwargs)
                return SimpleNamespace(st_mode=info.st_mode, st_uid=10001) if path == root else info
            with patch.object(Path, 'stat', app_owned):
                self.assertEqual(release_remote.check_snapshot(target, plan, []), root)
                (root / ('snapshot-' + 'a' * 16)).mkdir()
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    release_remote.check_snapshot(target, plan, [])
                with self.assertRaisesRegex(ValueError, 'overlap'):
                    release_remote.check_snapshot(target, plan, [
                        {'Type': 'bind', 'Source': str(root), 'Destination': '/var/lib/kat'}])

    def test_snapshot_race_restarts_only_identified_old_app_before_backup(self):
        with TemporaryDirectory() as directory:
            stage = Path(directory) / 'stage'
            stage.mkdir()
            target = synthetic_target() | {'stage': str(stage), 'snapshot_dir': directory}
            compose = b'synthetic compose'
            (stage / 'compose.yaml').write_bytes(compose)
            (stage / 'runtime.yaml').write_text(release_remote.installed_db_override(target))
            plan = {'plan_sha256': 'a' * 64, 'compose_sha256': sha256(compose).hexdigest(),
                    'artifact': {'config_digest': 'sha256:' + 'b' * 64}}
            config = effective_config(target, plan['artifact']['config_digest'])
            (stage / 'phase.json').write_text(json.dumps({'plan_sha256': plan['plan_sha256'], 'phase': 'preflight_ok'}))
            (stage / 'previous-container').write_text('existing-app\n')
            (stage / 'previous-image').write_text('sha256:' + 'd' * 64 + '\n')
            (stage / 'previous-db-container').write_text('existing-db\n')
            (stage / 'previous-db-image').write_text('sha256:' + 'e' * 64 + '\n')
            running = True
            calls = []
            def docker(*argv, **_kwargs):
                nonlocal running
                calls.append(argv)
                if 'config' in argv: return json.dumps(config)
                if argv[:3] == ('docker', 'inspect', 'existing-app'):
                    app = runtime_inspect(config, target)
                    app['State']['Running'] = running
                    return json.dumps([app])
                if argv[:3] == ('docker', 'inspect', 'existing-db'):
                    return json.dumps([runtime_inspect(config, target, app=False)])
                if 'stop' in argv:
                    running = False
                    return ''
                if argv[:2] == ('docker', 'start'):
                    self.assertEqual(argv[-1], 'existing-app')
                    running = True
                    return ''
                if 'ps' in argv: return 'existing-db' if argv[-1] == 'db' else ('existing-app' if running else '')
                raise AssertionError(argv)
            (stage / 'files.before.json').write_text('{}')
            with patch.object(release_remote, 'release_files', return_value={}), \
                 patch.object(release_remote, 'REQUEST', {'action': 'quiesce_and_snapshot',
                 'plan': plan, 'target': target}, create=True), \
                 patch.object(release_remote, 'run', side_effect=docker), \
                 patch.object(release_remote, 'check_snapshot', side_effect=[Path(directory), ValueError('synthetic snapshot race')]):
                release_remote.main()
            self.assertTrue(running)
            self.assertEqual(json.loads((stage / 'phase.json').read_text())['phase'], 'recovered_old_app')
            self.assertFalse(any('run' in argv or 'up' in argv for argv in calls))

    def test_public_verification_checks_redirect_tls_all_assets_and_authority(self):
        origin = 'https://example.invalid'
        assets = {'index.html': sha256(b'home').hexdigest(),
                  'assets/app.js': sha256(b'javascript').hexdigest(),
                  'manifest.webmanifest': sha256(b'manifest').hexdigest(),
                  'icons/kat-192.png': sha256(b'icon192').hexdigest(),
                  'icons/kat-512.png': sha256(b'icon512').hexdigest(),
                  'icons/kat-512-maskable.png': sha256(b'maskable').hexdigest()}
        class Response:
            def __init__(self, status, body=b'', headers=None):
                self.status, self.body, self.headers = status, body, headers or {}
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def read(self, _limit): return self.body
        class Opener:
            def __init__(self): self.calls = []; self.bad_asset = False; self.bad_host = False
            def open(self, request, timeout):
                self.calls.append((request.full_url, dict(request.header_items())))
                if request.full_url.startswith('http://'):
                    return Response(308, headers={'Location': origin + '/'})
                if request.full_url.endswith('/api/session'):
                    headers = dict(request.header_items())
                    return Response((403 if self.bad_host else 421) if 'Host' in headers else
                                    403 if 'Origin' in headers or 'Sec-fetch-site' in headers else 401)
                path = request.full_url.removeprefix(origin + '/') or 'index.html'
                body = {'index.html': b'home', 'assets/app.js': b'javascript',
                        'manifest.webmanifest': b'manifest', 'icons/kat-192.png': b'icon192',
                        'icons/kat-512.png': b'icon512', 'icons/kat-512-maskable.png': b'maskable'}[path]
                return Response(200, b'corrupt' if self.bad_asset and path == 'icons/kat-512.png' else body)
        opener = Opener()
        pipeline.verify_public(origin, assets, opener=opener)
        self.assertEqual(len(opener.calls), 11)
        self.assertTrue(all(url.startswith(origin) for url, _ in opener.calls[1:]))
        opener.bad_asset = True
        with self.assertRaisesRegex(ValueError, 'asset differs'):
            pipeline.verify_public(origin, assets, opener=opener)
        opener.bad_asset = False
        opener.bad_host = True
        with self.assertRaisesRegex(ValueError, 'wrong-Host'):
            pipeline.verify_public(origin, assets, opener=opener)

    def test_successful_fake_ssh_orchestration_and_public_failure_receipt(self):
        target = synthetic_target()
        receipt = {'commit': 'a' * 40, 'tree': 'b' * 40, 'image_id': 'sha256:' + 'c' * 64,
                   'config_digest': 'sha256:' + 'd' * 64, 'image_archive_sha256': 'e' * 64,
                   'source_offer_sha256': 'f' * 64}
        planned = pipeline.plan(receipt, target, 22, b'compose', '1' * 32, 15, 15)
        approval = {'approved_action': 'release', 'attempt': planned['attempt'], 'plan_sha256': planned['plan_sha256']}
        assets = {'index.html': sha256(b'home').hexdigest(),
                  'manifest.webmanifest': sha256(b'manifest').hexdigest()}
        with TemporaryDirectory() as directory:
            archive = Path(directory) / 'image.tar'
            archive.write_bytes(b'synthetic image')
            receipt['source_offer'] = str(archive)
            result = Path(directory) / 'result.json'
            steps = []
            def fake_remote(_alias, request, upload=None):
                self.assertEqual(set(request), {'action', 'plan', 'approval', 'signature'} | ({'bytes'} if upload else set()))
                if upload:
                    self.assertEqual(upload, archive)
                    self.assertEqual(request['bytes'], archive.stat().st_size)
                steps.append(request['action'])
                return {'status': 'ok', 'serving': 'stopped; exact owned app quarantined', **({'assets': assets} if request['action'] == 'verify_serving_path' else {})}
            with patch.object(pipeline, 'remote', side_effect=fake_remote), \
                 patch.object(pipeline, 'verify_public') as public:
                pipeline.execute(receipt, archive, b'compose', target, planned, approval, '-----BEGIN SSH SIGNATURE-----\nsynthetic\n-----END SSH SIGNATURE-----', result)
                public.assert_called_once_with(target['origin'], assets)
            self.assertEqual(steps, release_access.STEPS)
            self.assertEqual(json.loads(result.read_text())['status'], 'verified')
            result.unlink()
            with patch.object(pipeline, 'remote', side_effect=fake_remote), \
                 patch.object(pipeline, 'verify_public', side_effect=ValueError('synthetic bad TLS')):
                with self.assertRaisesRegex(RuntimeError, 'halted'):
                    pipeline.execute(receipt, archive, b'compose', target, planned, approval, '-----BEGIN SSH SIGNATURE-----\nsynthetic\n-----END SSH SIGNATURE-----', result)
            failed = json.loads(result.read_text())
            self.assertEqual(failed['status'], 'halted; stopped; exact owned app quarantined')
            self.assertEqual(failed['failed_phase'], 'verify_public')
            self.assertEqual(steps[-1], 'quarantine')
            self.assertEqual(next(t for t in failed['timings'] if t['phase'] == 'verify_public')['status'], 'failed')

    def test_remote_fake_docker_runs_full_owned_app_only_lifecycle(self):
        with TemporaryDirectory() as directory:
            stage_root, snapshot = Path(directory) / 'stages', Path(directory) / 'snapshot'
            stage_root.mkdir()
            snapshot.mkdir()
            target = synthetic_target() | {'stage_root': str(stage_root), 'snapshot_dir': str(snapshot)}
            compose_file = Path(directory) / 'protected-compose.yaml'
            compose_file.write_text('synthetic compose')
            env_file, source_file = Path(directory) / '.env', Path(directory) / 'public-source.tar'
            original_env = b'# retain comment\nKAT_APP_IMAGE=sha256:' + b'd' * 64 + b'\nOTHER=preserved\n'
            env_file.write_bytes(original_env)
            source_file.write_bytes(b'old source')
            target.update(release_env_file=str(env_file), source_offer_file=str(source_file))
            source = source_payload()
            receipt = {'commit': 'c' * 40, 'tree': 'd' * 40, 'image_id': 'sha256:' + 'f' * 64,
                       'config_digest': 'sha256:' + 'b' * 64,
                       'image_archive_sha256': sha256(b'image').hexdigest(),
                       'source_offer_sha256': sha256(source).hexdigest()}
            plan = pipeline.plan(receipt, target, 22, compose_file.read_bytes(), '1' * 32, 5, len(source))
            stage = stage_root / plan['attempt']
            policy = {'contract': 4, 'target': target, 'schema_version': 22,
                      'compose_file': str(compose_file), 'max_archive_bytes': 1024, 'max_source_bytes': 128 * 1024**2}
            config = effective_config(target, plan['artifact']['config_digest'])
            running = True
            image = 'sha256:' + 'd' * 64
            calls = []
            assets = {name: sha256(body).hexdigest() for name, body in {
                'index.html': b'home', 'manifest.webmanifest': b'manifest',
                'icons/kat-192.png': b'192', 'icons/kat-512.png': b'512',
                'icons/kat-512-maskable.png': b'mask'}.items()}
            bodies = {'/': b'home', '/manifest.webmanifest': b'manifest',
                      '/icons/kat-192.png': b'192', '/icons/kat-512.png': b'512',
                      '/icons/kat-512-maskable.png': b'mask'}
            def docker(*argv, **_kwargs):
                nonlocal running, image
                calls.append(argv)
                if 'config' in argv: return json.dumps(config)
                if 'ps' in argv: return 'existing-db' if argv[-1] == 'db' else ('existing-app' if running else '')
                if argv[:3] == ('docker', 'inspect', 'existing-app'):
                    app = runtime_inspect(config, target)
                    app['Image'] = image
                    app['State']['Running'] = running
                    return json.dumps([app])
                if argv[:3] == ('docker', 'inspect', 'existing-db'):
                    return json.dumps([runtime_inspect(config, target, app=False)])
                if argv[:3] == ('docker', 'image', 'inspect'):
                    return json.dumps([{'Id': argv[-1] if argv[-1].startswith('sha256:') else 'sha256:' + 'e' * 64,
                                        'Config': {'Labels': {'org.opencontainers.image.revision': 'c' * 40}}}])
                if argv[:2] == ('docker', 'load'): return ''
                if 'stop' in argv:
                    self.assertEqual(argv[-1], 'app')
                    running = False
                    return ''
                if release_remote.STATE_FINGERPRINT in argv:
                    return json.dumps({'files': 'stable', 'host': 'stable', 'deletions': 'stable'})
                if argv[-1].startswith('from pathlib import Path') and 'Tombstones(journal)' in argv[-1]:
                    return ''
                if 'run' in argv:
                    self.assertFalse(running)
                    folder = snapshot / ('snapshot-' + plan['plan_sha256'][:16])
                    folder.mkdir()
                    (folder / 'manifest.json').write_text(json.dumps({'schema_version': 22,
                        'journal_prefix_sha256': 'f' * 64}))
                    return ''
                if 'up' in argv:
                    self.assertIn('--no-deps', argv)
                    running, image = True, plan['artifact']['config_digest']
                    return ''
                if 'psql' in argv: return '22'
                if 'exec' in argv: return json.dumps(assets)
                raise AssertionError(argv)
            class Response:
                def __init__(self, status, body=b''): self.status, self.body = status, body
                def __enter__(self): return self
                def __exit__(self, *_args): pass
                def read(self): return self.body
            class Opener:
                def open(self, request, timeout):
                    from urllib.error import HTTPError
                    if request.get_header('Host') == 'wrong.invalid':
                        raise HTTPError(request.full_url, 403, 'denied', {}, BytesIO(b''))
                    path = request.full_url.split(str(target['loopback_port']), 1)[1]
                    return Response(401 if path == '/api/session' else 200, bodies.get(path, b''))
            original_stat = Path.stat
            def app_owned(path, *args, **kwargs):
                info = original_stat(path, *args, **kwargs)
                return SimpleNamespace(st_mode=info.st_mode, st_uid=10001) if path == snapshot else info
            with patch.object(Path, 'stat', app_owned), patch.object(release_remote, 'run', side_effect=docker), \
                 patch.object(release_remote, 'protected_file', side_effect=lambda p: Path(p)), \
                 patch.object(release_remote, 'build_opener', return_value=Opener()), \
                 patch.object(release_access, 'protected', side_effect=lambda path: Path(path)), \
                 patch.object(release_access, 'verify_signature'):
                def phase(action, **extra):
                    approval = {'approved_action': 'release', 'attempt': plan['attempt'],
                                'plan_sha256': plan['plan_sha256']}
                    return release_access.dispatch({'action': action, 'plan': plan,
                        'approval': approval, 'signature': 'synthetic', **extra},
                                                   policy, BytesIO(b'image' if action == 'upload' else source if action == 'upload_source' else b''))
                phase('stage')
                phase('upload', bytes=5)
                phase('upload_source', bytes=len(source))
                phase('compose')
                for action in ('preflight', 'quiesce_and_snapshot', 'promote_release', 'activate_app_only', 'verify_serving_path', 'complete'):
                    self.assertEqual(phase(action)['status'], 'ok', action)
            self.assertEqual(json.loads((stage / 'phase.json').read_text())['phase'], 'completed')
            self.assertFalse((stage_root / 'active-attempt').exists())
            self.assertEqual(source_file.read_bytes(), source)
            self.assertEqual(env_file.read_bytes(), original_env.replace(b'd' * 64, b'b' * 64))
            self.assertEqual((stage / 'env.before').read_bytes(), original_env)
            self.assertEqual((stage / 'source.before.tar').read_bytes(), b'old source')
            self.assertEqual(image, plan['artifact']['config_digest'])
            self.assertTrue(running)
            self.assertLess(next(i for i, argv in enumerate(calls) if 'stop' in argv),
                            next(i for i, argv in enumerate(calls) if 'run' in argv))
            self.assertFalse(any('stop' in argv and 'db' in argv for argv in calls))

    def test_invalid_target_never_calls_ssh(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'target.json'
            for field, value in [('ssh_alias', 'user@host'), ('stage_root', '/srv/../etc'),
                                 ('snapshot_dir', '/srv/synthetic-release')]:
                target = synthetic_target()
                target[field] = value
                path.write_text(json.dumps(target))
                with self.assertRaises(ValueError):
                    pipeline.target_config(path)


if __name__ == '__main__':
    unittest.main()
