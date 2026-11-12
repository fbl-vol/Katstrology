"""Versioned Kat expression and exact accepted-turn instruction reconstruction."""

from hashlib import sha256

from m2.chat import tone_profiles_v1 as v1, tone_profiles_v2 as v2, tone_profiles_v3 as v3
from m2.chat.prompting import HOSTED, identity
from m2.chat.tone_profiles_v4 import with_web_guidance
from m2.chat.tone_profiles_v5 import MEMORY_GUIDANCE
from m2.chat.tone_profiles_v6 import with_conversation_foundation

DEFAULT = 'quiet-wonder'
CURRENT_VERSION = 6
BY_ID = {profile[0]: profile for profile in v1.PROFILES}


def catalogue():
    profiles = []
    for tone_id, name, label, description, _instruction, example in v1.PROFILES:
        revised = v2.REVISIONS.get(tone_id)
        profiles.append({
            'id': tone_id, 'version': CURRENT_VERSION, 'name': name, 'voice_label': label,
            'description': revised['description'] if revised else description,
            'example': revised['preview'] if revised else example,
        })
    return {'default_id': DEFAULT, 'profiles': profiles}


def _versioned_instructions(tone_id, version):
    try:
        profile = BY_ID[tone_id]
    except (KeyError, TypeError):
        raise ValueError('Unknown Kat tone') from None
    if type(version) is not int:
        raise ValueError('Archived tone version is unavailable')
    if version == 1:
        text = v1.HOSTED + '\n\nKat tone guidance (expression only):\n' + v1.SHARED + '\n\n' + profile[4]
        prompt_version = v1.PROMPT_VERSION
    elif version == 2 and tone_id in v2.REVISIONS:
        revised = v2.REVISIONS[tone_id]
        # Only the two introductory style paragraphs are replaced. All governing
        # factual/tool instructions remain intact; Quiet Wonder never takes this path.
        governing = v1.HOSTED.split('\n\n', 2)[2]
        shared = v1.SHARED.replace(
            'Reduce humour and theatricality for painful, serious or practical topics and direct requests.',
            'Reduce humour and theatricality for painful or sensitive topics, high-stakes matters '
            'and direct requests for seriousness.')
        examples = '\n'.join('- ' + example for example in revised['examples'])
        text = ('Kat astrology companion. Match the user\'s language and expertise.\n\n'
                + governing + '\n\nKat tone guidance (expression only):\n' + shared
                + '\n\n' + v2.EXPRESSION + '\n\n' + revised['instruction']
                + '\n\nIllustrative traits, not chart evidence, user facts or stock responses to repeat. '
                'Invent fresh phrasing for the actual question; never infer a chart from these examples:\n'
                + examples)
        prompt_version = '2026-11-03.1.tone2'
    elif version == 3 and tone_id in v3.LANDINGS:
        # Append to the exact v2 body; never change accepted v1/v2 instructions.
        previous, _ = _versioned_instructions(tone_id, 2)
        text = (previous + '\n\nSection rhythm and a strong final landing:\n'
                + v3.SECTION_RHYTHM + '\n\n' + v3.LANDINGS[tone_id])
        prompt_version = '2026-11-03.1.tone3'
    elif version == 4:
        # Change governing capabilities, not expression or any accepted v1-v3 text.
        previous, _ = _versioned_instructions(tone_id, 3 if tone_id in v3.LANDINGS else 1)
        text = with_web_guidance(previous)
        prompt_version = '2026-11-09.1.tone4'
    elif version == 5:
        previous, _ = _versioned_instructions(tone_id, 4)
        text = previous + '\n\n' + MEMORY_GUIDANCE
        prompt_version = '2026-11-10.1.tone5'
    elif version == 6:
        previous, _ = _versioned_instructions(tone_id, 5)
        text = with_conversation_foundation(previous)
        prompt_version = '2026-11-12.1.tone6'
    else:
        raise ValueError('Archived tone version is unavailable')
    return text, {'tone_id': tone_id, 'tone_version': version,
                  'tone_shared_version': version, 'prompt_version': prompt_version,
                  'prompt_mode': 'hosted', 'prompt_sha256': sha256(text.encode('utf-8')).hexdigest()}


def instructions(tone_id):
    if not isinstance(tone_id, str):
        raise ValueError('Unknown Kat tone')
    return _versioned_instructions(tone_id, CURRENT_VERSION)


def archived_instructions(record):
    if record is None:
        return HOSTED, identity('hosted')  # Preserve the pre-tone legacy path.
    if not isinstance(record, dict):
        raise ValueError('Archived tone version is unavailable')
    text, expected = _versioned_instructions(record.get('tone_id'), record.get('tone_version'))
    if record != expected or type(record.get('tone_shared_version')) is not int:
        raise ValueError('Archived tone instruction identity differs')
    return text, expected
