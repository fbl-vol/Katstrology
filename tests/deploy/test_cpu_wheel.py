"""Real wheel acceptance/lifetime logic, mocked network and pip; no installation."""

from hashlib import sha256
from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit

from deploy import prepare_test_model as model


class Response(BytesIO):
    def read(self, size=-1):
        self.requested_size = size
        return super().read(size)


class InterruptedResponse(BytesIO):
    def read(self, size=-1):
        raise IncompleteRead(b'partial', 10)


class CpuWheelTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(model.CPU_WHEEL_SIZE, 27077498)
        self.assertEqual(model.CPU_WHEEL_SHA256,
            'c8a3e98093e950d7a770f794842e36f2db82b2933e8762ed7b5ffd435011e8e4')
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(model, 'TemporaryDirectory',
            side_effect=lambda **kwargs: tempfile.TemporaryDirectory(dir=self.root, **kwargs)))
        self.enterContext(patch.object(model.sys, 'prefix', '/synthetic-venv'))
        self.enterContext(patch.object(model.sys, 'base_prefix', '/synthetic-base'))
        self.content = b'small synthetic CPU wheel bytes'
        self.expected_hash = sha256(self.content).hexdigest()
        self.enterContext(patch.object(model, 'CPU_WHEEL_SIZE', len(self.content)))
        self.enterContext(patch.object(model, 'CPU_WHEEL_SHA256', self.expected_hash))
        self.opener = Mock()
        self.build = self.enterContext(patch.object(model, 'build_opener', return_value=self.opener))
        self.run = self.enterContext(patch.object(model.subprocess, 'run'))

    def assert_wheel_during_pip(self, argv, **kwargs):
        requirement = urlsplit(argv[-1])
        self.assertEqual(requirement.scheme, 'file')
        self.assertEqual(requirement.netloc, '')
        self.assertEqual(requirement.fragment, 'sha256=' + self.expected_hash)
        wheel = Path(unquote(requirement.path))
        self.assertEqual(wheel.name,
            'llama_cpp_python-0.3.36-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl')
        self.assertEqual(wheel.parent.parent, self.root)
        self.assertEqual(wheel.read_bytes(), self.content)
        self.assertEqual(list(wheel.parent.iterdir()), [wheel])
        self.assertEqual(argv, [model.sys.executable, '-m', 'pip', '--isolated',
            '--disable-pip-version-check', 'install', '--no-input', '--keyring-provider', 'disabled',
            '--index-url', 'https://pypi.org/simple', '--only-binary=:all:',
            '-r', str(model.ROOT / 'probes/requirements-model.txt'), argv[-1]])
        self.assertEqual(kwargs, {'cwd': model.ROOT, 'check': True, 'timeout': 300})
        return wheel

    def test_exact_binary_request_verified_local_requirement_and_success_cleanup(self):
        response = Response(self.content)
        self.opener.open.return_value = response
        self.run.side_effect = self.assert_wheel_during_pip
        model.install_binding()

        self.run.assert_called_once()
        self.opener.open.assert_called_once()
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url,
            'https://api.github.com/repos/abetlen/llama-cpp-python/releases/assets/602608411')
        self.assertEqual(dict(request.header_items()), {
            'Accept': 'application/octet-stream', 'User-agent': 'Kat-test-model-preparation/1.0',
        })
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(self.opener.open.call_args.kwargs, {'timeout': 60})
        self.assertEqual(self.build.call_args.args[0].proxies, {})
        self.assertEqual(response.requested_size, len(self.content) + 1)
        self.assertTrue(response.closed)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_corrupt_short_oversize_and_interrupted_downloads_never_reach_pip(self):
        for response in [Response(b'x' * len(self.content)), Response(self.content[:-1]),
                         Response(self.content + b'extra'), InterruptedResponse(b'partial')]:
            with self.subTest(response=response):
                self.opener.open.return_value = response
                with self.assertRaises((ValueError, IncompleteRead)):
                    model.install_binding()
                self.run.assert_not_called()
                self.assertTrue(response.closed)
                self.assertEqual(list(self.root.iterdir()), [])
        # Size validation must independently reject an otherwise matching hash.
        for content in [self.content[:-1], self.content + b'x']:
            with self.subTest(size=len(content)), \
                    patch.object(model, 'CPU_WHEEL_SHA256', sha256(content).hexdigest()):
                self.opener.open.return_value = Response(content)
                with self.assertRaisesRegex(ValueError, 'size/hash'):
                    model.install_binding()
                self.run.assert_not_called()
                self.assertEqual(list(self.root.iterdir()), [])

    def test_http_error_propagates_without_pip_or_temporary_files(self):
        failure = HTTPError(model.CPU_WHEEL_URL, 504, 'synthetic failure', {}, None)
        self.opener.open.side_effect = failure
        with self.assertRaises(HTTPError) as caught:
            model.install_binding()
        self.assertIs(caught.exception, failure)
        self.opener.open.assert_called_once()
        self.run.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_pip_failure_or_timeout_cleans_wheel_and_does_not_prepare_model(self):
        for failure in [subprocess.CalledProcessError(1, ['synthetic pip']),
                        subprocess.TimeoutExpired(['synthetic pip'], 300)]:
            with self.subTest(failure=failure), patch.object(model, 'prepare_model') as prepare:
                wheel_paths = []
                def fail(argv, **kwargs):
                    wheel_paths.append(self.assert_wheel_during_pip(argv, **kwargs))
                    raise failure
                self.opener.open.return_value = Response(self.content)
                self.run.side_effect = fail
                with self.assertRaises(type(failure)) as caught:
                    model.main()
                self.assertIs(caught.exception, failure)
                prepare.assert_not_called()
                self.assertEqual(len(wheel_paths), 1)
                self.assertFalse(wheel_paths[0].exists())
                self.assertFalse(wheel_paths[0].parent.exists())
                self.assertEqual(list(self.root.iterdir()), [])
