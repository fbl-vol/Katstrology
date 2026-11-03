"""Consume a newly enrolled constrained CI identity only inside an eligible job.

No key generation, agent, host-key discovery or fallback. Local/source execution
without hosted/main/explicit-enablement context refuses before reading secrets.
"""

import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from deploy.release_ci import execute


def main():
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or os.environ.get('GITHUB_REPOSITORY_ID') != '1437147047'
            or os.environ.get('GITHUB_REPOSITORY') != 'fbl-vol/Katstrology'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != 'push'
            or os.environ.get('GITHUB_RUN_ATTEMPT') != '1'
            or os.environ.get('KAT_AUTOMATION_ENABLED') != 'true'):
        raise ValueError('CI execution is not enrolled/eligible')
    host, user = os.environ['KAT_CI_SSH_HOST'], os.environ['KAT_CI_SSH_USER']
    if not re.fullmatch(r'[a-zA-Z0-9.-]+', host) or not re.fullmatch(r'[a-z_][a-z0-9_-]*', user):
        raise ValueError('Invalid enrolled transport target')
    known_hosts = os.environ['KAT_CI_KNOWN_HOSTS']
    if not re.fullmatch(re.escape(host) + r' ssh-ed25519 [A-Za-z0-9+/]+={0,2}\n?', known_hosts):
        raise ValueError('One exact enrolled SSH host key required')
    result = Path('.local/release-result.json')
    os.umask(0o077)
    with TemporaryDirectory(prefix='kat-ci-transport-') as directory:
        root = Path(directory)
        key = os.environ.pop('KAT_CI_TRANSPORT_KEY')
        if not key:
            raise ValueError('Dedicated constrained CI identity absent')
        (root / 'identity').write_text(key.rstrip() + '\n')
        del key
        (root / 'known_hosts').write_text(known_hosts.rstrip() + '\n')
        profile = root / 'config'
        profile.write_text(f'''Host kat-ci
    HostName {host}
    User {user}
    IdentityFile {root / 'identity'}
    UserKnownHostsFile {root / 'known_hosts'}
    GlobalKnownHostsFile /dev/null
    StrictHostKeyChecking yes
    IdentitiesOnly yes
    IdentityAgent none
    BatchMode yes
    ForwardAgent no
    ClearAllForwardings yes
    RequestTTY no
''')
        try:
            execute(Path('.local/ci-package/receipt.json'), Path('.local/ci-package/manifest.json'),
                    Path('.local/ci-package/bundle.json'), profile, result)
        finally:
            if result.exists():
                receipt = json.loads(result.read_text())
                summary = {key: receipt.get(key) for key in ('status', 'phase', 'failed_phase', 'plan_sha256', 'containment')}
                print(json.dumps(summary, sort_keys=True))
                if os.environ.get('GITHUB_STEP_SUMMARY'):
                    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
                        output.write('## Kat release outcome\n```json\n' + json.dumps(summary, indent=2) + '\n```\n')
                        output.write('On halted/unknown: inspect this attempt; never rerun the effectful job or restore older data.\n')


if __name__ == '__main__':
    main()
