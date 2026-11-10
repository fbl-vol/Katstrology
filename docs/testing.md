# Synthetic validation

[Documentation index](README.md) · [Review readiness and delivery ordering](delivery-workflow.md)

Run from the repository root with existing locked dependencies and public test
inputs. Choose local checks by changed behavior, dependencies and neighboring
regressions, with relevant lint/typecheck and affected UI checks. Record selection
rationale/results/unrun limits; independent reviewers assess sufficiency when
authorized. Broaden relevant selection for shared provider, persistence, security
or migration changes without automatically choosing every suite. Full PR/main CI
inventories, all lanes and native source/image/migration/preservation checks remain
mandatory when delivery is authorized. Full local suites are optional diagnosis/CI
reproduction, **not** automatic pre-review or final-release prerequisites.

Planning does not start containers or build assets. Plan the identical selection,
read `budget.recommended_outer_seconds` and allow that timeout plus any bounded
lock wait. Execution is for explicitly authorized local synthetic work only:

```sh
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile backend --tests tests.chat.test_agent_reads
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile backend --tests tests.chat.test_agent_reads --execute
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profiles browser siwc --browser-grep 'affected shared behavior' --execute
# Optional broad diagnosis/CI reproduction: plan first; execute only when selected/authorized.
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile all
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
not silently duplicate or hide cases. Preserve frozen review renders as well as
receipts. When tests use fixed screenshot paths, execute a fresh owned ordinary
qualification copy at the exact committed head rather than overwrite old images.
Keep the same whole-invocation lock and ownership rules; never use another reviewer's
clone. A prior receipt does not qualify a later policy-only or corrective commit.

For provider continuation use the repository
[regression selector](../.agents/skills/kat-provider-continuation-regression/SKILL.md).
For UI changes inspect actual desktop/mobile/short-height renders as described in
[frontend development](frontend-development.md); assertions alone are insufficient.
Private reference comparison is opt-in and unavailable in a public-only checkout.

Release/workflow/security-contract tests are under `tests/deploy/`; runtime,
backup/schema and tooling contracts are under `tests/operations/`. They are part
of backend discovery. Native image/source-offer/Compose/recovery checks are
separate: follow [deployment](../deploy/README.md), retaining immutable receipts
and exact source identity. A passing unit fixture is not a native recovery test.

Never replace missing prerequisites with port 8765, the current service/archive,
a real provider, private fixtures or served assets. Local results do not establish
physical-device, external-host, live-provider or deployed acceptance. Activation,
publication and private-data access remain separately scoped. The Kat-specific standing
authority in `AGENTS.md` covers coordinated review, ordinary remediation and guarded
publication/deployment of agreed work; it does not authorize provider/private-account
tests or bypass security dispositions, migration integrity or native release guards.
