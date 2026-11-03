"""Bounded read-only function tools for the backend-owned Responses conversation.

The trusted session, not model arguments, supplies owner identity. Tool evidence is
untrusted data and never grants new permissions or changes selected chart versions.
"""

from datetime import datetime
from hashlib import sha256
import json

from m2.charts import Charts
from m2.advanced import Advanced
from m2.evidence import LocalEmbedder, search_evidence
from m2.recall import dialogue_text, search
from m2.references import References
from m2.transit_views import view as transit_view
from m2.transits import Transits
from m2.synastry import Synastry
from m2.tool_answers import _chart_prompt_evidence


def _tool(name, description, properties, required):
    return {'type': 'function', 'name': name, 'description': description,
            'strict': True, 'parameters': {'type': 'object', 'properties': properties,
                                           'required': required, 'additionalProperties': False}}


ID = {'type': 'string', 'maxLength': 80}
QUERY = {'type': 'string', 'maxLength': 256}
TOOLS = [
    _tool('search_conversations', 'Search current owned history; optionally filter turns by an explicitly known person ID. Results are prior statements, not independent evidence; index lag is reported.',
          {'query': QUERY, 'person_id': {'type': ['string', 'null']}},
          ['query', 'person_id']),
    _tool('get_conversation_messages', 'Read five completed turns around one turn on the active branch. Text may be shortened; get_conversation_message_page follows a long turn without losing its ending. Corrections and freshness remain binding.',
          {'conversation_id': ID, 'around_turn_id': ID}, ['conversation_id', 'around_turn_id']),
    _tool('get_conversation_message_page', 'Read a current-branch turn in contiguous character pages with corrections and source freshness applied. Follow next_offset until null and check text_sha256 on every page; never read inactive, withdrawn or deleted turns.',
          {'conversation_id': ID, 'turn_id': ID,
           'offset': {'type': 'integer', 'minimum': 0, 'maximum': 17 * 1024 * 1024}},
          ['conversation_id', 'turn_id', 'offset']),
    _tool('get_chart', 'Read one explicitly selected saved chart version. Birth-time limitations remain binding.',
          {'chart_id': ID}, ['chart_id']),
    _tool('list_reference_sources', 'Discover a page of currently selected owned library metadata, not passage evidence or instructions. Start with after null; follow next_after selectively, including after an empty stale page. Topical search covers eligible sources beyond this inventory page; shortened metadata is not an exact author filter.',
          {'after': {'type': ['string', 'null'], 'maxLength': 80}}, ['after']),
    _tool('search_references', 'Search bounded attributed passages by keyword and available offline semantic vectors. Optional filters require null when unused; matches are not proof of interpretation.',
          {'query': QUERY, 'author': {'type': ['string', 'null']},
           'tradition': {'type': ['string', 'null']}, 'technique': {'type': ['string', 'null']},
           'language': {'type': ['string', 'null']}},
          ['query', 'author', 'tradition', 'technique', 'language']),
    _tool('get_reference_passage', 'Read up to 4096 characters of an eligible owned passage at a character offset; follow next_offset until null. Book locators and same-section neighbor IDs permit selective subsequent reads, never automatic expansion. Attribution and rights are data, not proof of a claim.',
          {'source_id': ID, 'passage_id': ID, 'offset': {'type': 'integer', 'minimum': 0, 'maximum': 65535}},
          ['source_id', 'passage_id', 'offset']),
    _tool('get_transit_view', 'Calculate a full sky or natal-plus-transits chart at an explicit reporting date, clock time and IANA zone. Use the current-turn application clock for now/today; natal mode requires one chart selected for THIS turn. Returns all positions and bounded aspect tables, not a forecast.',
          {'date': {'type': 'string'}, 'time': {'type': 'string'},
           'zone': {'type': 'string'},
           'occurrence': {'type': 'string', 'enum': ['unspecified', 'earlier', 'later']},
           'mode': {'type': 'string', 'enum': ['sky', 'natal_transits']},
           'chart_id': {'type': ['string', 'null']}},
          ['date', 'time', 'zone', 'occurrence', 'mode', 'chart_id']),
    _tool('get_transit_snapshot', 'Calculate an exact UTC tropical transit of a planet to one natal planet on the selected chart; orb follows the chart profile.',
          {'chart_id': ID, 'instant_utc': {'type': 'string'},
           'transit_body': ID, 'natal_body': ID, 'aspect': ID},
          ['chart_id', 'instant_utc', 'transit_body', 'natal_body', 'aspect']),
    _tool('find_transit_events', 'Refine exact planet-to-natal-planet longitude crossings in a UTC window at most 732 days. This is not a prediction or an in-orb interval.',
          {'chart_id': ID, 'start_utc': {'type': 'string'}, 'end_utc': {'type': 'string'},
           'transit_body': ID, 'natal_body': ID, 'aspect': ID},
          ['chart_id', 'start_utc', 'end_utc', 'transit_body', 'natal_body', 'aspect']),
    _tool('find_sky_events', 'Find tropical sign ingresses or speed-zero stations for a planet, UTC window at most 732 days, under the selected chart settings.',
          {'chart_id': ID, 'start_utc': {'type': 'string'}, 'end_utc': {'type': 'string'},
           'transit_body': ID, 'kind': {'type': 'string', 'enum': ['ingress', 'station']}},
          ['chart_id', 'start_utc', 'end_utc', 'transit_body', 'kind']),
    _tool('compare_selected_charts', 'Compute the full supported set of ecliptic inter-chart aspects and both directional recipient-house planet overlays for TWO explicitly selected, distinct people. One direction may have unsupported houses; no compatibility score or invented birth time.',
          {'chart_a_id': ID, 'chart_b_id': ID}, ['chart_a_id', 'chart_b_id']),
    _tool('get_planetary_returns', 'Find all direct/retrograde crossings of Jupiter, Saturn, Venus or Mars over that same saved natal planet longitude in a body-bounded half-open UTC window. Include reference-place houses and every pass; never silently choose one pass or imply a forecast.',
          {'chart_id': ID, 'body': {'type': 'string', 'enum': ['jupiter', 'saturn', 'venus', 'mars']},
           'start_utc': {'type': 'string'}, 'end_utc': {'type': 'string'},
           'latitude': {'type': 'number'}, 'longitude': {'type': 'number'}},
          ['chart_id', 'body', 'start_utc', 'end_utc', 'latitude', 'longitude']),
    _tool('find_actual_lunations_eclipses', 'Find actual-sky geocentric New/Full Moon syzygy UTC instants and separately Swiss-validated global solar/lunar eclipse maximum instants/classes over at most 732 days. Label natal planet/qualified angle contacts at each event. Global does not mean visible at the user location.',
          {'chart_id': ID, 'start_utc': {'type': 'string'}, 'end_utc': {'type': 'string'},
           'natal_target': ID, 'aspect': ID},
          ['chart_id', 'start_utc', 'end_utc', 'natal_target', 'aspect']),
    _tool('find_progressed_lunar_phases', 'Find symbolic secondary progressed Moon–Sun New, first-quarter, Full and last-quarter phase effective dates in a half-open UTC window of at most 40 years, with cycles counted from birth. This is not an actual-sky lunation, eclipse or lunar return.',
          {'chart_id': ID, 'start_utc': {'type': 'string'},
           'end_utc': {'type': 'string'}}, ['chart_id', 'start_utc', 'end_utc']),
    _tool('get_true_solar_arc', 'Read true forward solar-arc symbolic directions at one effective UTC date, using the actual secondary progressed Sun displacement applied uniformly to saved natal planets and qualified axes. Not fixed-degree mean arc, MCp, retrograde or a simultaneous sky.',
          {'chart_id': ID, 'effective_utc': {'type': 'string'}}, ['chart_id', 'effective_utc']),
    _tool('get_midpoint_composite', 'Read a two-person symbolic shortest-circle midpoint composite of compatible exact-time natal planets; antipodal axes are ambiguous, and no composite houses, physical instant or score are asserted. Both source chart IDs must be selected.',
          {'chart_a_id': ID, 'chart_b_id': ID}, ['chart_a_id', 'chart_b_id']),
    _tool('get_uncorrected_davison', 'Read a two-person uncorrected Davison derived UTC time and algebraic signed latitude/longitude midpoint, with Swiss natal-like chart and explicit partial houses. Not a spherical or corrected Davison; both source chart IDs must be selected.',
          {'chart_a_id': ID, 'chart_b_id': ID}, ['chart_a_id', 'chart_b_id']),
    _tool('find_progressed_mc_contacts', 'Search a bounded UTC effective-date interval (at most 732 days) for exact MCp progressed-MC-to-natal-planet or MCr directly progressed-planet-to-fixed-natal-MC contacts. These are distinct symbolic methods, not real-sky transits; may report incomplete near-station coverage.',
          {'chart_id': ID, 'start_utc': {'type': 'string'}, 'end_utc': {'type': 'string'},
           'branch': {'type': 'string', 'enum': ['mcp', 'mcr']},
           'body': ID, 'aspect': ID},
          ['chart_id', 'start_utc', 'end_utc', 'branch', 'body', 'aspect']),
    _tool('get_secondary_progression', 'Map an explicitly selected natal to an effective UTC instant using the declared one-day-per-anniversary secondary progression. Reports symbolic progressed planetary positions, MCp against natal planets and MCr progressed planets against saved natal astronomical MC, separately; no automatic interpretation or real-sky assertion.',
          {'chart_id': ID, 'effective_utc': {'type': 'string'}}, ['chart_id', 'effective_utc']),
    _tool('find_natal_mc_transits', 'Find exact transiting-planet contacts with the saved astronomical natal MC, in a UTC window at most 732 days. Requires one chart selected for this turn; no tenth-house substitution or predicted event.',
          {'chart_id': ID, 'start_utc': {'type': 'string'}, 'end_utc': {'type': 'string'},
           'transit_body': ID, 'aspect': ID},
          ['chart_id', 'start_utc', 'end_utc', 'transit_body', 'aspect']),
    _tool('get_solar_return', 'Calculate the solar return in a UTC anniversary year from one chart selected for this turn, at an explicitly supplied reference place. No message is sent by calculation alone.',
          {'chart_id': ID, 'year': {'type': 'integer'}, 'latitude': {'type': 'number'},
           'longitude': {'type': 'number'}}, ['chart_id', 'year', 'latitude', 'longitude']),
    _tool('get_lunar_returns', 'Calculate all lunar returns in an explicit UTC interval at most 732 days from one chart selected for this turn, at an explicit reference place. This is not a calendar-month cycle.',
          {'chart_id': ID, 'start_utc': {'type': 'string'}, 'end_utc': {'type': 'string'},
           'latitude': {'type': 'number'}, 'longitude': {'type': 'number'}},
          ['chart_id', 'start_utc', 'end_utc', 'latitude', 'longitude']),
]


def project_transit_view(result):
    """Bound provider text without trimming the authoritative archived chart."""
    if result.get('status') != 'supported':
        return result
    fields = ('status', 'mode', 'instant_utc', 'reporting', 'zodiac', 'engine_version',
              'ephemeris_sha256', 'method', 'orb_policy', 'chart_id', 'source_status', 'profile_id',
              'profile_revision', 'birth_time_status', 'natal_house_status',
              'same_sky_total', 'transit_to_natal_total', 'aspect_limit')
    projected = {key: result[key] for key in fields}
    if result.get('lilith_convention'):
        projected['lilith_convention'] = result['lilith_convention']
        projected['lilith_method'] = ('mean lunar apogee' if result['lilith_convention'] == 'mean'
                                      else 'true / osculating lunar apogee; not a claim of greater accuracy')
    projected['position_precision'] = 'ecliptic degrees and speed rounded to six decimals in model projection; complete chart is archived'
    projected['positions'] = [{key: round(value, 6) if isinstance(value, float) else value
                               for key, value in position.items()
                               if key in ('id', 'longitude_degrees', 'speed_degrees_per_day',
                                          'retrograde')}
                              for position in result['positions']]
    projected['natal_positions'] = [{key: round(value, 6) if isinstance(value, float) else value
                                     for key, value in position.items()
                                     if key in ('id', 'longitude_degrees', 'house')}
                                    for position in result['natal_positions']]
    projected['same_sky_aspects'] = list(result['same_sky_aspects'])
    projected['transit_to_natal_aspects'] = list(result['transit_to_natal_aspects'])
    projected['projection_note'] = 'Aspect lists are the tightest shown; totals include omitted aspects. Full bounded tables and provenance are archived with this turn.'
    projected['same_sky_shown'] = len(projected['same_sky_aspects'])
    projected['transit_to_natal_shown'] = len(projected['transit_to_natal_aspects'])
    return projected


def _args(store, arguments, keys):
    if not isinstance(arguments, dict) or set(arguments) != set(keys):
        raise ValueError('Invalid tool arguments')
    for key, value in arguments.items():
        if key == 'query' or key.endswith('_utc'):
            bound = 256 if key == 'query' else 80
            if not isinstance(value, str) or not 1 <= len(value) <= bound:
                raise ValueError('Invalid bounded query or instant')
        else:
            store._id(value)


def execute(store, session, name, arguments, selected_charts):
    """All reads are owner-scoped at the Store boundary; returns a bounded JSON value."""
    if name == 'search_conversations':
        if not isinstance(arguments, dict) or set(arguments) != {'query', 'person_id'}:
            raise ValueError('Invalid conversation search arguments')
        _args(store, {'query': arguments['query']}, ('query',))
        return search(store, session, arguments['query'], limit=16,
                      person_id=arguments['person_id'])
    if name == 'get_conversation_messages':
        _args(store, arguments, ('conversation_id', 'around_turn_id'))
        conv = arguments['conversation_id']
        chain = store.ancestry(session, conv, store.active_head(session, conv))
        if arguments['around_turn_id'] not in chain:
            raise KeyError('Turn not on active branch')
        index = chain.index(arguments['around_turn_id'])
        window = chain[max(0, index - 2):index + 3]
        texts = [dialogue_text(store, session, conv, turn_id) for turn_id in window]
        return {'conversation_id': conv, 'turns': [
            {'turn_id': turn_id, 'text': text[:4096], 'truncated': len(text) > 4096,
             'next_offset': 4096 if len(text) > 4096 else None,
             'text_sha256': sha256(text.encode('utf-8')).hexdigest()}
            for turn_id, text in zip(window, texts) if text is not None],
            'window': 'two turns before and after on active branch; use get_conversation_message_page for full turn text'}
    if name == 'get_conversation_message_page':
        if not isinstance(arguments, dict) or set(arguments) != {'conversation_id', 'turn_id', 'offset'}:
            raise ValueError('Invalid history page arguments')
        conv, turn_id, offset = arguments['conversation_id'], arguments['turn_id'], arguments['offset']
        store._id(conv)
        store._id(turn_id)
        if type(offset) is not int or not 0 <= offset <= 17 * 1024 * 1024:
            raise ValueError('Invalid history offset')
        chain = store.ancestry(session, conv, store.active_head(session, conv))
        if turn_id not in chain:
            raise KeyError('Turn not on active branch')
        text = dialogue_text(store, session, conv, turn_id)
        if text is None:
            return {'conversation_id': conv, 'turn_id': turn_id, 'status': 'not_current',
                    'text': '', 'next_offset': None}
        next_offset = offset + 4096 if offset + 4096 < len(text) else None
        return {'conversation_id': conv, 'turn_id': turn_id, 'status': 'current_dialogue',
                'offset': offset, 'text': text[offset:offset + 4096],
                'total_characters': len(text), 'next_offset': next_offset,
                'text_sha256': sha256(text.encode('utf-8')).hexdigest()}
    if name == 'get_chart':
        _args(store, arguments, ('chart_id',))
        if arguments['chart_id'] not in selected_charts:
            raise PermissionError('Chart not selected for this turn')
        chart = Charts(store).get_chart(session, arguments['chart_id'])
        payload = {'chart_id': chart['id'], 'source_status': chart['source_status'],
                   'result': chart['result'] if chart['source_status'] == 'current'
                   else {'status': 'unsupported_stale_birth_source'}}
        return {'chart_id': chart['id'], 'source_status': chart['source_status'],
                'evidence': _chart_prompt_evidence(payload) if chart['source_status'] == 'current'
                else 'Birth source superseded; chart cannot be used as current evidence.'}
    if name == 'list_reference_sources':
        if not isinstance(arguments, dict) or set(arguments) != {'after'}:
            raise ValueError('Invalid library page arguments')
        return References(store).selected_library(session, arguments['after'])
    if name == 'search_references':
        keys = ('query', 'author', 'tradition', 'technique', 'language')
        if not isinstance(arguments, dict) or set(arguments) != set(keys):
            raise ValueError('Invalid reference search arguments')
        _args(store, {'query': arguments['query']}, ('query',))
        for field in keys[1:]:
            if arguments[field] is not None and not isinstance(arguments[field], str):
                raise ValueError('Invalid reference filter')
        # The embedding model is a cached, offline helper, never a remote fetch.
        # Failure to load it must remain visible in semantic_available.
        if not hasattr(store, '_read_embedder'):
            try:
                store._read_embedder = LocalEmbedder()
            except (OSError, RuntimeError, ValueError):
                store._read_embedder = None
        result = search_evidence(store, session, arguments['query'], store._read_embedder,
            limit=16, include_history=False, author=arguments['author'],
            tradition=arguments['tradition'], technique=arguments['technique'],
            language=arguments['language'])
        result['search_mode'] = ('keyword_only_semantic_unavailable' if not result['semantic_available']
                                 else 'keyword_and_partial_semantic_index' if result['semantic_index_incomplete']
                                 else 'keyword_and_bounded_semantic')
        return result
    if name == 'get_transit_view':
        keys = {'date', 'time', 'zone', 'occurrence', 'mode', 'chart_id'}
        if not isinstance(arguments, dict) or set(arguments) != keys:
            raise ValueError('Invalid full transit chart arguments')
        chart_id = arguments['chart_id']
        if arguments['mode'] == 'natal_transits' and (
                not isinstance(chart_id, str) or chart_id not in selected_charts):
            raise PermissionError('Natal chart not selected for this turn')
        return transit_view(store, session, arguments['date'], arguments['time'],
                            arguments['zone'], arguments['occurrence'], arguments['mode'],
                            chart_id)
    if name in ('get_transit_snapshot', 'find_transit_events', 'find_sky_events'):
        keys = (('chart_id', 'instant_utc', 'transit_body', 'natal_body', 'aspect')
                if name == 'get_transit_snapshot' else
                ('chart_id', 'start_utc', 'end_utc', 'transit_body', 'kind')
                if name == 'find_sky_events' else
                ('chart_id', 'start_utc', 'end_utc', 'transit_body', 'natal_body', 'aspect'))
        _args(store, arguments, keys)
        if arguments['chart_id'] not in selected_charts:
            raise PermissionError('Chart not selected for this turn')
        transits = Transits(store)
        if name == 'get_transit_snapshot':
            return transits.snapshot(session, arguments['chart_id'],
                datetime.fromisoformat(arguments['instant_utc']),
                arguments['transit_body'], arguments['natal_body'], arguments['aspect'])
        if name == 'find_sky_events':
            return transits.sky_events(session, arguments['chart_id'],
                datetime.fromisoformat(arguments['start_utc']),
                datetime.fromisoformat(arguments['end_utc']),
                arguments['transit_body'], arguments['kind'])
        return transits.events(session, arguments['chart_id'],
            datetime.fromisoformat(arguments['start_utc']),
            datetime.fromisoformat(arguments['end_utc']),
            arguments['transit_body'], arguments['natal_body'], arguments['aspect'])
    if name == 'get_planetary_returns':
        if not isinstance(arguments, dict) or set(arguments) != {
                'chart_id', 'body', 'start_utc', 'end_utc', 'latitude', 'longitude'}:
            raise ValueError('Invalid planetary return arguments')
        chart_id = store._id(arguments['chart_id'])
        if chart_id not in selected_charts:
            raise PermissionError('Chart not selected for this turn')
        return Advanced(store).calculate(session, chart_id,
            'planetary_return', {key: arguments[key] for key in
                ('body', 'start_utc', 'end_utc', 'latitude', 'longitude')})
    if name == 'find_actual_lunations_eclipses':
        _args(store, arguments, ('chart_id', 'start_utc', 'end_utc', 'natal_target', 'aspect'))
        if arguments['chart_id'] not in selected_charts:
            raise PermissionError('Chart not selected for this turn')
        return Advanced(store).calculate(session, arguments['chart_id'],
            'actual_lunations_eclipses', {key: arguments[key] for key in
                ('start_utc', 'end_utc', 'natal_target', 'aspect')})
    if name == 'find_progressed_lunar_phases':
        _args(store, arguments, ('chart_id', 'start_utc', 'end_utc'))
        if arguments['chart_id'] not in selected_charts:
            raise PermissionError('Chart not selected for this turn')
        return Advanced(store).calculate(session, arguments['chart_id'],
            'progressed_lunar_phases', {key: arguments[key] for key in ('start_utc', 'end_utc')})
    if name == 'get_true_solar_arc':
        _args(store, arguments, ('chart_id', 'effective_utc'))
        if arguments['chart_id'] not in selected_charts:
            raise PermissionError('Chart not selected for this turn')
        return Advanced(store).calculate(session, arguments['chart_id'], 'true_solar_arc',
            {'effective_utc': arguments['effective_utc']})
    if name in ('get_midpoint_composite', 'get_uncorrected_davison'):
        _args(store, arguments, ('chart_a_id', 'chart_b_id'))
        if not {arguments['chart_a_id'], arguments['chart_b_id']} <= set(selected_charts):
            raise PermissionError('Both source charts must be selected for this turn')
        return Advanced(store).calculate(session, arguments['chart_a_id'],
            'midpoint_composite' if name == 'get_midpoint_composite' else 'uncorrected_davison',
            {'chart_b_id': arguments['chart_b_id']})
    if name == 'find_progressed_mc_contacts':
        _args(store, arguments, ('chart_id', 'start_utc', 'end_utc', 'branch', 'body', 'aspect'))
        if arguments['chart_id'] not in selected_charts:
            raise PermissionError('Chart not selected for this turn')
        return Advanced(store).calculate(session, arguments['chart_id'], 'progressed_mc_contacts',
            {key: value for key, value in arguments.items() if key != 'chart_id'})
    if name == 'get_secondary_progression':
        _args(store, arguments, ('chart_id', 'effective_utc'))
        if arguments['chart_id'] not in selected_charts:
            raise PermissionError('Chart not selected for this turn')
        return Advanced(store).calculate(session, arguments['chart_id'],
            'secondary_progression', {'effective_utc': arguments['effective_utc']})
    if name == 'find_natal_mc_transits':
        _args(store, arguments, ('chart_id', 'start_utc', 'end_utc', 'transit_body', 'aspect'))
        if arguments['chart_id'] not in selected_charts:
            raise PermissionError('Chart not selected for this turn')
        return Advanced(store).calculate(session, arguments['chart_id'], 'mc_transit',
            {key: value for key, value in arguments.items() if key != 'chart_id'})
    if name in ('get_solar_return', 'get_lunar_returns'):
        keys = ({'chart_id', 'year', 'latitude', 'longitude'} if name == 'get_solar_return' else
                {'chart_id', 'start_utc', 'end_utc', 'latitude', 'longitude'})
        if not isinstance(arguments, dict) or set(arguments) != keys:
            raise ValueError('Invalid return arguments')
        chart_id = store._id(arguments['chart_id'])
        if chart_id not in selected_charts:
            raise PermissionError('Chart not selected for this turn')
        parameters = {key: value for key, value in arguments.items() if key != 'chart_id'}
        return Advanced(store).calculate(session, chart_id,
            'solar_return' if name == 'get_solar_return' else 'lunar_return', parameters)
    if name == 'compare_selected_charts':
        _args(store, arguments, ('chart_a_id', 'chart_b_id'))
        return Synastry(store).compare(session, arguments['chart_a_id'],
                                       arguments['chart_b_id'], selected_charts)
    if name == 'get_reference_passage':
        if not isinstance(arguments, dict) or set(arguments) not in (
                {'source_id', 'passage_id'}, {'source_id', 'passage_id', 'offset'}):
            raise ValueError('Invalid passage arguments')
        _args(store, {key: arguments[key] for key in ('source_id', 'passage_id')},
              ('source_id', 'passage_id'))
        offset = arguments.get('offset', 0)
        if type(offset) is not int or not 0 <= offset <= 65535:
            raise ValueError('Invalid passage offset')
        row = References(store).readable_passage(session, arguments['source_id'], arguments['passage_id'])
        return {'source_id': arguments['source_id'], 'passage_id': row['id'],
                'author': row['author'], 'title': row['title'], 'edition': row['edition'],
                'section': row['section'], 'parent_section': row['parent_section'],
                'page_start': row['page_start'], 'page_end': row['page_end'],
                'printed_page_start': row['printed_page_start'],
                'printed_page_end': row['printed_page_end'],
                'source_locator_start': row['source_locator_start'],
                'source_locator_end': row['source_locator_end'],
                'ordinal': row['ordinal'], 'start_offset': row['start_offset'],
                'end_offset': row['end_offset'], 'extraction_status': row['extraction_status'],
                'review_status': row['review_status'], 'neighbors': row['neighbors'],
                'raw_sha256': row['raw_sha256'], 'transcript_sha256': row['transcript_sha256'],
                'processing_sha256': row['processing_sha256'],
                'normalized_sha256': row['normalized_sha256'],
                'tradition': row['tradition'],
                'technique': row['technique'], 'language': row['language'],
                'content_sha256': row['content_sha256'],
                'rights_basis': row['rights_basis'], 'rights_evidence': row['rights_evidence'],
                'source_url': row['source_url'],
                'approval': row['approval'], 'source_status': row['source_status'],
                'content': row['content'][offset:offset + 4096], 'offset': offset,
                'total_characters': len(row['content']),
                'next_offset': offset + 4096 if offset + 4096 < len(row['content']) else None,
                'truncated': offset + 4096 < len(row['content'])}
    raise ValueError('Unsupported read tool')
