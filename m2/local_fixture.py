"""Resolve only the owned ephemeral PostgreSQL fixture; never inspect other credentials."""

from pathlib import Path
import subprocess

from psycopg.conninfo import make_conninfo


ROOT = Path(__file__).resolve().parents[1]


def fixture_dsn(state_directory=None):
    """Resolve the owned fixture from an explicitly selected local state directory."""
    state = Path(state_directory) if state_directory is not None else ROOT / '.local'
    name = (state / 'm2-pg-name').read_text().strip()
    if not name.startswith('kat-m2-'):
        raise RuntimeError('Not an owned Kat PostgreSQL fixture')
    port = subprocess.check_output(['docker', 'port', name, '5432/tcp'], text=True).strip().rsplit(':', 1)[-1]
    config = dict(line.split('=', 1) for line in (state / 'm2-pg.env').read_text().splitlines())
    return make_conninfo(host='127.0.0.1', port=port, dbname=config['POSTGRES_DB'],
                         user=config['POSTGRES_USER'], password=config['POSTGRES_PASSWORD'])
