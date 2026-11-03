"""Native state/drain/restore rehearsal inside smoke_local's new disposable project."""

import json


def verify(command, compose, env, image, verification_volume):
    def c(*args):
        return command([*compose, *args], env=env)

    # Only this newly owned synthetic volume; no host state/keys or old data restore.
    command(['docker', 'run', '--rm', '--network', 'none', '--user', '0',
             '--mount', f'type=volume,src={verification_volume},dst=/verification',
             '--entrypoint', 'chown', image, '10001:10001', '/verification'])
    c('stop', 'app')
    seed = """from m2.web_server import deployment_dsn
from m2.store import Store
from m2.deletion import Tombstones
root='/var/lib/kat/browser-runtime/'
with Store(deployment_dsn('/run/secrets/db_password','db','kat','kat'),root+'files',Tombstones(root+'deletions/deletions.jsonl')) as store:
    store.register_local('release_fixture','synthetic-password-release')
    session=store.authenticate('release_fixture','synthetic-password-release')
    store.create_conversation(session,'retained_release_conversation')
"""
    c('run', '--rm', '--no-deps', '-T', 'app', 'python', '-c', seed)
    c('start', 'app')
    # Use the same bounded anonymous readiness boundary as the native smoke.
    from deploy.smoke_local import await_session
    config = json.loads(c('config', '--format', 'json'))
    await_session(int(config['services']['app']['ports'][0]['published']))
    attempt = 'b' * 32
    drained = json.loads(c('exec', '-T', 'app', 'python', '-m', 'm2.release_drain', 'drain', attempt))
    if drained['phase'] != 'drained' or drained['attempt'] != attempt:
        raise ValueError('Native runtime did not drain')
    c('stop', 'app')
    c('run', '--rm', '--no-deps', '-T', 'app', 'python', '-m', 'm2.deployment_backup', 'backup',
      '--state-directory', '/var/lib/kat', '--snapshot', '/verification/snapshot',
      '--db-password-file', '/run/secrets/db_password')
    retain = """from pathlib import Path
import shutil
root=Path('/verification/restored/browser-runtime/deletions')
root.mkdir(parents=True,mode=0o700)
for name in ('deletions.jsonl','deletions.jsonl.tip'):
    shutil.copyfile(Path('/var/lib/kat/browser-runtime/deletions')/name,root/name)
"""
    c('run', '--rm', '--no-deps', '-T', 'app', 'python', '-c', retain)
    c('exec', '-T', 'db', 'psql', '-U', 'kat', '-d', 'kat', '-v', 'ON_ERROR_STOP=1',
      '-c', 'CREATE DATABASE kat_release_restore')
    c('run', '--rm', '--no-deps', '-T', 'app', 'python', '-m', 'm2.deployment_backup', 'verify-restore',
      '--state-directory', '/verification/restored', '--snapshot', '/verification/snapshot',
      '--db-password-file', '/run/secrets/db_password', '--db-name', 'kat_release_restore')
    # Exercise the additive kernel in the disposable restored DB, NOT the serving DB.
    migration = """from pathlib import Path
from hashlib import sha256
import shutil
from m2.release_schema import migrate
from m2.web_server import deployment_dsn
root=Path('/verification/migrations')
shutil.copytree('/opt/kat/m2/migrations',root)
old=max(int(p.name.split('_')[0]) for p in root.glob('*.sql'))
path=root/f'{old+1:03d}_synthetic_release_fixture.sql'
path.write_text('CREATE TABLE synthetic_release_note (id text PRIMARY KEY);')
lane={'from':old,'to':old+1,'migrations':{path.name:sha256(path.read_bytes()).hexdigest()},'added_tables':['synthetic_release_note'],'added_columns':{}}
migrate(deployment_dsn('/run/secrets/db_password','db','kat_release_restore','kat'),lane,root)
"""
    c('run', '--rm', '--no-deps', '-T', 'app', 'python', '-c', migration)
    for database in ('kat', 'kat_release_restore'):
        retained = c('exec', '-T', 'db', 'psql', '-U', 'kat', '-d', database, '-At', '-c',
                     "SELECT id FROM conversations WHERE id='retained_release_conversation'")
        if retained != 'retained_release_conversation':
            raise ValueError('Native snapshot/restore/migration lost retained row')
    c('start', 'app')
    await_session(int(config['services']['app']['ports'][0]['published']))
    state = json.loads(c('exec', '-T', 'app', 'python', '-m', 'm2.release_drain', 'status', attempt))
    if state['phase'] != 'fenced' or state['attempt'] != attempt or state['boot'] == drained['boot']:
        raise ValueError('Restart did not inherit the exact durable admission fence')
    resumed = json.loads(c('exec', '-T', 'app', 'python', '-m', 'm2.release_drain', 'resume', attempt))
    if resumed != {'phase': 'open', 'attempt': None, 'boot': state['boot']}:
        raise ValueError('Native admission reopen unconfirmed')
    return {'drain': 'passed', 'snapshot_restore': 'passed', 'synthetic_additive_lane': 'passed',
            'restart_fence_and_resume': 'passed'}
