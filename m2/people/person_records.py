"""Explicit owner/person records; the private journal is not a model or recall source."""

from datetime import date, datetime, timezone

from m2.calculation.advanced import Advanced
from m2.operations.app_clock import reporting_zone, utc_now
from m2.calculation.core_calc import local_instant
from m2.people.people import People
from m2.people.saved_timing import source_event
from psycopg.types.json import Jsonb


def _person(store, session, person_id):
    owner = store.owner(session)
    store._id(person_id)
    if not store.db.execute('SELECT 1 FROM people WHERE owner_id=%s AND id=%s',
                            (owner, person_id)).fetchone():
        raise KeyError('Person not found')
    return owner


def _result(store, session, person_id, result_id, event_index=None):
    owner = _person(store, session, person_id)
    row = store.db.execute('''
        SELECT r.technique,r.result FROM advanced_results r JOIN charts c
          ON c.owner_id=r.owner_id AND c.id=r.chart_a_id
        WHERE r.owner_id=%s AND r.id=%s AND c.person_id=%s
    ''', (owner, store._id(result_id), person_id)).fetchone()
    if not row:
        raise KeyError('Saved result not found for person')
    if event_index is not None:
        source_event(row['technique'], row['result'], event_index)
    return row


def _note(store, text, limit):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Enter a note')
    store._text(text, limit)
    return text


def _reminder(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {'wall_time', 'zone', 'fold'} or
            value['fold'] not in (None, 0, 1) or type(value['fold']) is bool):
        raise ValueError('Choose a local reminder time and timezone')
    wall = value['wall_time']
    if not isinstance(wall, str):
        raise ValueError('Choose a local reminder time')
    try:
        local = datetime.strptime(wall, '%Y-%m-%dT%H:%M')
    except ValueError:
        raise ValueError('Choose a valid local reminder time') from None
    if local.strftime('%Y-%m-%dT%H:%M') != wall or not 1900 <= local.year <= 2099:
        raise ValueError('Reminder date outside supported range')
    if not isinstance(value['zone'], str) or not value['zone']:
        raise ValueError('Choose an IANA timezone for the local time')
    zone, _ = reporting_zone(value['zone'])
    instant = local_instant(local, zone.key, value['fold'])
    return {**value, 'instant_utc': instant.isoformat()}


class Watchlist:
    def __init__(self, store):
        self.store = store

    def save(self, session, person_id, item_id, result_id, event_index, note, reminder):
        store = self.store
        owner = _person(store, session, person_id)
        store._id(item_id)
        if store.ledger.contains_person_record(owner, person_id, item_id, 'watch_item'):
            raise ValueError('Deleted watch item identity cannot be reused')
        if not isinstance(note, str) or len(note.encode('utf-8')) > 512:
            raise ValueError('Note is too long')
        due = _reminder(reminder)
        with store.db.transaction():
            existing = store.db.execute('''
                SELECT result_id,event_index FROM watch_items
                WHERE owner_id=%s AND person_id=%s AND id=%s FOR UPDATE
            ''', (owner, person_id, item_id)).fetchone()
            if existing:
                first = store.db.execute('''
                    SELECT note,reminder FROM watch_actions WHERE owner_id=%s AND person_id=%s
                      AND item_id=%s AND id=%s
                ''', (owner, person_id, item_id, item_id)).fetchone()
                if (existing['result_id'], existing['event_index'], first['note'], first['reminder']) != (
                        result_id, event_index, note, due):
                    raise ValueError('Watch item ID reused with changed input')
                return item_id
            _result(store, session, person_id, result_id, event_index)
            store.db.execute('''
                INSERT INTO watch_items(owner_id,person_id,id,result_id,event_index)
                VALUES (%s,%s,%s,%s,%s)
            ''', (owner, person_id, item_id, result_id, event_index))
            store.db.execute('''
                INSERT INTO watch_actions(owner_id,person_id,item_id,id,version,note,reminder)
                VALUES (%s,%s,%s,%s,1,%s,%s)
            ''', (owner, person_id, item_id, item_id, note, Jsonb(due) if due else None))
        return item_id

    def change(self, session, person_id, item_id, action_id, note, reminder):
        store = self.store
        owner = _person(store, session, person_id)
        store._id(item_id); store._id(action_id)
        if not isinstance(note, str) or len(note.encode('utf-8')) > 512:
            raise ValueError('Note is too long')
        due = _reminder(reminder)
        with store.db.transaction():
            row = store.db.execute('''
                SELECT 1 FROM watch_items WHERE owner_id=%s AND person_id=%s AND id=%s FOR UPDATE
            ''', (owner, person_id, item_id)).fetchone()
            if not row:
                raise KeyError('Watch item not found')
            old = store.db.execute('''
                SELECT note,reminder FROM watch_actions
                WHERE owner_id=%s AND person_id=%s AND item_id=%s AND id=%s
            ''', (owner, person_id, item_id, action_id)).fetchone()
            if old:
                if old != {'note': note, 'reminder': due}:
                    raise ValueError('Watch action ID reused with changed input')
                return
            version = store.db.execute('''
                SELECT max(version) AS version FROM watch_actions
                WHERE owner_id=%s AND person_id=%s AND item_id=%s
            ''', (owner, person_id, item_id)).fetchone()['version']
            store.db.execute('''
                INSERT INTO watch_actions(owner_id,person_id,item_id,id,version,note,reminder)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            ''', (owner, person_id, item_id, action_id, version + 1, note,
                  Jsonb(due) if due else None))

    def list(self, session, person_id, clock=utc_now, offset=0):
        store = self.store
        owner = _person(store, session, person_id)
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError('Invalid watchlist page')
        rows = store.db.execute('''
            SELECT w.id,w.result_id,w.event_index,w.created_at,a.note,a.reminder
            FROM watch_items w JOIN LATERAL (
                SELECT note,reminder FROM watch_actions WHERE owner_id=w.owner_id
                AND person_id=w.person_id AND item_id=w.id ORDER BY version DESC LIMIT 1
            ) a ON true WHERE w.owner_id=%s AND w.person_id=%s
            ORDER BY w.created_at DESC,w.id DESC LIMIT 21 OFFSET %s
        ''', (owner, person_id, offset)).fetchall()
        now = clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError('Application clock must supply an aware instant')
        items = []
        for row in rows[:20]:
            saved = Advanced(store).get(session, row['result_id'])
            reminder = row['reminder']
            due = (datetime.fromisoformat(reminder['instant_utc']) <= now.astimezone(timezone.utc)
                   if reminder else False)
            items.append({'id': row['id'], 'result_id': row['result_id'],
                          'event_index': row['event_index'], 'note': row['note'],
                          'reminder': reminder, 'source_status': saved['source_status'],
                          'reminder_status': 'needs_review' if reminder and
                          saved['source_status'] != 'current' else 'due' if due else
                          'scheduled' if reminder else 'off',
                          'technique': saved['technique'],
                          'event': ({key: value for key, value in
                                     source_event(saved['technique'], saved['result'], row['event_index'])[1].items()
                                     if key in ('instant_utc', 'maximum_utc', 'effective_utc',
                                                'phase', 'pass_direction')}
                                    if row['event_index'] is not None else None),
                          'window_utc': saved['result'].get('window_utc')})
        return {'items': items, 'next_offset': offset + 20 if len(rows) > 20 else None,
                'delivery': 'in_app_only_on_visit'}


class Journal:
    def __init__(self, store):
        self.store = store

    def save(self, session, person_id, entry_id, kind, local_date, wall_time, zone, fold,
             linked_result_id, text):
        store = self.store
        owner = _person(store, session, person_id)
        store._id(entry_id)
        if store.ledger.contains_person_record(owner, person_id, entry_id, 'journal_entry'):
            raise ValueError('Deleted journal identity cannot be reused')
        if kind not in ('date', 'instant', 'uncertain'):
            raise ValueError('Choose date-only, exact local time or uncertain date')
        try:
            day = date.fromisoformat(local_date)
        except (TypeError, ValueError):
            raise ValueError('Choose a valid reflection date') from None
        if day.isoformat() != local_date or not 1900 <= day.year <= 2099:
            raise ValueError('Reflection date outside supported range')
        if kind == 'instant':
            instant = _reminder({'wall_time': wall_time, 'zone': zone, 'fold': fold})
            if instant['wall_time'][:10] != local_date:
                raise ValueError('Reflection day differs from local time')
        elif wall_time is not None or zone is not None or fold is not None:
            raise ValueError('Date-only and uncertain reflections do not invent an instant')
        else:
            instant = None
        if linked_result_id is not None:
            _result(store, session, person_id, linked_result_id)
        content = _note(store, text, 4096)
        with store.db.transaction():
            existing = store.db.execute('''
                SELECT kind,local_date,instant_utc,zone_name,linked_result_id
                FROM journal_entries WHERE owner_id=%s AND person_id=%s AND id=%s FOR UPDATE
            ''', (owner, person_id, entry_id)).fetchone()
            utc = datetime.fromisoformat(instant['instant_utc']) if instant else None
            if existing:
                original = store.db.execute('''
                    SELECT text FROM journal_actions WHERE owner_id=%s AND person_id=%s
                    AND entry_id=%s AND id=%s
                ''', (owner, person_id, entry_id, entry_id)).fetchone()
                if (existing['kind'], existing['local_date'], existing['instant_utc'],
                        existing['zone_name'], existing['linked_result_id'], original['text']) != (
                        kind, day, utc, zone, linked_result_id, content):
                    raise ValueError('Journal ID reused with changed input')
                return entry_id
            store.db.execute('''
                INSERT INTO journal_entries(owner_id,person_id,id,kind,local_date,instant_utc,
                                            zone_name,linked_result_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ''', (owner, person_id, entry_id, kind, day, utc, zone, linked_result_id))
            store.db.execute('''
                INSERT INTO journal_actions(owner_id,person_id,entry_id,id,version,text)
                VALUES (%s,%s,%s,%s,1,%s)
            ''', (owner, person_id, entry_id, entry_id, content))
        return entry_id

    def change(self, session, person_id, entry_id, action_id, text):
        store = self.store
        owner = _person(store, session, person_id)
        store._id(entry_id); store._id(action_id)
        content = _note(store, text, 4096)
        with store.db.transaction():
            if not store.db.execute('''
                SELECT 1 FROM journal_entries WHERE owner_id=%s AND person_id=%s AND id=%s FOR UPDATE
            ''', (owner, person_id, entry_id)).fetchone():
                raise KeyError('Journal entry not found')
            old = store.db.execute('''
                SELECT text FROM journal_actions WHERE owner_id=%s AND person_id=%s
                  AND entry_id=%s AND id=%s
            ''', (owner, person_id, entry_id, action_id)).fetchone()
            if old:
                if old['text'] != content:
                    raise ValueError('Journal action ID reused with changed text')
                return
            version = store.db.execute('''
                SELECT max(version) AS version FROM journal_actions
                WHERE owner_id=%s AND person_id=%s AND entry_id=%s
            ''', (owner, person_id, entry_id)).fetchone()['version']
            store.db.execute('''
                INSERT INTO journal_actions(owner_id,person_id,entry_id,id,version,text)
                VALUES (%s,%s,%s,%s,%s,%s)
            ''', (owner, person_id, entry_id, action_id, version + 1, content))

    def list(self, session, person_id, offset=0):
        store = self.store
        owner = _person(store, session, person_id)
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError('Invalid journal page')
        rows = store.db.execute('''
            SELECT j.id,j.kind,j.local_date,j.instant_utc,j.zone_name,j.linked_result_id,
                   j.attribution,j.created_at,a.text
            FROM journal_entries j JOIN LATERAL (
                SELECT text FROM journal_actions WHERE owner_id=j.owner_id
                AND person_id=j.person_id AND entry_id=j.id ORDER BY version DESC LIMIT 1
            ) a ON true WHERE j.owner_id=%s AND j.person_id=%s
            ORDER BY j.created_at DESC,j.id DESC LIMIT 21 OFFSET %s
        ''', (owner, person_id, offset)).fetchall()
        items = []
        for row in rows[:20]:
            linked = (Advanced(store).get(session, row['linked_result_id'])['source_status']
                      if row['linked_result_id'] else None)
            items.append({**dict(row), 'local_date': row['local_date'].isoformat(),
                          'instant_utc': row['instant_utc'].isoformat() if row['instant_utc'] else None,
                          'created_at': row['created_at'].isoformat(), 'linked_source_status': linked})
        return {'entries': items, 'next_offset': offset + 20 if len(rows) > 20 else None,
                'model_and_automatic_recall': 'excluded'}
