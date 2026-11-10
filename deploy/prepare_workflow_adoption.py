"""Offline future signer-pin handoff; never reads or writes installed trust."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

PUBLISHED = 'f64fb6dcbd104cff83219827dce5eef849fde89b'
PREVIOUS_SIGNER = 'c31e7dd8fa3becd61851647a3158c95172e68eb5'
WORKFLOWS = {
    'qualify.yml': '8a8bfaa104f910a7979086f3c1cb6116e00057021e5e2fa9bef28100755e7fd0',
    'trusted-release.yml': '0035b97f50a71fa61eaed9ca4a5fbd2bb4bd6a55415608ad1a672f4c5e2a769c',
}
ROOT = Path(__file__).resolve().parents[1]


def prepare(repository=ROOT):
    # These bytes were fetched from public main before authoring this handoff.
    # No network, credentials, mutable branch pin or invented future commit.
    for name, expected in WORKFLOWS.items():
        content = subprocess.check_output([
            'git', '-C', str(repository), 'show', f'{PUBLISHED}:.github/workflows/{name}'])
        if sha256(content).hexdigest() != expected:
            raise ValueError('Published nested workflow identity differs')
    return {
        'contract': 1, 'status': 'prepared-not-enrolled',
        'repository': 'fbl-vol/Katstrology', 'published_revision': PUBLISHED,
        'workflow_sha256': WORKFLOWS,
        'future_policy_change': {'field': 'signer_sha', 'from': PREVIOUS_SIGNER, 'to': PUBLISHED},
        'qualification_job': 'release / qualify / candidate',
        'preserve': ['all other policy fields', 'migration lanes', 'helpers', 'verifier',
                     'trusted root', 'target', 'keys', 'required Kat checks'],
        'prerequisites': [
            'Separate exact trust-adoption instruction; this manifest is not approval',
            'Reinspect actual protected policy/hash and previous signer; mismatch stops',
            'Use existing release lock with no active attempt and retain original policy',
            'Validate exact candidate/read-back with installed guards; no generic policy editor',
            'Record independent installed witness before protected-main release',
            'Fresh hosted PR and main qualification; no reruns or cross-run evidence reuse',
        ],
        'limits': ['No installed-state inspection or change',
                   'Parallel hosted speed and runner-minute cost remain unmeasured'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(prepare(args.repository), indent=2))


if __name__ == '__main__':
    main()
