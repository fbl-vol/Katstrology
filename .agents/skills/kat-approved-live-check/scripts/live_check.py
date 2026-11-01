#!/usr/bin/env python3
"""Plan a scoped one-send browser check; observe archived metadata separately."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parent
GUARDS = ROOT / '.local/kat-live-guards'


def git_tip():
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    return sha, dirty


def scope_digest(scope):
    if not isinstance(scope, list) or any(not isinstance(pair, list) or len(pair) != 2 or
            not isinstance(pair[0], str) or pair[1] is not None and not isinstance(pair[1], str)
            for pair in scope):
        raise ValueError('Invalid selection metadata')
    ordered = sorted(scope, key=lambda item: item[0])
    if len({pair[0] for pair in ordered}) != len(ordered):
        raise ValueError('Duplicate selected person')
    return sha256(json.dumps(ordered, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def approval(approved_path, args):
    if not approved_path:
        raise ValueError('A separate exact-scope user approval receipt is required')
    receipt = json.loads(Path(approved_path).read_text())
    expected = {'action': 'one-live-send', 'approval_id': receipt.get('approval_id'),
                'commit': args.commit, 'origin': args.origin, 'session': args.session,
                'question_sha256': args.question_sha256, 'model_slug': args.model_slug,
                'scope': receipt.get('scope')}
    if (receipt != expected or not isinstance(receipt['approval_id'], str) or
            not re.fullmatch('[a-zA-Z0-9_-]{8,64}', receipt['approval_id'])):
        raise ValueError('Approval scope does not match the requested send')
    expected['scope_sha256'] = scope_digest(receipt['scope'])
    return expected


def browser(session, script):
    completed = subprocess.run(['playwright-cli', '-s=' + session, 'run-code',
        '--filename', str(SCRIPTS / script)], cwd=ROOT, text=True,
        capture_output=True, timeout=20)
    if completed.returncode:
        raise RuntimeError('Browser command did not confirm its action')
    # CLI may add banners/snapshots. Never print them; accept one bounded marker.
    matches = re.findall(r'KAT_META:(\{[^\r\n]*\})', completed.stdout)
    if len(matches) != 1 or len(matches[0]) > 1200:
        raise ValueError('Browser metadata marker missing or ambiguous')
    return json.loads(matches[0])


def guard_path(receipt):
    data = {key: receipt[key] for key in ('approval_id', 'commit', 'origin', 'session',
                                          'question_sha256', 'model_slug', 'scope_sha256')}
    return GUARDS / (sha256(json.dumps(data, sort_keys=True).encode()).hexdigest() + '.json')


def preflight(meta, receipt):
    if (meta.get('origin') != receipt['origin'] or
            meta.get('model_slug') != receipt['model_slug'] or
            meta.get('question_sha256') != receipt['question_sha256'] or
            meta.get('scope_sha256') != receipt['scope_sha256'] or
            meta.get('scope_count') != len(receipt['scope']) or
            not meta.get('conversation_id') or not meta.get('send_ready') or
            meta.get('dialog_open') or not isinstance(meta.get('previous_turns'), int) or
            not isinstance(meta.get('question_length'), int) or meta['question_length'] < 1):
        raise ValueError('Browser model, draft, scope or readiness does not match approval')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('send', 'observe'))
    parser.add_argument('--commit', required=True, help='Exact clean 40-character source tip')
    parser.add_argument('--origin', required=True, help='Exact authorized 127.0.0.1 HTTP origin')
    parser.add_argument('--session', required=True, help='Existing authorized playwright-cli session name')
    parser.add_argument('--question-sha256', required=True, help='SHA-256 of already approved UI draft, never raw text')
    parser.add_argument('--model-slug', required=True)
    parser.add_argument('--approval-file', help='Private exact-tip one-send approval receipt; a flag alone is not permission')
    parser.add_argument('--execute', action='store_true', help='Operate browser only after actual scoped user approval')
    args = parser.parse_args()
    report = {'action': args.operation if args.execute else 'plan', 'status': 'stopped',
              'commit': args.commit, 'browser_calls': 0}
    try:
        origin = urlsplit(args.origin)
        if (origin.scheme != 'http' or origin.hostname != '127.0.0.1' or
                origin.port is None or args.origin != f'http://127.0.0.1:{origin.port}' or
                not re.fullmatch('[a-zA-Z0-9_-]{1,64}', args.session) or
                not re.fullmatch('[0-9a-f]{40}', args.commit) or
                not re.fullmatch('[0-9a-f]{64}', args.question_sha256) or
                not re.fullmatch('[a-zA-Z0-9_.-]{1,80}', args.model_slug)):
            raise ValueError('Invalid scoped browser identifiers')
        tip, dirty = git_tip()
        if tip != args.commit or dirty:
            raise ValueError('Checkout is not clean at approved tip')
        if not args.execute:
            report['status'] = 'planned'  # no browser/session/approval/credentials touched
        else:
            receipt = approval(args.approval_file, args)
            guard = guard_path(receipt)
            if args.operation == 'send':
                if guard.exists():
                    raise ValueError('This approval was already attempted; never resend')
                meta = browser(args.session, 'preflight.js')
                report['browser_calls'] += 1
                preflight(meta, receipt)
                GUARDS.mkdir(mode=0o700, parents=True, exist_ok=True)
                payload = {'approval_id': receipt['approval_id'], 'commit': args.commit,
                           'origin': args.origin, 'session': args.session,
                           'question_sha256': args.question_sha256,
                           'model_slug': args.model_slug, 'scope_sha256': receipt['scope_sha256'],
                           'previous_turns': meta['previous_turns'], 'dispatch_state': 'ambiguous'}
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                descriptor = os.open(guard, flags, 0o600)
                with os.fdopen(descriptor, 'w') as output:
                    json.dump(payload, output, sort_keys=True)
                    output.flush()
                    os.fsync(output.fileno())
                directory = os.open(GUARDS, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                # An exception/timeout here may occur after the click or ACK. Never retry.
                report['status'] = 'ambiguous-send-attempt'
                report['guard_recorded'] = True
                report['browser_calls'] += 1
                browser(args.session, 'dispatch.js')
            else:
                if not guard.is_file():
                    raise ValueError('No recorded send attempt for this approval')
                previous = json.loads(guard.read_text())
                if previous.get('scope_sha256') != receipt['scope_sha256']:
                    raise ValueError('Guard scope changed')
                meta = browser(args.session, 'observe.js')
                report['browser_calls'] += 1
                if meta.get('visible_turns', 0) <= previous['previous_turns']:
                    report['status'] = 'ack-unknown'
                elif meta.get('scope_sha256') != receipt['scope_sha256'] or meta.get('model_slug') != args.model_slug:
                    report['status'] = 'archive-scope-mismatch'
                else:
                    report['status'] = meta['status'] if meta['status'] in (
                        'complete', 'error', 'interrupted', 'open', 'pagination_exceeded',
                        'archive_unavailable') else 'archive-unknown'
                    report['metadata'] = {key: meta.get(key) for key in (
                        'pages', 'event_count', 'answer_length', 'tool_calls', 'tool_results',
                        'transit_artifacts', 'complete_markers', 'terminal_error_code')}
                    if report['status'] == 'complete' and (not meta.get('answer_length') or
                            meta.get('complete_markers') != 1):
                        report['status'] = 'empty-or-inconsistent-answer'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        report['error_type'] = type(exc).__name__
    print(json.dumps(report, sort_keys=True))
    if report['status'] in ('planned', 'complete'):
        return 0
    return 2 if report['status'] in ('ambiguous-send-attempt', 'open', 'ack-unknown') else 1


if __name__ == '__main__':
    sys.exit(main())
