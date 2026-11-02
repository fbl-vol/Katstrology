# Local conversation, chart and evidence application (synthetic-data-only)

This is a **local, single-process** Python CLI/gateway and optional loopback-only browser client over PostgreSQL 16.14 and private files, not a deployed service or a supported hosted client. Browser setup and boundaries are in [`web/README.md`](../web/README.md). M2 archive
behaviour is preserved; M3 chart versions and M4 source/personal records use
that same owner/correction/deletion/restore lifecycle. Legacy Sun-only calculations
and bounded transit events live in `m2/core_calc.py`; `probes/core_calc.py`
remains a compatibility import shim. Explicit versioned Western tropical natal charts add a separate, local Swiss calculation boundary.
See [`NATAL-CHART.md`](NATAL-CHART.md) for supported inputs, conventions,
reference cases and license gate before any public service. The 498 MiB Qwen fixture
runs in-process on two CPU threads with a 2048-token context ceiling;
its answers and tool choice are **not** product-quality evidence. The gateway,
not the model, recognizes the one explicit `solar longitude at <ISO instant>`
command; explicit `saved chart <id>`, `chart events <id> <start> <end>` and
`reference evidence <query>` use deterministic qualified tool answers. Other synthetic questions receive a plain local-model response. The browser offers default-off official ChatGPT-plan sign-in; new browser turns use only server-fixed `gpt-6.1-sol` via direct Responses with Copenhagen as reporting default, and fail without the selected plan/model. There is no new browser file upload, model choice, chart-version choice or local fallback; new turn scopes submit person IDs and resolve each person's one active generated natal on the Store worker at acknowledgement. A newer explicit Generate updates only the active pointer while retaining immutable birth/chart versions; retrying an older request ID never reactivates it. Schema 016 backfills only the latest recorded generated natal for each owned person, never guesses from legacy/solar charts. Legacy archive replay retains its original route, versions and evidence. Agent checks used fake OAuth/inference fixtures, not a live account or conversation import; the user reports live conversations separately. Synthetic direct Responses requests expose bounded read-only typed functions, including current owned conversation search/window reads, explicitly selected chart read, attributed reference search/passage read, selected-chart transit snapshot/crossing/sky-event reads, a full sky or selected natal-plus-transits view, and the separately qualified advanced techniques. Transit calculations use the saved tropical profile, Swiss engine/data checks, a 30-day UTC window and 60-second refinement; sky-only ingress/station events do not imply a known birth time. A two-person comparison requires two explicitly selected immutable natal versions, matching zodiac/aspect/orb policy and known birth instants; it returns at most 12 closest inter-chart ecliptic aspects with omission count and separately labelled planet-in-recipient-house overlays where that recipient’s saved houses are supported, never a compatibility score. One unsupported house direction remains unavailable without erasing the supported direction; unknown birth time suppresses unsupported degrees and polar/partial houses suppress angles. Each requested call and bounded result commits before the next stateless provider request; the model may request additional reads without a fixed conversational round count, subject to independent ownership, result-byte, context and cancellation guards. It chooses when to answer; no call count silently removes tools. Provider reasoning items are forwarded transiently when required for continuation, never archived or displayed. Restart or retry preserves the recorded prefix and does not repeat provider calls or tool effects. The local-model and MCP adapters remain separate entry points over the same Store. Versioned local and hosted instructions share a concise warm, curious, direct companion tone, permit occasional fitting emoji without quotas and call for substantive responses rather than menus or flattery; the hosted instructions alone permit bounded read tools. Synthetic prompt/assembly tests verify wording and context budgets, **not** human preference or live model dialogue quality. Do not ingest `session.txt`, chart/image, personal history
or other private M2 material. `PLAN.md` and private M1 fixtures stay local;
probe source and generic methods may be tracked without their personal oracle.

Reference editions retain UTF-8 originals, SHA-256, extraction note, language, HTTPS provenance URL and declared rights state. Legacy text imports keep their 128 KiB original / 32 KiB manifest / 64-passage admission limits. The separately explicit offline full-book package path accepts up to 16 MiB raw source bytes, 4 MiB UTF-8 normalized text/transcript, 8 MiB manifest, 1,024 ordered leaves and 512 exact located passages of at most 3,000 characters. These are per-source admission bounds, not an upload API or a promise of full-corpus recall. The immutable package keeps raw bytes, a normalized exact-slice transcript, physical and optional printed-page ranges with leaf locators, section/parent labels, ordering, adjacent passage IDs, extraction/review status and distinct raw/transcript/processing/normalized digests. A changed input or processing revision gets a new identity; an invalid or interrupted package does not replace an existing one. Transcript JSON must be canonical as written by `prepare-book`; reformatting it is rejected. Import commits the exact bytes validated in one snapshot, not paths reopened after validation. Chunk boundaries do not cross a changed section or parent; mixed/ambiguous historical spans never advertise parent-qualified neighbors. The operator supplies the raw source, extracted leaves and edition/rights metadata; this generic path does **not** OCR, verify an edition or infer printed pages. Import is owner-scoped, atomic, exact-ID idempotent and never selects a source. A later explicit selection is still required for non-fixture retrieval; predecessor revisions and deletion/revocation journal behavior are unchanged. Backup verifies the retained raw and normalized hashes. Existing small imports and their IDs remain compatible. Located passages must occur verbatim in the original when one is present; an edition is selected explicitly, never by a model. Edits use a new source ID linked to the older edition rather than rewriting cited evidence. Revocation excludes reference reads, keyword/semantic candidates and vectors, and invalidates dependent conversation derivatives while originals remain available for explicit deletion. One permitted OpenStax *Astronomy* paragraph is checked in with attribution/CC BY 4.0 as an **optional local import fixture**, not a Kat-approved interpretive edition. The selected source remains a local operator action; no user archive is changed by shipping it. `m2/STARTER-SOURCES.md` names editorial and language gaps. The authenticated CLI supports explicit UTF-8 text original + manifest import, same-ID exact retry, operator selection and revocation. It reads only paths you provide; do not pass private library files without separate scoped permission. It does not fetch URLs or perform OCR. For **synthetic inputs only**, `prepare-book <raw-source> <extracted-leaves.json> <metadata.json> <output-root>` atomically creates a content-addressed package, and `validate-book <package>` rechecks every byte/span; neither needs a database. Each leaf contains `text`, nondecreasing physical integer `page` (for split spreads), nullable mapped `printed_page`, distinct `source_locator` (such as a spread side), `section`, `parent_section`, `extraction_status` (`unverified_ocr`, `unverified_transcription` or `verified_extraction`) and `review_status` (`not_reviewed`, `sampled` or `reviewed`). Unknown printed pages stay null; a physical page is not represented as a verified printed-page mapping. Metadata includes the usual source attribution/rights fields plus `processing_revision` and nullable `supersedes_source_id`/`source_url`. The separate authenticated `import-book <package> --confirm-rights` retains the raw and normalized bytes in the existing database reference lifecycle, without selection. The private-books preparation/import phase, owner/rights decision and any OCR/profile corrections are **not** covered by synthetic readiness. The preserved original is the exact imported text file, not an entire remote webpage; never imply unimported figures or sections are available. Read tools return 1800-character windows with `next_offset` for complete bounded continuation. The browser's collapsed Sources consulted card shows actual saved reads, not a claim-support certification or current-source eligibility check. For book passages, search previews show page and parent-section locators and review status; exact passage reads include normalized character offsets, page range and only same-section-and-parent previous/next IDs. Following an ID requires another eligible owner-scoped bounded read. It does not automatically send neighboring pages or a whole book to a model. Reference search can use the cached offline semantic model, with keyword-only status if unavailable, plus exact author/tradition/technique/language filters. Person-scoped history filters at selected **turn** granularity, including correction lineage, not whole conversation membership. Source selection, numerical quality and interpretive relevance remain separate evidence gates.

The optional **Sky at a date** browser companion calls the authenticated read-only
`GET /api/transit-view` endpoint. The browser sends an explicit date and Copenhagen
clock time; the server fixes the reporting zone, rejects DST gaps and prompts for
earlier/later only when that hour actually repeats. Sky-only mode calculates ten
planetary positions/motions without a natal chart or local houses. Natal + transits
resolves the chosen owner's current generated exact-time natal (never a client chart
ID), reuses its tropical profile/aspect orbs and
Swiss ephemeris/data boundary, and separates same-sky from transit-to-natal
longitude aspects. Each category shows at most twelve tightest aspects with the
full matching count; it is not a pattern detector or forecast. Result/provenance
is ephemeral and changing views never writes a chart, birth record, draft,
conversation or model request. Tests use isolated synthetic owners and builds;
no live provider or real-source inputs were used.

The left-navigation Create chart hub also exposes a manual **Synastry** view via
read-only `GET /api/synastry?person_a_id=...&person_b_id=...`. It accepts exactly
two distinct owned person IDs, resolves the active generated chart for each on
the serialized Store worker, and delegates all aspect geometry and compatibility
checks to the same `Synastry.compare` used by agent reads. The response names
both immutable chart/profile/engine sources, their exact supplied-but-unverified
birth-time status, supported positions/angles, up to twelve closest ecliptic
aspects and total/omission count, plus separately labelled directional overlays
into each recipient’s supported natal houses. No client chart-ID override,
old-source substitution, inferred houses for an unsupported direction, model
message, chart write or score is supported.
Changing active charts after a result requires a fresh comparison; the old
result describes its calculation-time sources. Unknown times and incompatible
settings return qualified unsupported statuses rather than approximate degrees.
Child’s natal routes through ordinary one-step generation with no additional
birth method or stored child-status field.

The same Create chart catalogue groups thirteen manual choices by Personal charts,
Relationships and Timing. The saved [advanced-method contract](ADVANCED-TECHNIQUES.md)
covers solar/lunar/planetary returns, MC contacts, secondary progressions,
true solar arc, progressed lunar phases, global lunations/eclipses, and distinct
composite and uncorrected Davison methods. A selected return reference defaults
to the saved birthplace, may use a validated offline city-centre selection or
explicit coordinates, and stays in the archived result. Solar anniversary cycles
can have zero, one or multiple crossings; the actual UTC bounds and count are
shown rather than changing the v1 calculation or throwing away legitimate roots.
Only supported, owner-scoped results are saved. Manual calculations and opening
supporting detail never call the model. Missing/uncertain natal sources, invalid
periods and stale-source histories remain qualified; no birth time is inferred.

For each **new** gateway turn, event zero archives one application-observed UTC
instant and its IANA reporting-zone date/time/offset/DST occurrence before model
input is sent. New browser turns fix Europe/Copenhagen for reporting, independent
of the birth zone derived from historical location rules. The process clock is not
independently NTP verified, and a zone is not proof of location or birth time.
Historical turns and exact retries replay their original anchor. The same bounded
current-turn clock reaches local and synthetic hosted model context after
historical data, never inferred from older summaries. The authenticated read-only
`GET /api/clock?zone=<IANA>` supports manual **Use Now / Today**: it fills
explicit date, time to the second, zone and repeated-hour occurrence; users must
still click Show calculated view. No model request or conversation write follows
from changing the manual view.

The declared `get_transit_view` model read calls **the same** calculation function
as the manual endpoint. Its structured tool result (complete positions, motion,
provenance and two bounded aspect tables) is committed with the requesting turn
before a continuation; a smaller labelled projection fits the provider read
budget, with omitted-aspect counts and a digest of the exact projection. Natal
comparison is confined to that turn's selected immutable chart version; sky-only
needs none. A saved in-conversation chart card reopens from archived JSON without
recalculation or auto-attaching manual output. Later corrections take precedence
over a chart source's status as it was when the turn ran. These local tests use a
scripted fake transport, not a live provider or interpretive acceptance.

For the optional public text fixture, with an already owned isolated local Store/fixture and explicit editorial decision, run:

```bash
.venv-swiss/bin/python -m m2.fixture_cli import-reference m2/data/openstax-seasons-manifest.json m2/data/openstax-seasons-excerpt.txt --confirm-rights
.venv-swiss/bin/python -m m2.fixture_cli select-reference openstax-astronomy-seasons-4-2-excerpt-v1
.venv-swiss/bin/python -m m2.fixture_cli get-passage openstax-astronomy-seasons-4-2-excerpt-v1 seasons-distance-axis
# Optional withdrawal, then deletion only after dependent conversations are removed:
.venv-swiss/bin/python -m m2.fixture_cli revoke-reference openstax-astronomy-seasons-4-2-excerpt-v1
```

`--confirm-rights` acknowledges the manifest you inspected, **not** Kat endorsement.
Use a new immutable ID for an edited edition; a same-ID retry refuses changed
content/metadata. An offline vector index failure does not discard the original:
keyword search remains, `semantic_available` reports its limitation. The
external deletion/revocation ledger prevents older backups re-enabling removed
sources when that journal and its tip survive. Do not import private material
into the public test fixture. Original-source and claim-support correctness need
separate human evaluation.

## Owned fixture and reproducible checks

From the checkout root with `.venv-swiss` and the public hash-pinned Swiss
calculation files (setup in `probes/README.md`); the optional local Qwen and
cached **offline** BGE-small English embedding models have separate setup below:

```bash
umask 077
uv pip install --python .venv-swiss/bin/python -r m2/requirements.txt
# Only if .local/m2-pg-name and .local/m2-pg.env do not already exist:
./m2/start_local_postgres.sh
OPENBLAS_NUM_THREADS=2 .venv-swiss/bin/python -m unittest discover -s m2 -p 'test_*.py' -v
OPENBLAS_NUM_THREADS=2 .venv-swiss/bin/python -m unittest discover -s probes -v
```

`m2/requirements.txt` contains the hosted/web and calculation dependencies but
not `llama-cpp-python`; the hosted web server no longer imports that optional
native binding on startup. Only an explicitly chosen local Qwen/CLI model path
needs the separately installed binding and model file described in
[`probes/README.md`](../probes/README.md). An absent local model never becomes
a silent browser fallback. For tests, prefer the workspace-isolated validation
script over attaching to a running archive or building served `web/dist`.

The startup script creates **only** a uniquely named Docker
`postgres:16.14-alpine` fixture, randomly generated local fixture password in
`.local/m2-pg.env` (mode 0600), dynamic loopback port, no host mounts, and
512 MiB/2 CPU container limits. `m2/local_fixture.py` resolves only its saved
name/port and never prints the password. Tests create and drop their own unique
fixture databases and private file directories. Do not use a shared PostgreSQL
service. `./m2/stop_local_postgres.sh` stops/removes only the recorded container
with the exact expected name/image and removes **its** local connection files;
it does not remove unrelated processes, private evidence, backups or the
independent deletion journal. The fixture database is ephemeral when removed.
Run stop only when finished with this owned instance.

The tests executed against owned PostgreSQL 16.14 with CPython 3.11.16,
psycopg[binary] 3.2.9, argon2-cffi 25.1.0, pyswisseph 2.10.3.2 / Swiss engine
2.10.03, llama-cpp-python 0.3.36, MCP Python SDK 1.30.0 and FastEmbed 0.9.1. PostgreSQL **server**
version matters: host pg_dump/pg_restore are 18.4 and cannot restore to 16 due
to `transaction_timeout`; `m2/backup.py` deliberately invokes PG16 tools
**inside the exact owned fixture**. This is not a general backup adapter.

## Synthetic CLI path

The CLI asks for the local username and password via prompt, not command-line
arguments. `enroll` is a **local-workstation administrative operation** for the
owned fixture, not an unauthenticated network route; use synthetic accounts.
Passwords are hashed by maintained Argon2 (`argon2-cffi`), not home-grown tokens.
`fixture_cli` selects only the owned fixture without printing its DSN. Set
`umask 077` and use synthetic input only:

```bash
.venv-swiss/bin/python -m m2.fixture_cli enroll demo
OPENBLAS_NUM_THREADS=2 .venv-swiss/bin/python -m m2.fixture_cli demo
.venv-swiss/bin/python -m m2.fixture_cli rebuild
.venv-swiss/bin/python -m m2.fixture_cli search solar
.venv-swiss/bin/python -m m2.fixture_cli read <conversation-id> <turn-id> --offset 0
.venv-swiss/bin/python -m m2.fixture_cli replay <conversation-id> <turn-id>
# For an existing synthetic conversation, questions must remain synthetic:
OPENBLAS_NUM_THREADS=2 .venv-swiss/bin/python -m m2.fixture_cli chat <conversation-id> --synthetic
```

The CLI prints an unacknowledged attempted turn ID, then confirms the durable
user-input acknowledgement before any inference. It prints committed JSONL
events, including tool call/result, source settings, measured context, partial
assistant chunks and terminal state. `replay` redelivers stored events without
loading a model or re-executing a tool. `read`
returns at most 256 events per page with `next_event_offset`; repeat with that
offset to inspect the entire original turn. `chat --parent <turn-id>` selects a
branch; `chat --parent <parent-id> --revision edit --replaces <old-id>` records
an edit sibling, and `--revision regenerate --replaces <old-id>` requires the
same user text and parent as its source. `branch <conv> <head-id>` changes active
ancestry (`@root` clears it) without deleting originals. `correct <conv>
<source-turn> <correction-id> --synthetic` reads replacement text; `withdraw
<conv> <source-turn> <correction-id>` removes the source from active recall but
retains its original labelled history. `attach <conv> <id> <synthetic-file>`,
`download <conv> <id> <new-output-path>`, `export <conv> <new-output-path>`,
`delete-attachment <conv> <id>` and `delete-conversation <conv>` cover owned
files, original JSONL export and deletion. `delete-conversations <conv> <conv>
[more...]` journals one explicitly selected group (up to 20 IDs) when source
references make one-at-a-time deletion impossible; any dependent outside the
group still blocks it. Outputs are exclusive-create mode
0600; attachment filename and content are bounded to 100 characters/1 MiB.
Export streams all turns, events, corrections, attachments and bytes rather
than truncating the archive; it is a sensitive local file, not a diagnostic log.
Deletion of the managed archive cannot revoke an earlier independent export;
remove such local copies separately when retiring synthetic fixtures.

The synthetic CLI run `.local/m2-cli-demo-indexed.jsonl` executed the real Swiss
call through Qwen: **359.9997223853829°** at the synthetic 2024 instant,
91 measured prompt tokens plus 128 reserved of 1,024, committed tool result,
explicit input acknowledgement and 61 delivered events ending in `complete`.
The CLI then indexed/updated its extractive summary; a separately authenticated
CLI invocation searched, read and replayed the stored source **without a manual
rebuild** (results in `.local/m2-cli-recall-indexed.jsonl`). If that derivative
step fails, archival completion still stands and the CLI reports its error type
and a pending rebuild instead of presenting stale recall. Those private local artifacts must not
be published. This is evidence of the selected **local** path, not of a remote
provider, external client, large model or general numerical faithfulness.

## M3–M5 synthetic walkthrough and limits

**Only owned synthetic fixture content.** The offline embedding candidate is
[FastEmbed BAAI/bge-small-en-v1.5](https://qdrant.github.io/fastembed/examples/Supported_Models/)
(English, 384 dimensions, ~67 MB ONNX, MIT according to its model listing).
The model cache occupied 65 MiB here; after adding MCP and FastEmbed the local
Python environment grew from 157 to 315 MiB. Available memory exceeded 6 GiB
during assessment. Run this one-time public model download **without any
personal text** if the cache is absent (no Hugging Face token needed):

```bash
OPENBLAS_NUM_THREADS=2 .venv-swiss/bin/python - <<'PY'
from fastembed import TextEmbedding
TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='.local/models/fastembed',
              threads=2, providers=['CPUExecutionProvider'])
PY
```

Normal indexing/query uses `local_files_only=True` and fails rather than
silently contacting a provider if that cache is absent. This model is an
**English retrieval experiment**, not a validated Danish or specialist reader.
No embedding text was uploaded; `m2/evaluate.py` used only authored synthetic
fixtures. No pgvector extension or tenant-aware ANN index is claimed. The
hybrid view ranks PostgreSQL keyword hits plus offline semantic scores over at
most **120 eligible reference and 120 current-history candidates**, returning source
IDs, speaker/source kind, provenance, rights/approval status, match flags,
pending-conversation count and truncation flags. With `--person <owned-id>`
(or the MCP person filter), unattributed general conversation history is
excluded rather than guessed to belong to that person; separately selected
reference passages remain general sources, not personal claims. A semantic suggestion is **not**
evidence that a claim is true; if no direct keyword hit exists, the deterministic
answer explicitly declines a supported assertion. `index` rebuilds at most ten
vectors per call and retains originals after a derivative failure. Keyword and
owner-scoped passage reads still work if vectors are unavailable. Long corpora
may miss older semantic-only matches outside the candidate cap. Reference
eligibility is checked while paging through at most **1,200 raw passages**;
120 newer stale passages no longer hide an older current keyword match. If the
scan limit is hit without finding one, `incomplete_candidate_scan` and
`reference_scan_truncated` distinguish that limit from an exhaustive `not_found`.
Vector rebuilding similarly pages/filter-checks before indexing up to ten
current references, scans at most 1,200 raw candidates per call and reports
`reference_scan_truncated` when the index may still be starved. No corpus-wide
semantic recall or complete indexing guarantee is claimed beyond that bound.

With the owned PG16 fixture running, run the small seed and use the IDs in its
mode-0600 JSON output. Its login/password and all names are synthetic:

```bash
umask 077
OPENBLAS_NUM_THREADS=2 .venv-swiss/bin/python -m m2.walkthrough \
  --output .local/my-synthetic-walkthrough.json
OPENBLAS_NUM_THREADS=2 .venv-swiss/bin/python -m m2.fixture_cli index
OPENBLAS_NUM_THREADS=2 .venv-swiss/bin/python -m m2.fixture_cli search-evidence equinox
.venv-swiss/bin/python -m m2.fixture_cli get-passage <reference-id> fact
.venv-swiss/bin/python -m m2.fixture_cli personal-context <person-id>
OPENBLAS_NUM_THREADS=2 .venv-swiss/bin/python -m m2.fixture_cli chat <conversation-id> --synthetic
# Enter: saved chart <chart-id>
# Or: chart events <chart-id> 2024-03-23T00:00:00+00:00 2024-03-24T00:00:00+00:00
# Or: reference evidence equinox
OPENBLAS_NUM_THREADS=2 .venv-swiss/bin/python -m m2.evaluate \
  --output .local/my-new-evaluation.json
```

`m2/walkthrough.py` records an immutable exact and interval chart, conflicting
synthetic passages and one source-linked user-reported preference. The CLI
returns an actual committed call/result and qualified answer before `complete`;
new chart/reference command paths are deterministic because the tiny model was
observed to repeat stale answers and omit uncertainty. No model is loaded for
those commands. An ordinary or follow-up question does use Qwen with measured
selected-branch context; previous chart tool facts can be included from the
stored result rather than inferred from prior prose. The same owner-scoped
`Charts` and `References` services back a **locally tested MCP 1.30 stdio
adapter** (`m2/mcp_server.py`, both in-memory protocol and subprocess tests).
Its session is authenticated *before* tools are served and has no account
selector, network listener, unrestricted shell/file tool or capture hook.
An external MCP-only host still does **not** satisfy full conversation capture
or bounded client-managed context. The standalone adapter requires a controlling
TTY for local password entry; the synthetic subprocess test uses explicitly
fixture-only credentials. No GUI, multi-person selection UI or real host is
implemented.

The locally executed walkthrough is in `.local/m3-m5-walkthrough-{checked.json,cli.jsonl}`:
three CLI chart/reference turns completed with `rebuild_pending=false`; an
independently authenticated search/read returned owned passage and personal
context. `m2/evaluate.py` created and dropped its own fixture DB. Its eight
synthetic cases and raw replies are in `.local/m3-m5-evaluation-checked.json`:

- **Numerical checks:** exact supplied-time Sun was 359.999722° at the independent
  USNO 2024 March equinox minute (within the declared three-minute oracle);
  a ±12-hour supplied interval crossed 0° and explicitly had no single natal
  sign or reference-time birth fact. The March 23–24 closed window returned
  zero Sun-to-natal-Sun conjunction events, not an invented crossing. Vulcan
  ambiguity, Vulcanus unsupported, DST gaps/folds, out-of-range dates and
  within-60-second event timing are covered by focused connected/core tests.
- **Retrieval relevance (separate from answer claims):** `equinox` ranked the
  authored `equinox` fixture first and returned both contradictory fictional
  interpretations separately (`optimist`, `skeptic`); `personal change` returned
  both conflict passages. `unfindable comet` returned semantic-only candidates
  despite no keyword evidence, so its answer explicitly says no direct passage
  matched. These four fixtures are synthetic, **not Kat-approved sources**.
- **Generated-claim support, inspected separately:** deterministic tool answers
  repeat stored numeric status/method/window or quote attributed passage IDs;
  they do **not** endorse the fictional interpretations. The indirect-instruction
  source was surfaced *as quoted source text*; it did not gain a tool/action path.
  The local Qwen follow-up repeated the stored 359.999722° result and noted that
  birth accuracy and extra aspects were not verified, but rendered raw sign index
  `11` awkwardly. The ordinary sky reply completed without tool claims but was
  generic. Neither is a general faithfulness, tone or Kat usability verdict;
  no human Kat assessment was fabricated.
- **Context:** the model's immediate chart follow-up saw structured chart-result
  evidence at 829 prompt + 128 reserved tokens (1,024 cap; three old turns
  omitted). The later ordinary turn used 724 + 128, with 21 older turns omitted;
  the exact chart result was then outside that bounded prompt. The explicit
  chart retrieval tool remains available. Deterministic tool-only turns have no
  model context budget to report. All original events remain in the archive.

New records use immutable owner-scoped people, birth records, calculation
profiles/revisions and chart versions. The legacy solar-only tools compute
**tropical geocentric apparent Sun**, fixed-solar aspect geometry and bounded
solar crossing. The separate natal path computes the positions and major aspects
in [`NATAL-CHART.md`](NATAL-CHART.md); Moon/other-body events, stations,
rectification, MCp and specialist compatibility remain unsupported. Legacy
unknown time is an explicitly supplied <=24h UTC interval; the one-step browser
flow instead derives the entire historical local day from its selected IANA zone
(23/25 hours at DST boundaries). Neither invents noon. Saved charts link exact source turns when
supplied; changing settings creates a new profile/chart version rather than
mutating old conversation evidence. The one-step birth-to-chart API at
`POST /api/people/{id}/generate` uses a durable request ID and fingerprint inside
one transaction; a lost acknowledgement can be retried without duplicate draft,
birth, profile or chart. Offline place lookup at `POST /api/places/search` is
bounded and has no provider/geocoding calls; see [`data/README.md`](data/README.md).
Tool calls/results link to their immutable
chart version or source passage in the same PostgreSQL transaction as the event.
Personal entries retain user-report / explicit second-turn confirmation / agent
inference status and source event IDs, and are shown only on their active branch.
Reference ingestion is intentionally **synthetic-fixture-only** with rights and
provenance fields and `not_kat_selected` status; there is no book import, mass
scraper or trusted interpretive library. A read-only candidate-source proposal
with primary rights links is in `m2/STARTER-SOURCES.md`.

Corrections/branch changes transitively invalidate source-linked dependent
conversations and fence stale tool claims and descendants generated against an
**earlier** correction revision from current context/search, personal context
and vectors. A newly generated turn snapshots its direct parent's latest
correction sequence; explicit `--parent` uses that selected ancestry even if a
sibling branch is active. New replies based on the latest replacement remain
current; old originals and pre-correction descendants remain inspectable as
historical. Original chart/reference sources tied to a corrected turn remain
superseded rather than silently changing their immutable provenance. Explicit person/reference deletion is
journalled for old-backup replay. When an original source has been quoted into a
*different* conversation, delete that dependent conversation first: otherwise
its immutable archived event would still contain deleted material. For a cycle,
explicitly select the whole dependent group using `delete-conversations`; a
reference from outside that group still rejects deletion. This fail-closed
precondition avoids silently erasing unrelated conversation content.
Conversation deletion then cascades source-linked chart/reference/notes and
cached vectors. Export includes linked chart, personal and reference source
versions, with stale labels; it is an independent local copy and must be removed
separately if later deleted. An old-backup restore replays newer conversation,
person and reference tombstones before access. An earlier synthetic M2 snapshot
previously restored under migrations `001`–`007` and its three conversations
were readable (`.local/m3m5-legacy-restore.json`; test target DB/files removed).
A synthetic legacy-schema upgrade through `008` is exercised in connected tests;
that earlier saved snapshot has not been rerun through this final migration.
These local rules do not solve real-data backup retention, source redistribution rights, database RLS,
file-level cross-owner deduplication or external-client ingestion.

## Saved timing and private person records (local-only)

Person timing pages **saved** advanced results by immutable source chart and the selected UTC interval. Each row carries its technique, method version, source status and original result ID; the opened result uses the exact owner-scoped saved original. A dated point is not a prediction, a gap is not a no-event finding, and this is not an exhaustive ephemeris scan. The Now header describes the source's saved interval, never an inferred personal state. Source status and stale-source labels remain visible. Saved/manual calculation pages are the sources; no model request is made to load them.

A person may explicitly choose one saved crossing for **Discuss this result**. The retry identity includes that exact result, event index, UTC instant and person; the server verifies the source on acknowledgement and stores it with the user turn, then attaches bounded source/version/crossing evidence. A source invalidated before acknowledgement fails closed. Unselected browsing is not a discussion and neither browsing nor creating a watchlist sends a model request.

Watchlist reminders are owner-scoped, opt-in, local in-app date/time entries; there is no background scheduler, push, email or automatic chat. UTC, local wall time, timezone and DST occurrence are explicitly stored; same-ID writes/retries are idempotent. Private journal entries are owner-scoped local records, **not** semantic recall, provider context, model tools or conversation attachments. They link a saved result only for private navigation and remain private when discussing a result. Person/conversation deletion replay removes these projections when an older backup is restored with the independent newer deletion journal; exported old snapshots remain separate copies. No migration or service activation is implied by these local source changes.

Animation was not added: on the owned Swiss fixture, 31 directly calculated daily sky snapshots × 10 bodies took 0.005 s, but interpolating two month endpoints missed Mercury's retrograde midpoint by 9.479°. A future motion UI would need individually calculated, dated frames and frame-by-frame qualifications; a smooth endpoint tween would misrepresent the sky.

## Boundaries and evidence

- PostgreSQL schema migrations `001`–`008` are transactional/versioned, from
  the original turn/revision archive to owner-scoped chart, reference, embedding,
  exact tool-evidence and correction-lineage records. Migration `008` leaves
  existing turn/correction parent revisions NULL; if a legacy descendant's
  parent was corrected, its unknown generation revision fails closed rather
  than assuming it consumed that correction. New turns snapshot their parent's
  latest correction revision at creation; new corrections snapshot their own
  parent's revision. Original archived events are never rewritten. `(owner_id, conversation_id, turn_id)` and
  `(owner_id, conversation_id, attachment_id)` preserve colliding IDs across
  owners. Access methods derive ownership only from an in-process session
  returned by password verification; no caller-supplied owner selects data.
  Direct code or PostgreSQL-superuser access is outside this local CLI boundary.
- A user event and turn commit in one transaction **before** tool/model call;
  each tool event/model chunk/terminal status commits **before** delivery.
  Same-ID retries match prompt, parent, revision and attachment IDs and replay
  stored events page-by-page; conflicting IDs fail. Only a complete turn becomes
  the active head. Exclusive advisory-lock ownership gates migrations and
  startup recovery; open turns become `interrupted` without execution. A failed
  write or tool leaves an open turn for explicit recovery, never apparent
  completion. Zero delivered-but-uncommitted tail is observed locally; the
  upstream uncommitted chunk/reconnect loss for any remote model is **unknown**.
- The local Qwen test path keeps at most four selected completed ancestor turns
  plus one branch/epoch-matching **extractive** summary of at most twelve older
  turns; older omissions remain visible in its context event. The hosted path
  instead projects eligible active-branch turns and the current selected chart
  facts once. It triggers **before** dispatch when estimated next input plus
  reply planning reserve approaches model capacity, leaving up to 16,384 units
  of compaction headroom and retaining roughly 20,000 recent estimated units
  when possible. Completed user/tool call+result/assistant turns are indivisible;
  call/result snippets in a summary source are bounded at 2,000 characters,
  never truncated in the original archive. It summarizes retired eligible turns
  under a separate versioned astrology summary instruction with no tools or
  media, verifies completion/format/4,096-character bound and strict next-prompt
  fit, then atomically appends a checkpoint with covered turn IDs, kept boundary,
  source digest, selected person/chart and model/prompt identities, count method
  and any actual reported summary usage (`014_compaction_checkpoints.sql`).
  Successive summaries incorporate the prior checkpoint and newly retired turns;
  they do not stack every prior summary or silently omit a mandatory question or
  selected calculation. An older checkpoint is reusable only on the same owned,
  valid lineage, branch revision, source digest, selected scope and model/prompt
  policy. Corrections, branch switches and draft/source invalidations advance a
  separate compaction revision; ordinary completed turns leave the prior valid
  checkpoint available. Original turns and private JSONL exports are unchanged.
  Summary failure, cancellation, incomplete/length-stopped output, attempted
  tool call or concurrent source change cannot advance the kept boundary; the
  new archived turn is terminal and never rerun by retry. A small or newly
  switched model may require a fresh bounded summary or fail if its source
  cannot fit; there is no speculative provider retry or silent model switch.
  Local token counts use the actual Qwen tokenizer (2048 context, 128 reply reserve
  in the normal CLI); hosted text uses roughly one estimated unit per two UTF-8
  bytes, **not** provider tokenization or measured image/PDF cost. Hosted budget
  resolves optional validated `context_window`/`max_output_tokens` catalog
  extensions **independently**; the public [Models API](https://developers.openai.com/api/reference/resources/models/methods/list)
  does **not** promise either field. For `gpt-6.1-sol` without an advertised
  bound, the [API model specification](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
  supplies that bound's fallback (1,050,000 context or 128,000 maximum output).
  Thus a catalog row with only `context_window=500000` keeps the advertised
  500k context and uses the public **output** ceiling without claiming the
  catalog advertised 128k or that the direct-plan grant verified it. A present
  but malformed field (including null or bool) fails closed; other model slugs
  need both advertised bounds. Codex/ChatGPT Work's separate 500k default and
  the >272k API pricing threshold do not establish another route's live limit.
  Each context event identifies both bounds' sources/route verification separately,
  the text-estimation method and at most 16,384 units of reply-planning reserve
  (also bounded by the output ceiling and a quarter of smaller context windows).
  This reserve is **not** a request to
  generate that many tokens or a provider output cap. Unknown model capacity
  fails before inference rather than silently assuming 4k; malformed advertised
  limits fail closed. An advertised context field does not prove that a real
  inference at that size succeeds; no live inference or quality was tested.
  The local path may omit its extractive summary then oldest recent turns on
  overflow. Hosted compaction refuses a mandatory overflow before summary spend;
  if old context cannot be safely compacted it reports an actionable terminal
  error rather than dropping selected facts or the current request. Hosted
  `response.completed.usage` is archived only when valid positive provider
  usage exists; a matching prior model/chart/prompt/boundary can use input usage
  plus trailing estimates as a **trigger** signal, never as exact preflight.
  Zero/missing/stale usage falls back to explicitly labelled text estimates.
  `max_output_tokens` is set only for the **summary request**, bounded by the
  model's documented maximum and remaining window; it is distinct from the
  model's maximum, app reply reserve and compaction headroom. The stable product
  instructions in `m2/prompting.py` have separate local/hosted texts under a
  version and SHA-256; each model-backed new turn archives their identity in its
  context event, and exact prior versions remain reconstructible from Git history.
  Local instructions occur once in ChatML; hosted instructions occur once in the
  Responses `instructions` field, not again in the user input. Archived turns
  and retries are not rewritten. The text is not a source corpus, tool loop,
  permission grant or a guarantee of model faithfulness. Older
  original events remain in PostgreSQL. A turn with >256 events remains fully
  pageable/exportable but derivative rebuild rejects rather than quietly
  indexing an incomplete transcript. Low-level ChatML delimiters in retrieved
  text are neutralized; neither this nor a prompt is an authorization boundary.
  Direct Responses streaming holds at most eight bounded completed native output
  items until `response.completed`; a successful footer that omits `output` or
  supplies `[]` uses only verified `output_item.done` items, never an added-only
  call. A populated footer is checked against streamed IDs, names, arguments and
  completed contents; opaque reasoning is retained transiently for the current
  `store:false` stateless continuation, never archived. Visible text deltas are
  committed once; completed message text can supply only the missing suffix.
  Multiple calls, unfinished items, conflicts, unknown kinds and unsupported
  message content stop before a new tool executes. The single read remains
  owner-scoped to the archived per-turn chart selection at execution.
  `unsupported_provider_output` archives fixed categories, bounded item
  kinds/counts and presence/completion flags—no output, arguments, text or
  reasoning. Exact archived retries never resend. One authorized live metadata
  observation at `db91e2b` showed an announced call and no final output items,
  but did **not** reveal whether that item completed, the final `output` field was
  omitted versus empty, or any raw provider content. This assembly correction is
  proven only on synthetic streams until separately approved live verification.
  Model-directed reads have **no fixed conversational read or provider-round
  count**. A completed native call and its matching bounded result commit before
  every stateless provider continuation; the model chooses when to answer.
  Independent guards remain: up to 16 KiB of UTF-8 model projection per read,
  32 KiB of aggregate model evidence with an honest limit-result reserve, and
  the selected route's conservative context estimate with a reply reserve.
  Cancellation, archive failures and protocol errors stop continuation; no turn
  or tool is silently retried. Duplicate native call IDs fail as a distinct
  protocol error, not as a normal exhausted read allowance. A whitespace-only
  response after reads is not a completed answer. The
  owner-scoped authoritative `tool_result` event can hold up to 64 KiB to
  preserve bounded source-search matches and a full transit chart; all other
  events retain 16 KiB. These are application evidence limits, not model token
  counts or the provider's unverified output ceiling. Transit projections retain
  all placements/angles/uncertainty and the bounded aspect lists where they fit;
  an aspect total/shown count and archive reference distinguish any model-only
  omission. History windows, attributed search excerpts and passages may shorten
  only their model projection with explicit nonexhaustive labels; original
  owner-scoped events, source rights, provenance and numerical results remain
  accessible. An oversized archive read, per-call projection, aggregate read or
  provider context is a structured incomplete tool output (or an explicit
  context error when even that cannot fit), not a falsely empty match or an
  unlimited retry. If even the incomplete-result notice cannot fit the
  32-KiB model-evidence ceiling, the complete bounded result remains archived
  and the turn stops with `tool_result_capacity` before another provider call;
  this byte guard is not a conversational read-count policy. Limit diagnostics expose only
  scope, bounded byte/unit counts, round number and projection status, never
  private text/arguments. A separately approved metadata-only live turn after
  `6f35259` progressed past the parser but ended `tool_result_capacity` before
  its third requested read result; which read and which old byte guard tripped
  were not observed. This repair is source/synthetic evidence, not a claim that
  the original chat works live. A later separately approved live metadata-only
  turn at `6f35259` passed the parser/budget guard but stopped at
  `tool_round_limit` after three model-requested reads and four archived results,
  with zero assistant text; no duplicate ID was established. The count-free
  continuation change has not been activated or tested live. Exact-tip
  activation and one deliberate live test require new approval.
- M2 keyword search uses a separate PostgreSQL `simple`-language tsvector index
  of only the active branch; M4 hybrid recall is a distinct bounded view over
  attributed reference passages and current search entries, optionally including
  offline local embeddings. Default 10/max 20 results,
  200-character snippets and max 80-character query; each row links to its
  conversation, source turn/correction and speaker. Stale epoch indexes are
  invisible while `pending_conversations` reports unfinished rebuilds.
  Explicit corrections/withdrawals invalidate summary/search via epoch and
  queued work; rebuild checks current epoch before committing. Failed
  summarization cannot remove originals; the queue remains pending for retry.
  Old branches and corrected originals stay available through owner-scoped
  explicit reads/export, labelled with their revisions/corrections, not silently
  inserted into current continuity. An explicit parent selects its branch for
  this turn's context without changing unrelated branches' archived contents.
- Attachment reads authorize the owner-scoped **reference** before deriving a
  SHA-256 blob path. Startup checks all referenced blob hashes and fails closed
  if bytes are missing/corrupt; shared blobs are removed only after the last
  reference is deleted. Blobs may physically deduplicate across local synthetic
  accounts; authorization is at the database reference, not file-level tenant
  isolation. Do not treat this as ready for real multi-user private attachments.
  The external deletion journal contains identifiers only, is fsynced
  before database deletion, and survives separately from backups. A separately
  fsynced local `.tip` file records its latest length/hash; an isolated journal
  truncation fails closed before startup or restore. A failed journal-tip update
  or post-journal DB delete blocks serving until reconciliation; a damaged tip
  cannot be silently regenerated. Deleted conversation, attachment, person and
  reference IDs cannot be reused while their tombstones remain. The gateway does not grant tools
  filesystem/shell/network permissions; tool output and retrieved text are
  untrusted data. Routine CLI errors report only an error type, not payloads,
  prompts, passwords or DB connection strings.

Connected tests exercise allowed/denied access with colliding IDs, transaction
order through a second PostgreSQL connection, real tool invocation, same-ID
replay with tool reinvocation forbidden, a killed child process followed by
recovery, storage refusal, branch edits/regeneration, actual bounded prompts,
source-linked search across a new login, stale/corrected/withdrawn recall,
actual failed summary insert, long replay pagination, shared attachment deletion,
pending rebuild after deletion and restore of a database/file snapshot that
predates deletion. They do **not** prove external client capture, remote streaming
semantics, multi-process serving, RLS, production backup guarantees or model
answer quality. The older M1 chart and capture probes remain separate regression
evidence; SQLite is not a substitute for these PostgreSQL tests.

## Local backup, restore and retention

Quiesce all CLI writers, then back up the **owned** fixture and its matching files
using the source files path and the **independent**, previously created journal:

```bash
umask 077
.venv-swiss/bin/python -m m2.maintenance backup .local/m2-snapshot-new \
  --files .local/m2-runtime/files --ledger .local/m2-runtime/deletions.jsonl
.venv-swiss/bin/python -m m2.maintenance restore .local/m2-snapshot-new \
  --files .local/m2-restore-new-files --ledger .local/m2-runtime/deletions.jsonl
```

Use a **new** snapshot/files path; neither command overwrites existing paths or
an existing DB. Restore creates a uniquely named database only in the recorded
owned fixture, checks dump/blob hashes, journal identity/prefix **and the
separately retained current `.tip`**, then replays *all* later tombstones
**before** returning a Store that can authenticate or serve history. If the
journal or its tip is missing, mismatched, truncated or corrupt, restore fails
closed and the partial target is never exposed. Existing pre-tip journals are
not silently attested from their current bytes: restoring them requires
independent evidence of the latest deletion state and an explicit migration
procedure, not an invented current tip. The existing local synthetic runtime
journal predates this guard, so old CLI snapshots have **not** been certified
under it. Both copies rolling back together cannot be detected by this local
scheme; independent retained history and a real-data retention/destination
policy remain prerequisites before any production or personal-data use. `m2/maintenance.py`
reports its newly created DB name for explicit inspection/cleanup; tests drop
their own restored DB automatically. The one-off local maintenance smoke recorded
successful backup/restore against the final migrations in
`.local/m2-maintenance-{backup,restore}-checked.json` and removed only that
test's restored DB/files. The saved synthetic snapshot also restored into a
**newly started owned container** after the original was removed; a fresh login
found its indexed synthetic discussion (`.local/m2-cross-restore.json` records
the isolated target ID, subsequently cleaned). The deletion-after-backup replay
is independently exercised by the connected restore test. Backup assumes the
single owner is quiesced; it is not a concurrent multi-writer snapshot protocol. No backup is
allowed to be used as a live archive without replaying its independently retained
newer deletion journal. The journal is not copied *as the only source* into a
same-time snapshot.

**Local synthetic-test policy:** keep an owned ephemeral fixture only while
running local experiments; remove it with the explicit stop script after the
work. Keep both the independently protected deletion journal **and its latest
`.tip`** for as long as *any* older snapshot might be restored; remove obsolete
synthetic snapshots explicitly
once tests no longer need them, then the journal and file fixture can be retired
together. A deletion immediately removes live database references and unshared
blobs, but **older offline snapshots may still contain the deleted bytes** until
they are explicitly removed. No claim of immediate erasure from backups is made.
Real personal-data backup retention, provider/data destination, authentication
upgrade and deletion policy remain separate decisions/gates before real M2
history is used. This local experiment does not authorize that use.

Engineering consultation: the central KB pattern index and .NET tenant-isolation
reference (implementation/tests) informed composite ownership, while the
security/agent trust, domain/data contract, risk-based testing, exception/failure
boundary and recovery guides informed local Python/PostgreSQL boundaries. No
.NET-specific API is transplanted into this Python application.
