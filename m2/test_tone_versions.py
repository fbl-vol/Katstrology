"""Instruction-version compatibility, not real-model voice-quality evaluation."""

from hashlib import sha256
import unittest
from unittest.mock import patch

from m2 import tone_profiles_v1 as v1, tone_profiles_v2 as v2, tone_profiles_v3 as v3
from m2.tone_profiles import archived_instructions, catalogue, instructions

# Characterization of accepted instruction bytes in deployed155, independently
# captured before this revision. A style/base edit must not rewrite these identities.
V1_HASHES = {
    'quiet-wonder': '48c31046da101ce187523de66fa45126686702fa3a14dfdef0be8afde17661a1',
    'thoughtful-wit': '5e90aa6dfb822a425d469c955b459a1d2bd5baf0d688835b0f473404b60a6c99',
    'grounded-warmth': '48626f1bac2455e25e0d2d66874569b568c1b650b36191dcd0da801284b5fd9c',
    'playful-cheek': '4d67e307047115764dff86ae4e608a17df4e569a93a3ed7d8bf7c91d80205612',
    'cosmic-cabaret': 'a03c5b23e7be8ffb6c13f82149ca94e25140a7091e3752e44aeaafe3cec43621',
}


# Characterization captured from released8b before adding section rhythm.
V2_HASHES = {
    'thoughtful-wit': '2fde8c64248a6c1d038c2bef78471e70dfe4d63eb44dfef4c7fd623e7ea6f91f',
    'grounded-warmth': 'ec1b916c9c59ba3bffd0c82f66dec1eca6ddbf8f613cd450d770241c5687bfa1',
    'playful-cheek': '9787c21450532f0c3853b9400f6ad89fd040886bd0db33e265077b04ff107cc0',
    'cosmic-cabaret': 'cbc80f09c15161d1eb8bbb6209504fc88e62160d57fddcb0dc4bce46db0d9291',
}


def legacy_identity(tone_id, version=1):
    hashes = V1_HASHES if version == 1 else V2_HASHES
    return {'tone_id': tone_id, 'tone_version': version, 'tone_shared_version': version,
            'prompt_version': f'2026-11-03.1.tone{version}', 'prompt_mode': 'hosted',
            'prompt_sha256': hashes[tone_id]}


class ToneVersionTests(unittest.TestCase):
    def test_all_deployed_versions_reconstruct_even_if_current_base_changes(self):
        with patch('m2.tone_profiles.HOSTED', 'a future base must not rewrite accepted tones'):
            for version, hashes in ((1, V1_HASHES), (2, V2_HASHES)):
                for tone_id, expected_hash in hashes.items():
                    with self.subTest(tone_id=tone_id, version=version):
                        record = legacy_identity(tone_id, version)
                        text, recovered = archived_instructions(record)
                        self.assertEqual(recovered, record)
                        self.assertEqual(sha256(text.encode()).hexdigest(), expected_hash)

    def test_quiet_wonder_effective_instructions_identity_and_preview_do_not_change(self):
        text, record = instructions('quiet-wonder')
        self.assertEqual(record, legacy_identity('quiet-wonder'))
        self.assertEqual(sha256(text.encode()).hexdigest(), V1_HASHES['quiet-wonder'])
        quiet = catalogue()['profiles'][0]
        self.assertEqual(quiet['version'], 1)
        self.assertEqual(quiet['description'], 'Calm curiosity, clear observation and gentle wonder.')
        self.assertEqual(quiet['example'],
            'A square is an angle of roughly 90° between two planets. In astrology, it can symbolize '
            'priorities that take effort to coordinate. The interesting detail is which planets are '
            'involved: that tells us more than the square alone. Their signs, houses and the wider '
            'chart help make the interpretation specific.')

    def test_four_revisions_supply_real_traits_without_diluting_governing_rules(self):
        profiles = {p['id']: p for p in catalogue()['profiles']}
        self.assertEqual(set(profiles), set(V1_HASHES))
        for tone_id, revision in v2.REVISIONS.items():
            with self.subTest(tone_id=tone_id):
                text, record = instructions(tone_id)
                self.assertEqual((record['tone_version'], profiles[tone_id]['version']), (3, 3))
                self.assertNotEqual(record['prompt_sha256'], V1_HASHES[tone_id])
                self.assertEqual(archived_instructions(record), (text, record))
                self.assertIn(v1.HOSTED.split('\n\n', 2)[2], text)
                self.assertIn(revision['instruction'], text)
                self.assertIn(v2.EXPRESSION, text)
                for example in revision['examples']:
                    self.assertIn(example, text)
                self.assertIn('not chart evidence', text)
                self.assertNotIn('give a useful friendly answer with quieter warmth', text)
                self.assertNotIn('Reduce humour and theatricality for painful, serious or practical', text)
                self.assertNotRegex(text, r'\[p-[0-9a-f]+\]')
                self.assertEqual(profiles[tone_id]['example'], revision['preview'])

    def test_section_arcs_and_final_landing_apply_to_the_complete_answer_only(self):
        for tone_id, landing in v3.LANDINGS.items():
            with self.subTest(tone_id=tone_id):
                text, record = instructions(tone_id)
                previous, _ = archived_instructions(legacy_identity(tone_id, 2))
                self.assertTrue(text.startswith(previous + '\n\nSection rhythm and a strong final landing:'))
                self.assertEqual(record['tone_version'], 3)
                self.assertIn(v3.SECTION_RHYTHM, text)
                self.assertIn(landing, text)
                self.assertIn('existing flexible opening/body/closing arc', text)
                self.assertIn('A provider response or tool boundary is not automatically a section or ending', text)
                self.assertIn('Do not add an extra provider call solely to manufacture a closing', text)
                self.assertIn('not a new visible template', text)
                self.assertIn('Short factual sections and short answers may end naturally', text)
        quiet, _ = instructions('quiet-wonder')
        self.assertNotIn(v3.SECTION_RHYTHM, quiet)

    def test_reconstruction_refuses_missing_or_tampered_versions_without_falling_back(self):
        old = legacy_identity('cosmic-cabaret')
        for bad in [dict(old, tone_version=99), dict(old, tone_shared_version=2),
                    dict(old, prompt_sha256='0' * 64), dict(old, tone_version=True),
                    dict(old, tone_shared_version=True), dict(old, extra='untrusted'),
                    dict(old, tone_id=[]), dict(old, tone_version=2)]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                archived_instructions(bad)
        for unknown in [None, [], {}, 'not-a-profile']:
            with self.subTest(unknown=unknown), self.assertRaises(ValueError):
                instructions(unknown)
