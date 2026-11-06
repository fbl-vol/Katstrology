# Provider and context contracts

[Documentation index](README.md)

## Routes and authority

The browser selects `gpt-6.1-sol` server-side on the direct ChatGPT-plan Responses
route, with Copenhagen reporting dates. Optional Sign in with ChatGPT is
default-off. Identity authorization and `chatgpt.tokens.use.direct` permission are
separate. Missing model/grant fails without a silent model, provider or billing
fallback. Registration, host ID, one-time state/nonce/PKCE and validated ID tokens
belong to the backend; account-scoped rotating credentials stay in owner-only
files. The browser receives neither tokens nor callback codes.

Responses uses `store:false`, `stream:true`; selected context still leaves the
machine. Neither local archive ownership nor that flag guarantees local-only
processing or provider zero retention. No provider history is imported. Legacy
file-backed turns replay without resending; current person-file ingress and
forwarding are closed. Read tools cannot gain write/shell/filesystem authority
from retrieved text. CLI/MCP are separate capabilities, not model permissions.

Provider tests use fake HTTP/SSE and signed synthetic authorization fixtures.
They do not establish actual account eligibility, plan size, cost, quality or
real-provider acceptance. Provider policy can change independently of the code.

## Capacity and prompt identity

Local Qwen is a small plumbing fixture, loaded only when explicitly selected by
local tools. Its normal context is 2,048 tokenizer-measured tokens with a 128-token
reply reserve. Bounded selected ancestry/extractive summaries may be omitted on
local overflow; that is not a product-quality memory or interpretation guarantee.

Hosted preflight uses approximately one estimated unit per two UTF-8 bytes, not
provider tokenization or measured media cost. Optional catalogue context/output
bounds are validated independently. The public Models API does not promise them.
For the named model only, missing bounds use the source-documented API fallbacks
(1,050,000 context; 128,000 maximum output). A present malformed field fails closed;
other slugs require both advertised bounds. Catalogue and fallback provenance are
recorded separately and neither verifies the direct-plan grant.

Reply planning reserves at most 16,384 units, additionally bounded by output limit
and a quarter of small windows. This is not a requested response length. Prompt,
tone version/mode/digest and capacity/count provenance are archived per turn;
accepted tone versions remain reconstructible. Untrusted selected evidence is
separate from product instructions, which occur once per request.

## Committed reads and stateless continuation

There is no fixed conversational read or provider-round count. Each valid call and
matching result commits before the next request. Owner/source scope, arguments,
result bytes, context fit, cancellation and durable writes remain independent
guards. Duplicate call IDs, unsupported output and empty answers fail distinctly,
not as ordinary read exhaustion. Exact retry never repeats inference.

Streaming retains at most eight bounded completed native output items until the
footer. An omitted/empty footer output uses only verified completed items; an
added-only item is insufficient. A populated footer must agree on identities,
arguments and content. Visible deltas commit once; completed message text supplies
only a missing suffix. Reasoning needed for continuation is transient, never
archived or rendered. Unsupported-output diagnostics contain bounded categories,
not private arguments/text/reasoning.

Model projections allow up to 16 KiB per read and 32 KiB aggregate evidence with a
limit-result reserve. Authoritative tool-result events allow up to 64 KiB; other
events retain 16 KiB. Byte bounds are not token counts. Limited projections retain
provenance and honest omission labels; originals remain readable. If even an
incomplete-result notice cannot fit, the bounded result stays archived and the
turn stops with `tool_result_capacity` before another provider call.

## Derived continuity

Before hosted dispatch approaches capacity, compaction may summarize older eligible
active-branch turns, reserving up to 16,384 units of headroom and roughly 20,000
recent units when possible. Completed turns stay indivisible. Summary-source
call/result excerpts are bounded at 2,000 characters; originals are not truncated.
The separate tool-free summary must complete, fit 4,096 characters and leave the
next request within budget before an atomic checkpoint advances.

Checkpoints bind covered/kept turns, source digest, lineage/revision, selected scope,
model/prompt identity and count provenance. Successive checkpoints combine the
prior summary with newly retired turns, not every past summary. Corrections and
source/branch changes invalidate eligibility. Recent exact questions and mandatory
selected calculation facts cannot silently disappear to make a prompt fit.

Failure, cancellation, incomplete output, attempted tools or concurrent source
change leaves originals and the previous checkpoint intact. A failed turn is
terminal, never automatically retried. Valid prior usage can inform the trigger,
not exact preflight; missing/zero/stale usage falls back to labelled estimates.
Summaries can lose nuance and do not create source authority or renewed consent.
