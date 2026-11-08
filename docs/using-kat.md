# Using Kat

[Documentation index](README.md)

## Conversations

Sign in to the Kat workspace with its password; this is separate from connecting
a model provider. New conversation opens a general draft. Start conversation on
a person opens a scoped draft without sending. A thread can involve several
people. Search terms are submitted privately rather than placed in the URL;
background title/send completion does not replace your newer search or history
page. All conversations explicitly resets the filter.

Enter sends; Shift+Enter inserts a newline and IME composition is not submitted.
An unsent draft is not a request. The document scrolls rather than a fixed-height
message pane; long drafts enter document flow. Reading older content does not
force automatic following of incoming text.

The server archives input before acknowledging it and streams only committed
events. Reconnect and same-ID replay do not resend inference. Terminal errors
preserve committed content; an explicit new attempt must not replace a later
draft. Corrections, edit/regeneration and branch selection preserve originals.
Owner-scoped JSONL export includes original tool/context events; ordinary chat
keeps diagnostic traces out of the reading surface. Assistant Markdown supports
lists/tables and contained wide code; raw HTML/images are inert and external
links are HTTPS-only. User input and original event JSON remain literal.

At acknowledgement, new person discussions resolve the current generated natal
and archive its immutable identity. Later edits do not replace that turn's
versions. Historical drafts/charts remain available but are not silently promoted
for new sends. Unverified supplied details are labelled as such, not converted
into verified times or facts. Manual charts are never silently attached to chat.

A separate, one-attempt, tool-free title request may follow a substantive first
question. It uses a redacted question capped at 600 characters and a short output
budget, not the full archive. Failure leaves a placeholder; replay does not repeat
it. Manual rename and owner/revision checks fence late results. Legacy titles
remain legacy. Historical backfill requires explicit per-ID selection and scoped
provider permission; there is no automatic historical batch in the browser.

## People and birth details

A person may have only a name and no calculable chart. Generate chart explicitly
saves and calculates from the birth editor; opening a person or changing tabs
never generates one. Unsaved editor input survives tab changes while the person
stays open. Saved versions and earlier drafts remain in History.

Choose a disambiguated offline GeoNames city or explicit coordinates/IANA zone.
City-centre coordinates are reference inputs, not a verified birthplace. Mark
provisional details or unknown time honestly. Gap hours are rejected; repeated
DST hours require an occurrence. Unknown time retains the full historical local
day without inventing houses or a full natal. Save/calculate is atomic and safe
to retry after a lost response; a failed list refresh does not invalidate a
successfully saved chart.

Person pages have sibling **Overview / Context / Charts / Saved** panes.
Overview keeps optional personal details and directional links to existing people
in your own workspace. Links do not share accounts or automatically select another
person's records for chat. Unlinking leaves both people and their records intact. The relationship picker
searches and pages through all owned people. Same-name people show existing occupation/home
or an added-date preview with a local profile number; unique names need no suffix.
These recognition labels can change as profiles change, while links retain the chosen identity.
The Quiet Overview also leads to conversations, Charts and Saved. Exact-time natal
charts provide qualified planets/nodes, houses/angles, aspects, accessible tables
and downloadable wheels. Unsupported houses remain visibly partial. Child's
natal uses the same method with a family-focused explanation, not a distinct
record, diagnosis or personality classification. See [natal conventions](natal-charts.md).

## Personal context

Context keeps Life & plans and Interests & learning separate from charts, saved
passages and private journals. Add any number of independent entries; dates and
supporting details are optional. Click a row to edit only that entry. The compact
view shows up to two entries per populated group with honest remaining counts;
Each collection has its own View all, paged results and labeled search across all
its groups' titles, notes and user date fields. Expanding one leaves the other
collection available. Search does not match internal date-format metadata. Ordinary
navigation retains the pane, search/disclosure and pending context edits within
the signed-in workspace. Reload retrieves durable saved entries, not unsaved drafts.

Use Settings → Personal context to explicitly enable automatic collection/use.
It starts off even when a provider is connected. Selected relevant details may
then be sent to that provider; no chart is required. Speak naturally about an
explicitly identified selected person, for example `Alex here. I'm considering a
move next summer. What should I consider?` Selecting someone does not establish
who “I” refers to. Kat should omit or clarify ambiguous statements and correction targets.
Automatic interpretation can occasionally be wrong; inspect and correct entries in Context.
Clear updates do not require a separate confirmation each time.
You still control birth details, people and relationships. Plans do not become
completed events merely because a date passes. See the [provider contract](provider-and-context.md)
for exact accepted statement and source-lifecycle boundaries.

Source details are available inside the entry editor. Removing an entry removes
structured context, not the original conversation, archived answers or information
already sent to a provider. Conversation history may still contain the same facts.
Turning the setting off changes subsequent turns without erasing archives.

## Manual charts and timing

Create chart groups personal, relationship and timing techniques. Synastry uses
two distinct people's current exact-time generated natals, labelled rings and
actual inter-chart aspects; it does not manufacture a relationship score. House
overlays require supported recipient houses. Returns, progressions, true solar
arc, MC contacts, progressed phases, lunations/eclipses and derived relationship
charts retain their distinct [method contracts](advanced-calculations.md).
Solar returns expose UTC anniversary bounds and zero/one/multiple crossings.
Return places default to saved birthplace and may be explicitly changed.
Historical results keep original sources rather than silently recalculating.

Sky at a date is a read-only companion. Sky only has no birth assumption; Natal
+ transits uses the selected person's current exact-time natal. Results separate
same-sky and transit-to-natal aspects and disclose omitted counts. Use Now/Today
fills the authenticated clock's Copenhagen date/time without calculating or
sending. The clock is not NTP-verified, and Copenhagen is a reporting default,
not verified location or birth timezone. Each sent turn archives its own observed
clock; retries retain it. Conversation-directed chart reads use that turn's
immutable chart and reopen archived results without recalculation.

Manual calculation, browsing, export and disclosure never send a model message
or discard an unsent chat draft. Explicit Discuss this result selects a saved
result/crossing for a draft; only sending attaches it to a new discussion.

## Saved records

Save passage retains an exact completed user/assistant excerpt (up to 512 bytes)
and optional note for a person. Insights labels attribution and current versus
historical sources and can open the original discussion. It never edits the
original or treats a passage as a verified fact. Only current-source passages may
enter bounded personal-context recall; corrected/withdrawn/inactive sources stay
historical. Saving invokes no model.

Saved timing explores dated saved calculations for a selected natal/source and
interval, not predictions or a complete new scan. Saved for later contains only
manually selected items; optional local reminders send no external notifications
or automatic model requests. The private event journal holds deliberate
reflections, including date uncertainty; its text is not model context or
automatic recall. Glossary explanations distinguish geometry from interpretation.

## Provider and context limits

The browser uses the server-selected `gpt-6.1-sol` ChatGPT-plan Responses route;
there is no client model selector, billing fallback, upload or composer-zone
selector. Optional Sign in with ChatGPT is default-off. Connection alone does not
grant direct inference permission. Unsupported/unavailable plan/model access
fails recoverably rather than switching providers. Provider credentials stay on
the server, never in the browser. Requests use `store:false` and streaming;
selected context is still sent to the provider, so it is not local-only data.

Model-directed reads have no fixed conversational round count. Owner scope,
argument validity, evidence-byte limits, context/output capacity, cancellation
and archive commitment govern continuation. Invalid/duplicate call IDs,
incomplete results and empty answers fail distinctly. Capacity estimates and
named-model documentation fallbacks are not verification of actual plan grants,
output eligibility, cost or interpretation quality.

Long conversations may create a derived summary of older eligible active-branch
turns. Recent exact turns and authoritative chart facts remain separate. Summaries
can omit nuance; they are not new sources or renewed file consent. A failed or
aborted summary leaves originals and the previous checkpoint intact and does not
automatically retry a failed turn. Current browser upload/person-file ingress is
closed; legacy file-backed turns retain archive, backup/deletion and same-ID
no-resend semantics. Generated chart exports are distinct from uploaded files.

## Privacy and recovery

Export before removing material you need. Explicit conversation/person deletion
uses the deletion journal and dependency rules; a person with related
conversations cannot be deleted first. Independent exports are not revoked by
managed deletion. Do not discard the independent deletion authority when restoring
an older backup. See [archive recovery](archive-and-recovery.md) for local archives and
[deployment recovery](../deploy/README.md) for packaged operation.

Synthetic checks do not establish live-provider eligibility, response quality,
physical-device accessibility or permission to read private archives. Accurate
astronomical calculations do not scientifically validate interpretations.
