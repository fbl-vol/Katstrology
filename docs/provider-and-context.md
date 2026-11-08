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

## Personal context: consent, evidence and staged updates

Personal context is off by default. Settings has one explicit control for both
collection and use. Manual Context editing and personal details/links work without
a provider or birth chart. Opting in permits relevant selected-person details to
leave the machine with the current conversation. Opting out affects subsequent
turns, not already transmitted data or immutable archives. Revocation versions are
also retained in the independent deletion journal so an older database backup
cannot silently restore consent.

Turn acknowledgement freezes the consent version and exact entry/detail versions
in the original user event. Selection considers only explicitly selected people,
never relationship neighbors or private journals. It ranks the newest 500 candidate
entries per person by topic words, ongoing circumstances, guidance/learning and
nearby dates, retaining at most eight entries within an 8,000-byte projection.
This is selective context, not an exhaustive account summary. The server-owned
reporting clock anchors date relevance. Approximate month/year, ranges and unknown
dates remain distinct; they are not exact instants or countdowns. Context and source
statements are untrusted user-reported data, never calculated evidence or instructions.

Existing `agent_reads` tools remain read-only. The separately advertised
`stage_personal_context` capability is offered only for opted-in turns. Its closed
schema accepts a selected person, exact complete current-user context, statement and
identity spans (Unicode offsets plus matching text), a full-context assertion assessment,
an interpreted group/add-or-correct intent and an optional existing entry/version. It cannot supply arbitrary content,
owners, SQL, births or relationships. The existing response model interprets ordinary
conversation; no additional inference request is made. For example, `Alex here. I'm
thinking of moving next summer. What should I consider?` supplies an attributable
statement alongside a question. Multiple statements remain separate candidates;
natural explicit corrections target a version actually supplied to that turn.

The backend owns conservative complete sentence envelopes and requires the entire
current message (at most 4,096 UTF-8 bytes) as evidence. Candidates cannot trim away
question framing or negation, use quoted spans, or omit containing source context.
Paired single quotes are not contractions: apostrophes within words remain usable.
First-person attribution requires a complete opening introduction such as `Alex here`
or `I'm Alex`, not selection or an incidental name mention. Named-person assertions
must start with the uniquely selected name. Unattributed declarative framing, including
fictional preambles and later third-person retractions, requires clarification; ordinary
attributed facts and accompanying questions remain eligible. Complex punctuation and
unsupported attribution may conservatively omit a candidate.

Corrections additionally require a verbatim revision cue in the assertion (such as
“Actually”, “rather than” or “on second thought”) and a source identifying phrase that
matches exactly one supplied old record in the same group. The backend resolves that
phrase across supplied records independently of the requested ID, then checks ID and
version. For example a paraphrased correction about “answers” can resolve a unique
answer preference, but cannot replace a gardening entry or guess between two matching
answer preferences. No shared identifying phrase or an ambiguous match means clarify,
not overwrite. Model classification and an ID alone never authorize replacement.

Stored statement text preserves qualifiers verbatim; archived source evidence retains
the full message. The existing model still interprets assertion force, retractions,
fiction, attribution, intent and paraphrased meaning. This is deliberately fallible
automatic interpretation, not deterministic semantic proof. Occasional incorrect
interpretations remain possible without routine per-change confirmation. Uncertain
or non-asserted assessments are rejected. Users can inspect/correct entries in Context.
No sensitive traits or exact dates may be inferred; future plans stay tentative and
dates unnormalized. Synthetic checks establish these defined boundaries/lifecycle
controls, not universal semantic accuracy or real-provider interpretation quality.

Candidates are durable stages, explicitly **not saved context**. The existing
serialized terminal-event transaction finalizes only successful turns whose
source epoch and consent still match. Each update has a source-derived operation
identity, expected-version check and deletion-ledger fence. Cancellation, failure,
stale branches, consent changes and abandoned work publish nothing. Storage errors
are recorded as failed outcomes without another inference request; restart marks
unfinished stages abandoned. The terminal event records outcomes, and the UI warns
when a proposed change was not saved. No scheduler, extra summarization request,
background backfill or second archive sender is involved.

Manual edits take precedence over older staged updates. Source corrections,
withdrawals, branch abandonment and source deletion suppress derived projections;
manual corrections retain their own attribution. Removed entry identities cannot
be reused, including after backup restore. A later explicit statement is a distinct
source, not replay of a removed source. Context version/consent changes invalidate
cached continuity; subsequent recall/compaction omits assistant replies relying on
superseded structured context while retaining eligible original user text. Each new
context event records effective assistant-turn dependencies actually consumed by the
prompt, including summary sources. Those dependencies are checked transitively. A
fresh generation after invalidation can regain eligibility without reviving old
answers or descendants generated from stale material. Older archives without this
record retain conservative ancestry checks. Automatic publication invalidates other
conversations' cached continuity too, after the source head is durably established. Original
archive replay remains unchanged. Removing context does **not** erase conversations,
previous answers, exports or provider processing, and retained history can still
contain the same information.

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
