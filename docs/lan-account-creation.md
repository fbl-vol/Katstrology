# LAN-only account creation

The login screen keeps ordinary sign-in available from any permitted connection.
**Create account** is secondary and disabled until the server positively verifies
its private edge transport and an explicitly configured home subnet. Checking,
unconfigured, public and failed verification states never enable creation.

Use a username of 1–80 ASCII letters, numbers, underscores or hyphens, and a
password of at least 12 characters (the existing account rules). Confirm the
password. Success returns to ordinary sign-in with the username retained; it
does not issue a session. A new account has no other owner's people, context,
conversations, sessions or ChatGPT connection. CLI enrollment is unchanged.

If creation was not confirmed, including a duplicate username or lost response,
try ordinary sign-in with that same username/password before creating another
account. There is no automatic retry or account listing. Passwords are not put in
URLs, browser storage, application logs or the availability response. The only
persistent account credential is the existing Argon2 hash. Pending creation
locks the form and Back action. Uncertain results also lock the submitted fields
so Back to sign in retains the attempted username rather than a newly edited one.

## Default is off

Deploying the source alone **does not enable signup**. The existing TCP listener
always denies creation, including loopback/private peers and forged headers.
`--signup-policy` is accepted only for explicit deployment `serve` mode. Without
it `GET /api/signup` returns `available: false`; POST independently returns403
before parsing credentials, queueing Store work, hashing or writing an account.

When explicitly configured, the app binds a second Unix-domain listener. Admission
requires its actual ASGI local socket path, no TCP client tuple, exactly one
`X-Kat-Signup-Client` signal and no conventional forwarding headers. Uvicorn keeps
`proxy_headers=False`; an HTTP header cannot supply the transport identity.
The edge must overwrite that signal from its **connection peer**, remove
`Forwarded`, all `X-Forwarded-*` and `X-Real-IP` headers, and preserve the existing
canonical Host. Exact Host/Origin and cross-site mutation checks still apply.
Neither JavaScript availability nor a previous successful check authorizes POST.

The policy is a small root-owned regular JSON file, not group/world writable:

- `socket`: absolute private Unix path;
- `networks`: explicitly verified home CIDRs (1–16, IPv4 prefix at least16,
  IPv6 at least48; not a blanket private/Tailscale allowlist);
- `excluded_clients`: 1–16 router, NAT, proxy and other intermediary addresses
  that must **not** count as an original home visitor.

IPv4-mapped clients normalize to IPv4. Missing, duplicate, malformed, scoped,
loopback, link-local, unspecified and multicast addresses are denied, as are
configured exclusions and subnet boundary addresses. Explicit IPv6 home prefixes
can be used, but an unknown/changing prefix cannot enable creation. The policy
must be reloaded through a separately authorized service restart after changes.

Only the app UID and a deliberately restricted edge/app group may access the
socket directory: app-owned, primary app GID, mode0750 (or0700 for a same-UID
edge); socket0660. No group-write access to the directory. The process creates no
directory, group, permission grant or mount. It binds TCP first before replacing
an app-owned stale socket and cleans up only its own socket inode. Existing
normal port binding and exclusive Store ownership prevent a competing instance.

## Proportional resource bound

After early network and exact-origin checks, JSON is bounded to8192 bytes and
credentials are validated. At most one registration job is pending, and a single
global ten-second admission interval covers all trusted clients, including
duplicates. Excess attempts return429/`Retry-After: 10` without queueing hashes.
A client disconnect does not free the slot while its worker still runs. The
existing single Store executor and release-admission lifecycle remain in force.
Duplicate lookup happens before hashing, and a unique-constraint race cannot
overwrite an existing account. This is small-LAN abuse protection, not protection
against a compromised trusted edge, app UID or a distributed network attack.

## Prepared proposals; installation remains separate

`deploy/proposals/lan-signup.caddy`, `lan-signup.compose.yaml` and
`lan-signup-policy.example.json` are **inert source proposals**, not included by
the installed/native deployment. The example uses documentation-only networks,
not guessed home topology. No helper, installed Compose, policy or service has
been changed. Native immutable-config/digest, exact-tip and trust-enrollment gates
must not be bypassed to apply an overlay.

Before separately approving enablement, the following evidence/configuration is
still required:

1. Actual immediate edge topology and **original connection-peer** observations
   for home IPv4/IPv6, public internet, router hairpin/NAT and any tunnels/proxies.
   If public traffic is source-NATed to an address indistinguishable from home
   traffic, do not enable this policy; correct/separate the path first. Explicitly
   exclude all intermediary addresses. A denied hairpin request is preferable to
   falsely admitting the router. Synthetic tests cannot establish these facts.
2. Confirmed home CIDRs, all intermediary exclusions, and edge process UID/GID;
   pre-provisioned socket directory and read-only root policy mount. The current
   app UID/GID is10001:10001; granting edge access to that group requires checking
   its other host access, or choosing a dedicated primary app group and reviewing
   resulting file-access compatibility. No broad group membership by default.
3. Native Caddy adaptation/validation for the exact installed version and site,
   proving overwrite/removal (including duplicate incoming signals), preserved
   canonical Host, and that only `/api/signup` uses this private upstream. The
   proposal is a fragment, not a replacement site file. Existing sign-in and all
   other paths stay on their current TCP upstream. An unavailable socket must
   fail closed; never fall back to TCP as a trusted signup transport.
4. Review exact merged Compose/config/helper policy implications and enroll the
   new immutable configuration through the existing approved native workflow.
   The overlay repeats the current command plus one explicit policy argument and
   adds only policy/socket mounts. Preserve image, DB, state, deletion, credentials,
   origin, networks, runtime user and all existing release protections. A helper
   change, if required by its allowlist, needs its own scoped authorization.
5. Separately authorized deployment/enablement and bounded real-network checks,
   including forged direct/public requests and original-IP/hairpin distinctions.
   This document and local tests do not authorize or claim those checks.

Local synthetic verification covers HTTP/Store denial before hashing/writing,
actual Uvicorn Unix versus TCP socket identity, address boundaries, resource
limits, account isolation and browser behavior/renders. Browser network identities
are explicit synthetic fixture metadata, not evidence about a real router,
installed edge, provider, production account or independent review.
