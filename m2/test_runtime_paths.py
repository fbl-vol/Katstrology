"""CLI-only runtime path routing with fake local configuration; never open a Store."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from psycopg.conninfo import conninfo_to_dict

from m2.local_fixture import ROOT, fixture_dsn
from m2.web_server import main


class RuntimePathTests(TestCase):
    def test_fixture_dsn_reads_only_the_selected_synthetic_state(self):
        with TemporaryDirectory(prefix='kat-runtime-paths-') as directory:
            state = Path(directory)
            (state / 'm2-pg-name').write_text('kat-m2-synthetic-123\n')
            (state / 'm2-pg.env').write_text('POSTGRES_DB=synthetic_db\n'
                                             'POSTGRES_USER=synthetic_user\n'
                                             'POSTGRES_PASSWORD=synthetic_password\n')
            with patch('m2.local_fixture.subprocess.check_output', return_value='0.0.0.0:54329\n') as docker:
                parts = conninfo_to_dict(fixture_dsn(state))
            docker.assert_called_once_with(['docker', 'port', 'kat-m2-synthetic-123', '5432/tcp'], text=True)
            self.assertEqual({key: parts[key] for key in ('host', 'port', 'dbname', 'user')},
                {'host': '127.0.0.1', 'port': '54329', 'dbname': 'synthetic_db', 'user': 'synthetic_user'})
            (state / 'm2-pg-name').write_text('not-owned\n')
            with patch('m2.local_fixture.subprocess.check_output') as docker:
                with self.assertRaisesRegex(RuntimeError, 'Not an owned Kat'):
                    fixture_dsn(state)
                docker.assert_not_called()

    def test_main_routes_explicit_local_paths_without_starting_store_or_server(self):
        with TemporaryDirectory(prefix='kat-runtime-paths-') as directory:
            state, dist = Path(directory) / 'state', Path(directory) / 'verified-dist'
            with patch('sys.argv', ['kat-web', 'serve', '--state-directory', str(state),
                                     '--served-dist', str(dist), '--port', '9234']), \
                 patch('m2.web_server.fixture_dsn', return_value='fake-synthetic-dsn') as dsn, \
                 patch('m2.web_server.create_app', return_value=object()) as app, \
                 patch('m2.web_server.uvicorn.run') as run:
                main()
            dsn.assert_called_once_with(state)
            app.assert_called_once()
            self.assertEqual(app.call_args.args, ('fake-synthetic-dsn', state / 'browser-runtime/files',
                                                   state / 'browser-runtime/deletions.jsonl', dist))
            self.assertEqual(app.call_args.kwargs['port'], 9234)
            run.assert_called_once()

    def test_old_defaults_and_absolute_only_cli_contract(self):
        with patch('sys.argv', ['kat-web']), \
             patch('m2.web_server.fixture_dsn', return_value='fake-synthetic-dsn') as dsn, \
             patch('m2.web_server.create_app') as app, patch('m2.web_server.uvicorn.run'):
            main()
        dsn.assert_called_once_with(ROOT / '.local')
        self.assertEqual(app.call_args.args[1:],
            (ROOT / '.local/browser-runtime/files', ROOT / '.local/browser-runtime/deletions.jsonl',
             ROOT / 'web/dist'))
        with patch('sys.argv', ['kat-web', '--state-directory', 'relative']), \
             patch('m2.web_server.fixture_dsn') as dsn:
            with self.assertRaises(SystemExit):
                main()
            dsn.assert_not_called()
