#!/usr/bin/env python3
"""Run repository test profiles only against a freshly owned synthetic fixture."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from deploy.qualification_inventory import read_json, check_execution
from deploy.validation_budget import (budget, COMMAND_SECONDS, CONTROL_SECONDS,
                                     INTERRUPT_SECONDS, KILL_WAIT_SECONDS, READINESS_SECONDS)

PROFILES = ('backend', 'probes', 'browser', 'siwc', 'clock')
PASSWORD = 'synthetic_test_only'  # disposable test container, never a user credential


def command(argv, *, env=None, cwd=ROOT, log=None, timeout=None):
    timeout = timeout if timeout is not None else COMMAND_SECONDS if log else CONTROL_SECONDS
    if log is None:
        return subprocess.check_output(argv, cwd=cwd, env=env, text=True, timeout=timeout).strip()
    with log.open('x') as output:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            try:
                process.wait(timeout=timeout)
            except BaseException:
                # Give Playwright its native interruption/teardown path before
                # force-killing. A parent-only timeout otherwise orphans fixtures.
                try:
                    os.killpg(process.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=INTERRUPT_SECONDS)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=KILL_WAIT_SECONDS)
                raise  # Preserve the original timeout/interrupt, never a pass.
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, argv)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=KILL_WAIT_SECONDS)


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


def git_tree():
    return command(['git', 'rev-parse', 'HEAD^{tree}'])


def browser_shard(value):
    if not re.fullmatch(r'[1-9][0-9]?/[1-9][0-9]?', value):
        raise argparse.ArgumentTypeError('Browser shard must be index/count')
    index, count = map(int, value.split('/'))
    if not 1 <= index <= count <= 64:
        raise argparse.ArgumentTypeError('Browser shard requires 1 <= index <= count <= 64')
    return value


def discover_browser(profile, env, out, *, shard=None, grep=None):
    path = out / (profile + '-inventory.json')
    argv = [str(ROOT / 'web/node_modules/.bin/playwright'), 'test', '--list', '--forbid-only',
            '--reporter=./inventory-reporter.cjs']
    if shard:
        argv.append('--shard=' + shard)
    if grep:
        argv.extend(['--grep', grep])
    command(argv, cwd=ROOT / 'web', env=env | {'KAT_BROWSER_INVENTORY_FILE': str(path)},
            log=out / (profile + '-discovery.log'))
    return read_json(path)


def clean_environment(*, include_browser=False):
    # The fixtures otherwise fall back to the user's database/8765 when unset.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('KAT_', 'PG', 'VITE_KAT_', 'OPENAI_', 'ANTHROPIC_',
                                  'AZURE_', 'AWS_', 'GOOGLE_', 'SIWC_')) and
           key.upper() not in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY') and
           not key.startswith('DOCKER_')}
    # The only ambient KAT browser input admitted: an intentional executable,
    # never fixture paths, ports, provider flags or database configuration.
    browser = os.environ.get('KAT_BROWSER_BIN') if include_browser else None
    if browser is not None:
        path = Path(browser)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError('KAT_BROWSER_BIN must name an existing absolute executable file')
        env['KAT_BROWSER_BIN'] = browser
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
                '-U', 'kat_test', '-d', 'kat_test'], env=env, capture_output=True,
                timeout=READINESS_SECONDS)
            if ready.returncode == 0:
                env['KAT_ISOLATED_TEST_CONTAINER'] = name
                env['KAT_ISOLATED_TEST_DSN'] = ('host=127.0.0.1 port=' + str(port) +
                    ' dbname=kat_test user=kat_test password=' + PASSWORD)
                return container_id, name, port
            import time
            time.sleep(0.5)
        raise RuntimeError('Isolated fixture did not become ready')
    except BaseException:
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


def browser_location(location):
    """Only repository test-code coordinates; never messages or external paths."""
    path = Path(location.get('file', ''))
    if path.is_absolute():
        try:
            path = path.relative_to(ROOT / 'web')
        except ValueError:
            return None
    elif not path.parts or path.parts[0] != 'tests':
        path = Path('tests') / path
    name = path.as_posix()
    if ('..' in path.parts or not re.fullmatch(r'tests/[A-Za-z0-9_/.-]{1,240}\.ts', name)
            or not (ROOT / 'web' / path).is_file()
            or type(location.get('line')) is not int or location['line'] < 1):
        return None
    return {'file': 'web/' + name, 'line': location['line']}


def browser_errors(errors):
    locations = []
    for error in errors:
        candidates = [error.get('location', {})]
        # Native JSON has assertion stack coordinates but also raw message/source
        # snippets. Extract coordinates only, never publish the stack itself.
        for match in re.finditer(r'(?:\s|\()([/A-Za-z0-9_.-]+\.ts):(\d+):\d+(?:\)|$)',
                                 error.get('stack', ''), re.M):
            candidates.append({'file': match[1], 'line': int(match[2])})
        for candidate in candidates:
            location = browser_location(candidate)
            if location and location not in locations:
                locations.append(location)
    return locations[-8:]


def browser_diagnostics(path):
    with path.open() as source:
        text = source.read(8 * 1024 * 1024 + 1)
    if len(text) > 8 * 1024 * 1024:
        raise ValueError('Oversized browser report')
    report = json.loads(text)
    failures = []
    total = 0

    def record(failure):
        nonlocal total
        total += 1
        if len(failures) < 20:
            failures.append(failure)

    suites = list(report['suites'])
    while suites:
        suite = suites.pop()
        suites.extend(suite.get('suites', []))
        for spec in suite.get('specs', []):
            for test in spec['tests']:
                for result in test['results']:
                    status = result['status']
                    if status in ('failed', 'timedOut', 'interrupted', 'passed') and status != test['expectedStatus']:
                        record({'status': status, 'test': browser_location(spec),
                                'locations': browser_errors(result.get('errors', []))})
    for error in report.get('errors', []):
        record({'status': 'global_error', 'test': None, 'locations': browser_errors([error])})
    return {'counts': {key: value for key, value in report['stats'].items()
                       if key in ('expected', 'unexpected', 'flaky', 'skipped') and type(value) is int},
            'failures': failures, 'failure_count': total,
            'failures_omitted': total - len(failures)}


def browser_progress(path):
    with path.open() as source:
        text = source.read(16385)
    if len(text) > 16384:
        raise ValueError('Oversized browser checkpoint')
    report = json.loads(text)
    if report['status'] not in ('initializing', 'running', 'passed', 'failed', 'timedout', 'interrupted'):
        raise ValueError('Unknown browser checkpoint status')
    public = {'status': report['status']}
    for key in ('total', 'started', 'finished', 'global_errors', 'active_omitted'):
        if type(report[key]) is not int or report[key] < 0:
            raise ValueError('Invalid browser checkpoint count')
        public[key] = report[key]
    public['active'] = [browser_location(item) if isinstance(item, dict) else None
                        for item in report['active'][:8]]
    for key in ('last_started_test', 'last_finished_test'):
        value = report.get(key)
        public[key] = browser_location(value) if isinstance(value, dict) else None
    public['outcomes'] = {key: value for key, value in report['outcomes'].items()
                          if key in ('passed', 'failed', 'timedOut', 'skipped', 'interrupted')
                          and type(value) is int and value >= 0}
    public['resources'] = {key: value for key, value in report['resources'].items()
                           if key in ('node_rss', 'free_memory', 'total_memory', 'load1')
                           and type(value) in (int, float) and 0 <= value < 2**60}
    return public


def run_profile(profile, env, out, results, tests=(), browser_grep=None, *, timings,
                private_layout_reference=False, shard=None):
    python = ROOT / '.venv-swiss/bin/python'
    web = ROOT / 'web'
    if profile == 'backend':
        argv, cwd = [str(python), '-m', 'tests.runner', '--timings',
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
        env['PLAYWRIGHT_JSON_OUTPUT_FILE'] = str(out / (profile + '-report.json'))
        env['KAT_BROWSER_PROGRESS_FILE'] = str(out / (profile + '-progress.json'))
        env['KAT_BROWSER_INVENTORY_FILE'] = str(out / (profile + '-executed.json'))
        discovered = discover_browser(profile, env, out, shard=shard, grep=browser_grep)
        argv, cwd = [str(web / 'node_modules/.bin/playwright'), 'test', '--forbid-only', '--retries=0',
                     '--reporter=line,json,./validation-reporter.cjs,./inventory-reporter.cjs'], web
        if shard:
            argv.append('--shard=' + shard)
        if browser_grep:
            argv.extend(['--grep', browser_grep])
    logfile = out / (profile + '.log')
    results[profile] = {'status': 'stopped', 'log': str(logfile.relative_to(ROOT))}
    if profile in PROFILES[2:]:
        results[profile]['inventory'] = discovered
    try:
        with timed_stage(timings, profile + '-tests'):
            command(argv, cwd=cwd, env=env, log=logfile)
    except (OSError, subprocess.SubprocessError) as exc:
        results[profile]['error_type'] = type(exc).__name__
        if isinstance(exc, subprocess.CalledProcessError):
            results[profile]['returncode'] = exc.returncode
        elif isinstance(exc, subprocess.TimeoutExpired):
            results[profile]['timeout_seconds'] = exc.timeout
        raise
    finally:
        if profile == 'backend':
            # This is the runner's structured, message-free report, never backend.log.
            # Preserve the original process failure if its report is absent/corrupt.
            try:
                with (out / 'backend-timing.json').open() as source:
                    diagnostics = source.read(131073)
                if len(diagnostics) > 131072:
                    raise ValueError('Oversized diagnostics')
                results[profile]['diagnostics'] = json.loads(diagnostics)
            except (OSError, ValueError):
                results[profile]['diagnostics_status'] = 'unavailable'
        elif profile in PROFILES[2:]:
            try:
                results[profile]['progress'] = browser_progress(out / (profile + '-progress.json'))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                results[profile]['progress_status'] = 'unavailable'
            try:
                results[profile]['diagnostics'] = browser_diagnostics(out / (profile + '-report.json'))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                results[profile]['diagnostics_status'] = 'unavailable'
    if profile in PROFILES[2:]:
        executed = read_json(out / (profile + '-executed.json'))
        check_execution(discovered, executed)
        results[profile]['executed'] = executed
    text = logfile.read_text(errors='replace')
    summary = re.findall(r'\b\d+ (?:passed|skipped|failed)\b|Ran \d+ tests?|^OK$', text, re.M)
    if results[profile].get('diagnostics_status') == 'unavailable':
        raise RuntimeError('Profile diagnostics unavailable')
    results[profile].update(status='passed', summary=summary[-3:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--profile', choices=(*PROFILES, 'all'),
                           help='One profile, or all (default)')
    selection.add_argument('--profiles', nargs='+', choices=PROFILES,
                           help='Run selected profiles sequentially, sharing fixture and run-local builds')
    parser.add_argument('--execute', action='store_true', help='Create isolated fixture and run selected profile')
    parser.add_argument('--tests', nargs='+', default=[], help='Explicit tests.<capability>.test_* unittest selectors (backend only)')
    parser.add_argument('--browser-grep', help='Playwright title filter (browser profiles only)')
    parser.add_argument('--browser-shard', type=browser_shard, help='Main browser index/count; no filters')
    parser.add_argument('--inventory-only', action='store_true', help='Native browser discovery without fixtures/build')
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
            r'tests\.[a-z_]+\.test_[a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+){0,2}', name) for name in args.tests)):
        parser.error('--tests requires a backend profile and tests.<capability>.test_* selectors')
    if args.browser_grep and not any(profile in selected for profile in PROFILES[2:]):
        parser.error('--browser-grep requires a browser profile')
    if args.private_layout_reference and 'browser' not in selected:
        parser.error('--private-layout-reference requires the normal browser profile')
    if args.browser_shard and (selected != ('browser',) or args.browser_grep or args.tests or args.private_layout_reference):
        parser.error('--browser-shard requires only the complete main browser profile')
    if args.inventory_only and (selected != ('browser',) or args.browser_grep or args.tests or args.private_layout_reference):
        parser.error('--inventory-only requires only the complete main browser profile')
    report = {'action': 'execute' if args.execute else 'plan', 'git': git_state(),
              'tree': git_tree(), 'budget': budget(selected, inventory_only=args.inventory_only),
              'browser_shard': args.browser_shard, 'inventory_only': args.inventory_only,
              'selected': selected, 'unrun': list(selected), 'results': {}, 'timings': [],
              'status': 'stopped',
              'filters': {'tests': args.tests, 'browser_grep': args.browser_grep,
                          'private_layout_reference': args.private_layout_reference}}
    fixture = None
    previous_term = None
    started = perf_counter()
    try:
        if args.execute:
            def interrupted(_signum, _frame):
                raise KeyboardInterrupt
            previous_term = signal.signal(signal.SIGTERM, interrupted)
            os.umask(0o077)
            out = ROOT / '.local' / 'kat-validation' / secrets.token_hex(8)
            out.mkdir(parents=True, mode=0o700)
            report['logs_dir'] = str(out.relative_to(ROOT))
            env = clean_environment(include_browser=any(profile in PROFILES[2:] for profile in selected))
            if args.inventory_only:
                browser = browser_env(env, 'browser', out / 'unused-dist')
                report['results']['browser'] = {'status': 'discovered',
                    'inventory': discover_browser('browser', browser, out, shard=args.browser_shard)}
                report['unrun'] = []
            if not args.inventory_only and any(profile != 'probes' for profile in selected):
                with timed_stage(report['timings'], 'fixture-start'):
                    fixture = start_fixture(env)
                report['fixture'] = 'owned-isolated-loopback'
                report['fixture_identity'] = dict(zip(('container_id', 'name', 'port'), fixture))
                # Keep identity available even if an outer harness kills before final JSON.
                with (out / 'fixture-identity.json').open('x') as identity_file:
                    json.dump(report['fixture_identity'], identity_file, sort_keys=True)
            if 'backend' in selected:
                env['KAT_ISOLATED_TEST_TEMPLATE'] = 'kat_m2_template_' + secrets.token_hex(6)
                env['KAT_ISOLATED_TEST_RUN_DIR'] = str(out)
                with timed_stage(report['timings'], 'template-setup'):
                    command([str(ROOT / '.venv-swiss/bin/python'), '-m', 'tests.support.template'],
                            env=env, log=out / 'template.log')
            for profile in (() if args.inventory_only else selected):
                report['unrun'].remove(profile)
                report['results'][profile] = {'status': 'stopped'}
                run_profile(profile, env, out, report['results'], args.tests, args.browser_grep,
                            timings=report['timings'], private_layout_reference=args.private_layout_reference,
                            shard=args.browser_shard)
        report['status'] = 'ok'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
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
        if previous_term is not None:
            signal.signal(signal.SIGTERM, previous_term)
        report['total_seconds'] = round(perf_counter() - started, 3)
        print(json.dumps(report, sort_keys=True))
        if report['status'] != 'ok':
            # qualify redirects stdout to its local witness. Keep failure evidence
            # in the hosted job log even without an upload step in the pinned YAML.
            # Exclude filters (arbitrary input), raw logs, messages and environment.
            failure = {key: report[key] for key in (
                'git', 'selected', 'unrun', 'results', 'timings', 'error_type',
                'fixture_cleanup', 'cleanup_error_type') if key in report}
            print('kat validation stopped: ' + json.dumps(failure, sort_keys=True),
                  file=sys.stderr, flush=True)
    return 0 if report['status'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
