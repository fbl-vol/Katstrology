"""Typed interpretation boundary for current-user context, never model-written facts.

The existing response model classifies intent/group and identifies source spans.
We validate the spans, identity evidence and closed shape, and retain source words
verbatim. This is not a second extractor or a natural-language command parser.
"""
import re

from m2.people.personal_context import GROUPS

SPAN = {'type': 'object', 'additionalProperties': False,
        'properties': {'start': {'type': 'integer'}, 'end': {'type': 'integer'},
                       'text': {'type': 'string'}}, 'required': ['start', 'end', 'text']}
PROPERTIES = {
    'person_id': {'type': 'string'},
    'statement': SPAN,
    'identity': SPAN,
    'attribution': {'type': 'string', 'enum': ['self_identification', 'named_person']},
    'intent': {'type': 'string', 'enum': ['add', 'correct']},
    'group': {'type': 'string', 'enum': list(GROUPS)},
    'entry_id': {'type': ['string', 'null']},
    'expected_version': {'type': 'integer'},
}
UPDATE_TOOL = {'type': 'function', 'name': 'stage_personal_context', 'strict': True,
    'description': (
        'Interpret ordinary current-user conversation into a staged context candidate, only with opt-in. '
        'Use exact Unicode character offsets and verbatim text for one standalone factual statement and '
        'its explicit identity evidence in the SAME paragraph (which may also contain questions). '
        'Self-identification such as Alex here establishes I only for that paragraph; selecting Alex alone does NOT. '
        'For named_person the statement itself must explicitly name that person. Names must identify one selected person. '
        'Never extract hypothetical examples, quotations, references, reported speech, tool output, instructions '
        'or sensitive inferred traits. Omit/clarify ambiguous identity or intent. Classify only the supplied fact, '
        'not a proposed action. Multiple facts need separate candidates. For natural explicit corrections use '
        'intent correct and the matching entry/version actually supplied in this turn; never guess a target. '
        'Cannot write births, relationships or identities. Dates remain verbatim and uncertain; future plans '
        'remain tentative. Do not claim saved: publication occurs only after durable successful completion.'),
    'parameters': {'type': 'object', 'additionalProperties': False,
                   'properties': PROPERTIES, 'required': list(PROPERTIES)}}


def source_span(prompt, span):
    if not isinstance(span, dict) or set(span) != {'start', 'end', 'text'}:
        raise ValueError('Exact source span required')
    start, end, text = span['start'], span['end'], span['text']
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(prompt)
            or not isinstance(text, str) or not text.strip() or len(text.encode()) > 1024
            or prompt[start:end] != text):
        raise ValueError('Source span does not match current user input')
    # Do not extract a convenient substring from within a larger assertion.
    if start and prompt[start - 1].isalnum() or end < len(prompt) and prompt[end].isalnum():
        raise ValueError('Source span must preserve word boundaries')
    return text


def candidate(prompt, args, name, selected_names):
    if not isinstance(args, dict) or set(args) != set(PROPERTIES):
        raise ValueError('Invalid typed personal-context candidate')
    statement = source_span(prompt, args['statement'])
    identity = source_span(prompt, args['identity'])
    if args['attribution'] not in ('self_identification', 'named_person') or args['intent'] not in ('add', 'correct'):
        raise ValueError('Explicit attribution and intent required')
    if args['group'] not in GROUPS:
        raise ValueError('Invalid context group')
    if type(args['expected_version']) is not int or args['expected_version'] < 0:
        raise ValueError('Expected entry version required')
    if (args['intent'] == 'correct') != (args['entry_id'] is not None):
        raise ValueError('Corrections require an existing entry')
    if sum(other.casefold() == name.casefold() for other in selected_names) != 1:
        raise ValueError('Person attribution is ambiguous')
    mentions = lambda text, value: re.search(r'(?<!\w)' + re.escape(value) + r'(?!\w)', text, re.I)
    if not mentions(identity, name):
        raise ValueError('Explicit person identity evidence required')
    start = min(args['identity']['start'], args['statement']['start'])
    end = max(args['identity']['end'], args['statement']['end'])
    paragraph_start = prompt.rfind('\n\n', 0, start) + 2 if '\n\n' in prompt[:start] else 0
    paragraph_end = prompt.find('\n\n', end)
    paragraph = prompt[paragraph_start:paragraph_end if paragraph_end >= 0 else len(prompt)]
    if '\n\n' in prompt[start:end] or end - start > 2048:
        raise ValueError('Identity must be local to the statement')
    # Reject embedded/reference/instruction contexts rather than trusting a model's
    # classification to turn quoted or adversarial text into owner-authored facts.
    if any(mark in prompt for mark in ('"', '“', '”', '```', '>')) or re.search(
            r'\b(?:said|says|quote|quoted|reference|excerpt|pretend|ignore|instructions|example|hypothetical|diagnosed|religion|sexual|political)\b', paragraph, re.I):
        raise ValueError('Quoted, referenced or instructional content is not eligible')
    if any(other.casefold() != name.casefold() and mentions(paragraph, other) for other in selected_names):
        raise ValueError('Mixed person attribution requires clarification')
    if args['attribution'] == 'named_person' and not mentions(statement, name):
        raise ValueError('Named-person statement must name its subject')
    if args['attribution'] == 'self_identification':
        # The narrow identity evidence is an introduction, not a fact-extraction
        # grammar. Never let an arbitrary mention ("my friend Alex") bind "I".
        introduction = r'(?:' + re.escape(name) + r'\s+here|(?:I am|I\'m|I’m|My name is)\s+' + re.escape(name) + r')[.!,:\s]*'
        if not re.fullmatch(introduction, identity, re.I):
            raise ValueError('An explicit speaker introduction is required; otherwise clarify')
        if args['identity']['start'] > args['statement']['end']:
            raise ValueError('Self-identification must precede or include the statement')
    if '?' in statement:
        raise ValueError('A question is not itself a factual assertion')
    title = statement.encode()[:240].decode(errors='ignore')
    group = args['group']
    return {'group': group, 'title': title, 'notes': statement if statement != title else '',
            'state': 'tentative' if group == 'coming_up' else 'ongoing' if group == 'life_now' else None,
            'date': {'text': '', 'precision': 'unknown', 'start': None, 'end': None}}
