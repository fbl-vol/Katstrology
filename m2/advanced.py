"""Owner-qualified immutable results for on-demand advanced chart calculations."""

from datetime import datetime

import psycopg

from m2.lunations import Lunations
from m2.planetary_returns import PlanetaryReturns
from m2.people import People
from m2.places import selected as selected_place
from m2.progressed_phases import ProgressedPhases
from m2.progressions import Progressions
from m2.relationships import Relationships
from m2.returns import Returns
from m2.solar_arc import SolarArc
from m2.synastry import OVERLAY_METHOD, Synastry
from m2.transits import Transits


class Advanced:
    def __init__(self, store):
        self.store = store

    def calculate(self, session, chart_id, technique, parameters):
        if not isinstance(parameters, dict):
            raise ValueError('Technique parameters required')
        if technique in ('midpoint_composite', 'uncorrected_davison'):
            if set(parameters) != {'chart_b_id'}:
                raise ValueError('Select one distinct second chart')
            return Relationships(self.store).calculate(session, chart_id,
                                                       parameters['chart_b_id'], technique)
        if technique in ('solar_return', 'lunar_return'):
            keys = ({'year', 'latitude', 'longitude'} if technique == 'solar_return' else
                    {'start_utc', 'end_utc', 'latitude', 'longitude'})
            self._check_reference_place(parameters, keys)
            if technique == 'solar_return':
                return Returns(self.store).calculate(session, chart_id, technique,
                    year=parameters['year'], latitude=parameters['latitude'], longitude=parameters['longitude'])
            return Returns(self.store).calculate(session, chart_id, technique,
                start=datetime.fromisoformat(parameters['start_utc']),
                end=datetime.fromisoformat(parameters['end_utc']),
                latitude=parameters['latitude'], longitude=parameters['longitude'])
        if technique == 'progressed_mc_contacts':
            if set(parameters) != {'start_utc', 'end_utc', 'branch', 'body', 'aspect'}:
                raise ValueError('Specify an MCp/MCr branch, body, aspect and UTC interval')
            return Progressions(self.store).mc_events(session, chart_id,
                datetime.fromisoformat(parameters['start_utc']),
                datetime.fromisoformat(parameters['end_utc']),
                parameters['branch'], parameters['body'], parameters['aspect'])
        if technique == 'planetary_return':
            self._check_reference_place(parameters,
                {'body', 'start_utc', 'end_utc', 'latitude', 'longitude'})
            return PlanetaryReturns(self.store).calculate(session, chart_id, parameters['body'],
                datetime.fromisoformat(parameters['start_utc']),
                datetime.fromisoformat(parameters['end_utc']),
                parameters['latitude'], parameters['longitude'])
        if technique == 'actual_lunations_eclipses':
            if set(parameters) != {'start_utc', 'end_utc', 'natal_target', 'aspect'}:
                raise ValueError('Choose a bounded real-sky UTC interval, natal target and aspect')
            return Lunations(self.store).calculate(session, chart_id,
                datetime.fromisoformat(parameters['start_utc']),
                datetime.fromisoformat(parameters['end_utc']),
                parameters['natal_target'], parameters['aspect'])
        if technique == 'progressed_lunar_phases':
            if set(parameters) != {'start_utc', 'end_utc'}:
                raise ValueError('Choose a bounded UTC effective-date phase interval')
            return ProgressedPhases(self.store).calculate(session, chart_id,
                datetime.fromisoformat(parameters['start_utc']),
                datetime.fromisoformat(parameters['end_utc']))
        if technique == 'true_solar_arc':
            if set(parameters) != {'effective_utc'}:
                raise ValueError('Choose one effective UTC solar arc instant')
            return SolarArc(self.store).calculate(session, chart_id,
                datetime.fromisoformat(parameters['effective_utc']))
        if technique == 'secondary_progression':
            if set(parameters) != {'effective_utc'}:
                raise ValueError('Choose one effective UTC progression instant')
            return Progressions(self.store).calculate(session, chart_id,
                datetime.fromisoformat(parameters['effective_utc']))
        if technique == 'mc_transit':
            if set(parameters) != {'start_utc', 'end_utc', 'transit_body', 'aspect'}:
                raise ValueError('Specify exact MC transit interval, body and aspect')
            return Transits(self.store).mc_events(session, chart_id,
                datetime.fromisoformat(parameters['start_utc']),
                datetime.fromisoformat(parameters['end_utc']),
                parameters['transit_body'], parameters['aspect'])
        raise ValueError('Unsupported advanced technique')

    @staticmethod
    def _check_reference_place(parameters, keys):
        if set(parameters) not in (keys, keys | {'reference_place_id'}):
            raise ValueError('Specify a bounded interval and one reference place')
        if 'reference_place_id' in parameters:
            place = selected_place(parameters['reference_place_id'])
            if (type(parameters['latitude']) not in (int, float) or
                    type(parameters['longitude']) not in (int, float) or
                    parameters['latitude'] != place['latitude'] or
                    parameters['longitude'] != place['longitude']):
                raise ValueError('Selected city coordinates must match the offline catalog')

    @staticmethod
    def _reference_source(parameters, calculated):
        if 'reference_place_id' in parameters:
            place = selected_place(parameters['reference_place_id'])
            label = ', '.join(part for part in (place['name'], place['region'], place['country']) if part)
            return {'kind': 'offline_city_centre', 'label': label, 'place_id': place['id']}
        birth = calculated['source_birth']
        if (parameters['latitude'] == birth['latitude'] and
                parameters['longitude'] == birth['longitude']):
            return {'kind': 'saved_birthplace_coordinates'}
        return {'kind': 'user_supplied_coordinates'}

    def save(self, session, result_id, person_id, technique, parameters):
        owner = self.store.owner(session)
        self.store._id(result_id)
        self.store._id(person_id)
        existing = self.store.db.execute('''
            SELECT r.chart_a_id,r.technique,r.parameters,r.result,c.person_id
            FROM advanced_results r JOIN charts c ON (c.owner_id=r.owner_id AND c.id=r.chart_a_id)
            WHERE r.owner_id=%s AND r.id=%s
        ''', (owner, result_id)).fetchone()
        if existing:
            if (existing['person_id'], existing['technique'], existing['parameters']) != (
                    person_id, technique, parameters):
                raise ValueError('Result ID belongs to another request')
            return {**existing['result'], 'id': result_id, 'reused': True,
                    'source_status': self.get(session, result_id)['source_status']}
        chart_id = People(self.store).active_chart_id(session, person_id)
        if not chart_id:
            return {'status': 'no_active_natal', 'technique': technique}
        chart_b_id = None
        if technique in ('synastry_overlay', 'midpoint_composite', 'uncorrected_davison'):
            if not isinstance(parameters, dict) or set(parameters) != {'person_b_id'} or (
                    parameters['person_b_id'] == person_id):
                raise ValueError('Select a distinct second person')
            chart_b_id = People(self.store).active_chart_id(session, parameters['person_b_id'])
            if not chart_b_id:
                return {'status': 'no_active_natal', 'technique': technique}
            if technique == 'synastry_overlay':
                calculated = Synastry(self.store).view(session, chart_id, chart_b_id)
                if calculated['status'] == 'supported':
                    calculated = {**calculated, 'technique': technique, 'method_version': OVERLAY_METHOD}
            else:
                calculated = Relationships(self.store).calculate(session, chart_id,
                                                                 chart_b_id, technique)
        else:
            calculated = self.calculate(session, chart_id, technique, parameters)
        if calculated['status'] != 'supported':
            return calculated
        if technique in ('solar_return', 'lunar_return', 'planetary_return'):
            calculated['reference_place_source'] = self._reference_source(parameters, calculated)
        self.store.db.execute('''
            INSERT INTO advanced_results(owner_id,id,technique,chart_a_id,chart_b_id,method_version,parameters,result)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ''', (owner, result_id, technique, chart_id, chart_b_id, calculated['method_version'],
              psycopg.types.json.Jsonb(parameters), psycopg.types.json.Jsonb(calculated)))
        return {**calculated, 'id': result_id, 'reused': False}

    def list(self, session, person_id, technique):
        owner = self.store.owner(session)
        person_id = self.store._id(person_id)
        if technique not in ('solar_return', 'lunar_return', 'synastry_overlay',
                             'mc_transit', 'secondary_progression', 'progressed_mc_contacts',
                             'midpoint_composite', 'uncorrected_davison',
                             'true_solar_arc', 'progressed_lunar_phases',
                             'actual_lunations_eclipses', 'planetary_return'):
            raise ValueError('Unsupported technique filter')
        People(self.store).get(session, person_id)
        rows = self.store.db.execute('''
            SELECT r.id,r.created_at,COALESCE(r.result->>'effective_utc', r.result->'events'->0->>'effective_utc',
                   r.result->'events'->0->>'instant_utc') AS first_utc,
                   r.parameters->>'person_b_id' AS person_b_id,
                   r.parameters->>'branch' AS branch, r.parameters->>'body' AS body,
                   r.result->>'status' AS status, r.result->'window_utc' AS window_utc,
                   r.result->'reference_place_source' AS reference_place_source,
                   r.result->'reference_place' AS reference_place,
                   CASE WHEN jsonb_typeof(r.result->'events')='array'
                     THEN jsonb_array_length(r.result->'events') END AS event_count
            FROM advanced_results r JOIN charts c ON (c.owner_id=r.owner_id AND c.id=r.chart_a_id)
            WHERE r.owner_id=%s AND c.person_id=%s AND r.technique=%s
            ORDER BY r.created_at DESC, r.id DESC LIMIT 15
        ''', (owner, person_id, technique)).fetchall()
        return [{'id': row['id'], 'created_at': row['created_at'].isoformat(),
                 'first_utc': row['first_utc'], 'person_b_id': row['person_b_id'],
                 'branch': row['branch'], 'body': row['body'], 'status': row['status'],
                 'window_utc': row['window_utc'], 'event_count': row['event_count'],
                 'reference_place_source': row['reference_place_source'],
                 'reference_place': row['reference_place']} for row in rows]

    def get(self, session, result_id):
        owner = self.store.owner(session)
        row = self.store.db.execute('''
            SELECT id,chart_a_id,chart_b_id,technique,result,created_at
            FROM advanced_results WHERE owner_id=%s AND id=%s
        ''', (owner, self.store._id(result_id))).fetchone()
        if not row:
            raise KeyError('Advanced result not found')
        from m2.charts import Charts
        first = Charts(self.store).get_chart(session, row['chart_a_id'])
        active = People(self.store).active_chart_id(session, first['person_id'])
        current = first['source_status'] == 'current' and active == first['id']
        if row['chart_b_id']:
            second = Charts(self.store).get_chart(session, row['chart_b_id'])
            current = current and second['source_status'] == 'current' and (
                People(self.store).active_chart_id(session, second['person_id']) == second['id'])
        status = 'current' if current else 'historical'
        return {'id': row['id'], 'technique': row['technique'], 'source_status': status,
                'result': row['result'], 'created_at': row['created_at'].isoformat()}
