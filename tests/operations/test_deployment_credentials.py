"""Synthetic-only offline registration handoff; no OpenAI transport."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cryptography.exceptions import InvalidTag

from m2.deployment_credentials import main as handoff_main
from m2.provider.siwc import CredentialFiles, ProviderBridge, ProviderFailure
from tests.support.database import DatabaseCase


class CredentialHandoffTests(unittest.TestCase):
    def test_selected_owner_private_encrypted_handoff_preserves_target_host(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = CredentialFiles(root / 'source')
            target = CredentialFiles(root / 'target')
            original_host = target.host_id()
            original = {'client_id': 'synthetic-client', 'subject': 'synthetic-subject',
                        'scopes': ['chatgpt.tokens.use.direct'],
                        'refresh_token': 'synthetic-renewable-secret',
                        'access_token': 'synthetic-access-secret', 'expires_at': 1999999999}
            source.save('alice', {'selected': 'synthetic-client',
                                  'accounts': {'synthetic-client': original}})
            handoff = root / 'handoff.enc'
            source.export_selected('alice', handoff, 'synthetic-passphrase-12345')
            self.assertEqual(handoff.stat().st_mode & 0o077, 0)
            self.assertNotIn(b'synthetic-renewable-secret', handoff.read_bytes())
            with self.assertRaises(InvalidTag):
                target.import_selected('alice', handoff, 'incorrect-passphrase-12345')
            with self.assertRaises(ValueError):
                target.import_selected('bob', handoff, 'synthetic-passphrase-12345')
            self.assertEqual(target.load('alice')['accounts'], {})
            target.import_selected('alice', handoff, 'synthetic-passphrase-12345')
            restored = target.load('alice')['accounts']['synthetic-client']
            self.assertEqual(restored['refresh_token'], original['refresh_token'])
            self.assertIsNone(restored['access_token'])
            self.assertEqual(restored['expires_at'], 0)
            self.assertEqual(target.host_id(), original_host)
            self.assertNotEqual(source.host_id(), target.host_id())

            class FakeTransport:
                def __init__(self):
                    self.requests = []

                def token(self, request):
                    self.requests.append(request)
                    return {'token_type': 'Bearer', 'access_token': 'synthetic-new-access',
                            'refresh_token': 'synthetic-new-refresh', 'expires_in': 3600}

                def close(self):
                    pass

            transport = FakeTransport()
            bridge = ProviderBridge(root / 'target', transport=transport)
            self.assertEqual(bridge.status('alice')['phase'], 'refresh_required')
            self.assertTrue(bridge.status('alice')['connected'])
            self.assertEqual(bridge.status('bob')['phase'], 'not_connected')
            self.assertEqual(bridge.access('alice'), 'synthetic-new-access')
            self.assertEqual(bridge.status('alice')['phase'], 'ready')
            self.assertEqual(transport.requests[0]['refresh_token'], original['refresh_token'])
            self.assertEqual(target.host_id(), original_host)
            bridge.close()
            with self.assertRaises(ValueError):
                target.import_selected('alice', handoff, 'synthetic-passphrase-12345')
            with self.assertRaises(FileExistsError):
                source.export_selected('alice', handoff, 'synthetic-passphrase-12345')

    def test_recovery_refuses_live_or_multiple_registrations_without_mutation(self):
        with TemporaryDirectory() as directory:
            credentials = CredentialFiles(Path(directory) / 'server')
            account = {'client_id': 'a', 'subject': 'synthetic', 'access_token': None,
                       'refresh_token': None}
            record = {'selected': 'a', 'accounts': {'a': account, 'b': {**account, 'client_id': 'b'}}}
            credentials.save('alice', record)
            with self.assertRaisesRegex(ValueError, 'one disconnected'):
                credentials.forget_disconnected('alice')
            self.assertEqual(credentials.load('alice'), record)
            record['accounts'].pop('b')
            record['accounts']['a']['refresh_token'] = 'synthetic-renewable'
            credentials.save('alice', record)
            with self.assertRaisesRegex(ValueError, 'disconnected registration'):
                credentials.forget_disconnected('alice')
            self.assertEqual(credentials.load('alice'), record)

    def test_terminal_refresh_requires_explicit_owner_only_offline_recovery(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            local = CredentialFiles(root / 'dedicated-local')
            server = CredentialFiles(root / 'personal-server')
            host_id = server.host_id()
            original = {'client_id': 'oaiapp_synthetic', 'subject': 'synthetic-subject',
                        'id_token': 'synthetic-validated-id', 'scopes': ['chatgpt.tokens.use.direct'],
                        'refresh_token': 'synthetic-renewable', 'access_token': 'synthetic-old',
                        'expires_at': 0}
            local.save('alice', {'selected': 'oaiapp_synthetic',
                                 'accounts': {'oaiapp_synthetic': original}})
            local.save('bob', {'selected': None, 'accounts': {}})
            handoff = root / 'selected.enc'
            local.export_selected('alice', handoff, 'synthetic-passphrase-12345')
            server.import_selected('alice', handoff, 'synthetic-passphrase-12345')
            with self.assertRaisesRegex(ValueError, 'disconnected registration'):
                server.forget_disconnected('alice')

            class TerminalRefresh:
                def token(self, request):
                    if request['grant_type'] != 'refresh_token':
                        raise AssertionError('No authorization-code exchange is allowed')
                    raise ProviderFailure('invalid_grant')

                def close(self):
                    pass

            bridge = ProviderBridge(root / 'personal-server', TerminalRefresh())
            with self.assertRaises(ProviderFailure) as error:
                bridge.access('alice')
            self.assertEqual(error.exception.reason, 'invalid_grant')
            self.assertEqual(bridge.status('alice')['phase'], 'reauthorization_required')
            self.assertFalse(bridge.status('alice')['connected'])
            self.assertEqual(bridge.status('bob')['accounts'], [])
            with self.assertRaises(ValueError):
                server.import_selected('alice', handoff, 'synthetic-passphrase-12345')
            bridge.close()
            server.forget_disconnected('alice')
            self.assertEqual(server.host_id(), host_id)
            self.assertEqual(server.load('bob')['accounts'], {})
            server.import_selected('alice', handoff, 'synthetic-passphrase-12345')
            restarted = ProviderBridge(root / 'personal-server', TerminalRefresh())
            self.assertEqual(restarted.status('alice')['phase'], 'refresh_required')
            restarted.close()
            with self.assertRaisesRegex(ValueError, 'disconnected registration'):
                server.forget_disconnected('alice')


class RecoveryCliTests(DatabaseCase):
    def test_offline_forget_authenticates_owner_and_requires_explicit_confirmation(self):
        state = Path(self.directory.name) / 'new-personal-state'
        credentials = CredentialFiles(state / 'browser-runtime/siwc')
        host = credentials.host_id()
        credentials.save('alice', {'selected': 'oaiapp_fixture', 'accounts': {
            'oaiapp_fixture': {'client_id': 'oaiapp_fixture', 'subject': 'synthetic-alice',
                               'access_token': None, 'refresh_token': None, 'scopes': []}}})
        self.store.close()
        args = ['forget-disconnected-deployment', '--state-directory', str(state),
                '--db-password-file', str(state / 'fake-private-password-file')]
        with patch('m2.deployment_credentials.deployment_dsn', return_value=self.dsn), \
             patch('m2.deployment_credentials.getpass.getpass', return_value='incorrect-password'), \
             patch('builtins.input', side_effect=['alice']):
            self.assertEqual(handoff_main(args), 1)
        self.assertIsNotNone(credentials.load('alice')['selected'])
        with patch('m2.deployment_credentials.deployment_dsn', return_value=self.dsn), \
             patch('m2.deployment_credentials.getpass.getpass', return_value='synthetic-password-alice'), \
             patch('builtins.input', side_effect=['alice', 'NO']):
            self.assertEqual(handoff_main(args), 1)
        self.assertIsNotNone(credentials.load('alice')['selected'])
        with patch('m2.deployment_credentials.deployment_dsn', return_value=self.dsn), \
             patch('m2.deployment_credentials.getpass.getpass', return_value='synthetic-password-alice'), \
             patch('builtins.input', side_effect=['alice', 'FORGET']):
            self.assertEqual(handoff_main(args), 0)
        self.assertEqual(credentials.load('alice')['accounts'], {})
        self.assertEqual(credentials.host_id(), host)
        self.assertEqual(credentials.load('bob')['accounts'], {})


if __name__ == '__main__':
    unittest.main()
