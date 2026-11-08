"""Build-once qualification, sequential locally or joined from isolated CI lanes.

No signing, upload, deployment, or trust activation. --execute is not approval.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from deploy.release_pipeline import ROOT
from deploy.qualification_evidence import LANES, PROFILES, assemble, write_lane
from deploy.qualification_inventory import read_json

VALIDATOR = '.agents/skills/kat-isolated-validation/scripts/validate.py'


def run(*argv, timeout=3600, output=None):
    return subprocess.run(argv, cwd=ROOT, timeout=timeout, check=True, stdout=output)


def identity():
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    if git('status', '--porcelain'):
        raise ValueError('Qualification requires clean committed source')
    source = {'commit': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}')}
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        run_id = os.environ.get('GITHUB_RUN_ID', '')
        if (os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
                or os.environ.get('GITHUB_SHA') != source['commit']
                or not run_id.isdecimal() or int(run_id) < 1
                or os.environ.get('GITHUB_RUN_ATTEMPT') != '1'):
            raise ValueError('Exact hosted source and first run attempt required')
        return source | {'run_id': run_id, 'run_attempt': 1}
    return source | {'run_id': 'local', 'run_attempt': 1}


def run_lane(lane, source):
    folder = ROOT / '.local/qualification-lanes' / lane
    folder.mkdir(parents=True, exist_ok=False)
    report_path = folder / 'report.json'
    receipt_path = ROOT / '.local/fresh-production/package' / source['commit'][:12] / 'receipt.json'
    summary = {'lane': lane, 'identity': source, 'status': 'stopped'}
    started = perf_counter()
    try:
        # Retrieval tests and native packaging use the same pinned public embedding cache.
        run(sys.executable, '-m', 'deploy.prepare_public_model')
        if lane == 'native':
            run(sys.executable, 'deploy/build_local.py')
            with report_path.open('x') as output:
                run(sys.executable, '-m', 'deploy.smoke_local', '--receipt', str(receipt_path),
                    '--execute', output=output)
            write_lane(folder, lane, source, report_path, receipt_path=receipt_path)
        else:
            selected = PROFILES if lane == 'all' else LANES[lane]
            argv = [sys.executable, VALIDATOR, '--profiles', *selected, '--execute']
            if lane.startswith('browser-'):
                argv.extend(['--browser-shard', lane.removeprefix('browser-') + '/4'])
            with report_path.open('x') as output:
                run(*argv, output=output)
            write_lane(folder, lane, source, report_path)
        summary['status'] = 'passed'
    finally:
        summary['seconds'] = round(perf_counter() - started, 3)
        (folder / 'summary.json').write_text(json.dumps(summary, sort_keys=True) + '\n')
    return folder / 'evidence.json', receipt_path


def qualify():
    source = identity()
    synthetic, _ = run_lane('all', source)
    native, receipt = run_lane('native', source)
    full = read_json(synthetic.with_name('report.json'))['results']['browser']['inventory']
    assemble([synthetic, native], source, full, receipt,
             ROOT / '.local/release-qualification' / source['commit'], sequential=True)
    print(json.dumps({'status': 'qualified', 'package': str(receipt.parent.relative_to(ROOT)),
                      'commit': source['commit']}))


def join(evidence, receipt):
    source = identity()
    reports = ROOT / '.local/qualification-discovery'
    reports.mkdir(parents=True, exist_ok=False)
    with (reports / 'report.json').open('x') as output:
        run(sys.executable, VALIDATOR, '--profile', 'browser', '--inventory-only', '--execute', output=output)
    discovered = read_json(reports / 'report.json')
    if (discovered['git'] != {'sha': source['commit'], 'dirty': False}
            or discovered['tree'] != source['tree'] or discovered['status'] != 'ok'
            or not discovered['inventory_only'] or discovered['browser_shard'] is not None):
        raise ValueError('Join discovery differs from exact unfiltered source')
    assemble(sorted(evidence.glob('*/evidence.json')), source,
             discovered['results']['browser']['inventory'], receipt,
             ROOT / '.local/release-qualification' / source['commit'])
    print(json.dumps({'status': 'qualified', 'package': str(receipt.parent.relative_to(ROOT)),
                      'commit': source['commit']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--lane', choices=(*LANES, 'native'))
    parser.add_argument('--join', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if (args.lane and (args.join or args.receipt)) or bool(args.join) != bool(args.receipt):
        parser.error('Choose one lane or join with exact native receipt')
    if not args.execute:
        print('Plan: isolated lanes or sequential all; exact native archive; complete hash-bound evidence join.')
    elif args.lane:
        run_lane(args.lane, identity())
    elif args.join:
        join(args.join, args.receipt)
    else:
        qualify()


if __name__ == '__main__':
    main()
