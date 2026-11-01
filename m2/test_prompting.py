"""Pinned instruction releases; changed text must receive a new version and digest."""

from hashlib import sha256
import unittest

from m2.prompting import HOSTED, LOCAL, SUMMARY, identity, summary_identity
from m2.recall import SYSTEM


class PromptIdentityTests(unittest.TestCase):
    def test_versioned_instruction_bytes_and_compatibility_alias(self):
        self.assertIs(SYSTEM, LOCAL)
        expected = {
            'local': '704636f680a118535bfa69aa4f1b52bdcfe629ceeb7466c744a897845f8e6444',
            'hosted': '4239dfe3591551a4974ceac2c64c87b29ee64bdf33fc278cd473b8a39aeb1584',
        }
        for mode, text in (('local', LOCAL), ('hosted', HOSTED)):
            with self.subTest(mode=mode):
                self.assertEqual(identity(mode), {
                    'prompt_version': '2026-11-01.1', 'prompt_mode': mode,
                    'prompt_sha256': expected[mode],
                })
                self.assertEqual(sha256(text.encode('utf-8')).hexdigest(), expected[mode])
                self.assertNotIn('one or two short sentences', text.lower())
                # Delivery/contract checks, not a claim about actual model voice.
                self.assertIn('open briefly with extra warmth tied to this question', text)
                self.assertIn('give a useful friendly answer with quieter warmth', text)
                self.assertIn('Short facts or greetings can end naturally', text)
                self.assertIn('Finish the request before optional', text)
                self.assertIn('use topic headings or person lists when helpful, never rhythm labels or filler', text)
                self.assertIn('no em dashes (U+2014)', text)
                self.assertIn('rhetorical negation-then-reversal', text)
                self.assertNotIn('\u2014', text)
                self.assertIn('real corrections, uncertainty and exact source quotations', text)
                self.assertIn('Compare exact cycles only with verified dates and geometry', text)
                self.assertIn('skip known method, birth-time and default-zone boilerplate unless asked or material', text)
                self.assertIn('Separate computed chart facts from unverified input and symbolism', text)
                self.assertIn('now/today uses turn UTC/reporting date, not guessed zone', text)
                self.assertIn('No invented chart, altered time or upgraded provisional data', text)
                if mode == 'hosted':
                    self.assertIn('computed-versus-symbolic or Copenhagen/default-zone setup belongs in chart/message details', text)
                    self.assertIn('a cross-zone date boundary changes the answer', text)
                    self.assertIn('name uncertain houses/angles only when the claim depends on them', text)
                self.assertIn('new browser turns cannot attach', text.lower())
                if mode == 'hosted':
                    self.assertNotIn('You have no autonomous tools here.', text)
                    self.assertIn('Illustrative voice only, not chart facts or answer templates to reuse', text)
                    self.assertIn('semantic Markdown when helpful: subject headings, short paragraphs', text)
                    self.assertIn('selective bold takeaways and compact person-labelled comparison lists', text)
                    self.assertIn('No fixed template or visible Acknowledgement / Answer / Follow-up rhythm labels', text)
                    self.assertIn('No raw HTML', text)
                    self.assertIn('optional server-resolved saved chart context', text)
                    self.assertIn('authorized historical media or supported alternate clients', text)
                    self.assertIn('declared, bounded read-only functions', text)
                    self.assertIn('a read count alone does not end the conversation', text)
                    self.assertIn('Cite fetched passage IDs', text)
                    self.assertIn('follow next_offset when needed', text)
                    self.assertIn('Check claim support', text)
        with self.assertRaises(ValueError):
            identity('unknown')

    def test_separate_versioned_summary_instructions(self):
        expected = '7d1956ac80fa90eddc4df626932973b2f1d67f66ad36db105eb0f0b9c445bb13'
        self.assertEqual(summary_identity(), {'summary_version': '2026-10-29.1',
                                               'summary_sha256': expected})
        self.assertEqual(sha256(SUMMARY.encode()).hexdigest(), expected)
        self.assertNotIn('## Goal', SUMMARY)
        self.assertNotEqual(SUMMARY, HOSTED)


if __name__ == '__main__':
    unittest.main()
