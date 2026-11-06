# Architecture and source map

[Documentation index](../README.md)

Kat is a single-process application, not a collection of network microservices.
The browser loads built Preact/TypeScript assets from the same Python service that
handles its API. PostgreSQL and private runtime files are separate owned storage.
Packaged HTTPS deployment and standalone loopback development have distinct
configuration/security boundaries; see [deployment](../../deploy/README.md).

## Request and data flow

1. The HTTP boundary validates Host/Origin, session and mutation CSRF, then sends
   owner-scoped work through one serialized Store executor/connection.
2. Conversation workflow captures draft/navigation intent. The browser archive
   owner alone sends turns, tracks pending IDs and consumes ACK/SSE events.
3. The backend commits input and immutable selected source identities before
   inference. Context assembly selects bounded eligible ancestry and authoritative
   chart/reference facts; the provider may request qualified read-only tools.
4. Tool results, visible output chunks and terminal state commit before delivery.
   Reconnect pages committed events by cursor; same-ID retry never reruns inference.
5. Search, summaries and vectors are derived projections. Corrections, branch
   changes and revoked sources invalidate eligibility without rewriting originals.

Manual chart generation/inspection/export is separate from model sending. A saved
result can be selected for a draft, but only an explicit send attaches it to a
turn. Current person/chart pointers never replace an archived turn's versions.
Numerical solvers share checked Swiss/time/source primitives without merging
distinct techniques or changing their qualification contracts.

## Frontend ownership

| Location | Owner |
| --- | --- |
| `web/src/main.tsx` | Vite mount entry |
| `web/src/app/` | Session application, workspace navigation and shell composition |
| `web/src/features/conversation/` | Discovery, draft workflow, sole archive sender, turns/context and scrolling |
| `web/src/features/people/` | Birth/profile UI, insights, timing and private records |
| `web/src/features/charts/` | Manual catalogue, technique intents/results, geometry and exports |
| `web/src/features/settings/` | Appearance, provider and tone controls |
| `web/src/shared/` | API, shared style/theme and brand assets/source notice |
| `web/tests/` | Matching capability suites plus layout/provider and shared support |

Discovery refreshes capture browse intent before awaiting work. A delayed create,
send/retry or title completion cannot reset newer search/paging intent. Explicit
All conversations navigation remains a distinct reset. Component grouping does
not move transport/ACK/SSE ownership out of the archive module.

## Backend ownership

| Location | Owner |
| --- | --- |
| `m2/archive/` | Store, conversations, revisions/provenance, blobs, deletion and snapshots |
| `m2/chat/` | Turn execution, bounded context/compaction, evidence/read tools, prompts/tones and titles |
| `m2/calculation/` | Versioned charts, method-specific solvers and checked numerical primitives |
| `m2/people/` | People/birth workflow, offline place inputs and explicit saved records |
| `m2/references/` | Edition/package admission, retrieval, pinned embeddings and citation audit |
| `m2/provider/` | Optional local binding, SIWC, Responses parsing and capacity |
| `m2/http_boundary/` | Routes, auth, request security/configuration and serialized runtime lifecycle |
| `m2/operations/` | Clock/policy, owned fixture access and synthetic walkthrough/evaluation |
| `tests/` | Capability-grouped backend/release contracts; common database/template support |
| `probes/` | Separate feasibility/numerical checks and legacy probe import contract |

The [backend guide](../../m2/README.md) records the evidence-backed root CLI and
installed compatibility exceptions. Resource paths `m2/migrations`, `m2/data`,
requirements and model license stay stable. Docker explicitly copies production
packages; tests are not runtime dependencies. The source offer includes preferred
source/build inputs independently of installed image contents.

## Boundaries that grouping must preserve

- One Store/advisory owner and commit-before-delivery sequence; no per-request
  Store, duplicate sender, second journal or distributed-write design.
- Source-qualified facts, original event identities/order, immutable chart/result
  versions and schema24 compatibility. No inferred exact birth time or invented
  houses, interpretation or relationship score.
- Owner-scoped model reads are narrower than CLI/MCP. Prompt text is not an
  authorization boundary; provider reasoning is transient, not archive content.
- Private attachments, credentials, journals and snapshots are not all in the
  database. Older snapshots require independently retained current deletion
  authority before access; exported copies have their own retention lifecycle.
- Installed release helpers and immutable image/source identities have explicit
  trust contracts. Moving application modules is not permission to repin helpers,
  activate migrations, replace a source offer or deploy.

See [archive/recovery](../archive-and-recovery.md),
[provider/context](../provider-and-context.md), [reference library](../reference-library.md)
and [synthetic validation](../testing.md). Local checks do not establish live
provider quality, external-host capture, physical-device acceptance or your
production backup/retention policy.
