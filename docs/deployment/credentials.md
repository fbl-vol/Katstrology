# Connect a personal ChatGPT registration

[Documentation index](../README.md) · [Provider behavior](../provider-and-context.md)

Kat login and ChatGPT registration are separate. Signing in at chatgpt.com or
opening Manage usage does not register Kat. Deployment intentionally has no
browser OAuth/signup or credential-upload form: the supported OSS callback is
HTTP `127.0.0.1` on the computer running the browser, not an invented server HTTPS
callback. Manual charts remain usable without chat.

This guide describes credential handling, not permission to perform it. Real
local sign-in, private export/import, deployment activation and a provider check
require their applicable scope. Never use a user's existing fixture as a test.

## Establish a dedicated local registration

1. Use a dedicated computer/fresh checkout and the
   [backend development](../backend-development.md) dependencies. Choose an unused
   loopback port other than a running app's port. Confirm there is no pre-existing
   `.local/m2-pg-name` or `.local/m2-pg.env`; then `m2/start_local_postgres.sh` creates
   only the fresh checkout's fixture. Build an owned unserved output:

   ```sh
   npm ci --prefix web
   npm --prefix web run build -- --outDir "$PWD/.local/connection-dist"
   .venv-swiss/bin/python -m m2.web_server enroll --port <unused-port> --state-directory "$PWD/.local" --served-dist "$PWD/.local/connection-dist"
   ```

   Create the matching Kat username locally; this does not copy the server
   password/account. Each side authenticates independently.
2. Start only that local instance with `m2.web_server serve`, the same explicit
   port/state/build paths and `--enable-siwc`. Open the exact loopback address on
   the same computer, sign into Kat and choose **Connect ChatGPT plan** in Settings.
   The flow uses fresh state/nonce/PKCE. Explicit plan-use permission is separate:
   an identity-only result cannot enable chat. A phone's ChatGPT login or Manage
   usage link does not complete this callback. Stop the local server before export.

## Export and import while both Store owners are stopped

On the dedicated computer:

```sh
python -m m2.deployment_credentials export-local --state-directory <absolute-local-state> --handoff-file <absolute-new-private-encrypted-file>
```

Authenticate the local Kat username. The encryption passphrase is prompted; do
not put it in argv or send it alongside the artifact. Transfer the encrypted file
through the approved private channel to a 0600 file. On the stopped deployment:

```sh
python -m m2.deployment_credentials import-deployment --state-directory <absolute-server-state> --db-password-file <absolute-private-file> --handoff-file <absolute-transferred-file>
```

Authenticate the existing server account with the same username and enter the
passphrase. Import refuses prior destination registration, retains the server's
stable host ID and clears the copied access token. Activation is separate.
Settings may show **refresh required** until model listing or chat attempts the
server's token refresh. A saved grant does not prove eligibility or successful
provider use; listing models is itself provider traffic.

Never resolve an ambiguous transfer by overwriting a registration. Inspect status
first. Retain/remove the encrypted artifact only within its custody scope. The
source refresh token remains a separate risk; transferred sessions do not provide
Kat with reliable host-specific usage attribution/revocation. Do not reuse an
existing laptop registration merely for convenience.

## Replace only a confirmed disconnected registration

After terminal invalid-refresh or explicit disconnect, Kat retains identity for
recovery and still refuses import overwrite. Once a new local sign-in/export is
authorized, stop the deployment and run:

```sh
python -m m2.deployment_credentials forget-disconnected-deployment --state-directory <absolute-server-state> --db-password-file <absolute-private-file>
```

Authenticate and type `FORGET`. It refuses a renewable session or multiple
registrations, removes only the disconnected owner's mapping and preserves host
identity. Then import the new encrypted artifact. A temporary network/catalog
failure is not grounds to forget credentials; `invalid_client` calls for correcting
the integration, not wiping registration. Remote revocation may be unconfirmed.
No paid API fallback, history import or automatic model request is part of handoff.

## Provider references

These are upstream contract references, not evidence that a particular account is
eligible or a deployed integration has been checked:

- [OSS registration and callback](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Self-hosted VM handoff](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [Refresh and disconnect](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [Recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery)
