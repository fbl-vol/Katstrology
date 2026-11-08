"""Bounded, fallible interpretation of user text; not a semantic truth verifier.

The response model interprets assertion force and paraphrases. The server owns
source envelopes and target eligibility, and never accepts a correction ID alone.
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
    'context': SPAN,
    'assessment': {'type': 'string', 'enum': ['asserted', 'uncertain', 'non_asserted']},
    'attribution': {'type': 'string', 'enum': ['self_identification', 'named_person']},
    'intent': {'type': 'string', 'enum': ['add', 'correct']},
    # Empty for additions. Corrections require both a source discourse cue and
    # a source phrase identifying exactly one supplied old record in this group.
    'correction_cue': {'type': 'string'},
    'target_phrase': {'type': 'string'},
    'group': {'type': 'string', 'enum': list(GROUPS)},
    'entry_id': {'type': ['string', 'null']},
    'expected_version': {'type': 'integer'},
}
UPDATE_TOOL = {'type': 'function', 'name': 'stage_personal_context', 'strict': True,
    'description': (
        'Interpret ordinary current-user conversation only with opt-in. Supply context as the ENTIRE current '
        'user message, exact Unicode offsets and text. Read ALL of it before assessing assertion force, '
        'identity and intent, including later retractions, negation, fiction, quotes and hypotheticals. '
        'Use asserted only for a direct unretracted user assertion, never a reference, sensitive inference '
        'or instruction. Omit/clarify uncertainty. Statement and identity must be COMPLETE containing '
        'sentences, preserving every qualifier. Multiple facts use separate candidates. '
        'Self-identification must be an explicit opening introduction (Alex here or I am Alex); selection '
        'alone never establishes self. Named-person statements must start with that unique selected name. '
        'Only bounded locally attributed conversation is eligible; unsupported context must clarify. '
        'For a natural explicit correction, include a verbatim correction_cue (e.g. Actually, rather than, '
        'on second thought, no longer) and target_phrase from that same complete statement. The target '
        'phrase must also occur in exactly one supplied existing record in the same group. Interpret '
        'paraphrases only when this shared identifying phrase uniquely supports the intended old record '
        'and supplied version; otherwise clarify. Do not choose an unrelated ID or change its group. '
        'Additions have empty correction_cue and target_phrase, null entry_id and version zero. '
        'Cannot write births, relationships or identities. Dates remain verbatim/uncertain. '
        'Do not claim saved: publication requires durable successful completion.'),
    'parameters': {'type': 'object', 'additionalProperties': False,
                   'properties': PROPERTIES, 'required': list(PROPERTIES)}}

# Positive evidence of a revision, not an expanding list of forbidden meanings.
# These common discourse relations are necessary but not sufficient: the model
# still interprets their force, and the server separately resolves a unique target.
CORRECTION_CUE = re.compile(r'\b(?:actually|rather than|instead|on second thought|no longer|correction)\b', re.I)


def source_span(prompt, span, limit=1024):
    if not isinstance(span, dict) or set(span) != {'start', 'end', 'text'}:
        raise ValueError('Exact source span required')
    start, end, text = span['start'], span['end'], span['text']
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(prompt)
            or not isinstance(text, str) or not text.strip() or len(text.encode()) > limit
            or prompt[start:end] != text):
        raise ValueError('Source span does not match current user input')
    return text


def source_units(prompt):
    """Server-owned conservative sentence envelopes; no model-selected boundaries.

    Apostrophes inside words are contractions, not quotation delimiters. Other
    quote delimiters fail closed (including unmatched ones). Abbreviations and
    complex punctuation may require clarification, never partial extraction.
    """
    for index, char in enumerate(prompt):
        if char in "'’" and 0 < index < len(prompt) - 1 and prompt[index - 1].isalpha() and prompt[index + 1].isalpha():
            continue
        if char in '\"“”‘’\'`>':
            raise ValueError('Quoted or reference source is not eligible')
    units = []
    for match in re.finditer(r'[^.!?\n]+(?:[.!?]+|(?=\n)|$)', prompt):
        text = match.group().strip()
        if text:
            start = match.start() + len(match.group()) - len(match.group().lstrip())
            units.append({'start': start, 'end': start + len(text), 'text': text})
    return units


def candidate(prompt, args, name, selected_names):
    if not isinstance(args, dict) or set(args) != set(PROPERTIES):
        raise ValueError('Invalid typed personal-context candidate')
    statement = source_span(prompt, args['statement'])
    identity = source_span(prompt, args['identity'])
    context = source_span(prompt, args['context'], 4096)
    if args['context']['start'] != 0 or args['context']['end'] != len(prompt) or context != prompt:
        raise ValueError('Complete current-user context required')
    if args['assessment'] != 'asserted':
        raise ValueError('Uncertain, retracted or non-asserted context requires clarification')
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
    if any(other.casefold() != name.casefold() and mentions(context, other) for other in selected_names):
        raise ValueError('Mixed person attribution requires clarification')
    units = source_units(context)
    if args['statement'] not in units or args['identity'] not in units:
        raise ValueError('Complete containing statement and identity sentences required')
    if '?' in statement or '?' in identity:
        raise ValueError('A question cannot establish identity or a fact')
    if args['attribution'] == 'self_identification':
        introduction = r'(?:' + re.escape(name) + r'\s+here|(?:I am|I\'m|I’m|My name is)\s+' + re.escape(name) + r')[.!\s]*'
        if args['identity'] != units[0] or not re.fullmatch(introduction, identity, re.I):
            raise ValueError('An explicit opening speaker introduction is required')
        subject = r'(?:I\b|I[\'’]m\b|My\b)'
    else:
        subject = re.escape(name) + r'\b'
        if args['identity'] != args['statement'] or not re.match(subject, statement, re.I):
            raise ValueError('Named-person statement must identify its subject')
    # Unattributed declarative framing cannot be silently dropped from the source
    # (e.g. a fictional preamble or a later "That last sentence is false"). This
    # is an eligibility bound, not proof that every first-person sentence is true.
    for unit in units:
        text = unit['text']
        if unit == args['identity'] or text.endswith('?'):
            continue
        if not re.match(subject, text, re.I) and not CORRECTION_CUE.match(text):
            raise ValueError('Unattributed containing context requires clarification')
    cue, target = args['correction_cue'], args['target_phrase']
    if not isinstance(cue, str) or not isinstance(target, str):
        raise ValueError('Source correction evidence required')
    if args['intent'] == 'correct':
        if not CORRECTION_CUE.fullmatch(cue) or not mentions(statement, cue):
            raise ValueError('An explicit source correction cue is required')
        if (not 3 <= len(target) <= 120 or target != target.strip()
                or not re.search(r'[^\W\d_]{3}', target) or not mentions(statement, target)):
            raise ValueError('A source phrase identifying the old record is required')
    elif cue or target:
        raise ValueError('Addition cannot carry correction evidence')
    title = statement.encode()[:240].decode(errors='ignore')
    group = args['group']
    return {'group': group, 'title': title, 'notes': statement if statement != title else '',
            'state': 'tentative' if group == 'coming_up' else 'ongoing' if group == 'life_now' else None,
            'date': {'text': '', 'precision': 'unknown', 'start': None, 'end': None}}


def correction_target(args, entries):
    """Resolve evidence against supplied records, independently of the chosen ID."""
    phrase = re.compile(r'(?<!\w)' + re.escape(args['target_phrase']) + r'(?!\w)', re.I)
    matches = [row for row in entries if row['person_id'] == args['person_id']
               and row['content']['group'] == args['group']
               and phrase.search(row['content']['title'] + '\n' + row['content']['notes'])]
    if len(matches) != 1 or matches[0]['id'] != args['entry_id'] or matches[0]['version'] != args['expected_version']:
        raise ValueError('Correction target evidence must identify one supplied record/version; clarify')
