# Build and qualify an immutable package

[Documentation index](../README.md) · [Release operation](releases.md)

## Inputs and identity

Run from a clean committed public checkout. Use the pinned public BGE CPU snapshot
in `.local/models/fastembed` or an explicit `--public-model-cache` containing the
identical verified revision. Preparation is documented in
[backend development](../backend-development.md); downloads/installations are not
part of a source-only check.

```sh
.venv-swiss/bin/python -m deploy.build_local
```

The builder stages only five size/SHA-256-checked model files, never the whole
cache, and sets modes only on newly staged copies. Runtime repeats verification
once per embedder and binds FastEmbed to the verified local snapshot. The manifest
and notice live at `m2/references/public_model.py` and `m2/public-model-LICENSE.txt`. Offline
CPU loading runs as UID 10001; final model checks are read-only/network-none.
Private references, ephemeris, credentials, account state and journals are not
image or source-offer inputs. The model binary is in the image, not the source tar.

The ignored `.local/fresh-production/package/<tip>/` output contains the amd64
Docker archive, `git archive` corresponding-source offer and receipt. The receipt
binds commit/tree, platform, saved OCI index/config digests and both file hashes.
Classic Docker addresses the config; the containerd store addresses the saved
index. Native preflight freezes the store-specific identity and checks it after
load—never substitute a tar hash, mutable tag or guessed image ID. Preserve prior
immutable packages rather than overwriting them.

Node, Python and PostgreSQL bases are digest-pinned; browser dependencies use
`npm ci`, and Python direct versions are pinned. Transitive Python wheel hashes
are **not locked**: this is qualification of one artifact, not byte-identical
rebuild assurance. Review dependency resolution/licensing and refresh bases as a
separate change. See [third-party notices](../../THIRD-PARTY-NOTICES.md) and
[publication boundary](../PUBLICATION.md).

## Qualify the actual archive locally

Under the checkout's execution lock and synthetic-resource rules:

```sh
.venv-swiss/bin/python -m deploy.smoke_local --receipt <exact-tip-receipt>
.venv-swiss/bin/python -m deploy.smoke_local --receipt <exact-tip-receipt> --execute
```

The first invocation is a plan. Execution uses a uniquely owned disposable Compose
project, dynamic loopback port, synthetic secret and empty ephemeris mount. Native
qualification loads the actual archive and checks effective mounts, image-served
assets, Host admission, fresh schema, startup/restart, drain, backup/independent
ledger restore, additive migration and cleanup. It removes only that project's
containers/volumes. Do not substitute a running app, private database or served
`web/dist`; retain the exact receipt and reported limitations. Source/dependency
changes after qualification require new exact-tip evidence.

## Runtime configuration

`deploy/compose.yaml` is a template, not a command against an existing host. It
keeps PostgreSQL unpublished, binds the app to host loopback `127.0.0.1:28765`, and
listens inside the container on 8765 with untrusted proxy headers disabled. Native
HTTPS termination, routing and port availability are host prerequisites, not
created by local packaging. `KAT_APP_IMAGE` is an inspected immutable native image
ID. `KAT_EPHE_DIR` supplies licensed Swiss files read-only.

The DB password is a separate private file, owned by UID 10001 and 0400 for the
app bind mount; PostgreSQL receives its own Compose file secret. Never put secret
values in argv, environment, image, receipt or browser. Verify actual mounted
permissions—Compose's declared mode is not sufficient. State, independent deletion,
credential and DB volumes must be writable only by their intended owners.

Deployment uses an explicit HTTPS `--deployment-origin`, private DB/state/build
paths and configuration validation before Store opening. Host/Origin matching is
exact, mutations require Origin, cookies are strict/Secure on HTTPS, CSRF remains
enforced and proxy authority headers are ignored. Only the trusted reverse proxy
should reach the loopback port. Browser signup/OAuth registration and arbitrary
credential upload are deliberately absent in deployment mode.

An installation needs its own host/image/CPU, permission, account, route/TLS and
restore checks. A green local smoke is neither an installation nor a server
readiness receipt. Do not change shared routes, volumes, credentials or services
without the corresponding instruction.
