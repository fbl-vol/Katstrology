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
* The reusable workflow explicitly declares `KAT_CI_TRANSPORT_KEY` as required;
  its caller must forward only that name via
  `KAT_CI_TRANSPORT_KEY: ${{ secrets.KAT_CI_TRANSPORT_KEY }}`. Keep the value solely
  in the `kat-production` environment secret, never a repository secret or
  `secrets: inherit`. GitHub requires forwarding even for environment-only secrets;
  otherwise the called workflow sees an empty string. `required: true` checks that
  the caller passes the name, not that its value is nonempty, so the transport's
  empty-value refusal remains necessary. Qualification and attestation receive no
  forwarded transport secret. See [GitHub's reusable-workflow secret contract](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows#using-inputs-and-secrets-in-a-reusable-workflow).
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

### Updating the immutable secret contract

A declaration change needs two source commits: first commit the reusable contract
and its checks (A), then pin the caller's trusted-release reference to that exact A
and add the named forwarding (B). Keep the independent qualification pin unchanged.
The coordinator must publish the chain and re-pin the **disabled** root signer to A
before fresh hosted acceptance; it must not be pinned to B merely because B is the
candidate source. This does not authorize changing any other trust field or reading,
copying or rotating the environment-held private key. A failure before SSH is not
proof of server refusal. Use a fresh hosted refusal followed by a distinct fresh
positive release, never replay a failed run. Local contract/lint checks do not prove
GitHub environment-secret resolution or unattended delivery.

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
validated before native use. Qualification removes only its unused owned build
image (never force/prune), reloads the actual archive and exercises that import.
Classic Docker's native identity is the config digest; containerd's is the saved
index. Both are attested. Preflight selects by the native store type, checks the
exact loaded ID/revision, and freezes it for Compose/promotion/containment; there
is no alias or unverified identity fallback. Cross-job paths are basename-relative. The database
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
button as recovery. CI remains fenced through public verification. If reopening
succeeds but the final receipt cannot be committed, the verified candidate stays
open: stopping it could kill newly admitted work. The outcome remains halted /
completion unconfirmed, with the active attempt retained—not a success claim.

Same-schema releases retain exact migration history. An advancing schema needs
an installed explicit transition: exact hashed migration files, allowed new empty
tables and/or nullable columns with **no default**. There is no generic
`allow 23 -> 24` switch. Backfills, row mutation, constraints/index changes on old
tables, destructive SQL, skipped/extra migrations and an active Store owner are
rejected. Snapshot uses the **old image's** exact migration set before candidate
DDL. Migration is transactional; a durable `migrating` boundary makes an
ambiguous commit outcome stop-only, never an automatic rollback/old-data restore.
Enrollment does not change tone/account defaults or backfill existing accounts.

## One-time adoption — separate authorization, no commands run by this document

1. Review the exact source commit/tree and local evidence. Select the immutable
   trusted-workflow commit used by `release.yml`; a later workflow change requires
   a new reviewed signer pin on the server. Publish only with explicit permission.
   Source tests and lints do **not** show these files are installed or ran hosted.
2. Verify the existing main protections: no force-push/deletion, required `Kat checks`,
   protected trust-boundary changes and an explicit bypass policy. Verify the
   fixed `kat-production` environment for main only, **without required human
   reviewers** (those would reintroduce a routine gate). No PR or tag may access it.
   This repository has no automatic configuration writer; inspect actual settings.
3. Select and checksum the maintained native `gh` verifier2.97.0 against its
   official release. Export its public Sigstore trusted root, verify its origin,
   retain the exact bytes, and define refresh/expiry maintenance. Do not silently
   fetch a new root or verifier during a release. A stale root fails closed.
4. Prepare a fresh disabled adoption plan, using the existing manual protocol4
   target policy **only under adoption approval**, the public verifier/root files
   and the reviewed signer commit. Supply the retained **currently deployed
   schema24** receipt, not a future candidate or the old schema23 package:

   ```sh
   python -m deploy.prepare_enrollment \
     --manual-policy /approved/input/manual-policy.json \
     --running-receipt /retained/current-schema24/receipt.json \
     --signer-sha <immutable-workflow-commit> \
     --verifier /approved/public/gh \
     --trusted-root /approved/public/trusted-root.jsonl \
     --output /new/owned/adoption-plan
   ```

   This writes only `ci-policy.json` (`enabled:false`), the non-secret public
   `target-scope.json`, and exact helper/Compose/source hashes. It neither installs
   anything nor reads/generates an SSH/signing key. The shared manual helper,
   controller and template bytes must match the retained installed package;
   preparation refuses an implicit update. Preserve the complete manual policy,
   signer, target and allowlist. This preparation requires the actual finalized
   manual24 baseline with no pending transition. Completed155 policy finalization
   retired its consumed23→24 lane under separate completion guards; do not restore
   the old policy. Preparation itself never advances a baseline or retires a lane.
   The existing gateway derives its baseline directly from that manual policy;
   no schema-override field or changed gateway contract is needed. An empty CI
   transition list admits same-schema24, not23, a new migration or manual-lane replay.
   The adoption plan records both `manual_policy_file_sha256` (exact file bytes)
   and `manual_policy_sha256` (sorted compact JSON plus newline). These are
   preparation/preflight evidence, not new gateway authority or an installation
   claim. Recheck current policy/package facts before installation.
   Root-owned installed helper files/parents must not be symlinks or group/other-
   writable. No service restart, old key mutation, schema migration or historical
   receipt rewrite is implicit.
5. Set only the public `KAT_CI_TARGET_SCOPE` variable first. Leave
   `KAT_AUTOMATION_ENABLED` unset/false and the transport secret unenrolled. The
   configured-main workflow can now generate a qualified, attested candidate
   package but cannot contact production. Validate a real native verifier result
   for this repository's certificate/run identity and the actual successful job
   name; do not replace certificate checks with test JSON. Negative cases must
   still reject. No production preservation claim follows from this hosted build.
6. Match the actual running image/source/schema to that retained package, verify
   the existing maintenance socket/open admission and absence of an active release
   attempt. An already drain-capable schema24 app (including155) needs no bridge.
   Use the ordinary CI lifecycle: native quiesce, old-image snapshot, preservation,
   promotion and public verification before reopening. Do not create a bootstrap
   permit, stop via historical idle consent, downgrade or restore the old schema23
   runtime. `bootstrap_bridge.py` remains historical schema23-only source, is
   omitted from this adoption plan, and is inapplicable to the current target.
   A disabled plan, manual deployment or locally invoked genuine-provenance release
   is not proof of hosted unattended transport. If a priority manual release has
   since changed the running package or policy, regenerate preparation from its
   retained receipt and recheck current facts; never overwrite immutable evidence.
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
settings, new transport enrollment or current runtime preflight are concrete remaining
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

On a stopped synthetic profile, the validator emits `kat validation stopped:`
JSON to stderr, which remains visible in hosted job logs even when `qualify`
redirects its stdout witness. It includes child exit/timeout, cleanup and unrun
profiles. Backend diagnostics retain at most 20 failures (with an omitted count),
test identifiers, exception types and eight repository source locations per
failure; no exception messages, source lines, locals, subtest values, environment
or raw log tails are published. An interrupted backend may leave a `running`
checkpoint identifying its last-started test; that is not a completed result or
proof that that test caused termination. Missing/corrupt diagnostics are explicit
and never replace the original failing exit. Raw logs remain invocation-local.
Browser/SIWC/clock profiles additionally retain Playwright's native JSON report
inside the owned invocation directory. Only integer outcome counts and at most20
unexpected results/global errors, with repository test declaration coordinates and
at most8 source locations each, enter the public stopped-profile summary. Titles,
messages, stacks, snippets, stdout/stderr, attachments and external paths stay local.
Missing/malformed/oversized reports remain explicit without replacing a failing
child exit. No failure artifact upload or immutable workflow repin is needed.
A fresh hosted attempt is still required to diagnose an earlier failure whose
runner-local log was lost; do not call that failure transient or fixed from local
success alone.
