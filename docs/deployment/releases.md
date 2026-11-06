# Release an existing instance and inspect failures

[Documentation index](../README.md) · [Packaging](packaging.md) · [Automation](automation.md)

The protocol-4 manual runner updates a previously installed instance of the exact
Compose project. It does not provision a host, install trust, change routes or
enroll credentials. A protocol-3 helper cannot run it. Helper/template/policy or
resource-scope changes require their own protected installation; routine app
releases preserve those installed bytes and keys. Documentation describes the
contract, not proof of the current host's installation or permission to release.

## Prepare a same-schema plan

First qualify the exact immutable package. Keep a private mode-0600 target JSON
with these fields; paths are private prerequisites, not values to publish:

| Field | Required existing resource |
| --- | --- |
| `ssh_alias` | Configured restricted OpenSSH alias, not `user@host` |
| `project` | Installed Compose project |
| `stage_root` | Root-owned symlink-free Kat-only `/srv/...` directory |
| `password_file` | App-owned 0400 DB password file |
| `ephemeris_dir` | Licensed read-only Swiss directory |
| `db_image` | Inspected installed immutable native DB ID (`sha256:...`), not template tag/RepoDigest |
| `snapshot_dir` | Independent app-UID-10001 directory, outside staging and serving volumes |
| `origin`, `loopback_port` | Exact installed HTTPS origin and loopback host port |
| `release_env_file` | Root-protected canonical env file with one unquoted `KAT_APP_IMAGE=sha256:...` assignment |
| `source_offer_file` | Root-protected matching source-download archive |

The last two fixed policy destinations cannot alias secrets, policy, template,
staging or snapshots. No secret values belong in this file. Target paths become
a scope hash in sanitized output. Use installed constrained SSH access; there is
no general-root, Docker-group, password or agent fallback.

```sh
python3 -m deploy.release_pipeline --artifact-receipt <qualified-receipt> --target <private-target.json> --attempt <fresh-32-lowercase-hex> --prepare-dir <new-private-directory>
```

Generate a fresh cryptographically random 16-byte attempt, for example with
`python3 -c 'import secrets; print(secrets.token_hex(16))'`. Preparation creates a
0700 directory and 0600 plan/approval files without SSH, Docker or signing. It
revalidates archives, source, migrations, commit/tree, image identity, platform,
sizes and scope; it does not replace smoke or restore qualification.

Review the identities, schema, bounds, target and attempt. The canonical approval
is newline-terminated UTF-8:

```json
{"approved_action":"release","attempt":"<from-plan>","plan_sha256":"<from-plan>"}
```

The separate user-custodied signing key signs that exact file:

```sh
ssh-keygen -Y sign -n kat-release-approval-v1 -f <approval-private-key> <approval.json>
```

The deployment SSH key is not the signer. Keep signing keys off the server,
runner and Git. Key creation/access or verifier installation is a separate scope.
Once the exact release is approved, execution is deliberate:

```sh
python3 -m deploy.release_pipeline --artifact-receipt <same-receipt> --target <same-target.json> --attempt <same-attempt> --execute --approval <approval.json> --signature <approval.json.sig> --ssh-config <dedicated-profile> --result <new-private-receipt.json>
```

The existing dedicated wrapper-based SSH configuration is also supported when
`--ssh-config` is absent. Neither route installs access. The client creates an
exclusive durable guard before SSH; existing attempts/receipts refuse replay.

## What the installed gateway enforces

`deploy/release_access.py` loads root-owned `/etc/kat-release/policy.json`, a
protected Compose template and pinned helper bytes, validating ancestor ownership
and symlinks. Policy fixes contract 4, schema, target, helper/template hashes,
archive bounds (at most 2 GiB image/128 MiB source), verifier hash, one allowed
signer/principal and `kat-release-approval-v1`. Native OpenSSH verification checks
the exact plan/attempt before every phase. Contract 1/2/3 shapes do not downgrade.

The separately installed public transport entry has this restricted shape:

```text
restrict,command="/usr/bin/python3 -I /usr/local/libexec/kat-release/deploy/release_access.py" ssh-ed25519 <APP-RELEASE-PUBLIC-KEY> kat-app-release
```

Only `kat-release-v1` is accepted, with strict host-key checking, BatchMode and
no PTY. There is no shell, supplied Python, SCP/SFTP, forwarding, arbitrary path,
environment or client Compose. The isolated helper loads its adjacent fixed phase
file, not CWD/PYTHONPATH. Root privilege exists solely for the fixed Kat lifecycle;
it is not authority over unrelated services. Approved Kat application code does
necessarily have access to its own data and credentials.

A native lock serializes requests; a durable active-attempt fence prevents overlap
across SSH processes. Stages are exclusively derived from fresh signed attempts.
Image/source uploads enforce signed lengths/hashes, no extra/truncated bytes,
symlinks or replay; source tar admits only bounded unique safe regular paths.
Only verified completion retires the fence.

The phase engine:

1. Checks loaded native image identity and the complete effective runtime against
   the running app/DB: mounts, command/origin, flags, network and port. A DB-only
   override uses the installed native DB ID without pulling/recreating the DB.
   Canonical-env Compose is independently evaluated without policy `KAT_*`
   overrides so missing/conflicting persisted settings cannot be hidden.
2. Verifies schema/migration history, selected/running image, safe source tar and
   independent empty snapshot destination; retains original env/source hashes and
   bytes before stopping only the owned app. Default releases are same-schema;
   [explicit transitions](manual-transitions.md) are a different admitted lane.
3. Creates a quiesced native backup with independent deletion identity/tip, retains
   newer authority separately and checks the final quiesced preservation baseline.
4. Promotes source and image selection while stopped, preserving unrelated env
   bytes, then activates via `compose up --no-deps app`. File promotion and Docker
   activation are separate durable phases, **not an atomic transaction**.
5. Verifies serving identity, assets, session/Host/Origin behavior and public TLS.
   No credential enrollment or provider request occurs.

## Readiness is not activation retry

Docker `up --wait` is only running here: the app has no healthcheck. Anonymous
`GET /api/session` polling uses the fixed loopback origin/Host, no cookies,
authorization, redirects or proxy. The 90-second monotonic deadline includes
identity checks; each probe/query is bounded by remaining time and at most three
seconds. The exact activated container/image/mount/runtime is checked before every
probe and on success.

Only refusal, reset, response timeout and explicit 503 are transient within that
boundary. Anonymous 401 ends polling. Unexpected 200/403/404/redirect, other
transport errors or ownership failures are fatal. Definitive checks do not inherit
those retries. Image loading has its own budget; activation is bounded at 600
seconds and local serving verification at 900 seconds. These are failure bounds,
not expected deployment duration. Human signing wait is outside execution timing.

Every image asset, including manifest/icons, must match loopback and public HTTPS.
Checks require anonymous session 401, app wrong-Host 403, edge wrong-Host 421,
Origin/fetch-site 403 and exact HTTP→HTTPS redirect with certificate validation.
The public route is not created by this tool.

After exposure, normal activity may legitimately change rows, files and journal
tip. Do not compare those mutable totals to the old quiesced baseline. Verification
instead retains host identity and exact append-only journal prefix with required
journal/tip files; it does not attest a concurrently changing tip. A verified
receipt still requires all serving checks, unchanged DB-container identity and
exact promoted files. Private aggregates stay server-local.

## On a halt

Preserve the controller receipt, `phase.json`, `failure.json`, `files.before.json`,
`files.promoted.json`, `env.before`, `source.before.tar`, previous-image/container,
snapshot and retained authority when present. Inspect the actual phase, failed
phase and confirmed versus unknown containment. Do not clear the fence, rename or
reuse an attempt, rerun activation, or mark ambiguous output successful.

Preflight failures leave the old app running. A proven race before backup begins
can restart only the same old stopped container, recorded as recovered—not new
release success. Once backup starts or activation is ambiguous, halt rather than
blindly restarting. Failed public verification invokes signed quarantine only
for the exact owned app. Mismatched/unreachable ownership is `unknown; containment
unconfirmed`, not an invented stopped status.

Reconcile canonical env/source, native serving identity, schema and deletion
authority. A separately instructed compatible app-only recovery must select a
coherent image/source/config and preserve data. **Never restore an old DB or
journal to roll back application code.** Unknown schema compatibility means hold
and investigate. See [archive recovery](../archive-and-recovery.md). Off-server
retention, restore rehearsal and key management are not automated by this runner.

## Local evidence

Use [isolated validation](../testing.md) with `tests.deploy.test_release_access`,
`test_release_pipeline`, `test_release_promotion`, `test_release_readiness` and
`test_release_traffic`. These include ephemeral native signatures, Compose config
and owned synthetic HTTP/PostgreSQL activity. They do not establish installed
root protection, SSH/TLS routing, hosted identity or live release acceptance.
