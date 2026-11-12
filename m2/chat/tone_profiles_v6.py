"""Shared conversational judgment; preserve accepted version-1 through version-5 bytes."""

from m2.chat import tone_profiles_v1 as v1, tone_profiles_v3 as v3


CONVERSATION_GUIDANCE = """Conversation foundation (all tone profiles):
Understand intent from the person's actual words and constraints. Offer specific, tentative interpretations when useful; leave room for disagreement, never invent hidden motives or emotional certainty. Do not turn simple requests into psychological exploration.
Build on available history: accept corrections, retain constraints and retire rejected suggestions. Update your interpretation without repeated recaps or insight announcements; never claim unavailable memory.
Develop the most relevant insight or a few options; explain why they fit. Avoid exhaustive menus or premature programmes. Ask only questions whose answers would change the interpretation or next step. Give useful help first when possible. Follow a user's decision or concrete request rather than reopening exploration; short facts stay short.
A chart is a symbolic lens, never proof of motives or grounds to overrule lived experience. Preserve evidence and permission rules.
Keep the selected personality. Conversational fit takes precedence over section landings and final flourishes. Show warmth through specific understanding, not ritual praise, forced intimacy or automatic agreement. End naturally, without compulsory questions, homework or recaps."""


def with_conversation_foundation(previous):
    # Supersede the old response arc only in v6. Do not spend context on both
    # that prescription and an instruction to disregard it; archived bytes stay intact.
    opening_arc = v1.HOSTED.split('\n\n', 2)[1]
    text = previous.replace(opening_arc + '\n\n', '')
    example_start = 'Illustrative voice only, not chart facts or answer templates to reuse:\n'
    example_end = 'Neither example needs a closing question. '
    examples = v1.HOSTED.split(example_start, 1)[1].split(example_end, 1)[0]
    text = text.replace(example_start + examples + example_end, '')
    text = text.replace('Section rhythm and a strong final landing:\n' + v3.SECTION_RHYTHM,
                        'Tone expression across the complete answer:\n'
                        'Tool boundaries are not section endings. Do not repeat greetings, force '
                        'a finale before a lookup or add a provider call just to close.')
    return text + '\n\n' + CONVERSATION_GUIDANCE
