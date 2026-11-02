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
writable by their intended owners without publishing them. For a **local-only**
packaged startup regression, `python -m deploy.smoke_local --receipt
<ignored-exact-tip-receipt> --execute` creates a uniquely named disposable Compose
project, dynamic loopback host port and synthetic DB secret/empty ephemeris mount.
It checks effective mounts, image-served assets, unauthenticated Host behavior,
empty schema and restart, then removes only that project's containers and volumes.
The default without `--execute` is a plan. This is not host activation.

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
