"""Offline published workflow identity; no host, trust or GitHub writes."""
from pathlib import Path
import unittest
from unittest.mock import patch

from deploy import prepare_workflow_adoption as adoption

ROOT = Path(__file__).resolve().parents[2]


class WorkflowAdoptionTests(unittest.TestCase):
    def test_nested_published_bytes_bind_future_signer_without_installation(self):
        documents = [(ROOT / '.github/workflows' / name).read_bytes() for name in adoption.WORKFLOWS]
        with patch.object(adoption.subprocess, 'check_output', side_effect=documents) as git:
            result = adoption.prepare(ROOT)
        self.assertEqual(result['status'], 'prepared-not-enrolled')
        self.assertEqual(result['future_policy_change'], {
            'field': 'signer_sha', 'from': 'c31e7dd8fa3becd61851647a3158c95172e68eb5',
            'to': 'f64fb6dcbd104cff83219827dce5eef849fde89b'})
        self.assertEqual(result['qualification_job'], 'release / qualify / candidate')
        self.assertTrue(all(call.args[0][3] == 'show' for call in git.call_args_list))
        self.assertTrue(all('f64fb6dcbd104cff83219827dce5eef849fde89b:' in call.args[0][4]
                            for call in git.call_args_list))

    def test_old_serial_or_altered_workflow_cannot_be_adopted_as_parallel(self):
        with patch.object(adoption.subprocess, 'check_output', return_value=b'jobs: {candidate: {}}'):
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                adoption.prepare(ROOT)
