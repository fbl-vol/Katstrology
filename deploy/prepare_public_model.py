"""Fetch only the five pinned public model files; no ambient tokens or HF cache."""

import argparse
from hashlib import sha256
from pathlib import Path
import sys
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from m2.public_model import CACHE_FOLDER, FILES, REPOSITORY, REVISION, verified_snapshot


def prepare(cache):
    folder = cache / CACHE_FOLDER
    if folder.exists():
        verified_snapshot(cache)  # A cache hit is not evidence of integrity.
        return
    folder.mkdir(parents=True, mode=0o755)
    snapshot = folder / 'snapshots' / REVISION
    snapshot.mkdir(parents=True)
    opener = build_opener(ProxyHandler({}))
    # Redirects are needed for Hugging Face's public content-addressed CDN.
    # No Authorization header, cookies or ambient provider credentials are used.
    for name, (expected, size) in FILES.items():
        url = f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}'
        digest = sha256()
        count = 0
        with opener.open(url, timeout=60) as response, (snapshot / name).open('xb') as output:
            while block := response.read(1024 * 1024):
                count += len(block)
                if count > size:
                    raise ValueError('Public model download exceeds pinned size')
                digest.update(block)
                output.write(block)
        if count != size or digest.hexdigest() != expected:
            raise ValueError('Public model bytes differ from pin')
    (folder / 'refs').mkdir()
    (folder / 'refs/main').write_text(REVISION)
    verified_snapshot(cache)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT / '.local/models/fastembed')
    args = parser.parse_args()
    prepare(args.cache)
    print('Pinned public model verified; no private cache used.')
