"""Write a disabled, exact-source adoption plan. Never installs or generates keys.

Reading a real target policy belongs to separately approved adoption, not source
qualification. Tests use only a synthetic policy and public verifier/trust files.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tarfile

from deploy.release_ci_access import REPOSITORY, REPOSITORY_ID, canonical
from deploy.release_pipeline import ROOT, artifact, digest

HELPERS = ('release_access.py', 'release_remote.py', 'release_pipeline.py', 'release_ci_access.py')


def prepare(manual_policy, signer_sha, verifier, trusted_root, output, *, running_receipt):
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise ValueError('Enrollment requires exact clean committed source')
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip()
    workflow = '.github/workflows/trusted-release.yml'
    pinned = subprocess.check_output(['git', 'show', signer_sha + ':' + workflow], cwd=ROOT)
    if pinned != (ROOT / workflow).read_bytes():
        raise ValueError('Pinned signer workflow differs from reviewed source')
    manual = json.loads(manual_policy.read_text())
    installed, _, compose, schema = artifact(running_receipt)
    if (manual['contract'] != 4 or manual['schema_version'] != 24 or schema != 24
            or manual.get('manual_transitions', []) != []
            or compose != (ROOT / 'deploy/compose.yaml').read_bytes()):
        raise ValueError('Existing-runtime enrollment requires finalized manual24 policy, retained schema24 package and unchanged Compose')
    with tarfile.open(installed['source_offer']) as source_offer:
        for name in ('release_access.py', 'release_remote.py', 'release_pipeline.py'):
            if source_offer.extractfile('deploy/' + name).read() != (ROOT / 'deploy' / name).read_bytes():
                raise ValueError('Existing manual helper pins must remain unchanged for this enrollment')
    version = subprocess.check_output([str(verifier), '--version'], text=True, timeout=10,
                                     env={'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent',
                                          'GH_CONFIG_DIR': '/nonexistent', 'GH_PROMPT_DISABLED': '1'})
    if not version.startswith('gh version 2.97.0 '):
        raise ValueError('Reviewed native verifier version2.97.0 required')
    target = manual['target']
    scope = {key: target[key] for key in ('project', 'origin', 'loopback_port')}
    scope['target_sha256'] = sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()
    policy = {'contract': 1, 'enabled': False, 'repository': REPOSITORY, 'repository_id': REPOSITORY_ID,
              'signer_workflow': workflow, 'signer_sha': signer_sha,
              'caller_workflow': '.github/workflows/release.yml',
              'qualification_job': 'release / qualify / candidate',
              'verifier': '/usr/local/libexec/kat-release/gh', 'verifier_sha256': digest(verifier),
              'trusted_root': '/etc/kat-release/trusted-root.jsonl', 'trusted_root_sha256': digest(trusted_root),
              'helper_sha256': digest(ROOT / 'deploy/release_ci_access.py'),
              'max_age_seconds': 21600, 'transitions': []}
    plan = {'status': 'disabled adoption plan; not installed', 'commit': source, 'tree': tree,
            'helper_sha256': {name: digest(ROOT / 'deploy' / name) for name in HELPERS},
            'compose_sha256': digest(ROOT / 'deploy/compose.yaml'),
            'verifier_version': '2.97.0',
            'transport_command': 'restrict,command="/usr/bin/python3 -I /usr/local/libexec/kat-release/deploy/release_ci_access.py"',
            'mode': 'existing-drain-runtime', 'bootstrap': None,
            'existing_runtime': {key: installed[key] for key in (
                'commit', 'tree', 'image_id', 'config_digest', 'source_offer_sha256')},
            'baseline_schema': schema, 'manual_schema_baseline': manual['schema_version'],
            'manual_policy_sha256': sha256(canonical(manual)).hexdigest(),
            'manual_policy_file_sha256': digest(manual_policy),
            'manual_policy_action': 'preserve unchanged, including signer, target and manual_transitions',
            'runtime_prerequisites': ['match actual manual policy to the preparation hashes',
                                     'match actual running image/source/schema to the retained package',
                                     'verify maintenance socket/open admission and no active release attempt',
                                     'normal CI drain must settle before stop; no historical idle consent'],
            'normal_release': 'push protected main; no sign, manual package/upload, idle or dispatch',
            'required_check': 'Kat checks', 'environment': 'kat-production; main only; no required reviewers',
            'not_done': ['review', 'host trust installation', 'dedicated transport enrollment',
                         'verify current repository rules/environment settings',
                         'live runtime/admission preflight', 'hosted qualification and unattended positive proof']}
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, value in (('ci-policy.json', policy), ('target-scope.json', scope), ('adoption-plan.json', plan)):
        (output / name).write_text(json.dumps(value, indent=2) + '\n')
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manual-policy', required=True, type=Path)
    parser.add_argument('--running-receipt', required=True, type=Path,
                        help='retained currently deployed schema24 package; never a schema23 bootstrap')
    parser.add_argument('--signer-sha', required=True)
    parser.add_argument('--verifier', required=True, type=Path)
    parser.add_argument('--trusted-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.manual_policy, args.signer_sha, args.verifier, args.trusted_root,
                             args.output, running_receipt=args.running_receipt)))
