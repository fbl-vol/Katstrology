"""Local M1 comparison, not a production chart or event-search API.

Input/output contain private data. No geocoding, model calls or network requests.
Run using the pinned environment described in probes/README.md.
"""

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import swisseph as swe


BODIES = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
    "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO, "True Node": swe.TRUE_NODE, "Chiron": swe.CHIRON,
}
# Declared before comparison: seconds printed in the image have rounding error;
# allow 2 arcseconds for bodies, 60 for minute-only cusps. Not a universal SLA.
BODY_TOLERANCE_ARCSEC = 2.0
CUSP_TOLERANCE_ARCSEC = 60.0


def difference_degrees(actual, expected):
    return (actual - expected + 180) % 360 - 180


def sexagesimal(parts):
    return sum(value / 60 ** index for index, value in enumerate(parts))


def calculate(instant, latitude, longitude):
    utc = instant.astimezone(timezone.utc)
    # UTC to UT1/TT via Swiss leap-second and delta-T handling, not UTC = UT1.
    _, jd_ut = swe.utc_to_jd(
        utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second, swe.GREG_CAL
    )
    positions = {}
    for name, body in BODIES.items():
        values, flags = swe.calc_ut(jd_ut, body, swe.FLG_SWIEPH | swe.FLG_SPEED)
        if not flags & swe.FLG_SWIEPH:
            raise RuntimeError(f"Unexpected ephemeris fallback for {name}: {flags}")
        positions[name] = values[0]
    cusps, angles = swe.houses_ex(jd_ut, latitude, longitude, b"P", 0)
    positions.update(Ascendant=angles[0], MC=angles[1])
    return {
        "utc": utc.isoformat(),
        "positions_degrees": positions,
        "cusps_degrees": list(cusps),
        "local_apparent_sidereal_hours": (swe.sidtime(jd_ut) + longitude / 15) % 24,
    }


def compare(reference, ephemeris_dir):
    swe.set_ephe_path(str(ephemeris_dir.resolve()))
    instant = datetime.fromisoformat(reference["local_datetime"]).replace(
        tzinfo=ZoneInfo(reference["timezone"])
    )
    if instant.astimezone(timezone.utc).isoformat() != reference["expected_utc"]:
        raise ValueError("Time-zone conversion disagrees with the supplied UTC reference")
    latitude = reference["latitude_north_degrees"]
    longitude = reference["longitude_east_degrees"]
    result = calculate(instant, latitude, longitude)
    comparisons = []
    for name, dms in reference["body_reference_dms"].items():
        delta = difference_degrees(result["positions_degrees"][name], sexagesimal(dms)) * 3600
        comparisons.append({"name": name, "delta_arcsec": delta,
                            "within_tolerance": abs(delta) <= BODY_TOLERANCE_ARCSEC})
    for house, dm in reference["cusp_reference_dm"].items():
        delta = difference_degrees(result["cusps_degrees"][int(house) - 1], sexagesimal(dm)) * 3600
        comparisons.append({"name": f"Cusp {house}", "delta_arcsec": delta,
                            "within_tolerance": abs(delta) <= CUSP_TOLERANCE_ARCSEC})

    samples = [calculate(instant + timedelta(minutes=offset), latitude, longitude)
               for offset in range(-5, 6)]
    sensitivity = {}
    for name, baseline in result["positions_degrees"].items():
        shifts = [difference_degrees(sample["positions_degrees"][name], baseline)
                  for sample in samples]
        sensitivity[name] = {
            "sampled_min_shift_degrees": min(shifts),
            "sampled_max_shift_degrees": max(shifts),
            "sampled_sign_indices": sorted({int(sample["positions_degrees"][name] // 30)
                                            for sample in samples}),
        }
    return {
        "python": sys.version.split()[0], "pyswisseph": version("pyswisseph"),
        "swiss_engine": swe.version,
        "profile": "tropical, geocentric apparent, Placidus, true node, Gregorian",
        "ephemeris_sha256": {path.name: sha256(path.read_bytes()).hexdigest()
                             for path in sorted(ephemeris_dir.glob("*.se1"))},
        "tolerance_arcsec": {"bodies": BODY_TOLERANCE_ARCSEC, "cusps": CUSP_TOLERANCE_ARCSEC},
        "reference_source": reference["source_image"],
        "calculated": result, "comparisons": comparisons,
        "sidereal_delta_seconds": (
            result["local_apparent_sidereal_hours"] - sexagesimal(reference["sidereal_time_hms"])
        ) * 3600,
        "conditional_sensitivity": sensitivity,
        "sensitivity_limit": "One-minute samples at +/-5 minutes, not verified uncertainty bounds or event searches; houses/aspect membership not evaluated.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--ephemeris-dir", type=Path, default=Path(".local/ephe"))
    args = parser.parse_args()
    report = compare(json.loads(args.reference.read_text()), args.ephemeris_dir)
    print(json.dumps(report, indent=2))
    return 0 if all(row["within_tolerance"] for row in report["comparisons"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
