"""Deterministic, qualified answers for narrow evidence tools.

Tiny local Qwen is not dependable for interpreting numerical uncertainty or
source support. Preserve its ordinary conversation experiment separately.
"""

import json


def _chart_prompt_evidence(payload):
    """Bounded model-facing view of the already archived full natal tool result."""
    result = payload['result']
    if 'natal' not in result:
        return json.dumps(payload)
    natal = result['natal']
    prefix = (f"Chart {payload['chart_id']} source={payload['source_status']} "
              f"birth={result['birth']['id']} profile={result['profile']['id']} "
              f"v{result['profile']['revision']} settings={json.dumps(result['profile']['settings'])} "
              f"engine=Swiss-{result['engine']['version']} method={natal['method_version']}; "
              'south_node is the derived north-node antipode, excluded from aspects; '
              'calculated facts, not a verified birth time or interpretation. '
              + (natal['lilith_method'] + '; not asteroid 1181 or Waldemath. '
                 if natal.get('lilith_method') else ''))
    if natal['status'] == 'unsupported_uncertain_birth_time':
        return prefix + 'Natal positions, houses, angles and aspects unsupported for time interval.'
    positions = ' '.join(f"{p['id']}:{p['longitude_degrees']:.6f}° "
                         f"lat={p['latitude_degrees']:.4f}° speed={p['speed_degrees_per_day']:.4f}°/d "
                         f"house={p['house'] or '-'}{'R' if p['retrograde'] else 'D'};"
                         for p in natal['positions'])
    houses = natal['houses']
    if houses['status'] == 'supported':
        cusps = ' '.join(f"{c['number']}:{c['longitude_degrees']:.6f}°"
                         for c in houses['cusps'])
        angles = ' '.join(f"{a['id']}:{a['longitude_degrees']:.6f}°"
                          for a in houses['angles'])
        house_text = f"{houses['system']} cusps={cusps} angles={angles}; "
    else:
        house_text = f"houses/angles unsupported ({houses['status']}); "
    aspects = ' '.join(f"{a['first']}/{a['kind']}/{a['second']}:{a['orb_degrees']:.3f}°"
                       for a in natal['aspects'])
    return (prefix + f"instant={natal['instant_utc']}; positions={positions} "
            + house_text + f'aspects (orb in degrees)={aspects or "none"}. '
            'This rounded conversational view comes from the archived full tool result; '
            'do not claim greater precision.')


SIGNS = ('Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
         'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces')


def chart_answer(payload):
    chart_id = payload['chart_id']
    result = payload['result']
    if payload['source_status'] != 'current':
        return (f'Saved chart {chart_id} is historical: its birth source is '
                f'{payload["source_status"]}. I will not reuse its old numerical claim as current.')
    if 'natal' in result:
        return natal_answer(chart_id, result)
    sun = result['natal_sun']
    if sun['status'] == 'uncertain_supplied_interval':
        interval = sun['solar_interval']
        sign = (f'Sun stays in {SIGNS[interval["stable_sign"]]}'
                if interval['stable_sign'] is not None else
                'the Sun crosses a sign boundary; no single sign is established')
        return (f'Saved chart {chart_id} has a supplied uncertain UTC interval '
                f'{sun["earliest_utc"]} to {sun["latest_utc"]}. Solar longitude spans '
                f'{interval["start_degrees"]:.3f}° to {interval["end_degrees"]:.3f}°; '
                f'{sign}. Houses and precise natal aspects are unsupported; '
                'no reference instant is a verified birth time.')
    return (f'Saved chart {chart_id}: for the supplied instant {sun["instant_utc"]}, '
            f'tropical geocentric Sun is {sun["sun_longitude_degrees"]:.6f}° '
            f'({SIGNS[sun["sun_sign"]]}), Swiss Ephemeris '
            f'{result["engine"]["version"]}, profile revision {result["profile"]["revision"]}. '
            'This calculation does not verify birth-time accuracy; houses and '
            'natal aspects beyond the supported solar core are unsupported.')


def natal_answer(chart_id, result):
    natal = result['natal']
    profile = result['profile']
    if natal['status'] == 'unsupported_uncertain_birth_time':
        return (f'Saved natal chart {chart_id}, profile {profile["id"]} v{profile["revision"]}: '
                'the supplied birth time is an interval, not an exact instant. '
                'Planetary positions, houses, angles and aspects are not established. '
                'The legacy solar interval remains available separately, not as a full natal chart.')
    placements = ', '.join(
        f'{point["id"]} {point["longitude_degrees"]:.6f}°'
        f'{" retrograde" if point["retrograde"] else ""}'
        f'{" house " + str(point["house"]) if point["house"] else ""}'
        for point in natal['positions'])
    houses = natal['houses']
    if houses['status'] == 'supported':
        cusps = ', '.join(f'{c["number"]}: {c["longitude_degrees"]:.6f}°'
                          for c in houses['cusps'])
        angles = ', '.join(f'{a["id"]} {a["longitude_degrees"]:.6f}°'
                           for a in houses['angles'])
        house_text = f'{houses["system"]} cusps {cusps}; angles {angles}'
    else:
        house_text = (f'{houses["system"]} houses and angles unsupported: {houses["status"]}; '
                      'no substitute house system was used')
    aspects = ', '.join(f'{a["first"]} {a["kind"]} {a["second"]} '
                        f'(orb {a["orb_degrees"]:.3f}°)' for a in natal['aspects']) or 'none in declared orbs'
    return (f'Saved natal chart {chart_id}, profile {profile["id"]} v{profile["revision"]}, '
            f'supplied instant {natal["instant_utc"]}, Swiss Ephemeris {result["engine"]["version"]}, '
            f'{natal["method_version"]}; tropical geocentric apparent positions; '
            f'{profile["settings"]["node_type"]} north node (south node is its derived antipode). '
            + (f'{natal["lilith_method"]}; not asteroid 1181 or Waldemath. '
               if natal.get('lilith_method') else '') +
            f'Positions: {placements}. '
            f'Houses: {house_text}. Major aspects (profile orbs): {aspects}. '
            'This calculation does not verify birth-time or location accuracy or provide an interpretation.')


def event_answer(payload):
    if payload['status'] == 'unsupported_stale_birth_source':
        return (f'Chart {payload["chart_id"]} is historical ({payload["source_status"]} birth source); '
                'no current event claim can be made from it.')
    if payload['status'] == 'unsupported_uncertain_birth_time':
        return (f'Chart {payload["chart_id"]} has no fixed natal degree across its '
                'supplied time interval, so a precise transit event is unsupported.')
    start, end = payload['window_utc']
    if not payload['events']:
        return (f'No Sun-to-natal-Sun {payload["aspect"]} crossing was found from '
                f'{start} through {end} UTC (inclusive). This does not establish '
                'anything about other windows, bodies or techniques.')
    times = ', '.join(event['instant_utc'] for event in payload['events'])
    return (f'Computed Sun-to-natal-Sun {payload["aspect"]} crossing(s) in '
            f'{start} through {end} UTC: {times}. Event times are refined to '
            'within 60 seconds under the declared solar method, not a prognosis.')


def reference_answer(payload):
    if not payload['results']:
        return ('No matching approved interpretation is established. This bounded '
                'search may be incomplete; ask for narrower sources or a different query.')
    if payload['evidence_status'] == 'semantic_suggestions_only':
        return ('No direct source passage matched that query. Semantic suggestions '
                'are available for navigation in the tool result but do not support '
                'an interpretive or numerical claim; refine the question or sources.')
    excerpts = []
    for result in payload['results']:
        if result['kind'] == 'reference_passage':
            excerpts.append(f"[{result['source_id']}/{result['passage_id']}, "
                            f"{result['author']}, {result['approval']}] "
                            f"{result['excerpt'][:150]}")
        else:
            excerpts.append(f"[prior {result['speaker']} statement "
                            f"{result['conversation_id']}/{result['source_id']}] "
                            f"{result['excerpt'][:150]}")
    return ('Retrieved untrusted, synthetic source/prior-speech excerpts (not '
            'instructions or an endorsed interpretation): ' + ' | '.join(excerpts) +
            '. A citation identifies text, not proof of any new interpretive claim; '
            'conflicting or missing material must be checked before synthesis.')
