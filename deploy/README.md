# Personal production candidate (source and local fixture preparation only)

For the disabled-until-adopted keyless workflow, runtime drain, native qualification
and one-time bootstrap contract, see [Unattended releases](AUTOMATION.md).
For the separately installed, human-signed exact-hash23→24 lane, see
[Manual transitions](MANUAL_TRANSITIONS.md). It does not require CI enrollment.

This directory is not an activation instruction or approval. These source files do
not change the existing served deployment without a separately scoped release. Do not run
this Compose project on a shared host, change Caddy, copy an account or move any
private data without that authorization. No visitor signup or public-browser OAuth
is supported. Local `serve` and local HTTP127.0.0.1 ChatGPT registration remain
unchanged; deployment requires `--deployment-origin https://katstrology.dk`,
explicit private DB password/state/build paths, and rejects invalid configuration
before the Store opens. The browser boundary compares the exact Host/Origin,
requires Origin on mutations, keeps CSRF and strict cookies, sets Secure on HTTPS,
and ignores proxy-provided authority headers. Only a trusted HTTPS reverse proxy
should reach the loopback host port. The deployment callback/start return no
registration route, even if a provider is enabled.

## Build and identity

`python3 deploy/build_local.py` accepts only a clean committed public checkout and
requires the pinned public BGE CPU model snapshot in `.local/models/fastembed`
(or an explicitly supplied `--public-model-cache` directory with the identical
verified public revision). It stages only five allowed SHA-256/size-checked files
into a temporary Docker build context, never the whole HF cache. Missing or
changed weights fail before any accepted receipt; runtime repeats the same
read-only identity check once per embedder and binds inference to the verified
snapshot using FastEmbed's local `specific_model_path`. Only newly staged
public paths receive 0755 directory/0644 file modes; the original cache is
untouched. The build smoke loads the model with offline-only CPU execution
**after** switching to runtime UID 10001. Final packaged testing also uses
nonroot, read-only, network-none execution. The cache source is preparation input, not an
app volume or credential. The package receipt identifies its model revision and
per-file hashes; the checked-in `m2/public_model.py` and
`m2/public-model-LICENSE.txt` supply the manifest and upstream MIT notice.
`build_local.py` produces an ignored `.local/fresh-production/package/<tip>/` containing an amd64
Docker image archive, `git archive` corresponding source offer and a receipt with
SHA, tree, OS/arch, archive index/config digests and both file SHA-256 digests.
Classic Docker addresses the config; Docker's containerd store addresses the
saved index. Native preflight freezes the store-specific attested identity and
checks it exactly after load; never substitute a tar hash or guess between IDs. This is a local
artifact, not an upload, registry publication or release. The Node, Python and
PostgreSQL bases are pinned by digest; browser dependencies use `npm ci` and the
Python application pins direct versions. **Transitive Python wheel hashes are not
locked, and a rebuild is not guaranteed byte-identical.** Audit resolution and
licenses before promotion; refresh pinned bases through a separate review. See
`THIRD-PARTY-NOTICES.md` and `docs/PUBLICATION.md`. The image contains only
the pinned public model files, not private data or indexes; no ephemeris, real
credentials, account state or journal is in the image or source offer. The
source offer includes the public model manifest/licence, never its binary cache.
Check the actual old server CPU, base pulls and native image identity in its separately
authorized private preflight, not by assuming this local build can run there.

`compose.yaml` is a template, not a server command. It names a new project and
fresh volumes, keeps PostgreSQL unpublished, binds the app to host loopback
127.0.0.1:28765 only, and expects native Caddy to terminate HTTPS later. The
container listens on 8765 with untrusted proxy headers disabled. Recheck the
candidate host port and Caddy routing before use. `KAT_APP_IMAGE` must be an
inspected local immutable image ID; `KAT_EPHE_DIR` is an explicitly supplied
licensed Swiss-ephemeris directory mounted read-only. The DB password is a
separate private file (owned by UID 10001, 0400 for the app bind mount); no
secret value may be supplied in argv, environment, image, receipt or browser.
PostgreSQL receives its own Compose file secret. Confirm the effective mounted
permissions on the intended host; a Compose file-secret mode is not a substitute
for this check. Make the separate state, deletion, credential and DB volumes
writable by their intended owners without publishing them. For a **local-only**
packaged startup regression, `python -m deploy.smoke_local --receipt
<ignored-exact-tip-receipt> --execute` creates a uniquely named disposable Compose
project, dynamic loopback host port and synthetic DB secret/empty ephemeris mount.
It checks effective mounts, image-served assets, unauthenticated Host behavior,
empty schema and restart, then removes only that project's containers and volumes.
The default without `--execute` is a plan. This is not host activation.

## Existing-instance app-only release pipeline (source tooling; not authorization)

This is **protocol 4 source tooling**, not evidence of installation or a successful
real signed release. A protocol-3 helper/policy cannot run it. Adoption requires a
separately reviewed protected-helper/policy transition; never replay historical
schema-22 controls on a schema-23 installation. Existing app and signer credentials
must not be regenerated merely to adopt this version.

`release_pipeline.py` is for a **previously installed and running instance of this
exact Compose project**, not initial installation, host provisioning, Caddy route
changes or the frozen release being coordinated elsewhere. Plan mode has no SSH,
Docker or server effects. Build an immutable package with `build_local.py`, then
run `smoke_local.py` with its separately scoped disposable `--execute` before
promoting that exact receipt. The immutable archive/source-offer digests, Git
commit/tree, OCI index, config digest, architecture, source files and migration set
are checked again at plan time. A green smoke is not a server readiness receipt.

Keep a private, untracked JSON target file (mode 0600) with exactly these keys:
`ssh_alias` (configured OpenSSH key alias, no user@host), `project` (the existing
Compose project), `stage_root` (pre-existing root-owned, symlink-free `/srv/...` Kat-only directory),
`password_file` (existing app-owned 0400 path), `ephemeris_dir` (existing licensed
read-only directory), `db_image` (the **inspected installed immutable DB runtime
runtime ID**, `sha256:...`, supplied under the exact approval; not a registry tag
or the source template RepoDigest), `snapshot_dir` (pre-existing independent
`/srv/...` directory owned by app UID 10001, distinct from staging and all serving
volumes), `origin`
(exact HTTPS deployment origin) and `loopback_port` (the existing loopback host
port). Also supply `release_env_file` (the existing root-protected canonical
Compose env file with exactly one unquoted `KAT_APP_IMAGE=sha256:...` assignment) and
`source_offer_file` (the existing root-protected source-download archive). Both are
fixed `/srv/...` destinations in protected policy, distinct from secrets, policy,
template, staging and snapshots; clients cannot choose other write destinations.
The server must already have the correct image-platform runtime and Compose.
For this runner, the root-owned forced-command helper and protected policy/template
must be qualified for protocol 4 under their **separately approved** adoption scope.
Reuse existing restricted SSH access when already installed; there is no fallback
to a general root key, Docker group or
interactive shell. This source does not install keys or prompt for passwords. Do not put secret values
in the target file. The target's *paths* stay private and are represented by a
hash in the plan and final sanitized receipt.

```
python3 deploy/release_pipeline.py --artifact-receipt <verified-package-receipt> --target <private-target.json> --attempt <fresh-32-lowercase-hex> --prepare-dir <new-private-preparation-directory>
```

Use a fresh cryptographically random 16-byte attempt ID for each plan (for example
`python3 -c 'import secrets; print(secrets.token_hex(16))'`); retain it for
execution. The protected server derives one absent stage as
`<stage_root>/<attempt>`; neither client nor signature can select an arbitrary path.
Preparation creates a mode-0700 directory and mode-0600 `plan.json`/`approval.json`,
without SSH, Docker, signing or generated server programs. It validates both local
artifacts against the package/commit identities; the caller supplies an already
qualified immutable package. Preparation is not smoke/restore qualification.
Check the plan's immutable identities, target, schema, both sizes, bounds and
attempt, using the applicable existing approval. The prepared approval contains
precisely this canonical, newline-terminated UTF-8 content:
`{"approved_action":"release","attempt":"<from-plan>","plan_sha256":"<from-plan>"}`.
Only the separate user-custodied approval key signs that file with native OpenSSH:
`ssh-keygen -Y sign -n kat-release-approval-v1 -f <approval-private-key> <private-approval.json>`.
The output is `<private-approval.json>.sig`. A deployment SSH key is **not** a
signer, and client-provided approval JSON alone has no authority. Keep the
signing private key off the server and out of Git; managing/generating any real
key or installing its public verifier needs separate exact-scope permission.
Execution is a separate deliberate invocation:

```
python3 deploy/release_pipeline.py --artifact-receipt <same-receipt> --target <same-target.json> --attempt <same-attempt> --execute --approval <prepared-directory/approval.json> --signature <prepared-directory/approval.json.sig> --ssh-config <existing-dedicated-OpenSSH-profile> --result <new-private-receipt.json>
```

The runner creates an exclusive durable attempt guard **before SSH**; an existing
receipt refuses replay. The explicit SSH profile selects existing constrained access;
it does not install a key or enable agent/general-root fallback. Existing dedicated
wrapper-based OpenSSH configuration remains supported when `--ssh-config` is absent.
The server verifies the exact signed plan/attempt through
its pinned OpenSSH allowed-signers identity and namespace **before every phase**;
a stale, unsigned, wrongly signed or modified plan cannot stage or upload. Each
phase advances an exclusive attempt marker; a reused attempt cannot restage,
reupload, recompose or reactivate. Its only SSH command is `kat-release-v1` with `-T`,
BatchMode and strict host-key checking. Stdin is one bounded JSON request line,
with image bytes framed only for `upload` and source bytes only for `upload_source`.
Both exact hashes and byte counts are signed; each upload refuses truncation,
trailing bytes, hash changes, symlinks and replay. Source tar accepts only bounded
regular files/directories with unique safe names, never extraction or special files.
The client prepares an unlinked,
local owned input file before SSH; `subprocess.run` bounds the **whole** child
operation even if the peer stops reading its input. No SCP, SFTP, supplied Python,
remote command string, client-selected path, environment or Compose is sent.
The installed helper stages the archive only under the **root-protected policy's**
fixed staging root at a fresh signed attempt ID and uses the root-owned protected Compose template. It
writes a stage-local DB-image-only override from the installed policy's immutable
`db_image`, without pulling/retagging/recreating the DB. A source template registry
alias may not exist after archive import; the installed native ID must exist and
match the unchanged DB container. It checks the resulting effective Compose
project **against the running app and DB** (actual state,
credential, ephemeris and DB mounts; command/origin, runtime flags, network and
loopback route), loaded immutable native image ID, and independent app-owned empty
snapshot destination before stopping **only the app**. Unsupported runtime
overrides are rejected before any serving mutation; the runner never silently
switches to fresh volumes or a different port. It invokes the existing quiesced
`deployment_backup` API against the existing DB/attachment state and independent
deletion journal/tip, verifying snapshot schema before `compose up --no-deps app`.
Before stop it also verifies the actual DB schema matches the signed package
(or the exact old schema of an explicitly admitted manual transition),
canonical selected image equals the running image, source tar safety, and retains
original env/source bytes and hashes. A separate native Compose evaluation uses
the canonical env file with NO policy KAT_* environment overrides; its full effective
configuration must match the intended configuration (old image before promotion,
new image after). Missing/conflicting persisted secret or ephemeris paths refuse
before image load/stop, rather than being masked by the helper's trusted overrides.
The default remains a **same-schema app release**, not a model/CPU qualification
workflow. Schema changes require the separate signed-plan/protected-policy lane
in [Manual transitions](MANUAL_TRANSITIONS.md); merely changing the policy's
schema number cannot authorize a migration. After quiesced backup, retain
an independent journal/tip copy outside the snapshot and ongoing serving volumes.
Promote the matching source archive and canonical image selection while the app is
stopped, preserving every unrelated env byte. Source/config replacement and Docker
activation are distinct durable phases, **not an atomic transaction**. Drift or
partial promotion halts with originals/snapshot retained; it never restores old data.
Docker `up --wait` means running here, not HTTP-ready: there is no app healthcheck.
Before definitive serving checks, an explicit local readiness boundary polls ONLY
anonymous `GET /api/session` at the fixed loopback origin/Host, with no cookies,
authorization, proxy or redirects. The 90-second monotonic deadline includes owner
checks; probes and each Docker identity query are bounded to the remaining time
and at most three seconds. Exactly the activated container/image/mount/runtime
identity is required before every probe and again on success.

Only connection refusal (ECONNREFUSED), connection reset (ECONNRESET, 104 on Linux),
HTTP response timeout and explicit 503 are transient inside this initial anonymous
local boundary. Docker loopback forwarding can accept then reset while the exact
running app has not yet bound its listener. Normal anonymous 401 ends polling;
subsequent definitive session/Host/assets/public checks never inherit reset retries.
Unexpected 200/403/404/redirect, other transport failures and any identity/ownership failure are fatal without readiness retry.
Timeout or a real verification failure retains exact-owned quarantine/unknown-state
semantics, never another activation, credential/provider call or old-data restore.
This is safe read-only readiness polling, not a retry of a deployment phase.

It hashes every image asset against both loopback and the **public HTTPS origin**,
including the manifest and icons; it checks anonymous session 401, edge wrong-Host
**421** (distinct from app loopback wrong-Host 403), Origin/fetch-site 403 and
exact HTTP→HTTPS redirect without disabling TLS certificate checks.
Full archive aggregates and attachment/host/deletion hashes must remain equal at
the LAST QUIESCED boundary immediately before app activation. Once the app reopens,
normal logins/chats/saves/deletions may legitimately change rows, files and the tip;
these are NOT compared to the old quiesced totals during public verification.
Post-exposure integrity checks instead retain stable host identity and the exact
append-only journal baseline prefix (refusing truncation/overwrite), with required
journal/tip files present; new journal appends/tip advances are allowed. Current
mutable tip consistency is not attested against a potentially concurrent writer.
A `verified` receipt still requires all serving checks, DB-container identity,
exact promoted files and those traffic-compatible integrity checks. No new edge
maintenance/service authority is introduced. Aggregate/hash evidence stays
server-local; credentials and private rows never enter controller output.
No credential re-enrollment or provider request is made.
The source archive is promoted on-host; Git publication and any public download
route remain separately owned (this tool does not create/change edge routes).
A failed public check triggers a signed `quarantine`, not activation retry. It
stops only the exact owned app after image/project/mount/runtime validation; a
mismatched or unreachable owner yields `unknown; containment unconfirmed`, never
an invented stopped/success status. No DB rollback, credential import, edge route
change, Git publication or provider request is performed. HTTP checks do not replace human usability or Android device install.
The key, protected helper/policy/template, app-owned snapshot path and a reachable
public TLS origin remain actual execution prerequisites, not established by local
tests. The authorized Kat app image executes as Kat UID 10001 and necessarily can
access Kat data and Kat credentials; **that is not authority over unrelated host
services, a general root shell, Docker commands or credential browsing**.

### Restricted server-side access contract (protocol-4 source; adoption required)

`release_access.py` is a **root-owned installed** forced-command entry point; it
loads `/etc/kat-release/policy.json` (see generic
`release_access_policy.example.json`) and a root-owned Compose template, checking
all ancestor ownership/modes. The protected target fixes the exact Kat project, root-owned stage root,
snapshot destination, secret/ephemeris references, immutable installed DB image,
origin and loopback port. The policy explicitly fixes contract 4, the existing schema, maximum image archive
size (at most 2 GiB) and source archive size (at most 128 MiB), plus one root-owned pinned OpenSSH `allowed-signers` entry, exact approval
principal and `kat-release-approval-v1` namespace. The stage is derived from the
signed fresh 32-hex attempt, not edited in policy for each release. Each approval
signature authenticates the canonical action `release`, attempt ID and exact plan
hash, which binds commit/tree, OCI image/config, archive/source digests and exact
image AND source byte counts (also limited by the stable protected maximum), schema,
target scope, protected helper/template hashes and phase list. The server recomputes
that hash and independently verifies the signature before any effect. Its target fields must match the
local target file byte-for-byte in the plan hash; the SSH alias is merely a local
connection name, never a server command. The protected template SHA and the installed helper/phase-code SHA must equal
the approved plan's pinned source bytes, or the forced command refuses before
loading/stopping. Protocol contract 4 deliberately rejects contract-1/2/3 plans and old policy shape;
no unsigned downgrade or old-plan translation exists.
Policy, verifier key and code must be root-owned and not writable through group,
others or any symlink ancestor. Only an independently approved signed plan can
advance a release; routine new Kat versions and attempts need no privileged policy
edit while their fixed Kat resource scope, installed helper/template bytes and
schema remain compatible. A helper/template or target-scope change is **not** a
routine release: it needs separate protected installation review. The stage root
must already exist root-owned; the attempt stage is created exclusively and upload
refuses replay/symlink/truncated/extra bytes. A native file lock serializes each
request; a durable `active-attempt` fence prevents different signed attempts racing
between SSH processes. Only successfully verified `complete` retires that fence;
a halt retains it for explicit recovery/reconciliation, not automatic retry. Signature verification is native
`ssh-keygen -Y verify`, not client assertion, custom crypto or an SSH-agent
side channel. A signed approval lets its holder deploy approved Kat code with
access to Kat data and Kat credentials, never unrelated host services.

For a *future separately approved* installation, use native OpenSSH
`authorized_keys` key options of this exact shape, with a separately generated
public key replacing the placeholder and executable root-owned helper files:

```
restrict,command="/usr/bin/python3 -I /usr/local/libexec/kat-release/deploy/release_access.py" ssh-ed25519 <APP-RELEASE-PUBLIC-KEY> kat-app-release
```

Keep the full helper tree `/usr/local/libexec/kat-release/deploy/`,
`/etc/kat-release/` including the one-entry `allowed-signers` file, and the fixed
Kat stage root root-owned, non-writable to the key holder and symlink-free. Pin
the exact SHA-256 of that public verifier file in the policy; never install the
signing private key on the server. Under Python `-I`,
the helper checks the fixed adjacent phase file and loads it explicitly; it never
uses CWD or client PYTHONPATH. `restrict` denies PTY,
agent/X11/port forwarding and user rc; the forced command rejects every original
SSH command except `kat-release-v1`, including shell, Python, SCP and SFTP requests.
The installed code runs under root solely to perform its **fixed** Kat app lifecycle
through Docker; it is not permission to grant a `docker` group, unrestricted sudo,
arbitrary helper subcommands or a root login. Do not enable agent-/port-forwarding,
SFTP, PermitUserEnvironment or host/user-specific overrides that bypass the forced
command. The private key, root-owned policy/template and SSH configuration are
separate installation decisions, not shipped or created here. No keys, secrets or
private server paths belong in Git or in receipts.

On timeout, partial upload, backup failure, or ambiguous `up`, **halt**: the
private stage's `phase.json`, `previous-image` and `previous-container` identify
the last phase and prior runtime. Preflight failures leave the old app running.
A confirmed race before the backup command starts restarts **only the same old
stopped container** and records `recovered_old_app; release not activated`, without
requiring a second approval for that known-safe action. If a backup command has
started or activation is ambiguous, do not auto-restart or blindly replay. Inspect
app/DB/deletion identities and snapshot manifest. For an independently verified
failed new app with compatible DB, prepare a separately approved app-only recovery
using the retained previous image and unchanged volumes; reverify serving and
unchanged deletion authority. **Never restore an older DB or journal for an app
rollback.** If previous app/schema compatibility is unknown, hold serving for
investigation instead of guessing. Snapshot
retention/off-host backup, true remote restore rehearsal and key management are
not automated by this runner. Leave the old maintenance route alone.

### Receipts, timing and recovery inspection

Receipts distinguish current phase, failed phase, server-reported containment and
unconfirmed serving state. Per-phase elapsed seconds cover preparation of framed
uploads and execution, not human signing wait; no runtime performance guarantee is
implied. Preparation/build qualification and signing wait are outside execution.
Image loading has its own bounded preflight budget rather than an outer SSH timeout
shorter than Docker load. Activation includes the final quiesced scan and has a
bounded 600-second controller budget; this is a failure bound, not an expected
deployment duration. Local serving verification has a separate 900-second outer SSH
budget to cover the 90-second readiness window plus bounded owner queries, asset
listing and up to 64 definitive asset requests with eight-second HTTP timeouts. Healthy readiness has
no unconditional delay. Readiness attempts/elapsed seconds are recorded in the
controller receipt when reported by the helper. Definitive Host/Origin/assets and
public TLS checks are never folded into startup polling or retried as readiness;
no activation/credential/provider/mutating network retry is hidden in the runner.

On a halt, preserve `phase.json`, `failure.json`, `files.before.json`,
`files.promoted.json` when present, `env.before`, `source.before.tar`, previous
container/image files, snapshot, retained authority and the controller receipt.
Some files may be absent if their phase never completed. Do not delete the fence,
reset phase markers, reuse an attempt or re-run activation to make a status green.
Reconcile actual canonical env/source hashes, exact owned serving identity and
schema/deletion authority first. Any later compatible app-only recovery must
explicitly select coherent source/config/image without restoring old DB/journal.
If containment or owner identity is unknown, inspect before intervening.

The old copied administrative workflow is **not retired by source completion**.
Retire it only after independent review, separately authorized helper/policy adoption,
a user-local signature and one successful real end-to-end signed release receipt.
Do not use the installation-verification approval for an old version as a new
release approval. No signing private key belongs on the server or runner.

Offline focused checks (no SSH server/provider/user fixture):
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s deploy -p 'test_*.py'`.
Use the shared local execution lock where required by the checkout. These checks
include real OpenSSH ephemeral signing and real Compose config, but Docker lifecycle
and public HTTP are synthetic; they do not prove target installation or full live
release. The fixed state/authority scripts also run on newly owned synthetic files.
`deploy.test_release_traffic` additionally exercises a real synthetic HTTP login
and PostgreSQL session write during verification, but runs ONLY with an explicit
fresh owned isolated fixture. Readiness regressions exercise delayed/never-ready,
permanent identity/authority/asset failures, exact-owned quarantine and one-time
activation under a controlled clock. Without an isolated DB the one HTTP/PG
integration test is skipped;
never let it fall back to the user's database. Fixture setup/cleanup can reuse
this checkout's existing isolated-validation helpers; no real provider is involved.

## Accounts and selected model

The Kat username/password is separate from ChatGPT. Signing in at chatgpt.com,
including its **Manage usage** page, does not register Kat. The production web
app deliberately offers no browser OAuth/signup or credential-upload form: OpenAI's
OSS callback must be HTTP `127.0.0.1` on the computer running the browser, not a
made-up HTTPS callback to the server. This is a **future, separately approved
personal-credential handoff**, not a command to run against the current host.

1. On a **dedicated computer and fresh, separate Kat source checkout**, install
   the Python/Swiss dependencies as documented in [`m2/README.md`](../m2/README.md)
   and run `npm ci --prefix web`. Choose an unused loopback port other than 8765.
   Confirm that checkout has no `.local/m2-pg-name` or `.local/m2-pg.env`.
   Run `m2/start_local_postgres.sh` (creates only this new checkout's owned
   fixture), then build into an owned unserved directory with
   `npm --prefix web run build -- --outDir "$PWD/.local/connection-dist"`.
   Run `.venv-swiss/bin/python -m m2.web_server enroll --port <loopback-port>
   --state-directory "$PWD/.local" --served-dist "$PWD/.local/connection-dist"`
   to create the matching Kat username locally. This does **not** copy the
   server's Kat password or account; use the same username and authenticate
   independently on each side.
2. Start only that local checkout with `.venv-swiss/bin/python -m m2.web_server
   serve --port <loopback-port> --enable-siwc --state-directory "$PWD/.local"
   --served-dist "$PWD/.local/connection-dist"`, open its exact
   `http://127.0.0.1:<loopback-port>/` address on the same computer, log in to
   the new local Kat account and choose **Connect ChatGPT plan** in Settings.
   The supported flow uses fresh state/nonce/PKCE and the loopback callback; grant
   separate plan-use permission. An identity-only result cannot enable chat.
   Neither a phone's Manage usage link nor its normal ChatGPT website login
   completes this local callback. Stop the local server before export.
3. With both Store owners stopped and only under approved private credential
   access, run `python -m m2.deployment_credentials export-local
   --state-directory <absolute-dedicated-local-state>
   --handoff-file <absolute-new-private-encrypted-file>` on the dedicated
   computer. Authenticate that local Kat username; the encryption passphrase is
   prompted and must not be in argv or the transfer channel. Securely transfer
   the encrypted file (for example via SSH) to a private 0600 target file, then
   run `python -m m2.deployment_credentials import-deployment
   --state-directory <absolute-server-state> --db-password-file <absolute-private-file>
   --handoff-file <absolute-transferred-file>` on the stopped personal server.
   Authenticate the **existing server Kat account with the same username** and
   enter the passphrase. Import refuses any prior destination registration,
   retains the server's own stable host ID, and clears the copied access token.
   Start the server under its separately approved scope; Settings may show
   **refresh required** until the server first requests available models or
   chat, when it attempts its own token refresh. A saved grant is not proof of
   actual eligibility or that a provider request will succeed. Never retry an
   ambiguous transfer by overwriting a record; inspect status first. Keep the
   encrypted artifact under approved custody and remove it only within that
   scope. The source refresh token remains a risk until separately handled.

If the server confirms a terminal invalid-refresh or you explicitly disconnect,
its selected registration remains for identity/recovery, but a new import still
refuses overwrite. After a new authorized **local** sign-in and encrypted export,
stop the server and run `python -m m2.deployment_credentials
forget-disconnected-deployment --state-directory <absolute-server-state>
--db-password-file <absolute-private-file>`; authenticate the server Kat owner
and type `FORGET`. It refuses a renewable session or multiple registrations,
removes only the one already-disconnected owner's mapping, and preserves the
server host ID. Then import the new encrypted file as above. A temporary network
or model-catalog failure is **not** evidence to forget credentials: retry later
without clearing them. If `invalid_client` occurs, correct the integration rather
than wiping a registration. Remote revocation can be unconfirmed; ChatGPT settings
can manage access but cannot create Kat's loopback callback. OpenAI currently
cannot provide host-specific usage attribution/revocation for transferred
sessions; avoid reusing an existing laptop registration. No paid API fallback,
ChatGPT-history import, or automatic model request is part of the handoff.
Manual charts remain usable without chat.

Current first-party contracts: [OSS registration and loopback callback](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[self-hosted VM handoff](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms),
[refresh/disconnect](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
and [recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery).
These describe an eligible personal OSS route; they do not authorize a provider
sign-in, production credential handling or verification under this source request.

## Recovery and release boundary

`python -m m2.deployment_backup backup --state-directory <stopped-source-state>
--snapshot <new-private-dir-outside-state> --db-password-file <private-file>`
requires the serving Store to be stopped. It acquires the exclusive Store advisory
lock on a read-only connection and checks the exact current schema and existing
independent journal/tip **before** any snapshot. It never starts a Store or
migrates the source while backing up. It snapshots the DB
(including inline reference originals/passages), all referenced attachment and
person-file blobs, and the journal identity/prefix, but **not** the deletion
journal/tip themselves. Verify-restore takes a disposable **empty separate DB**
and absent file directory, explicit independent newer deletion journal and tip,
and `--db-name <disposable-name>`; it refuses a diverged journal, hash mismatch,
old schema, or nonempty DB before restoring. It reconciles deletions and verifies
blob/reference content before returning; a partial target is quarantined and
must never be served or retried in place. Do not restore into a production DB.
The deletion volume and its independently retained newer tip need separate
protection from the DB snapshot. A single host volume is not an off-server backup.
An approved off-server encrypted destination, tested retention and restore
procedure are prerequisites before treating personal data as durably protected.
No backup export/transfer or server restore is authorized by this document.

Later preflight (requires exact app-install scope): inspect saved image ID, actual
CPU architecture and dependencies, secret/volume permissions and empty state,
port availability, Caddy origin/Host forwarding, HTTPS/tls routing, isolated
account/login, deletion-journal independence, and one disposable restore. Keep
maintenance visible until a separate route-activation decision. Rollback the
route to maintenance without deleting state or rolling back the journal; never
restore an older DB without a newer independently retained journal. Separate
permissions are needed for provider credential enrollment/handoff, package or
source publication, off-server backup retention and a single real-model check.
Local fixture tests and screenshots do not prove these host prerequisites.
