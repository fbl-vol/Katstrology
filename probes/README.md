# Calculation and capture probes

[Documentation index](../docs/README.md) · [Synthetic validation](../docs/testing.md)

These small experiments retain independently checkable numerical and capture
contracts. They are not the hosted application or its production API. Use
synthetic inputs; keep outputs under ignored `.local/`. Private charts,
conversations and archives are not repository fixtures.

## Run the public tests

Prepare the Python/Swiss environment using the
[backend guide](../docs/backend-development.md), then use the isolated runner:

```sh
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile probes --execute
```

Public solar/capture checks need verified Swiss files. Expected fixture hashes:

| File | SHA-256 |
| --- | --- |
| `sepl_18.se1` | `ca1393ceab3a44fbc895887cf789c68819ae6a1cbc9b22225872dbe4ccd99a66` |
| `semo_18.se1` | `1ca07bd67c24374d77226180c20a4f9996cba013697894810518e7eb582ca4f7` |
| `seas_18.se1` | `a2cd8fc33807c78ca9a700c91c2e042258b12fc4796519e00781440b5ad8b2e2` |

The [upstream Swiss repository](https://github.com/aloistr/swisseph/tree/master/ephe)
is mutable; verify bytes, not only names. Different hashes change numerical
provenance. Time-zone data also affects historical conversion: retain the actual
zoneinfo provenance when assessing differences. Licensing remains separate from
successful numerical tests.

## Ownership and limits

- `core_calc.py` re-exports `m2/calculation/core_calc.py` for these retained probes. Its contract
  is solar-only tropical geocentric longitude, supplied UTC uncertainty endpoints
  up to 24 hours, ecliptic aspect geometry (no orb policy), and bounded forward
  solar crossings against fixed natal longitude. It brackets to 60 seconds over
  at most30 days, accepts UTC years1900–2099 and rejects unresolved DST folds/gaps.
  It does not implement unknown-time houses, Moon extrema, retrograde/station or
  general MC/planet searches. The independent
  [USNO2024 seasons table](https://aa.usno.navy.mil/calculated/seasons?dst=false&submit=Get+Data&tz=0&tz_label=true&tz_sign=0&year=2024)
  anchors the March equinox at03:06UT (minute resolution); tests allow three
  minutes, not a universal accuracy claim.
- `chart_probe.py` compares a separately supplied reference using tropical,
  geocentric apparent positions, Placidus, true node and Gregorian dates. It
  rejects timezone/UTC disagreement and missing Swiss flags/fallback. Tolerances
  are2 arcseconds for body/point values and60 arcseconds for minute-only cusps;
  ±5-minute samples are conditional sensitivity, not interval extrema or verified
  birth uncertainty. An optional `KAT_CHART_REFERENCE`/`.local/chart-reference.json`
  is outside public synthetic qualification. Its absence skips image agreement;
  an explicitly configured missing file errors. Do not enable private comparisons
  without separately scoped access, and never infer image agreement from a skip.
- `capture_probe.py` is a disposable SQLite ordering experiment: input before
  invocation, generated events before delivery, replay without reinvocation,
  no delivery after failed writes, interruption on startup and readable older
  nullable-parent archives. This is not PostgreSQL/provider durability evidence.
- `conversation_probe.py` adds bounded selected-branch context, explicit gateway
  solar-tool capture and token budgeting; it is not a supported external client.
- `local_model_probe.py` and `integrated_model_probe.py` optionally run an
  in-process CPU Qwen fixture. Answers measure plumbing, not interpretation quality.

The production implementation lives under `m2/`; see
[architecture](../docs/architecture/README.md), [natal](../docs/natal-charts.md) and
[advanced methods](../docs/advanced-calculations.md) for its broader contracts.

## Optional public tokenizer fixture

Backend token-budget tests need native binding/GGUF even though hosted browser
startup does not. On supported Linux x86_64 with pip-enabled CPython3.11:

```sh
.venv-swiss/bin/python -m deploy.prepare_test_model
```

This is dependency preparation: it installs the SHA-pinned official
llama-cpp-python0.3.36 CPU wheel from `probes/requirements-model.txt` and downloads
the public [Qwen snapshot](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/tree/9217f5db79a29953eb74d5343926648285ec7e67).
`qwen2.5-0.5b-instruct-q5_k_m.gguf` is522186592 bytes with SHA-256
`041474553fcabfc2a2d67903f9d2c2e50bd92528e670da4f33b5d0ce6e59fd55`.
Cold and cached files must match; corruption fails rather than silently replacing
files. Preparation performs no inference/provider call. The fixture is test-only,
not a production-image input; `deploy.prepare_ci_inputs` prepares it after Swiss
files in CI. Do not run installation/download commands under source-only scope.

Swiss Ephemeris/pyswisseph have AGPL/professional-license boundaries. Review
[Swiss licensing](https://www.astro.com/swisseph/swephinfo_e.htm),
[pyswisseph licensing](https://raw.githubusercontent.com/astrorigin/pyswisseph/master/LICENSE.txt)
and [third-party notices](../THIRD-PARTY-NOTICES.md) before distribution. Tests do
not grant distribution rights or establish scientific validity of astrology.
