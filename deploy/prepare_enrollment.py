"""Write a disabled, exact-source adoption plan. Never installs or generates keys.

Reading a real target policy belongs to separately approved adoption, not source
qualification. Tests use only a synthetic policy and public verifier/trust files.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from deploy.release_ci_access import REPOSITORY, REPOSITORY_ID
from deploy.release_pipeline import ROOT, digest

HELPERS = ('release_access.py', 'release_remote.py', 'release_pipeline.py', 'release_ci_access.py',
           'bootstrap_bridge.py')


def prepare(manual_policy, signer_sha, verifier, trusted_root, output):
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise ValueError('Enrollment requires exact clean committed source')
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip()
    workflow = '.github/workflows/trusted-release.yml'
    pinned = subprocess.check_output(['git', 'show', signer_sha + ':' + workflow], cwd=ROOT)
    if pinned != (ROOT / workflow).read_bytes():
        raise ValueError('Pinned signer workflow differs from reviewed source')
    manual = json.loads(manual_policy.read_text())
    if manual['contract'] != 4 or manual['schema_version'] != 23:
        raise ValueError('Bootstrap expects existing manual protocol4/schema23')
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
            'bootstrap': 'bootstrap_bridge.py: consumed local-root permit + fresh keyless manifest + one-time settled maintenance; never an SSH bypass',
            'normal_release': 'push protected main; no sign, manual package/upload, idle or dispatch',
            'required_check': 'Kat checks', 'environment': 'kat-production; main only; no required reviewers',
            'not_done': ['review', 'host trust installation', 'dedicated transport enrollment',
                         'repository rules/environment setup', 'drain-capable runtime bootstrap',
                         'hosted qualification and unattended positive proof']}
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, value in (('ci-policy.json', policy), ('target-scope.json', scope), ('adoption-plan.json', plan)):
        (output / name).write_text(json.dumps(value, indent=2) + '\n')
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manual-policy', required=True, type=Path)
    parser.add_argument('--signer-sha', required=True)
    parser.add_argument('--verifier', required=True, type=Path)
    parser.add_argument('--trusted-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.manual_policy, args.signer_sha, args.verifier, args.trusted_root, args.output)))
