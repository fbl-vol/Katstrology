# Local review readiness and delivery

This is the owning Kat workflow guide. [Testing](testing.md) describes fixture
isolation; [automation](deployment/automation.md) owns the installed release
protocol. Instructions and an explicit user hold override the ordinary sequence.
Nothing here grants publication, root access, enrollment or provider/private-data
access. Do not start pipelines to prove compliance with a local-only task.

## Order work by feedback value

1. Implement a coherent batch with focused consequential regressions. Commit the
   review candidate; record actual selectors/results and remaining limits. Resolve
   ordinary failures locally. Do not rebuild a native image after each todo.
2. Investigate migration and immutable workflow-pin prerequisites early, using
   public/supplied artifacts offline. Prepare exact manifests; identify missing
   installed witnesses without pretending that preparation activates anything.
3. Send committed source and focused evidence for independent review when review
   is authorized. Selected corrections get focused checks and same-cycle bounded
   re-verification. Review-ready does **not** mean release-qualified.
4. On the final reviewed candidate, run the complete required local acceptance
   once: full regressions, affected exact-tip renders/performance and native
   package/recovery qualification. A later fix requires applicable requalification
   and review; never borrow old-tip receipts or omit required acceptance.
5. Only with delivery authority and cleared security/migration/trust prerequisites:
   publication audit, one PR, fresh required PR CI, protected merge, fresh main CI,
   native completion and serving verification. Required hosted checks are not
   replaced by local evidence or a prior PR artifact. Preserve failures/halts.

During a local-only hold, stop after implementation, focused checks and self-review.
List independent review, full qualification, hosted execution, enrollment and
release as held/unrun. Do not convert the hold into another approval question.

## Parallel CI is an immutable authority chain

The entry workflow pins both qualification and trusted release to published
`f64fb6dcbd104cff83219827dce5eef849fde89b`. The trusted workflow's relative qualifier
resolves at that same revision, which contains backend, four independent browser
shards, interaction and native lanes. The final `candidate` job requires all lanes,
matching source/run/attempt, complete unfiltered discovery and exact native bytes.
`Kat checks` and `release / qualify / candidate` names remain stable. Permissions,
non-cancelling concurrency, single build and owned fixtures are unchanged.

Run `python -m deploy.prepare_workflow_adoption` to print an **offline** future
signer-pin handoff from existing Git objects (no fetch/install). If that object is
not present, use an explicitly available public checkout; do not invent hashes.
Installed trust still needs separately authorized, guarded adoption and independent
read-back. Never change the installed signer through the migration utility.
Parallel lanes may spend more runner-minutes; no speedup is claimed before approved
hosted measurement. No branch pins, higher runner tier or cross-run cache is added.

## Early migration preparation

`python -m deploy.prepare_migration --help` describes offline comparison of two
public migration directories and optional supplied policy. The result binds exact
SQL and unchanged history to the narrow native additive lane. It cannot certify
live schema, ownership or data preservation. A same-schema result needs no lane;
unsupported/destructive SQL requires a real migration decision, not a wider flag.

`deploy.enroll_migration` is a future root utility, not a release command. Without
`--execute` it only checks provided bytes offline. Execution needs specific user
instruction and exact lane/policy/installed-helper/host pins, existing release
lock/no active attempt, running native schema/image, durable exclusive backup,
installed candidate validation and read-back. Ambiguity leaves evidence and stops;
no rollback, replay, app restart or DDL is performed. Supply `--lane`,
`--expectations` and the reviewed `--expectations-sha256`. The expectations object
has exactly `request`, `hostname`, `lane_sha256`, `policy_sha256`,
`native_policy_sha256`, and `helper_sha256` (hashes for `release_access.py`,
`release_remote.py`, `release_pipeline.py`, `release_ci_access.py`). Obtain these
from separately authorized inspection, never guessed defaults. The offline plan
reads only those supplied files; execution fixes the installed policy/helper paths
and derives the exclusive backup name from `request`. A flag/hash is not approval.
Independent read-back remains necessary before release. Native deployment still owns transactional migration,
snapshot, retained-data/deletion checks and admission.

## One local receipt, short recovery checkpoints

Use `python -m deploy.delivery_receipt --help` to bind the clean source/diff to
existing evidence and generate a concise summary. The record indexes evidence;
it is **not** an attestation, approval or replacement release gate. Hashes establish
identity/integrity, not the truth of arbitrary JSON. Unsupported, missing, foreign,
failed and merely reported evidence remain explicitly distinct. Independent review
and external enrollment/native results retain their producer/provenance and do not
become self-certified by importing a file.

Keep one registered recovery checkpoint with only request/scope, current state,
remaining action and the receipt path. Preserve old artifacts instead of copying
hash inventories and repeated completion narratives into several Markdown files.
A useful handoff is the generated summary plus material decisions/limits.

## Invocation deadlines

Before execution, plan the **same** validator selection and read its execution
budget. Set the outer tool timeout at least to the recommended total, including
fixture ownership checks and cleanup grace. Do not wrap a long browser run in an
arbitrary240-second timeout. The runner's existing SIGTERM interruption path cleans
only owned resources and records stopped, never passed. If the outer harness kills
before cleanup can finish, preserve its receipt/identities for inspection rather
than guessing a container/process to remove. A deadline recommendation is a bound,
not a performance promise or permission to execute a wider suite.
