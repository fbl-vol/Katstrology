"""Compatibility import for the M1 probe; production calculation contracts live in m2."""

from m2.calculation.core_calc import (ASPECTS, END_YEAR, START_YEAR, STEP, TOLERANCE,
                          AmbiguousLocalTime, NonexistentLocalTime,
                          aspect_separation, difference_degrees, local_instant,
                          solar_crossings, solar_interval, solar_longitude)
