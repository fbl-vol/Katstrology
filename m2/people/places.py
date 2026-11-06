"""Offline GeoNames populated-place selection; names and centroids are references, not birth coordinates."""

from functools import lru_cache
from pathlib import Path
from unicodedata import combining, normalize
from zipfile import ZipFile


DATA = Path(__file__).resolve().parents[1] / 'data'


def _key(text):
    return ''.join(character for character in normalize('NFKD', text.casefold()) if not combining(character))


@lru_cache(maxsize=1)
def catalog():
    countries = {}
    for line in (DATA / 'geonames-countries.txt').read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#'):
            parts = line.split('\t')
            countries[parts[0]] = parts[4]
    regions = {}
    for line in (DATA / 'geonames-admin1.txt').read_text(encoding='utf-8').splitlines():
        parts = line.split('\t')
        if len(parts) > 1:
            regions[parts[0]] = parts[1]
    rows = {}
    with ZipFile(DATA / 'geonames-cities5000.zip') as archive:
        for line in archive.read('cities5000.txt').decode('utf-8').splitlines():
            parts = line.split('\t')
            if len(parts) < 19 or not parts[17]:
                continue
            place_id, name, ascii_name = parts[:3]
            country, admin = parts[8], parts[10]
            rows[place_id] = {
                'id': place_id, 'name': name, 'region': regions.get(f'{country}.{admin}', admin),
                'country': countries.get(country, country), 'country_code': country,
                'latitude': float(parts[4]), 'longitude': float(parts[5]),
                'zone': parts[17], 'population': int(parts[14]),
                'search': (_key(name), _key(ascii_name)),
            }
    return rows


def search(query, limit=10):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
        raise ValueError('Place search must be 2–80 characters')
    term = _key(query.strip())
    matches = [row for row in catalog().values() if any(term in value for value in row['search'])]
    matches.sort(key=lambda row: (not any(value.startswith(term) for value in row['search']),
                                  -row['population'], row['country'], row['name'], row['id']))
    return [{key: value for key, value in row.items() if key not in ('search', 'population')}
            for row in matches[:limit]]


def selected(place_id):
    if not isinstance(place_id, str) or not place_id.isdecimal():
        raise ValueError('Select a place from the offline suggestions')
    row = catalog().get(place_id)
    if row is None:
        raise ValueError('Selected place is not available in the offline catalog')
    return row
