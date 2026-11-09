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

Model projections allow up to 256 KiB per read and 2 MiB aggregate evidence with a
limit-result reserve. Authoritative tool-result events allow up to 1 MiB; other
events retain 16 KiB. Byte bounds are not token counts. Limited projections retain
provenance and honest omission labels; originals remain readable. If even an
incomplete-result notice cannot fit, the bounded result stays archived and the
turn stops with `tool_result_capacity` before another provider call.

## Public search and page evidence

Hosted chat can request focused public searches for current reporting or source
research. Ordinary astrology does not force a search. The separate search request
contains only the chosen public query and filters, not the conversation, selected
people, charts or files. The model chooses query text, so do not request searches
for private details: instruction guidance is not an automatic privacy classifier.
Search uses the selected connected plan, without a fallback or automatic retry.
Provider-written search summaries are not article text; coverage, recency and
publication dates may be incomplete. Public reporting never overrides calculated
chart geometry or establishes astrological causation. Selected-library grounding
and personal-context consent retain their separate authority.

The public reader accepts user-supplied or conversation-discovered HTTP(S) URLs.
It sends no cookies, authorization or proxy credentials, pins a validated public
address and rechecks redirects. It does not bypass login/paywalls, run scripts or
analyze media. Static HTML/plain-text reads have a 20-second total deadline,
bounded framing/Stop polling, at most 256 KiB response bytes and 24,000 UTF-8 text
bytes per page; at most two URLs are fetched sequentially. Static extraction is
not proof of complete article coverage. Sites receive the requested URL and the
server's network address. Page content is untrusted evidence, never instructions.

Calls and results commit through the existing archive before continuation.
Public evidence has its own 3,072-byte per-result and 8,192-byte aggregate model
allowance, subordinate to the unchanged global bounds. The complete bounded
retrieval remains archived. `read_web_content` discovers source metadata, finds
literal text and pages retained content without another network request. Empty
conversation scope binds to the executing conversation; empty source ID discovers
one source and returns a cursor. A committed result in the currently executing
open turn is available only through trusted gateway context, never a model flag.
Owner, active-lineage, correction, withdrawal and source-provenance checks still
apply. Deep retrieval expires after seven days; original archive replay remains
historical and follows ordinary deletion/backup ownership.

Public source links and honest searching/unavailable states appear beside the
reply. Reload uses saved results, not another search. Links open separately;
unsafe schemes, embedded credentials and local-address links are not rendered.
Capability guidance is versioned independently of tone expression: accepted
version 1-3 instructions still reconstruct exactly, while new version 4 turns gain
public-web guidance. Local and summary instruction text is unchanged. Synthetic
checks establish transport, archive and UI behavior, not real-model judgment,
provider acceptance or live public-network reliability.

## Personal context: consent, evidence and staged updates

Personal context is off by default. Settings has one explicit control for both
collection and use. Manual Context editing and personal details/links work without
a provider or birth chart. Opting in permits relevant selected-person details to
leave the machine with the current conversation. Opting out affects subsequent
turns, not already transmitted data or immutable archives. Revocation versions are
also retained in the independent deletion journal so an older database backup
cannot silently restore consent.

Settings also has a separate, explicit **Who is me?** choice of an owned person.
It neither enables consent nor adds anyone to conversation selection. Names, login,
selected charts and model output never establish this authority. Migration032 stores
only the owner-scoped person ID/version. Each change journals its revocation generation
without the replacement identity; restoring an older generation clears the association
rather than reviving the former speaker. A backup may predate a later account's enrollment:
self/consent revocations apply only to accounts present in that restored database, without
creating ghost accounts or removing journal records. The same retained revocations still
apply when restoring another backup that contains the account. Person/account deletion
uses existing foreign keys and deletion replay. Old facts and archives are never retagged.
The single-person read returns the same canonical owner-scoped `picker_label` as
picker pages, so saved-self recognition survives reopening, reload and failure refresh.
Duplicate-name ranking happens before the ID filter; other owners never contribute.
This is a current display label, not stored authority or a version change. The UI keeps
its name/ID fallback when a descriptive label is unavailable; it does not enumerate
all people or reconstruct label rules in the client.

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
conversation in its existing response/tool-continuation flow; no separate extraction
inference pass or background request is made. For example, `Alex here. I'm
thinking of moving next summer. What should I consider?` supplies an attributable
statement alongside a question. Multiple statements remain separate candidates;
natural explicit corrections target a version actually supplied to that turn.

The backend requires the entire current message (at most 4,096 UTF-8 bytes) as
evidence. Legacy explicit introduction and uniquely named-person paths retain their
complete sentence envelopes. With an eligible explicit self association, the new
`associated_self` attribution accepts complete clauses within a containing sentence,
including compound facts followed by a question. The identity span is that entire
sentence, not a new identity claim. Server-owned comma/semicolon/coordinating-conjunction
boundaries (including a following wh-question) prevent arbitrary substring extraction;
adjacent clauses can retain qualifiers.
Quoted/reference delimiters still fail closed, and a question itself is not a fact.
Apostrophes within words remain contractions. Named subjects must use the named-person
path, not self association to bypass ambiguous names. Unattributed framing outside the
containing envelope still requires clarification.

For example, an explicitly associated and selected Casey can say `Got married in May
2020, joined ExampleWorks as a trainee in July 2021, became full time around 2022,
I am building a small venture, what does my chart suggest?` without another name
introduction. Four separately inspectable entries retain the exact assertions and
full source message. Date wording stays verbatim; normalized date bounds remain unknown.
The model must assess the **whole** source, including negation, conditional scope,
quotation/reference, retraction and mixed speakers, before proposing any clause.
Clause boundaries do not prove that meaning: an asserted classification can be wrong.
These are provenance/authority bounds, not an English semantic verifier. Unsupported
punctuation or uncertain omitted-subject attribution must omit/clarify rather than guess.

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
source epoch, consent and (for associated-self proposals) frozen self ID/version still match.
The selected projection exposes the association target only when that person is selected;
unselected self has a status, not a leaked person ID or automatic selection expansion. Each update has a source-derived operation
identity, expected-version check and deletion-ledger fence. Cancellation, failure,
stale branches, consent changes and abandoned work publish nothing. Storage errors
are recorded as failed outcomes without another inference request; restart marks
unfinished stages abandoned. The terminal event records per-entry/person outcomes.
A quiet archive disclosure distinguishes saved, discarded, conflict, storage failure,
rejected tool proposals and no proposal. It offers selected-person Context inspection
through the existing navigation authority, preserving the conversation draft on return.
It does not equate staging, an empty bounded projection, or no proposal with a successful
save or an empty profile. Historical saved outcomes are not a current storage audit. No scheduler, extra summarization request,
background backfill or second archive sender is involved.

Manual edits take precedence over older staged updates. Source corrections,
withdrawals, branch abandonment and source deletion suppress derived projections;
manual corrections retain their own attribution. Removed entry identities cannot
be reused, including after backup restore. A later explicit statement is a distinct
source, not replay of a removed source. Explicit self-association changes also invalidate
derived assistant continuity that used the prior speaker authority, without rewriting
originals or moving facts. Context version/consent changes invalidate
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
