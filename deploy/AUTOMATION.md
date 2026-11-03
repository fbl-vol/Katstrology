# Unattended releases (source contract, not installed automation)

The manual protocol4 gateway remains available. CI uses a separate keyless
admission adapter and **the same** lock, active-attempt fence, native snapshot,
preservation, promotion and public-verification phases. No human signing key is
uploaded to GitHub. After one-time adoption, an eligible protected-main push
qualifies, packages, attests and releases without a signature, manual build/upload,
KAT IDLE confirmation or dispatch. There is deliberately no dispatch trigger.

Source/local evidence does not prove repository protection, installed trust,
hosted identity or a successful unattended production release. Those require the
separately authorized adoption and positive proof below. The initial policy is
`enabled: false`; absent GitHub variables also disable transport.

## Workflow and trust boundaries

* PR/unconfigured-main: read-only hosted qualification; no production environment,
  identity token, attestation write, transport secret or server access.
* Configured main: the entry workflow calls an immutable SHA of
  `trusted-release.yml`. No caller-selected source, artifact, command or test input
  is accepted. Its `qualify / candidate` job checks out `github.sha`, runs **all**
  isolated suites (including deploy tests), builds once, loads and exercises that
  archive using disposable native Compose, drain, snapshot/restore and a synthetic
  additive migration. Only that image/source/receipt/qualification set is uploaded.
* Only the subsequent attestation job receives `id-token: write` and
  `attestations: write`. It prepares a canonical manifest over those qualified
  hashes and the enrolled public target fingerprint. The GitHub/Sigstore native
  bundle attests the manifest as its exact subject. No `tests_passed` predicate is
  accepted as authority.
* Only the deployment job enters `kat-production` and receives its dedicated
  transport secret. Its SSH identity can invoke **only** `kat-release-ci-v1`, not a
  shell, Docker API, SCP/SFTP, port/agent forwarding or arbitrary helper command.
  `StrictHostKeyChecking yes`, one pinned host key and `IdentityAgent none` are
  mandatory. Do not reuse/migrate a personal identity or release-signing key.
* GitHub concurrency is non-cancelling across main releases. Server locks and the
  durable active attempt remain authoritative even if a job is killed. Re-runs
  (`run_attempt != 1`), old run numbers, PR/tag/wrong-repo/wrong-source artifacts,
  stale bundles and non-current-main revisions are rejected.

The root-protected CI policy pins repository **ID**1437147047 and name
`fbl-vol/Katstrology`, `refs/heads/main`, the caller, signer workflow and signer
commit, GitHub issuer, hosted runner, native verifier binary hash/version,
trusted-root file hash and CI helper hash. Native verification checks the
certificate identity, source digest, build config, invocation and subject; the
server also reads the current repository/branch/run/jobs API records. Main must
be protected and the exact successful job is `release / qualify / candidate`.
The final workflow need not have completed before deployment: requiring its own
success would be circular. Run attempt, timestamp and successful mandatory job
are checked instead. Network authorization stops after the root-owned admission
witness is frozen; later phases do not re-fetch mutable policy decisions.

A root administrator or an authorized protected-main change remains a trust
principal. Source-controlled tests cannot prove an authorized source change is
benevolent. Protect workflow, deployment and runtime admission code accordingly;
CODEOWNERS alone is not enforcement. No broad access token is needed by the
release job: normal `GITHUB_TOKEN` scopes above suffice. The server's public API
reads are token-free and bounded; exhaustion/unavailability fails closed.

## Native package compatibility

The hosted daemon is an **ephemeral** Docker29.7.2/containerd image store, not an
upgrade to the user's or production daemon. Buildx0.38.1 and Compose2.38.2 plugins
are downloaded from official releases with source-pinned SHA256 values. CPython
3.11.16, Node22.23.4 and action commit SHAs are fixed. Dependency installation uses
repository locks/requirements; this is a qualified single artifact, not a claim
of byte-for-byte reproducible dependency resolution. Public BGE and Swiss fixture
files are size/hash checked, token-free and do not include a private chart.

The validator accepts the setup action's explicit local Unix Docker socket only
on a hosted runner; ordinary local validation still fixes `/var/run/docker.sock`.
The image archive index/platform/config, loaded ID, source offer and receipt are
validated before native use. Cross-job paths are basename-relative. The database
image remains digest-pinned. Native qualification checks effective Compose config,
loopback Host admission, packaged assets, startup/restart, empty fresh DB, retained
synthetic rows through backup/independent-ledger restore/additive migration,
persisted drain fence/reopen, and removal of the new project's containers/volumes.

## Runtime drain and failure meaning

Admission closes atomically **before** waiting. Full accepted request lifetime,
actual executor completion despite cancellation, chat jobs, title work, rebuild
work and effectful GETs (including model refresh) are accounted for. New work gets
503 `release_maintenance`; anonymous readiness/static resources remain available,
and cancellation can help existing work settle. The private Unix socket validates
peer UID and accepts only status/drain/resume with an exact attempt identity.
A drain timeout (300 seconds) does not kill inference or retry it: release aborts
and the identical still-running old process is reopened only after native identity
and boot checks. Candidate restart inherits a persisted fence until verification.
The browser retains the same pending turn identity/draft and does not auto-resend.

Before old stop, proven same-process containment can leave the existing service
usable. After stop, unknown work/outcome or preservation failures halt behind the
active attempt, with the owned app stopped where safe. A changed container is not
stopped merely because it has a matching name. No old database/files/deletion
journal is restored, no uncertain effect is retried, and no completed/recovered
historical attempt is replayed or renamed as successful. Workflow/result artifacts
report actual phase/containment; inspect them rather than using GitHub's re-run
button as recovery. Failure during public verification also retains containment.

Same-schema releases retain exact migration history. An advancing schema needs
an installed explicit transition: exact hashed migration files, allowed new empty
tables and/or nullable columns with **no default**. There is no generic
`allow 23 -> 24` switch. Backfills, row mutation, constraints/index changes on old
tables, destructive SQL, skipped/extra migrations and an active Store owner are
rejected. Snapshot uses the **old image's** exact migration set before candidate
DDL. Migration is transactional; a durable `migration_started` boundary makes an
ambiguous commit outcome stop-only, never an automatic rollback/old-data restore.
The tone/account-default decision is not made here; no product migration is added.

## One-time adoption — separate authorization, no commands run by this document

1. Review the exact source commit/tree and local evidence. Select the immutable
   trusted-workflow commit used by `release.yml`; a later workflow change requires
   a new reviewed signer pin on the server. Publish only with explicit permission.
   Source tests and lints do **not** show these files are installed or ran hosted.
2. Configure main protections: no force-push/deletion, required `Kat checks`,
   protected trust-boundary changes and an explicit bypass policy. Configure the
   fixed `kat-production` environment for main only, **without required human
   reviewers** (those would reintroduce a routine gate). No PR or tag may access it.
   This repository has no automatic configuration writer; inspect actual settings.
3. Select and checksum the maintained native `gh` verifier2.97.0 against its
   official release. Export its public Sigstore trusted root, verify its origin,
   retain the exact bytes, and define refresh/expiry maintenance. Do not silently
   fetch a new root or verifier during a release. A stale root fails closed.
4. Prepare a fresh disabled adoption plan, using the existing manual protocol4
   target policy **only under adoption approval**, the public verifier/root files
   and the reviewed signer commit:

   ```sh
   python -m deploy.prepare_enrollment \
     --manual-policy /approved/input/manual-policy.json \
     --signer-sha <immutable-workflow-commit> \
     --verifier /approved/public/gh \
     --trusted-root /approved/public/trusted-root.jsonl \
     --output /new/owned/adoption-plan
   ```

   This writes only `ci-policy.json` (`enabled:false`), the non-secret public
   `target-scope.json`, and exact helper/Compose/source hashes. It neither installs
   anything nor reads/generates an SSH/signing key. The manual root policy's helper,
   controller and template pins must be deliberately updated to these exact bytes;
   it must retain its signer and target restrictions. Root-owned installed helper
   files/parents must not be symlinks or group/other-writable. No service restart,
   old key mutation, schema migration or historical receipt rewrite is implicit.
5. Set only the public `KAT_CI_TARGET_SCOPE` variable first. Leave
   `KAT_AUTOMATION_ENABLED` unset/false and the transport secret unenrolled. The
   configured-main workflow can now generate a qualified, attested bootstrap
   package but cannot contact production. Validate a real native verifier result
   for this repository's certificate/run identity and the actual successful job
   name; do not replace certificate checks with test JSON. Negative cases must
   still reject. No production preservation claim follows from this hosted build.
6. The old dfc/schema23 app has no drain socket. During a separately approved
   **one-time** planned maintenance window, let existing work settle, stage the
   fresh CI-attested package as root-owned bytes, and install an exact root-only
   `/etc/kat-release/bootstrap.json` permit containing `plan_sha256`, `old_image`,
   `old_source_sha256` and `settled_existing_work:true`. These are measured old
   image/source identities and the newly attested plan, not a reusable idle flag.
   The local-root `bootstrap_bridge.py` defaults to a non-mutating plan. Its
   `--execute --package <root-owned-package>` operation additionally verifies fresh
   keyless identity/eligibility and all bytes, consumes the permit exclusively as
   `bootstrap.used.json` **before effects**, and drives the shared lifecycle. It
   stops the settled old owner, seeds the new persisted fence, snapshots with the
   old image, promotes/starts/verifies and reopens the drain-capable same-schema
   app. No human signature is needed. Failure consumes the permit and retains
   attempt evidence; do not recreate/replay it. There is no bootstrap field/action
   in either SSH protocol, and ordinary CI cannot resume a bootstrap witness.
   A bridge installation is not an unattended-release proof.
7. Enroll a **new dedicated** CI transport identity only with explicit approval;
   never inspect/copy/migrate an existing private key. Install its public half with
   `restrict` and the fixed root-owned `release_ci_access.py` forced command (the
   plan includes the exact command), no forwarding/PTY/shell/SCP/SFTP/Docker-group
   access. Install only its private half as the `kat-production` environment's
   `KAT_CI_TRANSPORT_KEY`; pin the public SSH host key in `KAT_CI_KNOWN_HOSTS`, and
   set `KAT_CI_SSH_HOST` / `KAT_CI_SSH_USER`. Confirm restrictions with denials.
   Activate the reviewed root CI policy and then set `KAT_AUTOMATION_ENABLED=true`.
   Do not configure arbitrary sudo/Docker access or a generic command gateway.
8. Prove a **fresh subsequent** eligible main revision end-to-end: hosted job,
   exact artifact/bundle/plan, admitted witness, non-overlap, automatic drain,
   old-image snapshot, native preserved/deleted state and identity, serving/public
   verification, reopened admission and completed receipt. Record the actual
   installed commit/image/schema and pre/post preserved facts. No paid-provider
   or private-fixture probe is implied. A failed/ambiguous/historical run is not
   replayed/relabelled; diagnosis/recovery and another fresh revision are distinct.

These are you/your agent's separately authorized adoption steps, not a handoff to
an invented operator. Missing host access, public verifier/root bytes, repository
settings, new transport enrollment or a maintenance window are concrete remaining
prerequisites. The routine path after adoption has no human release gate.

## Local qualification

Use the owning isolated-validation skill and its native execution lock. Focused
checks include `deploy.test_release_ci`, `deploy.test_release_access`,
`deploy.test_release_promotion`, runtime drain/HTTP/provider/browser tests and real
owned PostgreSQL migration/backup tests. Run workflow actionlint and security
checks, then full `--profile all`; the qualification command also runs the exact
archive through native smoke. Inspect cleanup and final source tip/tree. A native
unsigned-bundle denial or synthetic certificate fixture is not a positive GitHub
identity check. Local Compose is not production host/Caddy/SSH verification.
