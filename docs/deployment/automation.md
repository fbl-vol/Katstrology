# Unattended releases

[Documentation index](../README.md) · [Manual release](releases.md)

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
* Only the deployment job enters `kat-production`, joins the private release
  network with its scoped OAuth secret, and receives its dedicated SSH transport
  secret. Its SSH identity can invoke **only** `kat-release-ci-v1`, not a
  shell, Docker API, SCP/SFTP, port/agent forwarding or arbitrary helper command.
  `StrictHostKeyChecking yes`, one pinned host key and `IdentityAgent none` are
  mandatory. Do not reuse/migrate a personal identity or release-signing key.
* The reusable workflow requires exactly `KAT_CI_TRANSPORT_KEY` and
  `KAT_CI_TS_CLIENT_SECRET`; its caller forwards each explicitly from the matching
  `secrets` name. Keep both values solely in the `kat-production` environment,
  never repository secrets or `secrets: inherit`. GitHub requires forwarding even for environment-only secrets;
  otherwise the called workflow sees an empty string. `required: true` checks that
  the caller passes the name, not that its value is nonempty, so the transport's
  empty-value refusal remains necessary. Qualification and attestation receive no
  forwarded SSH/OAuth secrets or network identity. See [GitHub's reusable-workflow secret contract](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows#using-inputs-and-secrets-in-a-reusable-workflow).
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

Your root access and approved protected-main changes remain trust principals. Source-controlled tests cannot prove an authorized source change is
benevolent. Protect workflow, deployment and runtime admission code accordingly;
CODEOWNERS alone is not enforcement. No broad access token is needed by the
release job: normal `GITHUB_TOKEN` scopes above suffice. The server's public API
reads are token-free and bounded; exhaustion/unavailability fails closed.

### Updating the immutable secret contract

A declaration change needs two source commits: first commit the reusable contract
and its checks (A), then pin the caller's trusted-release reference to that exact A
and add the named forwarding (B). Keep the independent qualification pin unchanged.
The separately approved publication/adoption must pin the **disabled** root signer to A
before fresh hosted acceptance; it must not be pinned to B merely because B is the
candidate source. This does not authorize changing any other trust field or reading,
copying or rotating the environment-held private key. A failure before SSH is not
proof of server refusal. Use a fresh hosted refusal followed by a distinct fresh
positive release, never replay a failed run. Local contract/lint checks do not prove
GitHub environment-secret resolution or unattended delivery.

## Private release network

Only `deploy`, after its main/push/attempt1/enabled checks and `kat-production`
environment gate, runs [tailscale/github-action v4.4.0](https://github.com/tailscale/github-action/tree/064b10558093f38325e838ddea35486bdc6b1d5c).
It uses OAuth, **not OIDC**: deploy retains only `contents: read`; provenance
attestation alone receives `id-token: write`. No network identity reaches qualify
or attest. Checkout remains `github.sha`; artifacts retain their exact IDs.

The action pins Linux amd64 Tailscale `1.104.5` and the [official tarball checksum](https://pkgs.tailscale.com/stable/tailscale_1.104.5_amd64.tgz.sha256)
`720cbbccbfc03d8b55df72afc19e5a72e31b0f65934700aa6fa38074d4ad7bf7`.
`use-cache: false` avoids unverified action-cache binaries. Empty `statedir` selects
in-memory state; the pinned action requests ephemeral/preauthorized registration
and registers its native post logout/daemon cleanup. Its cleanup failures emit
warnings, so a green job alone does not prove node removal; retain post-cleanup
and actual ephemeral-device removal evidence during hosted acceptance. Abrupt
runner loss can defer removal to Tailscale's ephemeral-node cleanup. Leave Actions
debug logging disabled; never upload daemon logs, credentials or state files.

The pinned action unconditionally supplies `--accept-routes` to native `up`.
Tailscale `1.104.5` rejects repeated flags (`onceFlagValue`/`noDupFlagify`), rather
than letting a later value override an earlier one. Do not add a second routes
flag to `up`. The required chronology is:

1. Native action `up` supplies routes=true once. Our additional args are only
   `--accept-dns=false --ssh=false`; ephemeral memory state and native peer ping
   remain unchanged. The action pings `vars.KAT_CI_SSH_HOST` (direct or DERP),
   **before** the preference fence. Ping is not TCP22 authorization or admission.
2. Immediately after successful join/ping, a dedicated step runs
   `sudo tailscale set --accept-routes=false --accept-dns=false --ssh=false`.
   Native `set` changes just these preferences; it is not another login or retry.
3. Only after that command succeeds may native OpenSSH forced-key transport run.
   Neither fence nor transport has a failure-bypass condition or error suppression.
   Join, ping or fence failure prevents transport; there is no public SSH fallback.

Routes are therefore transiently accepted during setup/ping, **not** during release
transport. This path requires the separately verified isolated tailnet: only the
CI->server TCP22 grant, no other devices/rules or advertised/approved subnet/exit
routes, and OAuth limited to CI-tag nodes with no server-tag ownership. Under those
preconditions the transient setting adds no reachable destination. If they change,
keep both gates disabled and reassess; do not broaden policy or rely solely on the
later fence to contain setup. Runner DNS and Tailscale SSH remain disabled throughout;
Pi-hole/DNS, public80/443, host pin, secrets and provenance permissions are unchanged.
No subnet/exit route, Serve, Funnel or general-shell capability is introduced.

Focused regression checks cover unique vendor-composed flags and mandatory
join/ping → native set → transport ordering. Static wiring or isolated CLI parsing
does not establish live preferences, routing, logout or hosted acceptance.

Setup requires the separate approved account/network scope:

1. Keep both release gates false while enrolling the server privately, preserving
   Pi-hole, DNS and existing services. Do not add public22 forwarding: existing
   public80/443 exposure is unchanged. Do not enable Tailscale SSH on the server.
2. Restrict the OAuth client to **Auth Keys → Write**, only `tag:kat-release-ci`.
   The [official scope ID](https://tailscale.com/kb/1623/trust-credentials) is
   `auth_keys` (the Write permission, not a literal `auth_keys:write` scope ID).
   Grant no broader device, policy, DNS or account scopes. The CI tag must not own
   the server tag or other tags; the credential must never mint server identities.
   Store its secret as environment-only `KAT_CI_TS_CLIENT_SECRET` and its public
   ID as `KAT_CI_TS_CLIENT_ID` (environment or repository variable). Leave the
   existing environment-only CI SSH key untouched; no recovery, copying or rotation.
3. Review the **existing** tailnet policy before integrating the narrowly scoped
   grant below. This is a fragment, NOT a replacement policy or an API instruction.
   Use the separately enrolled server tag (`tag:kat-release-server` here):

   ```json
   {"src": ["tag:kat-release-ci"], "dst": ["tag:kat-release-server"], "ip": ["tcp:22"]}
   ```

   [Grants](https://tailscale.com/kb/1324/grants) are additive: this fragment cannot
   restrict an existing allow-all rule. Ensure neither legacy ACLs nor grants
   otherwise permit this CI tag; no default allow-all, wildcard destinations or
   broader port grants. Deny all other tailnet destinations/ports by omission,
   including DNS TCP/UDP53, web80/443 and app8765. Validate allowed TCP22 and those
   denials against the resulting policy while preserving unrelated existing access.
   This does not replace the runner's ordinary DNS/control-plane connectivity.
4. Set `KAT_CI_SSH_HOST` to the actual stable server Tailscale IPv4. Rebind the
   **same previously pinned public SSH host key** to that host identifier in
   `KAT_CI_KNOWN_HOSTS`. Keep the existing SSH user, forced command and restrictions;
   no host-key discovery, trust-on-first-use, fallback or personal/account keys.
5. Publish the reviewed contract/caller chain and pin the disabled signer to the
   immutable reusable-workflow commit, not merely the newest caller commit.
   For the scoped connection test, enable only the GitHub transport gate while
   root admission stays disabled. Require fresh hosted qualification/attestation
   and actual disabled-policy refusal, not a skipped deploy. Only after that proof
   enable root admission for a **distinct** fresh positive release. Preserve
   failure and cleanup receipts. Local workflow tests/lints establish wiring only:
   no tailnet join, policy enforcement, secret delivery or live proof is implied.

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
   schema24 manual baseline with no pending transition. A consumed 23→24 lane must
   already be finalized under its separate completion guards; do not restore an
   old policy. Preparation never advances a baseline or retires a lane.
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
   attempt. An already drain-capable schema24 app needs no bridge.
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
   set `KAT_CI_SSH_HOST` / `KAT_CI_SSH_USER`. If already enrolled, retain that key
   unchanged. Complete the private-network setup above and confirm restrictions
   with hosted denials while root CI remains disabled. Only then activate the
   reviewed root CI policy for a distinct fresh eligible release.
   Do not configure arbitrary sudo/Docker access or a generic command gateway.
8. Prove a **fresh subsequent** eligible main revision end-to-end: hosted job,
   exact artifact/bundle/plan, admitted witness, non-overlap, automatic drain,
   old-image snapshot, native preserved/deleted state and identity, serving/public
   verification, reopened admission and completed receipt. Record the actual
   installed commit/image/schema and pre/post preserved facts. No paid-provider
   or private-fixture probe is implied. A failed/ambiguous/historical run is not
   replayed/relabelled; diagnosis/recovery and another fresh revision are distinct.

Host access, public verifier/root bytes, repository settings, transport enrollment
and current runtime preflight are concrete prerequisites. Local source inspection
cannot establish them. The routine path after adoption has no human release gate.

## Local qualification

Use the owning isolated-validation skill and its native execution lock. Focused
checks include `tests.deploy.test_release_ci`, `tests.deploy.test_release_access`,
`tests.deploy.test_release_promotion`, runtime drain/HTTP/provider/browser tests and real
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
