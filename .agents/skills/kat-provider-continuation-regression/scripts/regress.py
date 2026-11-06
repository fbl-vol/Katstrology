#!/usr/bin/env python3
"""Select the repository's synthetic Responses/gateway regressions; never contact a provider."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
VALIDATE = ROOT / '.agents/skills/kat-isolated-validation/scripts/validate.py'
CASES = {
    'stream': ['tests.provider.test_provider_output_compat.OutputParserTests',
               'tests.provider.test_provider_output_compat.OutputArchiveTests'],
    'identity': ['tests.chat.test_agent_reads.AgentReadTests'],
    'many-reads': ['tests.chat.test_tool_evidence_budget.ToolEvidenceBudgetTests'],
    'capacity': ['tests.chat.test_agent_reads.AgentReadTests.test_continuation_capacity_preserves_call_result_but_never_sends_overflow',
                 'tests.chat.test_tool_evidence_budget.ToolEvidenceBudgetTests.test_exhausted_aggregate_byte_guard_archives_result_and_stops_cleanly'],
}
BROWSER_GREP = 'three native reads|eight model-directed reads|synthetic completed streamed read|incomplete synthetic streamed call'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=(*CASES, 'all', 'browser'), default='all')
    parser.add_argument('--execute', action='store_true', help='Run only via owned isolated validation runner')
    args = parser.parse_args()
    # Class selections already include the two focused capacity methods. Keep those methods
    # as a separate fast case, not duplicate unittest identities in the full selection.
    names = ('stream', 'identity', 'many-reads') if args.case == 'all' else (args.case,)
    selectors = [item for name in names for item in CASES.get(name, [])]
    report = {'action': 'execute' if args.execute else 'plan', 'case': args.case,
              'backend_selectors': selectors,
              'browser_filter': BROWSER_GREP if args.case in ('all', 'browser') else None,
              'status': 'planned', 'runs': []}
    if args.execute:
        profiles = (['backend'] if selectors else []) + (
            ['siwc'] if args.case in ('all', 'browser') else [])
        argv = [sys.executable, str(VALIDATE), '--profiles', *profiles, '--execute']
        if selectors:
            argv.extend(['--tests', *selectors])
        if 'siwc' in profiles:
            argv.extend(['--browser-grep', BROWSER_GREP])
        # Only the runner's sanitized stage notices reach stderr; keep its final JSON on stdout.
        result = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE, text=True)
        try:
            child = json.loads(result.stdout.strip())
            report['runs'].append(child)
            report['status'] = 'passed' if result.returncode == 0 and child['status'] == 'ok' else 'stopped'
        except (json.JSONDecodeError, KeyError):
            report['runs'].append({'status': 'stopped', 'error_type': 'InvalidRunnerOutput'})
            report['status'] = 'stopped'
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] in ('planned', 'passed') else 1


if __name__ == '__main__':
    sys.exit(main())
