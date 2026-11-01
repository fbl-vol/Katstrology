"""Build an identified local amd64 image, immutable archive, and source offer.

Never uploads, loads another host, serves, or uses Docker runtime credentials.
Run from a clean committed public-only checkout. Output stays in ignored .local.
"""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def file_hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    if run('git', 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('Only a clean committed source tip may be packaged')
    commit, tree = run('git', 'rev-parse', 'HEAD'), run('git', 'rev-parse', 'HEAD^{tree}')
    output = ROOT / '.local/fresh-production/package' / commit[:12]
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'kat-public-source.tar'
    image = output / 'kat-production-amd64.tar'
    with source.open('wb') as stream:
        subprocess.run(['git', 'archive', '--format=tar', 'HEAD'], cwd=ROOT,
                       stdout=stream, check=True)
    tag = f'kat-production-local:{commit[:12]}'
    subprocess.run(['docker', 'build', '--platform', 'linux/amd64', '--pull=false',
                    '--label', f'org.opencontainers.image.revision={commit}',
                    '-t', tag, '.'], cwd=ROOT, check=True)
    image_id = run('docker', 'image', 'inspect', tag, '--format', '{{.Id}}')
    architecture = run('docker', 'image', 'inspect', tag, '--format', '{{.Os}}/{{.Architecture}}')
    if architecture != 'linux/amd64':
        raise RuntimeError('Image architecture does not match the requested artifact')
    subprocess.run(['docker', 'save', '-o', str(image), image_id], cwd=ROOT, check=True)
    with tarfile.open(image) as archive:
        manifest = json.load(archive.extractfile('manifest.json'))
        if len(manifest) != 1 or manifest[0]['Config'] != image_id.removeprefix('sha256:') + '.json':
            raise RuntimeError('Saved archive config is not the inspected image ID')
        config = json.load(archive.extractfile(manifest[0]['Config']))
        if config.get('config', {}).get('Labels', {}).get('org.opencontainers.image.revision') != commit:
            raise RuntimeError('Saved archive does not identify the committed source')
    receipt = {'commit': commit, 'tree': tree, 'architecture': architecture,
               'image_id': image_id, 'image_archive_sha256': file_hash(image),
               'source_offer_sha256': file_hash(source),
               'image_archive': str(image), 'source_offer': str(source)}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Local packaging failed ({type(error).__name__}); no artifact accepted.',
              file=sys.stderr)
        raise SystemExit(1)
