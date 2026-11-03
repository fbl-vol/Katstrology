#!/usr/bin/env python3
"""Run repository test profiles only against a freshly owned synthetic fixture."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[4]
PROFILES = ('backend', 'probes', 'browser', 'siwc', 'clock')
PASSWORD = 'synthetic_test_only'  # disposable test container, never a user credential


def command(argv, *, env=None, cwd=ROOT, log=None, timeout=900):
    if log is None:
        return subprocess.check_output(argv, cwd=cwd, env=env, text=True, timeout=timeout).strip()
    with log.open('x') as output:
        subprocess.run(argv, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
                       timeout=timeout, check=True)


@contextmanager
def timed_stage(timings, name):
    entry = {'stage': name, 'status': 'running'}
    timings.append(entry)
    started = perf_counter()
    print(f'kat validation: {name} started', file=sys.stderr, flush=True)
    try:
        yield
    except BaseException:
        entry['status'] = 'stopped'
        raise
    else:
        entry['status'] = 'passed'
    finally:
        entry['seconds'] = round(perf_counter() - started, 3)
        print(f'kat validation: {name} {entry["status"]} ({entry["seconds"]}s)',
              file=sys.stderr, flush=True)


def git_state():
    return {'sha': command(['git', 'rev-parse', 'HEAD']),
            'dirty': bool(command(['git', 'status', '--porcelain']))}


def clean_environment():
    # The fixtures otherwise fall back to the user's database/8765 when unset.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('KAT_', 'PG', 'VITE_KAT_', 'OPENAI_', 'ANTHROPIC_',
                                  'AZURE_', 'AWS_', 'GOOGLE_', 'SIWC_')) and
           key.upper() not in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY') and
           not key.startswith('DOCKER_')}
    docker_host = 'unix:///var/run/docker.sock'
    hosted_socket = os.environ.get('KAT_HOSTED_DOCKER_SOCKET')
    if hosted_socket is not None:
        hosted_socket = hosted_socket.removeprefix('unix://')
        # The pinned setup-docker action owns a separate local daemon. Never
        # accept a TCP/remote Docker override or use this on the user's fixture.
        if (os.environ.get('GITHUB_ACTIONS') != 'true'
                or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
                or not Path(hosted_socket).is_absolute()
                or not Path(hosted_socket).is_socket()):
            raise ValueError('Explicit hosted-runner local Docker socket required')
        docker_host = 'unix://' + hosted_socket
    env.update(PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='2',
               NO_PROXY='127.0.0.1,127.0.0.2,localhost', DOCKER_HOST=docker_host)
    return env


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    if port == 8765:
        return free_port()
    return port


def owned_container(container_id, name, port):
    docker_env = clean_environment()
    inspected = command(['docker', 'inspect', '--format',
        '{{.Id}} {{.Name}} {{index .Config.Labels "kat.siwc.test"}}', container_id], env=docker_env).split()
    mapped = command(['docker', 'port', container_id, '5432/tcp'], env=docker_env)
    return (len(inspected) == 3 and inspected[0] == container_id and
            inspected[1] == '/' + name and inspected[2] == 'isolated' and
            re.fullmatch(r'127\.0\.0\.1:[0-9]+', mapped) and
            mapped == f'127.0.0.1:{port}')


def start_fixture(env):
    name = 'kat-origin-isolated-' + secrets.token_hex(7)
    container_id = command(['docker', 'run', '-d', '--name', name,
        '--label', 'kat.siwc.test=isolated', '-e', 'POSTGRES_USER=kat_test',
        '-e', 'POSTGRES_PASSWORD=' + PASSWORD, '-e', 'POSTGRES_DB=kat_test',
        '-p', '127.0.0.1::5432', '--memory', '512m', '--cpus', '2',
        'postgres:16.14-alpine'], env=env)
    try:
        mapped = command(['docker', 'port', container_id, '5432/tcp'], env=env)
        if not re.fullmatch(r'127\.0\.0\.1:[0-9]+', mapped):
            raise RuntimeError('Fixture port is not loopback-only')
        port = int(mapped.rsplit(':', 1)[1])
        if not owned_container(container_id, name, port):
            raise RuntimeError('Fixture identity mismatch')
        for _ in range(40):
            ready = subprocess.run(['pg_isready', '-h', '127.0.0.1', '-p', str(port),
                '-U', 'kat_test', '-d', 'kat_test'], env=env, capture_output=True)
            if ready.returncode == 0:
                env['KAT_ISOLATED_TEST_CONTAINER'] = name
                env['KAT_ISOLATED_TEST_DSN'] = ('host=127.0.0.1 port=' + str(port) +
                    ' dbname=kat_test user=kat_test password=' + PASSWORD)
                return container_id, name, port
            import time
            time.sleep(0.5)
        raise RuntimeError('Isolated fixture did not become ready')
    except Exception:
        # Never remove an unverified container; report its ID without credentials.
        if 'port' in locals() and owned_container(container_id, name, port):
            command(['docker', 'rm', '-f', container_id], env=clean_environment())
        raise


def browser_env(base, profile, dist):
    env = base.copy()
    env.update(KAT_BROWSER_TEST_PORT=str(free_port()), KAT_BROWSER_DIST=str(dist),
               KAT_BROWSER_SIWC='1' if profile in ('siwc', 'clock') else '0',
               KAT_BROWSER_FAKE_PLAN='0' if profile == 'siwc' else '1',
               KAT_BROWSER_CLOCK_CHART='1' if profile == 'clock' else '0')
    if profile == 'clock':
        env['KAT_BROWSER_FIXED_CLOCK'] = '2026-01-01T01:15:42+00:00'
    return env


def run_profile(profile, env, out, results, tests=(), browser_grep=None, *, timings,
                private_layout_reference=False):
    python = ROOT / '.venv-swiss/bin/python'
    web = ROOT / 'web'
    if profile == 'backend':
        argv, cwd = [str(python), '-m', 'm2.validation_runner', '--timings',
                     str(out / 'backend-timing.json'), *tests], ROOT
    elif profile == 'probes':
        argv, cwd = [str(python), '-m', 'unittest', 'discover', '-s', 'probes', '-p', 'test_*.py', '-q'], ROOT
    else:
        dist = out / 'normal-dist'
        if not (dist / 'index.html').is_file():
            with timed_stage(timings, 'normal-build'):
                command(['npm', 'run', 'build', '--', '--outDir', str(dist)], cwd=web, env=env,
                        log=out / 'normal-build.log')
        env = browser_env(env, profile, dist)
        if profile == 'browser' and private_layout_reference:
            env['KAT_LAYOUT_PRIVATE_REFERENCE'] = '1'
        argv, cwd = [str(web / 'node_modules/.bin/playwright'), 'test'], web
        if browser_grep:
            argv.extend(['--grep', browser_grep])
    logfile = out / (profile + '.log')
    with timed_stage(timings, profile + '-tests'):
        command(argv, cwd=cwd, env=env, log=logfile)
    text = logfile.read_text(errors='replace')
    summary = re.findall(r'\b\d+ (?:passed|skipped|failed)\b|Ran \d+ tests?|^OK$', text, re.M)
    results[profile] = {'status': 'passed', 'summary': summary[-3:],
                        'log': str(logfile.relative_to(ROOT))}
    if profile == 'backend':
        results[profile]['diagnostics'] = json.loads((out / 'backend-timing.json').read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--profile', choices=(*PROFILES, 'all'),
                           help='One profile, or all (default)')
    selection.add_argument('--profiles', nargs='+', choices=PROFILES,
                           help='Run selected profiles sequentially, sharing fixture and run-local builds')
    parser.add_argument('--execute', action='store_true', help='Create isolated fixture and run selected profile')
    parser.add_argument('--tests', nargs='+', default=[], help='Explicit m2.test_* or deploy.test_* unittest selectors (backend only)')
    parser.add_argument('--browser-grep', help='Playwright title filter (browser profiles only)')
    parser.add_argument('--private-layout-reference', action='store_true',
                        help='Explicitly compare with an available approved private mockup and historical CSS')
    args = parser.parse_args()
    if args.profiles:
        selected = tuple(dict.fromkeys(args.profiles))
    elif args.profile in (None, 'all'):
        selected = PROFILES
    else:
        selected = (args.profile,)
    if args.tests and ('backend' not in selected or any(not re.fullmatch(
            r'(?:m2|deploy)\.test_[a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+){0,2}', name) for name in args.tests)):
        parser.error('--tests requires a backend profile and m2.test_* or deploy.test_* selectors')
    if args.browser_grep and not any(profile in selected for profile in PROFILES[2:]):
        parser.error('--browser-grep requires a browser profile')
    if args.private_layout_reference and 'browser' not in selected:
        parser.error('--private-layout-reference requires the normal browser profile')
    report = {'action': 'execute' if args.execute else 'plan', 'git': git_state(),
              'selected': selected, 'unrun': list(selected), 'results': {}, 'timings': [],
              'status': 'stopped',
              'filters': {'tests': args.tests, 'browser_grep': args.browser_grep,
                          'private_layout_reference': args.private_layout_reference}}
    fixture = None
    started = perf_counter()
    try:
        if args.execute:
            os.umask(0o077)
            out = ROOT / '.local' / 'kat-validation' / secrets.token_hex(8)
            out.mkdir(parents=True, mode=0o700)
            report['logs_dir'] = str(out.relative_to(ROOT))
            env = clean_environment()
            if any(profile != 'probes' for profile in selected):
                with timed_stage(report['timings'], 'fixture-start'):
                    fixture = start_fixture(env)
                report['fixture'] = 'owned-isolated-loopback'
            if 'backend' in selected:
                env['KAT_ISOLATED_TEST_TEMPLATE'] = 'kat_m2_template_' + secrets.token_hex(6)
                env['KAT_ISOLATED_TEST_RUN_DIR'] = str(out)
                with timed_stage(report['timings'], 'template-setup'):
                    command([str(ROOT / '.venv-swiss/bin/python'), '-m', 'm2.test_template'],
                            env=env, log=out / 'template.log')
            for profile in selected:
                report['unrun'].remove(profile)
                report['results'][profile] = {'status': 'stopped'}
                run_profile(profile, env, out, report['results'], args.tests, args.browser_grep,
                            timings=report['timings'], private_layout_reference=args.private_layout_reference)
        report['status'] = 'ok'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        report['status'] = 'stopped'
        report['error_type'] = type(exc).__name__  # never include command, DSN, stdout or input
    finally:
        if fixture:
            container_id, name, port = fixture
            try:
                with timed_stage(report['timings'], 'fixture-cleanup'):
                    if not owned_container(container_id, name, port):
                        report['fixture_cleanup'] = 'identity-mismatch-manual-inspection-required'
                        raise RuntimeError('Fixture identity changed')
                    command(['docker', 'rm', '-f', container_id], env=clean_environment())
                    report['fixture_cleanup'] = 'owned-container-removed'
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                report.setdefault('fixture_cleanup', 'stopped-manual-inspection-required')
                report['cleanup_error_type'] = type(exc).__name__
                report['status'] = 'stopped'
        report['total_seconds'] = round(perf_counter() - started, 3)
        print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
