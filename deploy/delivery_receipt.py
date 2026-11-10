"""Local evidence index and generated summary; never a release attestation/gate.

Only Git identity and file integrity are verified here. Local runner reports are
unsigned reports of execution, not proofs supplied by an arbitrary JSON author.
External review/qualification/enrollment/native/serving artifacts stay references;
their original independent authority is neither recreated nor weakened here.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STATES = ('reviewed', 'qualified', 'enrolled', 'deployed', 'serving')


def git(repository, *args):
    return subprocess.check_output(['git', '-C', str(repository), *args])


def source_identity(repository, base):
    commit = git(repository, 'rev-parse', 'HEAD').decode().strip()
    base = git(repository, 'rev-parse', '--verify', base + '^{commit}').decode().strip()
    if git(repository, 'status', '--porcelain'):
        raise ValueError('Commit source before creating an exact-tip receipt')
    subprocess.run(['git', '-C', str(repository), 'merge-base', '--is-ancestor', base, commit], check=True)
    diff = git(repository, 'diff', '--binary', base, commit)
    return {'commit': commit, 'tree': git(repository, 'rev-parse', 'HEAD^{tree}').decode().strip(),
            'base': base, 'diff_sha256': sha256(diff).hexdigest(), 'changed': bool(diff)}


def reference(path, producer):
    path = path.absolute()
    if path.resolve() != path or not path.is_file():
        raise ValueError('Missing or indirect evidence reference')
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest(),
            'producer': producer, 'provenance': 'local-unsigned-reference-not-attestation'}


def focused(path, repository, source):
    ref = reference(path, 'kat-isolated-validation')
    report = json.loads(path.read_bytes())
    if (report.get('git') != {'sha': source['commit'], 'dirty': False}
            or report.get('tree') != source['tree']):
        return {'state': 'foreign-or-dirty-report', 'evidence': [ref]}
    if (report.get('action') != 'execute' or report.get('inventory_only') is not False
            or report.get('fixture') != 'owned-isolated-loopback'
            or not report.get('selected') or not isinstance(report.get('results'), dict)
            or not isinstance(report.get('filters'), dict)
            or not re.fullmatch(r'\.local/kat-validation/[a-f0-9]{16}', report.get('logs_dir', ''))):
        return {'state': 'unsupported-report', 'evidence': [ref]}
    state = 'local-reported-pass'
    if (report.get('status') != 'ok' or report.get('unrun') != []
            or report.get('fixture_cleanup') != 'owned-container-removed'
            or set(report['results']) != set(report['selected'])):
        state = 'failed-or-incomplete-report'
    evidence = [ref]
    for profile, result in report['results'].items():
        log = repository / result.get('log', '')
        directory = repository / report['logs_dir']
        if log.parent != directory or not log.resolve().is_relative_to(directory.resolve()):
            raise ValueError('Runner log is not in its owned evidence directory')
        evidence.append(reference(log, 'kat-isolated-validation/' + profile))
        if result.get('status') != 'passed':
            state = 'failed-or-incomplete-report'
        if profile == 'backend':
            details = result.get('diagnostics', {})
            if (details.get('status') != 'passed' or details.get('failure_count') != 0
                    or details.get('tests_run', 0) < 1):
                state = 'failed-or-incomplete-report'
    return {'state': state, 'evidence': evidence, 'selected': report['selected'],
            'filters': report['filters'], 'seconds': report.get('total_seconds'),
            'results': {name: {'status': result.get('status'),
                       'tests_run': result.get('diagnostics', {}).get('tests_run')}
                        for name, result in report['results'].items()}}


def external_reference(path, kind, source):
    ref = reference(path, kind + '/external-producer')
    ref['source_binding'] = 'not-established'
    if path.suffix == '.json':
        body = json.loads(path.read_bytes())
        identity = body.get('artifact', body) if isinstance(body, dict) else {}
        if isinstance(identity, dict) and 'commit' in identity:
            ref['source_binding'] = ('matches' if all(identity.get(key) == source[key]
                                      for key in ('commit', 'tree')) else 'foreign-or-incomplete')
    return ref


def prepare(repository, base, request, reports=(), external=None, limits=()):
    source = source_identity(repository, base)
    runs = [focused(path, repository, source) for path in reports]
    state = ('unrun' if not runs else 'local-reported-pass' if all(
        run['state'] == 'local-reported-pass' for run in runs) else 'not-established')
    states = {'implemented': {'state': 'committed-changes' if source['changed'] else 'unchanged'},
              'focused-tested': {'state': state, 'runs': runs}}
    for name in STATES:
        paths = (external or {}).get(name, [])
        # No status/approval Boolean, file name or arbitrary JSON can promote this.
        states[name] = {'state': 'unverified-reference' if paths else 'held-unrun',
                        'evidence': [external_reference(path, name, source) for path in paths]}
    if source_identity(repository, base) != source:
        raise ValueError('Source changed while collecting evidence')
    return {'contract': 1, 'request': request, 'status': 'LOCAL-ONLY HOLD',
            'source': source, 'states': states,
            'limits': ['Independent review, full qualification, hosted CI, trust enrollment and deployment held',
                       'Execution reports are unsigned; integrity/source checks are not release attestation',
                       'No measured hosted speedup or active production optimization', *limits]}


def evidence_refs(record):
    for value in record['states'].values():
        yield from value.get('evidence', [])
        for run in value.get('runs', []):
            yield from run['evidence']


def summary(record):
    # This command cannot render arbitrary user JSON as successful release proof.
    if (record['contract'] != 1 or record['status'] != 'LOCAL-ONLY HOLD'
            or set(record['states']) != {'implemented', 'focused-tested', *STATES}
            or record['states']['implemented']['state'] not in ('committed-changes', 'unchanged')
            or record['states']['focused-tested']['state'] not in ('unrun', 'local-reported-pass', 'not-established')
            or any(record['states'][name]['state'] not in ('held-unrun', 'unverified-reference')
                   for name in STATES)):
        raise ValueError('Unsupported delivery assertion; preserve original producer authority')
    # Recheck frozen references when generating a later checkpoint/handoff.
    for item in evidence_refs(record):
        current = reference(Path(item['path']), item['producer'])
        if any(item.get(key) != value for key, value in current.items()):
            raise ValueError('Evidence changed since the receipt was created')
    source = record['source']
    states = record['states']
    counts = [result['tests_run'] for run in states['focused-tested'].get('runs', [])
              for result in run.get('results', {}).values() if result.get('tests_run') is not None]
    return '\n'.join([
        f"{record['status']} — {record['request']}",
        f"Source {source['commit'][:12]} / tree {source['tree'][:12]}; diff SHA256 {source['diff_sha256']}",
        f"Implemented: {states['implemented']['state']}; focused tests: {states['focused-tested']['state']}"
        + (f" ({sum(counts)} reported backend tests)." if counts else '.'),
        '; '.join(f"{name}: {states[name]['state']}" for name in STATES) + '.',
        *[f'- {limit}' for limit in record['limits']],
    ]) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=ROOT)
    parser.add_argument('--base')
    parser.add_argument('--request')
    parser.add_argument('--focused', type=Path, action='append', default=[])
    for name in STATES:
        parser.add_argument('--' + name, type=Path, action='append', default=[])
    parser.add_argument('--limit', action='append', default=[])
    parser.add_argument('--output', type=Path, help='Exclusively create local record; no pipelines run')
    parser.add_argument('--summary', type=Path, help='Verify frozen evidence and summarize an existing record')
    args = parser.parse_args()
    if args.summary:
        print(summary(json.loads(args.summary.read_text())), end='')
        return
    if not args.base or not args.request:
        parser.error('--base and --request are required for preparation')
    record = prepare(args.repository.resolve(), args.base, args.request, args.focused,
                     {name: getattr(args, name) for name in STATES}, args.limit)
    if args.output:
        with args.output.open('x') as output:
            json.dump(record, output, indent=2)
            output.write('\n')
        print(summary(record), end='')
    else:
        print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
