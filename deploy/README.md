# Personal production candidate (source and local fixture preparation only)

This directory is not an activation instruction or approval. The existing public
maintenance page remains served until a separately scoped app release. Do not run
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
produces an ignored `.local/fresh-production/package/<tip>/` containing an amd64
Docker image archive, `git archive` corresponding source offer and a receipt with
SHA, tree, OS/arch, inspected image config ID and both file SHA-256 digests. It
compares the saved archive manifest/config with the inspected ID; do not treat a
Docker archive index digest or a tar hash as the runtime image ID. This is a local
artifact, not an upload, registry publication or release. The Node, Python and
PostgreSQL bases are pinned by digest; browser dependencies use `npm ci` and the
Python application pins direct versions. **Transitive Python wheel hashes are not
locked, and a rebuild is not guaranteed byte-identical.** Audit resolution and
licenses before promotion; refresh pinned bases through a separate review. See
`THIRD-PARTY-NOTICES.md` and `docs/PUBLICATION.md`. No ephemeris, model cache,
real credentials, account state or journal is in the image or source offer.
Check the actual old server CPU, base pulls and archive config ID in its separately
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
writable by their intended owners without publishing them.

## Accounts and selected model

After explicit approval and with the sole Store process stopped, `m2.web_server
enroll --deployment-origin ... --db-password-file <absolute-file>
--state-directory <absolute-private-dir> --served-dist <absolute-build>` prompts
for a Kat username/password offline; there is no signup API. For the optional
ChatGPT plan, first create a **new dedicated local registration** in the supported
127.0.0.1 OAuth flow using a synthetic-free, separately approved personal
session. Stop both source/target owners, then use
`python -m m2.deployment_credentials export-local --state-directory <owned-local>
--handoff-file <absolute-new-private-file>` and
`python -m m2.deployment_credentials import-deployment --state-directory
<fresh-deployment-state> --handoff-file <approved-securely-transferred-file>
--db-password-file <absolute-private-file>`. Both sides require the same
username and authenticated Kat account password; the passphrase is prompted, not
passed as an argument. Transfer the encrypted file through a separately approved
secure channel, keep the passphrase separate, verify file custody and remove the
transfer artifact only under that scope. Import refuses overwrite, preserves the
server's own `ext_agent_host_id` and clears the copied access token so the **first
use on the server** must refresh. It does not call the provider or prove live plan
eligibility. The source refresh token remains a risk until separately handled.
OpenAI's OSS self-hosted VM guidance notes that host-specific attribution and
revocation of transferred sessions are not yet available; refresh/revocation may
fail. Never reuse an existing laptop's registration by default. Local
login/settings are not a promise of provider access; manual charts work while
chat is unavailable.

## Recovery and release boundary

`python -m m2.deployment_backup backup --state-directory <stopped-source-state>
--snapshot <new-private-dir-outside-state> --db-password-file <private-file>`
requires sole Store ownership and current migrated schema. It snapshots the DB
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
