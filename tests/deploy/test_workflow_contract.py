"""Offline workflow wiring and synthetic transport handoff; no hosted/SSH proof."""

from contextlib import chdir
import os
from pathlib import Path
import shlex
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from deploy import ci_transport

ROOT = Path(__file__).resolve().parents[2]
KEY = 'KAT_CI_TRANSPORT_KEY'
TS_KEY = 'KAT_CI_TS_CLIENT_SECRET'


def workflow(name):
    # BaseLoader keeps GitHub's `on` key literal instead of YAML1.1 boolean coercion.
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


class WorkflowContractTests(unittest.TestCase):
    def test_parallel_qualification_requires_every_lane_before_candidate_upload(self):
        document = workflow('qualify.yml')
        jobs = document['jobs']
        self.assertEqual(set(jobs), {'synthetic', 'native', 'candidate'})
        matrix = jobs['synthetic']['strategy']
        self.assertEqual(matrix['fail-fast'], 'false')
        self.assertEqual([entry['lane'] for entry in matrix['matrix']['include']],
                         ['backend', 'browser-1', 'browser-2', 'browser-3', 'browser-4', 'interaction'])
        candidate = jobs['candidate']
        self.assertEqual(candidate['name'], 'candidate')
        self.assertEqual(candidate['needs'], ['synthetic', 'native'])
        self.assertEqual(candidate['if'], 'success()')
        self.assertEqual(document['on']['workflow_call']['outputs']['artifact-id']['value'],
                         '${{ jobs.candidate.outputs.artifact-id }}')
        for job in jobs.values():
            self.assertEqual(job['runs-on'], 'ubuntu-24.04')
            self.assertNotIn('concurrency', job)
            self.assertNotIn('secrets', job)
            self.assertNotIn('continue-on-error', str(job))
            self.assertEqual(job['steps'][0]['with'], {
                'persist-credentials': 'false', 'ref': '${{ github.sha }}'})
        steps = candidate['steps']
        join = next(step for step in steps if '--join' in step.get('run', ''))
        upload = next(step for step in steps if step.get('id') == 'upload')
        self.assertLess(steps.index(join), steps.index(upload))
        self.assertNotIn('if', upload)  # Normal success gate, never always().
        self.assertIn('qualification.json', upload['with']['path'])
        downloads = [step['with'] for step in steps if step.get('uses', '').startswith('actions/download-artifact@')]
        self.assertTrue(all('${{ github.run_attempt }}' in str(step) for step in downloads))
        self.assertTrue(all('${{ github.run_id }}' in str(step) for step in downloads))
        self.assertEqual(downloads[0]['merge-multiple'], 'false')
        native_upload = next(step for step in jobs['native']['steps'] if step.get('id') == 'native')
        self.assertNotIn('qualification.json', native_upload['with']['path'])
        self.assertNotIn('deploy/build_local.py', str(candidate))
        self.assertEqual(document['permissions'], {'contents': 'read'})

    def test_caller_forwards_only_named_secrets_to_reviewed_authority(self):
        jobs = workflow('release.yml')['jobs']
        self.assertEqual(jobs['release'].get('secrets'), {
            KEY: '${{ secrets.KAT_CI_TRANSPORT_KEY }}',
            TS_KEY: '${{ secrets.KAT_CI_TS_CLIENT_SECRET }}'})
        # Deliberate authority pins, not history lookups: hosted checkout is shallow.
        self.assertEqual(jobs['release']['uses'],
            'fbl-vol/Katstrology/.github/workflows/trusted-release.yml@'
            'c31e7dd8fa3becd61851647a3158c95172e68eb5')
        self.assertEqual(jobs['validate']['uses'],
            'fbl-vol/Katstrology/.github/workflows/qualify.yml@'
            'c4310ac296fade23959efccbe340afb0239d0bb5')
        self.assertNotIn('secrets', jobs['validate'])
        self.assertNotIn('environment', jobs['release'])

    def test_only_deployment_consumes_the_explicit_required_secrets(self):
        trusted = workflow('trusted-release.yml')
        secrets = (trusted['on']['workflow_call'] or {}).get('secrets', {})
        self.assertEqual(set(trusted['on']['workflow_call']), {'secrets'})
        self.assertEqual(set(secrets), {KEY, TS_KEY})
        for secret in secrets.values():
            self.assertEqual(secret['required'], 'true')
        jobs = trusted['jobs']
        self.assertEqual(jobs['deploy']['environment'], 'kat-production')
        self.assertEqual(jobs['deploy']['permissions'], {'contents': 'read'})
        self.assertEqual(jobs['qualify']['permissions'], {'contents': 'read'})
        self.assertEqual(jobs['attest']['permissions'], {
            'contents': 'read', 'id-token': 'write', 'attestations': 'write'})
        self.assertEqual(jobs['deploy']['needs'], 'attest')
        self.assertEqual(jobs['deploy']['if'],
            "github.event_name == 'push' && github.ref == 'refs/heads/main' && "
            "github.repository_id == '1437147047' && github.run_attempt == 1 && "
            "vars.KAT_AUTOMATION_ENABLED == 'true'")
        transport = next(step for step in jobs['deploy']['steps']
                         if step.get('run') == 'python -m deploy.ci_transport')
        self.assertEqual(transport['env'][KEY], '${{ secrets.KAT_CI_TRANSPORT_KEY }}')
        for name in ('qualify', 'attest'):
            self.assertNotIn('secrets', jobs[name])
            self.assertNotIn('secrets.', str(jobs[name]))
            self.assertNotIn('environment', jobs[name])
            self.assertNotIn('KAT_CI_TS_', str(jobs[name]))

    def test_vendor_up_arguments_do_not_repeat_native_flags(self):
        steps = workflow('trusted-release.yml')['jobs']['deploy']['steps']
        join = next(step for step in steps if step.get('uses', '').startswith('tailscale/'))
        # Reviewed vendor064b105 prepends these options; CLI1.104.5 rejects repeats.
        vendor = ['--advertise-tags=tag:kat-release-ci', '--hostname=synthetic-argv-only',
                  '--accept-routes']
        flags = [arg.split('=', 1)[0] for arg in vendor + shlex.split(join['with']['args'])]
        self.assertEqual(len(flags), len(set(flags)), 'Native up flags must each occur once')

    def test_private_join_is_pinned_ephemeral_and_fenced_before_transport(self):
        jobs = workflow('trusted-release.yml')['jobs']
        joins = [(name, step) for name, job in jobs.items()
                 for step in job.get('steps', [])
                 if step.get('uses', '').startswith('tailscale/')]
        self.assertEqual(len(joins), 1)
        name, join = joins[0]
        self.assertEqual(name, 'deploy')
        self.assertEqual(join['uses'],
            'tailscale/github-action@064b10558093f38325e838ddea35486bdc6b1d5c')
        # This immutable action owns ephemeral registration and post logout.
        # Exact inputs forbid OIDC/authkey fallbacks, extra tags/routes or state reuse.
        self.assertEqual(set(join), {'name', 'uses', 'with'})
        self.assertEqual(join['with'], {
            'oauth-client-id': '${{ vars.KAT_CI_TS_CLIENT_ID }}',
            'oauth-secret': '${{ secrets.KAT_CI_TS_CLIENT_SECRET }}',
            'tags': 'tag:kat-release-ci',
            'version': '1.104.5',
            'sha256sum': '720cbbccbfc03d8b55df72afc19e5a72e31b0f65934700aa6fa38074d4ad7bf7',
            'use-cache': 'false',
            'statedir': '',
            'args': '--accept-dns=false --ssh=false',
            'ping': '${{ vars.KAT_CI_SSH_HOST }}',
        })
        deploy = jobs['deploy']
        self.assertEqual(deploy['runs-on'], 'ubuntu-24.04')  # Linux amd64 checksum.
        steps = deploy['steps']
        fence = steps[steps.index(join) + 1]
        # No condition, failure swallowing or extra command between join and transport.
        self.assertEqual(set(fence), {'name', 'run'})
        self.assertEqual(fence['run'],
                         'sudo tailscale set --accept-routes=false --accept-dns=false --ssh=false')
        transport = steps[steps.index(join) + 2]
        self.assertEqual(transport['run'], 'python -m deploy.ci_transport')
        self.assertNotIn(TS_KEY, str(transport))
        self.assertNotIn('if', transport)  # Native success gate: join AND fence must succeed.
        self.assertNotIn('continue-on-error', transport)
        checkout = steps[0]
        self.assertTrue(checkout['uses'].startswith('actions/checkout@'))
        self.assertEqual(checkout['with'], {'persist-credentials': 'false', 'ref': '${{ github.sha }}'})


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

    def test_private_target_rejects_an_unrebound_host_pin_before_transport(self):
        os.environ['KAT_CI_SSH_HOST'] = '100.64.0.42'  # Synthetic; never contacted.
        with self.assertRaisesRegex(ValueError, 'One exact enrolled SSH host key required'):
            ci_transport.main()
        self.execute.assert_not_called()

    def test_nonempty_synthetic_value_reaches_only_the_owned_profile_and_is_removed(self):
        os.environ[KEY] = 'SYNTHETIC_NOT_A_REAL_KEY'
        os.environ['KAT_CI_SSH_HOST'] = '100.64.0.42'
        # Rebind the same fake public key, not a newly discovered key.
        os.environ['KAT_CI_KNOWN_HOSTS'] = '100.64.0.42 ssh-ed25519 AAAA\n'
        roots = []

        def inspect_profile(_receipt, _manifest, _bundle, profile, _result):
            roots.append(profile.parent)
            identity = profile.parent / 'identity'
            self.assertEqual(identity.read_text(), 'SYNTHETIC_NOT_A_REAL_KEY\n')
            self.assertEqual(identity.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(KEY, os.environ)
            self.assertIn('StrictHostKeyChecking yes', profile.read_text())
            self.assertIn('IdentityAgent none', profile.read_text())
            self.assertIn('HostName 100.64.0.42', profile.read_text())
            self.assertEqual((profile.parent / 'known_hosts').read_text(),
                             '100.64.0.42 ssh-ed25519 AAAA\n')

        self.execute.side_effect = inspect_profile
        ci_transport.main()
        self.execute.assert_called_once()
        self.assertFalse(roots[0].exists(), 'Owned transport files must be cleaned after handoff')
