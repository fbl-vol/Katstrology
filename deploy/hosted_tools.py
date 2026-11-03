"""Install hash-pinned Docker CLI plugins only on an ephemeral hosted runner."""

import argparse
from hashlib import sha256
import os
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

PLUGINS = {
    'docker-buildx': ('https://github.com/docker/buildx/releases/download/v0.38.1/buildx-v0.38.1.linux-amd64',
                     'e25d5cd675092bb5d1d03632fdc46cdf3fede7b514dc5f023a105e00d3ce5ad4'),
    'docker-compose': ('https://github.com/docker/compose/releases/download/v2.38.2/docker-compose-linux-x86_64',
                      '486b3ffc0f806ca2efbc430cef89955386011662f0c76bad17c103d059cfa9cf'),
}


def install():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise ValueError('Only an ephemeral GitHub-hosted runner may install these plugins')
    folder = Path.home() / '.docker/cli-plugins'
    folder.mkdir(parents=True, exist_ok=True)
    opener = build_opener(ProxyHandler({}))
    for name, (url, expected) in PLUGINS.items():
        with opener.open(url, timeout=60) as response:
            content = response.read(150 * 1024 * 1024 + 1)
        if len(content) > 150 * 1024 * 1024 or sha256(content).hexdigest() != expected:
            raise ValueError('Docker plugin differs from official release checksum')
        target = folder / name
        if target.is_symlink():
            raise ValueError('Unexpected plugin symlink')
        target.write_bytes(content)
        target.chmod(0o755)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    if parser.parse_args().execute:
        install()
    else:
        print('Plan only: hosted Docker Buildx0.38.1 and Compose2.38.2, verified release hashes.')
