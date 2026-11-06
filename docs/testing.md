# Synthetic validation

[Documentation index](README.md)

Run from the repository root with existing locked dependencies and public test
inputs. Planning does not start containers or build assets. Execution is for
explicitly authorized local synthetic work only:

```sh
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile all
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile all --execute
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile backend --tests tests.chat.test_agent_reads --execute
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profiles browser siwc clock --execute
```

`--help` lists selectors. Profiles run sequentially in one owned invocation:
backend, probes, normal browser, synthetic SIWC and fixed-clock browser. The
backend runner discovers `tests/` recursively with repository top-level imports,
then `.agents/skills/tests`; probes use their own discovery. Browser capability
folders retain recursive basename selectors in `web/playwright.config.ts`.
Common backend support lives in `tests/support/`, browser assertions/fixtures in
`web/tests/support/`. Test helpers are not copied into the production image.

The runner clears ambient fixture/provider variables, creates an owned disposable
PostgreSQL container, uses invocation-local migrated templates except for explicit
migration/recovery cases, selects free loopback ports and builds outside served
`web/dist`. It removes only resources whose ownership it can verify. Keep source
fixed during a run. Where a workspace supplies a shared execution lock, hold that
same lock from setup through cleanup; a second lock does not serialize the work.

The sanitized JSON receipt records source/dirty state, selection, counts, timings,
bounded failure locations, skipped/unrun profiles and cleanup. Detailed synthetic
logs/renders remain ignored under `.local/`. Zero matches, skips, a stopped suite
or dirty-source evidence are not exact committed-tip qualification. Confirm
collection counts before and after moving suites; imported fixture classes must
not silently duplicate or hide cases.

For provider continuation use the repository
[regression selector](../.agents/skills/kat-provider-continuation-regression/SKILL.md).
For UI changes inspect actual desktop/mobile/short-height renders as described in
[frontend development](../web/README.md); assertions alone are insufficient.
Private reference comparison is opt-in and unavailable in a public-only checkout.

Release/workflow/security-contract tests are under `tests/deploy/`; runtime,
backup/schema and tooling contracts are under `tests/operations/`. They are part
of backend discovery. Native image/source-offer/Compose/recovery checks are
separate: follow [deployment](../deploy/README.md), retaining immutable receipts
and exact source identity. A passing unit fixture is not a native recovery test.

Never replace missing prerequisites with port 8765, the current service/archive,
a real provider, private fixtures or served assets. Local results do not establish
physical-device, external-host, live-provider or deployed acceptance. Activation,
publication and private-data access remain separate scoped actions.
