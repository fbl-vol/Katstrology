"""Bounded projection of saved, immutable timing results for one person's source chart.

Coverage describes saved computations, not an ephemeris scan of the requested period.
Viewing this projection never calculates a chart or invokes a model.
"""

from datetime import date, datetime, time, timedelta, timezone

from m2.charts import Charts
from m2.people import People

TIMING = ('mc_transit', 'actual_lunations_eclipses', 'progressed_mc_contacts',
          'progressed_lunar_phases', 'secondary_progression', 'true_solar_arc',
          'solar_return', 'lunar_return', 'planetary_return')


class Periods:
    def __init__(self, store):
        self.store = store

    def read(self, session, person_id, chart_id, start_date, end_date, offset=0):
        owner = self.store.owner(session)
        person = People(self.store).get(session, self.store._id(person_id))
        chart = Charts(self.store).get_chart(session, self.store._id(chart_id))
        if chart['person_id'] != person['id']:
            raise KeyError('Chart not found for person')
        try:
            start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        except (TypeError, ValueError):
            raise ValueError('Choose valid period dates') from None
        if (start.isoformat() != start_date or end.isoformat() != end_date or
                not 1 <= (end - start).days <= 366):
            raise ValueError('Choose a period of 1 to 366 days with an exclusive end')
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError('Invalid period page')
        start_utc = datetime.combine(start, time.min, timezone.utc)
        end_utc = datetime.combine(end, time.min, timezone.utc)
        rows = self.store.db.execute('''
            SELECT id,technique,method_version,parameters,result,created_at
            FROM advanced_results
            WHERE owner_id=%s AND chart_a_id=%s AND technique=ANY(%s)
              AND ((result->'window_utc'->>0)::timestamptz < %s
                   AND (result->'window_utc'->>1)::timestamptz >= %s
                   OR (result->>'effective_utc')::timestamptz >= %s
                   AND (result->>'effective_utc')::timestamptz < %s)
            ORDER BY created_at DESC,id DESC LIMIT 11 OFFSET %s
        ''', (owner, chart_id, list(TIMING), end_utc, start_utc, start_utc, end_utc,
              offset)).fetchall()
        more = len(rows) > 10
        entries = []
        for row in rows[:10]:
            result = row['result']
            # Keep all saved crossings including repeat retrograde passes. The
            # offset is by source result, not by event, so no crossing is split.
            events = []
            for index, event in enumerate(result.get('events', [])):
                instant = event.get('instant_utc') or event.get('effective_utc')
                if instant and start_utc <= datetime.fromisoformat(instant) < end_utc:
                    events.append({'index': index, 'instant_utc': instant,
                                   'phase': event.get('phase'),
                                   'pass_direction': event.get('pass_direction')})
            effective = result.get('effective_utc')
            if effective and start_utc <= datetime.fromisoformat(effective) < end_utc:
                events.append({'index': None, 'instant_utc': effective})
            entries.append({'id': row['id'], 'technique': row['technique'],
                            'method_version': row['method_version'],
                            'created_at': row['created_at'].isoformat(),
                            'status': result.get('status'),
                            'window_utc': result.get('window_utc'),
                            'parameters': {key: value for key, value in row['parameters'].items()
                                           if key in ('body', 'branch', 'aspect', 'transit_body')},
                            'events': events})
        return {'person_id': person['id'], 'chart_id': chart_id,
                'source_status': chart['source_status'],
                'start_date': start_date, 'end_date': end_date,
                'entries': entries, 'next_offset': offset + 10 if more else None,
                'coverage': ('partial_saved_results' if more else
                             'saved_results_only' if entries else 'no_saved_calculations'),
                'note': 'Only saved calculations for this exact chart are shown. Gaps are not a no-event finding.'}
