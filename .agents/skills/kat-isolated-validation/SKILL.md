---
name: kat-isolated-validation
description: 'Run focused or grouped Kat backend, probe and browser validation using a freshly owned synthetic fixture. Use for local test suites, fake SIWC, proof UI or fixed-clock checks. Differentiator: selects repository profiles without touching the user fixture, live provider or served assets.'
---

# Kat isolated validation

Run commands below from this skill directory. `python3 scripts/validate.py --help` lists all options. The default is a **non-mutating plan**; `--execute` is appropriate only within authorized local synthetic testing.

```sh
# Plan the complete selection without starting fixtures or building.
python3 scripts/validate.py --profile all

# Fast feedback while correcting layout: execute the relevant existing checks.
python3 scripts/validate.py --profile browser --browser-grep 'pinned synthetic reading layout' --execute

# Focus backend work using actual unittest selectors, not a new test harness.
python3 scripts/validate.py --profile backend --tests m2.test_store --execute

# Targeted backend and synthetic SIWC in one invocation, with distinct filters.
python3 scripts/validate.py --profiles backend siwc --tests m2.test_provider_output_compat --browser-grep 'synthetic streamed read' --execute

# Final UI batch: share one fixture and the normal build across browser profiles.
python3 scripts/validate.py --profiles browser siwc clock --execute

# Optional private layout comparison only on a checkout with the approved reference and baseline.
python3 scripts/validate.py --profile browser --browser-grep 'pinned synthetic reading layout' --private-layout-reference --execute
```

## Choose the feedback loop

- During iteration, run the relevant existing/new checks using `--tests m2.test_...` or `--browser-grep 'test title'`. Match consequential behavior, not whichever test is cheapest. Inspect selection/results; zero matches, skips and unrun profiles are not validation of the change.
- Once a coherent change is ready, run its required broader checks and rendered acceptance. Group applicable profiles with `--profiles` rather than launching separate invocations that repeat builds/setup. `--profile all` retains the complete suite; do not substitute a focused pass for required handoff checks.
- Read `risk-based-testing` for selection and `ui-review` for rendered acceptance. For responsive chat/chart changes, inspect actual six-viewport geometry and images in `web/tests/layout-visual.spec.ts` (`web/README.md`, “Synthetic layout comparison”). Private-reference overlays/diffs require `--private-layout-reference` and locally available inputs; the public default marks that comparison not requested. Images are diagnostic, not an approved pixel baseline. A green runner alone is not visual acceptance.

## Execution and reuse boundaries

`--profile` selects one of `backend|probes|browser|siwc|clock|all`. Alternatively, `--profiles` accepts several concrete profiles, preserves their order and removes duplicates. The options are mutually exclusive. Backend selectors require backend in the selection; a browser title filter requires at least one browser profile. When grouped, each filter applies only to its own profile family; probe tests retain their ordinary discovery. Invalid selectors fail before fixture startup.

Grouped profiles execute **sequentially**. Backend tests additionally clone an invocation-local migrated synthetic template except for explicit migration/recovery/auth paths, retaining independent databases, files and deletion journals. They share one newly owned PostgreSQL container; each browser-server launch still creates its own disposable database/files. Normal assets build once when needed, solely within that invocation's new ignored `.local/kat-validation/` directory. There is no cross-run cache and no reuse of served `web/dist`. Keep source fixed while a validation invocation runs; source edits require another run. Dirty-source results are advisory, not exact committed-tip acceptance.

The runner clears ambient `KAT_*`/PG/provider fixture variables, uses `m2/test_support.py` and `web/browser_fixture.py`, and selects explicit compatible browser flags. SIWC must **not** combine with the prelinked fake-plan flag; the fixed-clock profile explicitly enables synthetic callback and prelinked scenarios. Normal browser tests use the fake plan; all browser profiles deny external hosts. Never substitute port 8765, the user's fixture, actual provider calls or an unowned container when setup fails.

## Read the report

The runner prints bounded stage start/finish notices to stderr and one sanitized JSON object on stdout containing `git.sha/dirty`, `selected`, `filters`, `unrun` (not attempted), per-profile results and ignored log paths. Backend results include at most five slow-test and five fixture-setup timing entries (synthetic test IDs only). `timings` lists fixture startup, template preparation, build/typecheck, test and cleanup stages with seconds/status; `total_seconds` includes cleanup. Normal build timing includes its TypeScript check. A stopped profile remains explicitly stopped, later profiles remain unrun, and failed stages retain timings. Cleanup failures also produce a stopped report without dumping commands, environment or credentials.

Use those measurements to locate the next bottleneck; do not promise a speedup from CPU allocation alone. Do not blindly raise browser workers: shared fixture identities and the single Store executor require independently isolated application/database groups before parallel benchmarking. Preserve existing resource limits, security/migration/durability checks and final acceptance obligations. No global skill changes, runtime activation or live-model traffic are needed.
