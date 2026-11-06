"""Pinned public CPU tokenizer fixture for CI tests, never the production image."""

from hashlib import file_digest
from pathlib import Path
import subprocess
import sys
from tempfile import NamedTemporaryFile
from urllib.request import ProxyHandler, build_opener

from m2.provider.local_model import DEFAULT_MODEL

ROOT = Path(__file__).resolve().parents[1]
MODEL_REVISION = '9217f5db79a29953eb74d5343926648285ec7e67'
MODEL_SHA256 = '041474553fcabfc2a2d67903f9d2c2e50bd92528e670da4f33b5d0ce6e59fd55'
MODEL_SIZE = 522186592
MODEL_URL = ('https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/'
             + MODEL_REVISION + '/' + DEFAULT_MODEL.name)
CPU_WHEEL = ('https://github.com/abetlen/llama-cpp-python/releases/download/v0.3.36/'
             'llama_cpp_python-0.3.36-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl'
             '#sha256=c8a3e98093e950d7a770f794842e36f2db82b2933e8762ed7b5ffd435011e8e4')


def install_binding():
    if sys.prefix == sys.base_prefix:
        raise ValueError('Test dependencies require a pip-enabled virtualenv')
    # The direct, hash-pinned CPU wheel avoids a native build or an accidental
    # CUDA selection. Existing model requirements also pin its Python dependencies.
    subprocess.run([sys.executable, '-m', 'pip', '--isolated', '--disable-pip-version-check',
        'install', '--no-input', '--keyring-provider', 'disabled',
        '--index-url', 'https://pypi.org/simple', '--only-binary=:all:',
        '-r', str(ROOT / 'probes/requirements-model.txt'), CPU_WHEEL],
        cwd=ROOT, check=True, timeout=300)


def verify_model(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != MODEL_SIZE:
        raise ValueError('Public tokenizer model size/type differs from pin')
    with path.open('rb') as source:
        if file_digest(source, 'sha256').hexdigest() != MODEL_SHA256:
            raise ValueError('Public tokenizer model hash differs from pin')


def prepare_model(path):
    if path.exists() or path.is_symlink():
        verify_model(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = build_opener(ProxyHandler({}))  # No HF cache, tokens, cookies or ambient proxy.
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix='.qwen-download-', delete=False) as output:
            temporary = Path(output.name)
            count = 0
            with opener.open(MODEL_URL, timeout=60) as response:
                while block := response.read(1024 * 1024):
                    count += len(block)
                    if count > MODEL_SIZE:
                        raise ValueError('Public tokenizer model exceeds pinned size')
                    output.write(block)
        verify_model(temporary)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    install_binding()
    prepare_model(ROOT / DEFAULT_MODEL)
    print('Pinned public CPU tokenizer test fixture verified; no inference or production packaging.')


if __name__ == '__main__':
    main()
