# Western tropical natal charts

[Documentation index](README.md) · [Advanced methods](advanced-calculations.md)

This feature is opt-in per immutable chart version. A person can remain name-only
or hold unverified draft details without a chart. `solar-default` and existing
solar profiles/results keep their original shape and transit behavior. A natal
profile declares `chart_kind=natal`, tropical zodiac, Placidus (default) or
whole-sign houses, true (default) or mean north node, the five major aspects,
and per-aspect orbs (default conjunction/opposition 8°, square/trine 6°,
sextile 4°; custom numbers >0 and ≤10). Angles participate in aspects only
when houses succeed. There is no applying/separating assertion. The north node
is the selected Swiss true/mean calculation; the south node is explicitly
its derived geometric antipode (+180° longitude), not a separate ephemeris
calculation. South-node aspects are omitted to avoid mirrored duplication.

Only an **explicit exact local wall time with a selected IANA zone** is converted
to UTC; nonexistent DST times are rejected and ambiguous folds require an
explicit choice. The normal one-step browser form requires a selected offline
GeoNames populated place or explicit Advanced coordinates and IANA zone. The
selected place supplies **city-centre reference coordinates**, country/region and
IANA identifier; it never verifies the person's precise birthplace, birth time
or timezone border. Its provenance and the user's provisional confidence are
stored separately. Historical offsets use Python IANA zoneinfo for the supplied
date, not GeoNames' current UTC offset. See [place-data contract](../m2/data/README.md)
for the source, license and coverage limits. The older API can still store
explicit records without coordinates; it never geocodes a free-text label.
Without coordinates, planetary degrees and major aspects
are calculated but houses/angles are unsupported. Swiss Placidus house failures
(including at polar latitudes) result in a marked partial chart, never silent
Porphyry cusps; whole-sign is a separately selected setting. At |latitude| ≥
89.9°, houses are unsupported. Unknown or interval time does not produce full
natal quantities or sampled bounding claims. One-step unknown time stores the
entire historical local day as a UTC interval (including 23/25-hour DST days),
without inventing a noon or exact time. Its legacy solar interval remains
separately available. Explicitly supplied birth inputs are not independently
verified birth certificates.

Positions: Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn, Uranus,
Neptune, Pluto and both lunar nodes (one selected north calculation and its
south antipode); tropical geocentric apparent
ecliptic longitude/latitude and longitude speed. Retrograde is speed <0.
Displayed Placidus house membership is the conventional **ecliptic-projected**
position (latitude zero) relative to Placidus cusps, not the distinct 3D
planet-in-house position for its true ecliptic latitude. The Moon or Uranus
can differ near a cusp. Aspects are shortest ecliptic-longitude separations,
with a closed `orb ≤ declared threshold`; zero-time static geometry only.
The stored result contains numeric degrees (unrounded), birth/profile version,
engine/method versions and SHA-256 of the two required `.se1` files. The
wheel uses only stored results; its table exposes all positions, angles, cusps
and aspects. Selected-chart turns archive the complete result as a tool event;
the small local model receives a rounded, bounded view of those same placements,
cusps, angles and major aspects (with a terminal error rather than silent
omission if the model context is too small). Local context is capped at 2048
tokens; this does not alter hosted permissions or cost. The downloadable SVG
is original static geometry with no remote
assets or arbitrary markup. Wheel geometry is a visualization, not a source
of new facts. Missing ephemeris files or non-Swiss returned flags fail closed;
no Moshier fallback. Declared conservative date span: 1900–2099 UTC, within
the locally available 1800–2399 `.se1` files. Separate services provide bounded transit views, synastry/house overlays and
derived relationship charts on saved generated natals; their distinct contracts
are in [advanced methods](advanced-calculations.md). No rectification,
compatibility score, validated interpretation engine or uploaded-image permission
is implied.

## Explore a saved natal

The full natal view has searchable Positions, Houses (including actual angles),
Aspects and Patterns directories. Selecting a row or a named wheel control shows
its facts and highlights the complete geometry. Back retains the category and
search; Previous/Next traverses the whole named category, not only search matches.
All original tables remain under **All chart tables**. Compact conversation and
return/derived wheels do not acquire these controls.

Symbols and house numbers take precedence over connections; connections take
precedence over pattern interiors. Shared locations offer only matching choices,
with contained T-squares identified explicitly. Cancel restores the prior view
and wheel focus. The directory is an alternative to precision pointing, especially
for dense lines on small screens. Connections have a 16-CSS-pixel-wide hit stroke
at every wheel size. Conjunctions include both endpoint discs and the actual arc;
all intersected hit shapes contribute candidates, not just the topmost SVG target.
The bounded width preserves exposed shared pattern interiors, although narrow
pattern-only slivers can become connection targets on mobile. This is a local
screen-space policy, not physical-device or accessibility certification.
Oppositions are dashed when selected. House shading uses saved cusp sectors,
not equal-house assumptions; the midheaven is its actual angle, not an inferred
whole-sign tenth cusp. Exports retain the full original chart, without transient
selection, hit targets or overlap markers.

`GET /api/charts/{chart_id}/exploration` is an authenticated, owner-scoped,
read-only projection on the existing serialized runtime. Its `natal-patterns-v1`
rule is separate from the natal method and canonical chart result. It enumerates
only Sun through Pluto: Grand Trine requires three trines; T-square requires one
opposition and two squares (with the square junction named as apex); Grand Cross
requires two disjoint oppositions and all four cross-pair squares. Every required
edge must already exist in the saved qualified graph and satisfy that chart's
saved enabled kinds and exact orb limits. No missing edge, current default,
rounded display value, sign element or modality is substituted. Identities include
the chart, rule and canonical typed edges. Each T-square retains **every** Grand
Cross containing its members and edges; an isolated cross contains four T-squares.
Nodes, Chiron, Lilith and angles remain individually available but cannot become
pattern members. Patterns are geometric relationships, not strength or predictions.

A complete graph with no matches is distinct from unavailable/failed/loading
pattern reads. A house failure still permits patterns from established positions
and aspects, without fabricating a wheel. Historical sources, unknown-time natal
facts and Sun-only legacy records do not become successful zero-pattern results.
The browser fetches on opening, fences late responses and keeps individual facts
usable during failure/retry. The projection never calls ephemeris or a provider,
rewrites a saved result, migrates a schema or expands archived chat evidence.
Exact selected-pattern discussion is deferred; no new Discuss action silently
substitutes the active natal for the inspected chart.

Black Moon Lilith is **off by default**, not a rewrite of saved profiles or charts.
An explicit per-chart `include_lilith: "mean" | "osculating"` selects Swiss
`MEAN_APOG` or `OSCU_APOG` (traditionally called *true*). These are two lunar
apogee conventions, not accuracy rankings; neither is asteroid 1181 Lilith or
Waldemath's hypothetical moon. Saved positions have separate `lilith_mean` /
`lilith_osculating` IDs, the selected profile, method annotation, original
engine/file hashes and owner-qualified immutable chart identity. Selected
natal-plus-transit snapshots and dated views use that same convention; sky-only
views keep the normal bodies. Approximate osculating-apogee discontinuities make
exact contact-event scans unsupported for a transiting apogee; snapshots and
ordinary planetary contacts *to* a fixed selected natal apogee remain available.
Unknown birth time still produces no full natal apogee placement. Solar return
charts inherit the saved convention; other techniques do not silently add it.
The independent rounded example in [Lilith in Capricorn](https://horoscopetools.com/guides/lilith-in-capricorn/)
records 2017-11-09 03:58:17 UTC at mean 270.0000775° and osculating
242.4181950°. `tests.calculation.test_lilith` verifies both with the installed Swiss
2.10.03 engine and pinned lunar/planetary files, without using that site's
interpretation as authority.

The optional **Play dated transits** panel on the current natal loads only after
an explicit date selection and click. It accepts 1–7 UTC days in the supported
1900–2099 range, uses the owned current chart and Swiss 15-minute positions for
actual transiting planets, and keeps the natal fixed. The 20-second loop uses
shortest-circle interpolation only for the displayed movement. It labels the
UTC time and **never** treats an unsampled frame as an exact degree, crossing,
station or aspect event; the dated transit view remains the exact calculation.
Pause, replay, manual scrub, reduced-motion stills, document-hidden and
out-of-view stop are built in. No provider request, persisted result, login
animation, model inference or background calculation is involved. A seven-day
synthetic Mercury station/zodiac-wrap sample measured <0.0001° midpoint error
and 6730 Swiss planet samples in <0.1s locally; this is a bounded feasibility
check, not production-device profiling. No unbounded dates or apogee animation.

Source references and reproducible independent checks (published values are
only computational anchors, not approval of a person's historical birth time):

- [Astrodienst Swiss programming reference](https://www.astro.com/swisseph/swephprg.htm):
  `calc_ut`, Swiss returned flags, speed, true/mean node, `houses_ex`,
  polar Placidus error with **Porphyry** fallback. Python raises on ERR; the
  implementation does not persist fallback cusps.
- [Swiss general documentation](https://www.astro.com/swisseph/swisseph.htm):
  `sepl_18.se1` / `semo_18.se1` 1800–2399 coverage and licensing. Swiss
  Ephemeris is **AGPL or professional-license** dual-licensed; distribution or
  activation as a public service requires an explicit license choice and
  compliance review. Local synthetic tests do not grant deployment rights.
- [Published London tropical Placidus chart](https://cafeastrology.com/articles/howtoobtainchart.html):
  1948-11-14 21:14 GMT, 51°30′ N 0°10′ W: Sun 22°25′ Scorpio, Moon
  0°26′ Taurus, Mercury 6°57′ Scorpio, true north node 4°58′ Taurus,
  Ascendant 5°23′ Leo, MC 13°16′ Aries, house 2 cusp 22°08′ Leo.
- [Published Sydney tropical Placidus chart](https://fourfoldastrology.com/charts/gould-shane):
  1956-11-23 23:15 AEST, 33°52′ S 151°13′ E: Sun 1°14′ Sagittarius,
  Moon 11°26′ Leo, mean north node 28°45′ Scorpio, Ascendant 7°04′ Leo,
  MC 24°48′ Taurus. The quoted birth minute is reportedly an estimate; tests
  reproduce the **published input**, not a verified biography. Public chart
  art and interpretations are neither copied nor used as product assets.

Run through the [isolated validation runner](testing.md):

```sh
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile backend --tests tests.calculation.test_natal --execute
```

The suite includes database-backed version/source contracts and independent
numerical anchors. Browser checks live in `web/tests/charts/natal.spec.ts` and
`web/tests/charts/natal-wheel.spec.ts` and `web/tests/charts/exploration.spec.ts`,
using a separate synthetic fixture. `tests.calculation.test_exploration` contains
worked graph/orb/containment cases; the actual ASGI projection and unchanged stored
result bytes are checked in `tests.http_boundary.test_web_transits`. Browser pattern
interaction fixtures are explicitly synthetic presentation data, not another
detector or a claim of ephemeris-calculated formations.
