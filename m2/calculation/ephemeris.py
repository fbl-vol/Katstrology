"""Pinned Swiss source, flags and real-sky sampling shared by calculations."""
from hashlib import sha256
from pathlib import Path

import swisseph as swe

from m2.calculation.time import julian_ut

LILITH_IDS = {'mean': 'lilith_mean', 'osculating': 'lilith_osculating'}
LILITH_BODY_IDS = {'lilith_mean': swe.MEAN_APOG, 'lilith_osculating': swe.OSCU_APOG}
BODY_IDS = {
    'sun': swe.SUN, 'moon': swe.MOON, 'mercury': swe.MERCURY,
    'venus': swe.VENUS, 'mars': swe.MARS, 'jupiter': swe.JUPITER,
    'saturn': swe.SATURN, 'uranus': swe.URANUS, 'neptune': swe.NEPTUNE,
    'pluto': swe.PLUTO,
}
EPHE_FILES = ('sepl_18.se1', 'semo_18.se1')
CHIRON_FILE = 'seas_18.se1'
CHIRON_SHA256 = 'a2cd8fc33807c78ca9a700c91c2e042258b12fc4796519e00781440b5ad8b2e2'
EPHE_DIRECTORY = Path(__file__).resolve().parents[2] / '.local/ephe'


def ephemeris(directory=EPHE_DIRECTORY, *, include_chiron=False):
    """Verify declared files before computing; Swiss fallback is never acceptable."""
    directory = Path(directory).resolve()
    digests = {}
    for name in EPHE_FILES + ((CHIRON_FILE,) if include_chiron else ()):
        try:
            digests[name] = sha256((directory / name).read_bytes()).hexdigest()
        except FileNotFoundError as exc:
            if name == CHIRON_FILE:
                raise ValueError('chiron_data_missing_or_unverified') from exc
            raise RuntimeError(f'Required Swiss data file {name} is unavailable') from exc
        if name == CHIRON_FILE and digests[name] != CHIRON_SHA256:
            raise ValueError('chiron_data_missing_or_unverified')
    swe.set_ephe_path(str(directory))
    return digests


def position(body_id, jd):
    values, flags = swe.calc_ut(jd, body_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
    if not flags & swe.FLG_SWIEPH or not flags & swe.FLG_SPEED:
        raise RuntimeError('Swiss ephemeris or speed unavailable; no fallback permitted')
    return values


def position_at(body, instant):
    jd = julian_ut(instant)
    values = position(swe.CHIRON if body == 'chiron' else
                      LILITH_BODY_IDS[body] if body in LILITH_BODY_IDS else BODY_IDS[body], jd)
    return values[0], values[3]
