"""Local synthetic-only CLI. No HTTP listener, remote inference or private import."""

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import swisseph as swe

from m2.attachments import Attachments, MAX_ATTACHMENT
from m2.deletion import Tombstones
from m2.evidence import LocalEmbedder, personal_context, rebuild_vectors, search_evidence
from m2.gateway import (CHART_PREFIX, EVENT_PREFIX, REFERENCE_PREFIX,
                        run_turn)
from m2.local_model import DEFAULT_MODEL, model_at
from m2.recall import rebuild_one, rebuild_pending, search
from m2.references import References
from m2.revisions import correct, export_conversation, select_branch
from m2.store import Store


def output(value):
    print(json.dumps(value, default=str, ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    enroll = sub.add_parser('enroll', help='local-workstation user enrollment')
    enroll.add_argument('user')
    for action in ('demo', 'chat', 'read', 'replay', 'search', 'rebuild', 'index',
                   'search-evidence', 'get-passage', 'personal-context', 'attach', 'download',
                   'branch', 'correct', 'withdraw', 'export',
                   'delete-conversation', 'delete-conversations', 'delete-attachment',
                   'delete-person', 'delete-reference'):
        sub.add_parser(action)
    sub.choices['chat'].add_argument('conversation')
    sub.choices['chat'].add_argument('--parent', default='@active')
    sub.choices['chat'].add_argument('--revision', choices=('normal', 'edit', 'regenerate'),
                                     default='normal')
    sub.choices['chat'].add_argument('--replaces')
    sub.choices['chat'].add_argument('--synthetic', action='store_true')
    sub.choices['read'].add_argument('conversation')
    sub.choices['read'].add_argument('turn')
    sub.choices['read'].add_argument('--offset', type=int, default=0)
    sub.choices['replay'].add_argument('conversation')
    sub.choices['replay'].add_argument('turn')
    sub.choices['search'].add_argument('query')
    sub.choices['search-evidence'].add_argument('query')
    sub.choices['search-evidence'].add_argument('--tradition')
    sub.choices['search-evidence'].add_argument('--technique')
    sub.choices['search-evidence'].add_argument('--person')
    sub.choices['get-passage'].add_argument('source_id')
    sub.choices['get-passage'].add_argument('passage_id')
    sub.choices['personal-context'].add_argument('person_id')
    sub.choices['attach'].add_argument('conversation')
    sub.choices['attach'].add_argument('attachment_id')
    sub.choices['attach'].add_argument('file', type=Path)
    sub.choices['download'].add_argument('conversation')
    sub.choices['download'].add_argument('attachment_id')
    sub.choices['download'].add_argument('output', type=Path)
    sub.choices['branch'].add_argument('conversation')
    sub.choices['branch'].add_argument('head')
    for action in ('correct', 'withdraw'):
        sub.choices[action].add_argument('conversation')
        sub.choices[action].add_argument('source_turn')
        sub.choices[action].add_argument('correction_id')
    sub.choices['correct'].add_argument('--synthetic', action='store_true')
    sub.choices['export'].add_argument('conversation')
    sub.choices['export'].add_argument('output', type=Path)
    sub.choices['delete-conversation'].add_argument('conversation')
    sub.choices['delete-conversations'].add_argument('conversations', nargs='+')
    sub.choices['delete-attachment'].add_argument('conversation')
    sub.choices['delete-attachment'].add_argument('attachment_id')
    sub.choices['delete-person'].add_argument('person_id')
    sub.choices['delete-reference'].add_argument('source_id')
    args = parser.parse_args(argv)
    dsn = os.environ.get('KAT_M2_DSN')
    if not dsn:
        parser.error('KAT_M2_DSN is required (owned local PostgreSQL only)')
    files = Path(os.environ.get('KAT_M2_FILES', '.local/m2-runtime/files'))
    ledger = Tombstones(os.environ.get('KAT_M2_LEDGER', '.local/m2-runtime/deletions.jsonl'))
    try:
        with Store(dsn, files, ledger) as store:
            store.recover_open()
            if args.command == 'enroll':
                password = getpass.getpass('New local password: ')
                store.register_local(args.user, password)
                output({'enrolled': args.user})
                return 0
            name = input('Local user: ')
            session = store.authenticate(name, getpass.getpass('Password: '))
            attachments = Attachments(store)
            if args.command == 'read':
                output(store.read_turn(session, args.conversation, args.turn,
                                       event_offset=args.offset))
            elif args.command == 'replay':
                offset = 1  # input was already acknowledged on the original call
                while True:
                    page = store.read_turn(session, args.conversation, args.turn,
                                           event_offset=offset)
                    for event in page['events']:
                        output(event)
                    if page['next_event_offset'] is None:
                        output({'status': page['status'], 'event_count': page['event_count']})
                        break
                    offset = page['next_event_offset']
            elif args.command == 'search':
                output(search(store, session, args.query))
            elif args.command == 'rebuild':
                output({'rebuilt': rebuild_pending(store, session)})
            elif args.command == 'index':
                output({'rebuild_conversations': rebuild_pending(store, session),
                        'vectors': rebuild_vectors(store, session, LocalEmbedder())})
            elif args.command == 'search-evidence':
                output(search_evidence(store, session, args.query, LocalEmbedder(),
                                       tradition=args.tradition, technique=args.technique,
                                       person_id=args.person))
            elif args.command == 'get-passage':
                output(References(store).get_passage(session, args.source_id, args.passage_id))
            elif args.command == 'personal-context':
                output(personal_context(store, session, args.person_id))
            elif args.command == 'attach':
                with args.file.open('rb') as source:
                    content = source.read(MAX_ATTACHMENT + 1)
                output({'digest': attachments.add(session, args.conversation,
                                                  args.attachment_id, args.file.name, content)})
            elif args.command == 'download':
                content = attachments.read(session, args.conversation, args.attachment_id)
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as destination:
                    destination.write(content)
                output({'bytes': len(content)})
            elif args.command == 'branch':
                output({'active_head': select_branch(store, session, args.conversation,
                                                       None if args.head == '@root' else args.head)})
            elif args.command in ('correct', 'withdraw'):
                if args.command == 'correct' and not args.synthetic:
                    parser.error('Only synthetic correction content permitted at the local M2 gate')
                replacement = input('Synthetic correction: ') if args.command == 'correct' else None
                output({'created': correct(store, session, args.conversation, args.correction_id,
                                           args.source_turn, args.command, replacement)})
            elif args.command == 'export':
                output(export_conversation(store, session, args.conversation, args.output))
            elif args.command == 'delete-conversation':
                ledger.delete_conversation(store, session, args.conversation)
                output({'deleted': args.conversation})
            elif args.command == 'delete-conversations':
                ledger.delete_conversations(store, session, args.conversations)
                output({'deleted_conversations': args.conversations})
            elif args.command == 'delete-attachment':
                ledger.delete_attachment(store, session, args.conversation, args.attachment_id)
                output({'deleted_attachment': args.attachment_id})
            elif args.command == 'delete-person':
                ledger.delete_person(store, session, args.person_id)
                output({'deleted_person': args.person_id})
            elif args.command == 'delete-reference':
                ledger.delete_reference(store, session, args.source_id)
                output({'deleted_reference': args.source_id})
            elif args.command in ('demo', 'chat'):
                if args.command == 'chat' and not args.synthetic:
                    parser.error('Local M2 real-data gate is closed; pass --synthetic for synthetic-only questions')
                conv_id = 'synthetic-' + uuid4().hex[:12] if args.command == 'demo' else args.conversation
                store.create_conversation(session, conv_id)
                question = ('solar longitude at 2024-03-20T03:06:00+00:00'
                            if args.command == 'demo' else input('Synthetic question: '))
                swe.set_ephe_path(str((Path(__file__).resolve().parents[1] / '.local/ephe').resolve()))
                deterministic_tool = question.startswith((CHART_PREFIX, EVENT_PREFIX,
                                                         REFERENCE_PREFIX))
                model = None if deterministic_tool else model_at(DEFAULT_MODEL)
                try:
                    turn_id = 'turn-' + uuid4().hex[:12]
                    output({'conversation': conv_id, 'attempted_turn': turn_id,
                            'acknowledged': False})
                    status = run_turn(store, session, conv_id, turn_id, question, model,
                                      output, parent_id=('@root' if args.command == 'demo' else args.parent),
                                      revision_kind=('normal' if args.command == 'demo' else args.revision),
                                      replaces_turn_id=(None if args.command == 'demo' else args.replaces),
                                      acknowledge=output)
                    derivative_error = None
                    if status == 'complete':
                        try:
                            epoch = store._conversation(store.owner(session), conv_id)['epoch']
                            rebuild_one(store, session, conv_id, epoch)
                        except Exception as exc:
                            # Archival completion is already durable and delivered;
                            # expose derivative lag rather than recasting it as lost.
                            derivative_error = type(exc).__name__
                    pending = bool(store.db.execute(
                        'SELECT 1 FROM rebuild_queue WHERE owner_id=%s AND conversation_id=%s',
                        (store.owner(session), conv_id)).fetchone())
                    output({'status': status, 'rebuild_pending': pending,
                            'derivative_error': derivative_error})
                finally:
                    if model is not None:
                        model.close()
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        # No raw DB errors, request content, DSN or private model prompt in diagnostics.
        print(f'Local operation failed ({type(exc).__name__}); inspect turn status by ID.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
