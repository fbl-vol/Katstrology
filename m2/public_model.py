"""Pinned, public-only FastEmbed cache staged for the identified Docker image.

Never copy the user's full Hugging Face cache into a release context. The five
files below are the only public weights/configuration this app's CPU model needs.
"""

from hashlib import sha256
from pathlib import Path
from shutil import copyfile


MODEL = 'BAAI/bge-small-en-v1.5'
REPOSITORY = 'Qdrant/bge-small-en-v1.5-onnx-Q'
REVISION = 'aa8f8b060edb00e03bfdd08813a2949946c8ba55'
CACHE_FOLDER = 'models--Qdrant--bge-small-en-v1.5-onnx-Q'
# (SHA-256 of the resolved file bytes, byte count), not HF pointer identities.
FILES = {
    'config.json': ('13582bcf2effc85b7bf3d3f5532e686bc1c9ce86bb009d10f0ec33cbe92299dd', 706),
    'model_optimized.onnx': ('51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431', 66465124),
    'special_tokens_map.json': ('5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a', 695),
    'tokenizer_config.json': ('0b29c7bfc889e53b36d9dd3e686dd4300f6525110eaa98c76a5dafceb2029f53', 1242),
    'tokenizer.json': ('d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66', 711396),
}


def file_hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def stage_cache(source_cache, destination):
    """Verify exact public bytes, then stage regular files with a fixed HF snapshot ref."""
    source = Path(source_cache) / CACHE_FOLDER
    ref = source / 'refs/main'
    if not source.is_dir() or not ref.is_file() or ref.read_text().strip() != REVISION:
        raise ValueError('Pinned public model revision is unavailable offline')
    snapshot = source / 'snapshots' / REVISION
    for name, (digest, size) in FILES.items():
        path = snapshot / name
        if not path.is_file() or path.stat().st_size != size or file_hash(path) != digest:
            raise ValueError(f'Pinned public model file unavailable or mismatched: {name}')

    target = Path(destination) / CACHE_FOLDER
    (target / 'refs').mkdir(parents=True)
    (target / 'snapshots' / REVISION).mkdir(parents=True)
    (target / 'refs/main').write_text(REVISION)
    for name, (digest, _) in FILES.items():
        output = target / 'snapshots' / REVISION / name
        copyfile(snapshot / name, output)
        if file_hash(output) != digest:
            raise ValueError(f'Staged public model file changed: {name}')
    return {'model': MODEL, 'repository': REPOSITORY, 'revision': REVISION,
            'licence': 'MIT', 'files': {name: {'sha256': digest, 'bytes': size}
                                       for name, (digest, size) in FILES.items()}}
