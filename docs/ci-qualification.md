# Parallel qualification: source readiness versus activation

The qualifier supports two paths with one evidence validator:

- `python -m deploy.qualify --execute`: sequential local/all-profile path, then one native build/smoke and the same final assembler.
- Hosted reusable `qualify.yml`: backend/probes, four native Playwright browser shards, SIWC/clock, and native build/smoke run independently. Each synthetic lane owns a PostgreSQL fixture, disposable browser databases/files, port, reports and cleanup. Browser workers stay at one; `fullyParallel` is not enabled. The final `candidate` job joins evidence and transfers the unchanged native package.

These commands are execution mechanisms, not permission to install, build, contact providers or deploy. Local validation uses the isolated-validation skill and the workspace's exclusive validation lock. Default qualifier invocation without `--execute` only prints a plan.

## Inventory and evidence contract

`validate.py --profile browser --browser-shard 1/4 --execute` passes the shard to native discovery and execution. Shards reject filters, mixed profiles and private-reference mode before any fixture starts. `--profile browser --inventory-only --execute` performs native discovery without a fixture, build or browser launch. Existing unsharded/focused local selections remain available but filtered reports cannot qualify a release.

The reporter emits hashed native test identities and bounded outcomes, never titles, messages, attachments, session data or environment. Every selected test must execute exactly once with a passing outcome. Only the four already-superseded SIWC scenarios are named as permitted skips; normal browser/clock inventories allow none. Native discovery and actual execution must agree, including skip contracts. `.only`, retries, missing results and duplicate identities cannot silently qualify.

Lane records bind source commit/tree and workflow run/attempt to the exact report bytes. The final job discovers the unfiltered browser inventory again, requires all expected lane/shard identities, rejects overlaps/missing tests, validates successful owned cleanup and matches the native result to the receipt and actual immutable archive/source bytes. Final assembly does not rebuild, export or rewrite them. The existing seven-field `qualification.json` witness remains unchanged for release_ci consumers. Only the final successful join uploads a candidate containing that witness; native intermediate artifacts are not candidates.

Artifacts are named by run and attempt; downloads stay within that run. Duplicate lanes, stale/foreign source or attempt, changed reports/receipt, unsuccessful or partial execution and cleanup failures refuse qualification. Attempts other than1 are refused rather than filling a rerun's gaps with old artifacts. The existing release admission still separately rejects reruns. This is trusted-workflow evidence assembly, not a new mechanism accepting user-authored success summaries as attestations.

The job name `release / qualify / candidate`, caller output `artifact-id`, native archive/source format and downstream attestation/deployment locks remain compatible. Qualification has read-only contents permissions and no release secrets. Failure uploads contain only bounded report/summary JSON, not raw browser logs or environments. Ordinary interruption preserves stopped status and runs verified-owned cleanup; it never turns interrupted execution into passing evidence.

## Activation is deliberately NOT performed

Changing source `qualify.yml` alone does not activate this graph in production:

- `release.yml` still pins the validation qualifier to `c4310ac296fade23959efccbe340afb0239d0bb5`.
- The release path still pins signer workflow `trusted-release.yml` to `c31e7dd8fa3becd61851647a3158c95172e68eb5`. Its relative qualifier resolves at that pinned workflow revision, not automatically at the newly checked-out application source.
- Those old workflows can still execute the preserved sequential CLI against newer source. That is compatibility, not parallel-graph activation.

A later explicitly authorized activation must choose actual published, reviewed immutable revisions for the qualifier and signer graph, validate the unchanged candidate/job contract, and align the installed signer policy with the exact new signer workflow SHA before repointing the production caller. No placeholder refs, branch pins, installed policy edits, protected helper/Compose changes or trust relaxation are included here. Merely repointing the validation job does not activate the release graph. Retain the sequential CLI as a source-level rollback option; publishing or activating any rollback still needs permission.

## Timing and acceptance

The current historical deployed baseline is run42484287422/e422e1b, not the plan's earlier997f637 snapshot. Retained hosted logs measure backend165.955s, probes0.214s, browser549.539s, SIWC37.665s, clock17.657s, build7.497s and fixture startup13.947s. Local native discovery currently partitions321 main-browser tests into81/80/81/79; equal counts are not a balance or hosted speed claim.

Record exact CI-only source/timing evidence separately from later phone changes. Local serial execution of four shards establishes correctness/isolation, not hosted concurrency or under-ten performance. No runner tier/capacity purchase or hosted benchmark is authorized by this source work. A later approved qualification-only run must measure setup, queueing, each lane, native build/smoke and join; account capacity for seven concurrent runners is unverified. A final under-ten acceptance claim requires at least three separately approved comparable complete successful releases, including queue/handoff/attestation/deployment, with cache conditions recorded. No such improvement is claimed from source changes or local tests.
