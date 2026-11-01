"""Application-observed UTC instants and explicitly qualified reporting dates.

The process clock is not proof of NTP synchronization. A client-supplied IANA zone
is a reporting preference, never verified physical location or birth evidence.
"""

from datetime import datetime, timezone
from functools import lru_cache
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones


def utc_now():
    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def _iana_names():
    return available_timezones()


def reporting_zone(name):
    """Return an IANA zone and its declared origin; absent means labelled UTC."""
    if name is None or name == '':
        return ZoneInfo('UTC'), 'utc_fallback_no_client_zone'
    if (not isinstance(name, str) or not 1 <= len(name) <= 80 or
            not re.fullmatch(r'[A-Za-z0-9_+./-]+', name)):
        raise ValueError('Invalid IANA reporting zone')
    if name not in _iana_names():
        raise ValueError('Unknown IANA reporting zone')
    try:
        return ZoneInfo(name), 'client_reported_or_user_entered_not_verified_location'
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError('Unknown IANA reporting zone') from exc


def snapshot(clock, zone_name=None):
    """Capture a single instant, its UTC identity and zone-local calendar view."""
    zone, origin = reporting_zone(zone_name)
    instant = clock()
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise ValueError('Application clock must supply an aware UTC instant')
    instant = instant.astimezone(timezone.utc).replace(microsecond=0)
    local = instant.astimezone(zone)
    return {'instant_utc': instant.isoformat(),
            'instant_source': 'application_process_clock_not_ntp_verified',
            'reporting': {'date': local.date().isoformat(),
                          'time': local.strftime('%H:%M:%S'),
                          'zone': zone.key, 'zone_source': origin,
                          'offset': local.strftime('%z'),
                          'occurrence': ('later' if local.fold else 'earlier') if
                          local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset()
                          else 'unspecified'}}
