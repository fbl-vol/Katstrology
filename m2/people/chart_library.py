"""Bounded owner-scoped directory over existing immutable charts and results.

Summary ranks the entire saved collection, not a listing page. History uses the
same durable (created_at, id) order and a keyset cursor. No calculation or writes.
Transient sky/transit and unsaved synastry views are deliberately not invented.
"""
from m2.calculation.advanced import Advanced
from m2.calculation.charts import Charts
from m2.people.people import People

TECHNIQUES = (
    'solar_return', 'lunar_return', 'planetary_return', 'mc_transit',
    'secondary_progression', 'progressed_mc_contacts', 'true_solar_arc',
    'progressed_lunar_phases', 'actual_lunations_eclipses', 'synastry_overlay',
    'midpoint_composite', 'uncorrected_davison',
)
SOURCES = '''FROM advanced_results r
    JOIN charts a ON a.owner_id=r.owner_id AND a.id=r.chart_a_id
    LEFT JOIN charts b ON b.owner_id=r.owner_id AND b.id=r.chart_b_id
    WHERE r.owner_id=%s AND (a.person_id=%s OR b.person_id=%s)'''
PAGE_SIZE = 20


def _positions(points):
    return [{'id': p['id'], 'longitude_degrees': p['longitude_degrees']}
            for p in points or [] if isinstance(p.get('longitude_degrees'), (int, float))]


def preview(result, technique):
    """Small geometry from saved facts; no representative event substituted silently."""
    if technique == 'natal':
        natal = result.get('natal') or {}
        points = _positions(natal.get('positions'))
        return {'kind': 'wheel' if points else 'unavailable', 'positions': points,
                'aspects': (natal.get('aspects') or [])[:24]}
    if result.get('status', '').startswith('unsupported'):
        return {'kind': 'unavailable', 'positions': []}
    if technique == 'uncorrected_davison':
        return preview({'natal': result.get('derived_natal')}, 'natal')
    if technique == 'synastry_overlay':
        return {'kind': 'comparison', 'positions': _positions(result.get('positions_a')),
                'other_positions': _positions(result.get('positions_b'))}
    if technique in ('secondary_progression', 'true_solar_arc', 'midpoint_composite'):
        return {'kind': 'comparison' if result.get('natal_positions') else 'wheel',
                'positions': _positions(result.get('positions')),
                'other_positions': _positions(result.get('natal_positions'))}
    events = result.get('events', [])
    if technique in ('solar_return', 'lunar_return', 'planetary_return') and len(events) == 1 and events[0].get('chart'):
        return preview({'natal': events[0]['chart']}, 'natal')
    if technique == 'actual_lunations_eclipses':
        events = [*result.get('lunations', []), *result.get('eclipses', [])]
    dated = sorted(({'date': event.get('instant_utc') or event.get('effective_utc') or event.get('maximum_utc'),
                     'label': event.get('phase') or event.get('family') or event.get('pass_direction') or 'Contact'}
                    for event in events), key=lambda e: e['date'] or '')
    return {'kind': 'timeline', 'events': dated[:3], 'total': len(events)}


class ChartLibrary:
    def __init__(self, store):
        self.store = store
        self.people = People(store)

    def summary(self, session, person_id):
        owner = self.store.owner(session)
        self.people._person(session, person_id)
        active = self.people.active_chart_id(session, person_id)
        natal_count = self.store.db.execute('''SELECT count(*) AS count FROM charts
            WHERE owner_id=%s AND person_id=%s''', (owner, person_id)).fetchone()['count']
        entries = []
        if natal_count:
            entries.append({'technique': 'natal', 'count': natal_count, 'variants': 1,
                            'representative': self._natal(session, active) if active else None})
        # Window functions range over all eligible results before selecting one per type.
        rows = self.store.db.execute('''
            WITH eligible AS (
                SELECT r.id,r.technique,r.created_at,
                       jsonb_build_array(a.person_id,b.person_id,r.parameters->>'body',
                         r.parameters->>'branch',r.parameters->>'transit_body',
                         r.parameters->>'aspect',r.parameters->>'natal_target') AS variant
                ''' + SOURCES + '''
            ), ranked AS (
                SELECT *,row_number() OVER (PARTITION BY technique ORDER BY created_at DESC,id DESC) AS rank
                FROM eligible
            ), counts AS (
                SELECT technique,count(*) AS count,count(DISTINCT variant) AS variants
                FROM eligible GROUP BY technique
            )
            SELECT r.id,r.technique,c.count,c.variants FROM ranked r JOIN counts c USING(technique)
            WHERE rank=1 ORDER BY r.technique
        ''', (owner, person_id, person_id)).fetchall()
        order = {technique: index for index, technique in enumerate(TECHNIQUES)}
        for row in sorted(rows, key=lambda row: (order.get(row['technique'], len(order)), row['technique'])):
            entries.append({'technique': row['technique'], 'count': row['count'], 'variants': row['variants'],
                            'representative': self._advanced(session, row['id'])})
        return {'person_id': person_id, 'entries': entries}

    def history(self, session, person_id, technique, before=None):
        owner = self.store.owner(session)
        self.people._person(session, person_id)
        if technique != 'natal' and technique not in TECHNIQUES:
            raise ValueError('Unknown saved technique')
        if technique == 'natal':
            source = 'FROM charts r WHERE r.owner_id=%s AND r.person_id=%s'
            args = (owner, person_id)
            read = self._natal
        else:
            source = SOURCES + ' AND r.technique=%s'
            args = (owner, person_id, person_id, technique)
            read = self._advanced
        boundary = ''
        if before:
            cursor = self.store.db.execute('SELECT r.created_at,r.id ' + source + ' AND r.id=%s',
                                           (*args, self.store._id(before))).fetchone()
            if not cursor:
                raise KeyError('Saved history cursor not found')
            boundary = ' AND (r.created_at,r.id)<(%s,%s)'
            args = (*args, cursor['created_at'], cursor['id'])
        rows = self.store.db.execute('SELECT r.id ' + source + boundary +
                                    ' ORDER BY r.created_at DESC,r.id DESC LIMIT %s',
                                    (*args, PAGE_SIZE + 1)).fetchall()
        entries = [read(session, row['id']) for row in rows[:PAGE_SIZE]]
        return {'person_id': person_id, 'technique': technique, 'entries': entries,
                'next_before': rows[PAGE_SIZE - 1]['id'] if len(rows) > PAGE_SIZE else None}

    def _natal(self, session, chart_id):
        chart = Charts(self.store).get_chart(session, chart_id)
        birth = chart['result']['birth']
        sun = chart['result'].get('natal_sun', {})
        interval = [sun['earliest_utc'], sun['latest_utc']] if sun.get('earliest_utc') and sun.get('latest_utc') else None
        return {'id': chart['id'], 'technique': 'natal', 'created_at': chart['created_at'].isoformat(),
                'source_status': chart['source_status'], 'date': birth.get('wall_time'),
                'window_utc': interval, 'zone': birth.get('zone'), 'place': self._place(birth),
                'variant': {}, 'people': [], 'event_count': None,
                'preview': preview(chart['result'], 'natal')}

    @staticmethod
    def _place(result):
        place = result.get('reference_place') or result.get('source_birth') or result
        label = result.get('reference_place_source', {}).get('label')
        return {'label': label, 'latitude': place.get('latitude'), 'longitude': place.get('longitude')}

    def _advanced(self, session, result_id):
        saved = Advanced(self.store).get(session, result_id)
        result, technique = saved['result'], saved['technique']
        owner = self.store.owner(session)
        row = self.store.db.execute('''SELECT r.parameters,a.person_id AS person_a,b.person_id AS person_b
            FROM advanced_results r JOIN charts a ON a.owner_id=r.owner_id AND a.id=r.chart_a_id
            LEFT JOIN charts b ON b.owner_id=r.owner_id AND b.id=r.chart_b_id
            WHERE r.owner_id=%s AND r.id=%s''', (owner, result_id)).fetchone()
        people = [{'id': pid, 'name': self.people._person(session, pid)['name']}
                  for pid in (row['person_a'], row['person_b']) if pid]
        events = result.get('events', [])
        geometry = preview(result, technique)
        place = self._place(result)
        if technique == 'uncorrected_davison':
            place = {'label': 'Derived midpoint', 'latitude': result.get('derived_latitude'),
                     'longitude': result.get('derived_longitude')}
        return {'id': result_id, 'technique': technique, 'created_at': saved['created_at'],
                'source_status': saved['source_status'], 'window_utc': result.get('window_utc'),
                'date': result.get('effective_utc') or result.get('derived_instant_utc') or
                        (events[0].get('instant_utc') if len(events) == 1 else None),
                'zone': 'UTC', 'place': place, 'people': people,
                'variant': {key: value for key, value in row['parameters'].items()
                            if key in ('body', 'branch', 'aspect', 'transit_body', 'natal_target')},
                'event_count': len(events) if 'events' in result else None,
                'preview': geometry}
