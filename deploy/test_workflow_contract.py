"""Offline workflow wiring and synthetic transport handoff; no hosted/SSH proof."""

from contextlib import chdir
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from deploy import ci_transport

ROOT = Path(__file__).resolve().parents[1]
KEY = 'KAT_CI_TRANSPORT_KEY'


def workflow(name):
    # BaseLoader keeps GitHub's `on` key literal instead of YAML1.1 boolean coercion.
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


class WorkflowContractTests(unittest.TestCase):
    def test_only_deployment_consumes_the_explicit_required_secret(self):
        trusted = workflow('trusted-release.yml')
        secrets = (trusted['on']['workflow_call'] or {}).get('secrets', {})
        self.assertEqual(set(secrets), {KEY})
        self.assertEqual(secrets[KEY]['required'], 'true')
        jobs = trusted['jobs']
        self.assertEqual(jobs['deploy']['environment'], 'kat-production')
        transport = next(step for step in jobs['deploy']['steps']
                         if step.get('run') == 'python -m deploy.ci_transport')
        self.assertEqual(transport['env'][KEY], '${{ secrets.KAT_CI_TRANSPORT_KEY }}')
        for name in ('qualify', 'attest'):
            self.assertNotIn('secrets', jobs[name])
            self.assertNotIn('secrets.', str(jobs[name]))
            self.assertNotIn('environment', jobs[name])


class TransportSecretTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix='workflow-secret-', dir=ROOT / '.local'))
        self.enterContext(chdir(directory))
        self.enterContext(patch.dict(os.environ, {
            'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
            'GITHUB_REPOSITORY_ID': '1437147047', 'GITHUB_REPOSITORY': 'fbl-vol/Katstrology',
            'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'push',
            'GITHUB_RUN_ATTEMPT': '1', 'KAT_AUTOMATION_ENABLED': 'true',
            'KAT_CI_SSH_HOST': 'synthetic.invalid', 'KAT_CI_SSH_USER': 'synthetic',
            'KAT_CI_KNOWN_HOSTS': 'synthetic.invalid ssh-ed25519 AAAA\n', KEY: '',
        }, clear=True))
        self.execute = self.enterContext(patch.object(ci_transport, 'execute'))
        previous_umask = os.umask(0o077)
        self.addCleanup(os.umask, previous_umask)

    def test_empty_forwarded_value_still_refuses_before_transport(self):
        with self.assertRaisesRegex(ValueError, 'Dedicated constrained CI identity absent'):
            ci_transport.main()
        self.execute.assert_not_called()

    def test_nonempty_synthetic_value_reaches_only_the_owned_profile_and_is_removed(self):
        os.environ[KEY] = 'SYNTHETIC_NOT_A_REAL_KEY'
        roots = []

        def inspect_profile(_receipt, _manifest, _bundle, profile, _result):
            roots.append(profile.parent)
            identity = profile.parent / 'identity'
            self.assertEqual(identity.read_text(), 'SYNTHETIC_NOT_A_REAL_KEY\n')
            self.assertEqual(identity.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(KEY, os.environ)
            self.assertIn('StrictHostKeyChecking yes', profile.read_text())
            self.assertIn('IdentityAgent none', profile.read_text())

        self.execute.side_effect = inspect_profile
        ci_transport.main()
        self.execute.assert_called_once()
        self.assertFalse(roots[0].exists(), 'Owned transport files must be cleaned after handoff')
