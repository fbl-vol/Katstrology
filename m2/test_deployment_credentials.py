"""Synthetic-only offline registration handoff; no OpenAI transport."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cryptography.exceptions import InvalidTag

from m2.siwc import CredentialFiles, ProviderBridge


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
            self.assertEqual(bridge.access('alice'), 'synthetic-new-access')
            self.assertEqual(transport.requests[0]['refresh_token'], original['refresh_token'])
            self.assertEqual(target.host_id(), original_host)
            bridge.close()
            with self.assertRaises(ValueError):
                target.import_selected('alice', handoff, 'synthetic-passphrase-12345')
            with self.assertRaises(FileExistsError):
                source.export_selected('alice', handoff, 'synthetic-passphrase-12345')


if __name__ == '__main__':
    unittest.main()
