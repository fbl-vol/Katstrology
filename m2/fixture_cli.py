"""Run the local synthetic CLI against only the owned fixture, without printing DSN."""

import os

from m2.cli import main
from m2.operations.local_fixture import fixture_dsn


if __name__ == '__main__':
    os.environ['KAT_M2_DSN'] = fixture_dsn()
    raise SystemExit(main())
