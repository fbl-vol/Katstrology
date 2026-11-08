"""Install hash-pinned Docker CLI plugins only on an ephemeral hosted runner."""

import argparse
from hashlib import sha256
import os
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

PLUGINS = {
    # docker/buildx v0.38.1 — buildx-v0.38.1.linux-amd64 (official release asset).
    'docker-buildx': ('https://api.github.com/repos/docker/buildx/releases/assets/660618355',
                     'e25d5cd675092bb5d1d03632fdc46cdf3fede7b514dc5f023a105e00d3ce5ad4'),
    # docker/compose v2.38.2 — docker-compose-linux-x86_64 (official release asset).
    'docker-compose': ('https://api.github.com/repos/docker/compose/releases/assets/270980274',
                      '486b3ffc0f806ca2efbc430cef89955386011662f0c76bad17c103d059cfa9cf'),
}
MAX_PLUGIN_BYTES = 150 * 1024 * 1024


def install():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise ValueError('Only an ephemeral GitHub-hosted runner may install these plugins')
    folder = Path.home() / '.docker/cli-plugins'
    folder.mkdir(parents=True, exist_ok=True)
    opener = build_opener(ProxyHandler({}))
    for name, (url, expected) in PLUGINS.items():
        request = Request(url, headers={
            'Accept': 'application/octet-stream', 'User-Agent': 'Kat-hosted-tools/1.0',
        })
        with opener.open(request, timeout=60) as response:
            content = response.read(MAX_PLUGIN_BYTES + 1)
        if len(content) > MAX_PLUGIN_BYTES or sha256(content).hexdigest() != expected:
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
