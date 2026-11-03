"""Repository-owned synthetic qualification and build-once release candidate.

No upload, provider, user fixture or deployment. CI and local use the same entry
point; the explicit execute flag is not itself permission outside assigned scope.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from deploy.release_pipeline import ROOT, artifact, digest


def run(*argv, timeout=3600, output=None):
    result = subprocess.run(argv, cwd=ROOT, timeout=timeout, check=True,
                            stdout=output)
    return result


def qualify():
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise ValueError('Qualification requires clean committed source')
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    reports = ROOT / '.local/release-qualification' / sha
    reports.mkdir(parents=True, exist_ok=False)
    run(sys.executable, '-m', 'deploy.prepare_public_model')
    with (reports / 'synthetic.json').open('x') as output:
        run(sys.executable, '.agents/skills/kat-isolated-validation/scripts/validate.py',
            '--profile', 'all', '--execute', output=output)
    report = json.loads((reports / 'synthetic.json').read_text())
    if report['status'] != 'ok' or report['unrun'] or report['git'] != {'sha': sha, 'dirty': False}:
        raise ValueError('Incomplete or foreign-source qualification')
    run(sys.executable, 'deploy/build_local.py')
    receipt_path = ROOT / '.local/fresh-production/package' / sha[:12] / 'receipt.json'
    receipt, _, _, _ = artifact(receipt_path)
    with (reports / 'native.json').open('x') as output:
        run(sys.executable, '-m', 'deploy.smoke_local', '--receipt', str(receipt_path),
            '--execute', output=output)
    native = json.loads((reports / 'native.json').read_text())
    if native['status'] != 'passed' or native['cleanup'] != 'passed':
        raise ValueError('Native qualification or cleanup incomplete')
    witness = {'commit': receipt['commit'], 'tree': receipt['tree'],
               'receipt_sha256': digest(receipt_path),
               'image_archive_sha256': receipt['image_archive_sha256'],
               'source_offer_sha256': receipt['source_offer_sha256'],
               'synthetic_report_sha256': digest(reports / 'synthetic.json'),
               'native_report_sha256': digest(reports / 'native.json')}
    (receipt_path.parent / 'qualification.json').write_text(json.dumps(witness, sort_keys=True) + '\n')
    print(json.dumps({'status': 'qualified', 'package': str(receipt_path.parent.relative_to(ROOT)),
                      'commit': sha}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    if parser.parse_args().execute:
        qualify()
    else:
        print('Plan: pinned public model; all isolated suites including deploy; build once; native Compose; hash-bound qualification.')
