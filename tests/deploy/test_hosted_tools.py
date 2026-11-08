"""Network-free installer checks; all writes stay in an owned temporary HOME."""

from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from deploy import hosted_tools


class Response(BytesIO):
    def read(self, size=-1):
        self.requested_size = size
        return super().read(size)


class HostedToolsTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.folder = self.home / '.docker/cli-plugins'
        self.enterContext(patch.dict(os.environ, {
            'HOME': str(self.home), 'GITHUB_ACTIONS': 'true',
            'RUNNER_ENVIRONMENT': 'github-hosted',
        }, clear=True))
        self.opener = Mock()
        self.build = self.enterContext(patch.object(hosted_tools, 'build_opener', return_value=self.opener))

    def test_exact_official_binary_requests_and_verified_executable_files(self):
        expected_urls = [
            'https://api.github.com/repos/docker/buildx/releases/assets/660618355',
            'https://api.github.com/repos/docker/compose/releases/assets/270980274',
        ]
        contents = [b'synthetic buildx binary', b'synthetic compose binary']
        responses = [Response(content) for content in contents]
        self.opener.open.side_effect = responses
        # Only expected hashes change for small fixtures; production URLs and logic run.
        plugins = {name: (url, sha256(content).hexdigest())
                   for (name, (url, _)), content in zip(hosted_tools.PLUGINS.items(), contents)}
        with patch.object(hosted_tools, 'PLUGINS', plugins):
            hosted_tools.install()

        self.assertEqual(self.build.call_args.args[0].proxies, {})
        self.assertEqual(self.opener.open.call_count, 2)
        for call, url in zip(self.opener.open.call_args_list, expected_urls):
            request = call.args[0]
            self.assertEqual(getattr(request, 'full_url', request), url)
            self.assertEqual(dict(request.header_items()), {
                'Accept': 'application/octet-stream', 'User-agent': 'Kat-hosted-tools/1.0',
            })
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(call.kwargs, {'timeout': 60})
        for name, content, response in zip(plugins, contents, responses):
            target = self.folder / name
            self.assertEqual(target.read_bytes(), content)
            self.assertEqual(target.stat().st_mode & 0o777, 0o755)
            self.assertEqual(response.requested_size, 150 * 1024 * 1024 + 1)
            self.assertTrue(response.closed)

    def test_official_pins_reject_mismatched_bytes_without_overwriting(self):
        pins = {
            'docker-buildx': 'e25d5cd675092bb5d1d03632fdc46cdf3fede7b514dc5f023a105e00d3ce5ad4',
            'docker-compose': '486b3ffc0f806ca2efbc430cef89955386011662f0c76bad17c103d059cfa9cf',
        }
        self.folder.mkdir(parents=True)
        for name, expected in pins.items():
            with self.subTest(plugin=name):
                url, actual = hosted_tools.PLUGINS[name]
                self.assertEqual(actual, expected)
                target = self.folder / name
                target.write_bytes(b'existing plugin')
                target.chmod(0o600)
                self.opener.open.return_value = Response(b'not the pinned binary')
                with patch.object(hosted_tools, 'PLUGINS', {name: (url, actual)}):
                    with self.assertRaisesRegex(ValueError, 'checksum'):
                        hosted_tools.install()
                self.assertEqual(target.read_bytes(), b'existing plugin')
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_oversized_bytes_rejected_even_when_checksum_matches(self):
        self.assertEqual(hosted_tools.MAX_PLUGIN_BYTES, 150 * 1024 * 1024)
        # Exercise the real bounded read and length guard with a small byte ceiling.
        response = Response(b'x' * 64)
        self.opener.open.return_value = response
        url = hosted_tools.PLUGINS['docker-buildx'][0]
        with patch.object(hosted_tools, 'MAX_PLUGIN_BYTES', 32), \
                patch.object(hosted_tools, 'PLUGINS', {'docker-buildx': (url, sha256(b'x' * 33).hexdigest())}):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                hosted_tools.install()
        self.assertEqual(response.requested_size, 33)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_symlink_refused_even_for_valid_bytes(self):
        self.folder.mkdir(parents=True)
        victim = self.home / 'untouched'
        victim.write_bytes(b'keep this')
        victim.chmod(0o600)
        target = self.folder / 'docker-buildx'
        target.symlink_to(victim)
        content = b'synthetic verified binary'
        self.opener.open.return_value = Response(content)
        url = hosted_tools.PLUGINS['docker-buildx'][0]
        with patch.object(hosted_tools, 'PLUGINS', {'docker-buildx': (url, sha256(content).hexdigest())}):
            with self.assertRaisesRegex(ValueError, 'symlink'):
                hosted_tools.install()
        self.assertTrue(target.is_symlink())
        self.assertEqual(victim.read_bytes(), b'keep this')
        self.assertEqual(victim.stat().st_mode & 0o777, 0o600)

    def test_non_hosted_environments_refused_before_io(self):
        for actions, runner in [('', ''), ('true', 'self-hosted'), ('false', 'github-hosted')]:
            with self.subTest(actions=actions, runner=runner), \
                    patch.dict(os.environ, {'GITHUB_ACTIONS': actions, 'RUNNER_ENVIRONMENT': runner}):
                with self.assertRaisesRegex(ValueError, 'ephemeral'):
                    hosted_tools.install()
        self.build.assert_not_called()
        self.assertFalse(self.folder.exists())

    def test_http_failure_propagates_without_install_or_fallback(self):
        self.opener.open.side_effect = HTTPError('https://api.github.com/', 504, 'synthetic failure', {}, None)
        with self.assertRaises(HTTPError):
            hosted_tools.install()
        self.opener.open.assert_called_once()
        self.assertEqual(list(self.folder.iterdir()), [])
