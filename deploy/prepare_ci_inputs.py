"""Cold-cache public numerical fixtures for owned CI; never private chart inputs."""

from hashlib import sha256
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from deploy import prepare_test_model

FILES = {
    'sepl_18.se1': 'ca1393ceab3a44fbc895887cf789c68819ae6a1cbc9b22225872dbe4ccd99a66',
    'semo_18.se1': '1ca07bd67c24374d77226180c20a4f9996cba013697894810518e7eb582ca4f7',
    'seas_18.se1': 'a2cd8fc33807c78ca9a700c91c2e042258b12fc4796519e00781440b5ad8b2e2',
}


def main():
    root = Path(__file__).resolve().parents[1] / '.local/ephe'
    root.mkdir(parents=True, exist_ok=True)
    opener = build_opener(ProxyHandler({}))
    for name, expected in FILES.items():
        path = root / name
        if not path.exists():
            with opener.open('https://raw.githubusercontent.com/aloistr/swisseph/master/ephe/' + name,
                             timeout=60) as response:
                content = response.read(16 * 1024 * 1024 + 1)
            if len(content) > 16 * 1024 * 1024 or sha256(content).hexdigest() != expected:
                raise ValueError('Public ephemeris bytes differ from qualified pin')
            with path.open('xb') as output:
                output.write(content)
        if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Public ephemeris cache changed')
    print('Three pinned public Swiss files verified; not included in release artifacts.')
    prepare_test_model.main()


if __name__ == '__main__':
    main()
