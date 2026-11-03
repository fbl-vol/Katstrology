# Local source and companion evaluation boundary

This phase exercises retrieval, rights, citation identity and read-loop plumbing,
not Kat's source endorsement, interpretive usefulness or a real provider's choice.
The selected **test** source is a single English OpenStax *Astronomy* 4.2
paragraph, CC BY 4.0 (manifest, original and attribution in `data/` and
`THIRD-PARTY-NOTICES.md`). It explains seasonal geometry, not modern Western
interpretation. The public synthetic tests contain no private books, real conversations,
hosted inference or model training. A separate private, local-only check is
summarized without its content below.

| Property | Reproducible local check | Limit |
| --- | --- | --- |
| Rights and provenance | `test_reference_lifecycle`: exact UTF-8 original/hash, located span, owner isolation, same-ID retry, changed-content refusal, selection, revocation and delete; old-backup replay and indexing failure | Rights basis is from reviewed manifest, not an automated license adjudication. No OCR or page images. |
| Retrieval/relevance | `test_rag_evaluation`: independent wording for seasons, Danish-only authored fixture, tradition/language separation, no keyword match and conflicting synthetic authors | English offline embeddings rank hints, not global relevance; incomplete vector index is reported. No supported modern interpretive corpus or verified Danish translation. |
| Citation identity | `audit_citation` checks current owned eligible edition/passage and literal quote against the complete stored passage, including withdrawn/cross-owner refusal | A quote occurring in a passage does not prove the accompanying claim, and a past archived read can later become withdrawn. |
| Claim support | Manually inspect exact excerpt against claim. For this fixture, the text supports an explanation that axial tilt causes seasons, **not** a personalized square forecast, empirical astrology, medical or career advice. The audit deliberately reports `not_assessed`. | Human passage-level interpretation and Kat's selection are pending. No automated semantic support certification. |
| Numerical accuracy | Existing separate independently referenced chart/transit/return suites, not this astronomy excerpt | Never derive dates or placements from retrieved prose. |
| Chat/tool integration | `test_agent_reads`, `test_tool_evidence_budget` and synthetic SIWC browser roundtrip: normal question, model-chosen reads, commit-before-continuation, bounded actual passage windows, denial of write tools, archive replay and collapsed actual excerpt | A scripted fake provider chooses calls; no evidence of real `gpt-6.1-sol` tool selection or answer quality. No fixed read-round cap. |
| Conversation usefulness | No automated acceptance claim | Requires Kat's separate human assessment with an actually acceptable licensed interpretive collection and separately approved provider/private-data scope. |

## Measured public-only synthetic baseline

The actual pinned CPU BGE model, PostgreSQL service, source eligibility rules,
vector indexing and hybrid search were exercised in an owned isolated fixture
(`m2.test_rag_retrieval`). Seven manually labelled answer queries used passages
written before measuring rank: three English (exact, paraphrase, uncertain-time
multi-factor), three Danish (exact, paraphrase, multi-factor) and one mixed
English/Danish. The no-answer query was separate. **Top-3 labelled hits:**

| Mode | English (of 3) | Danish (of 3) | mixed (of 1) | no-answer behavior |
| --- | ---: | ---: | ---: | --- |
| PostgreSQL keyword | 1 | 1 | 0 | `not_found` |
| CPU semantic alone | 3 | 3 | 1 | Returns a ranking regardless of support |
| Bounded hybrid | 3 | 3 | 1 | `semantic_suggestions_only`, never evidence of entailment |

The bilingual test above expects **Danish passages**, so it does **not** test
Danish questions over the actual English-only private books. A separate
independently labelled **English-only synthetic** six-passage check used four
Danish questions (direct, paraphrase, multi-factor, and a stationery distractor)
plus a Danish no-answer question. All six indexed passages declare `en`;
none is a translation or private excerpt. Keyword found **0/4** labelled
answers. CPU semantic and hybrid placed the direct and paraphrase answers
**first**, the distractor answer **second**, and the multi-factor answer
**fourth** (thus **3/4 top-3**, not 4/4). All four hybrid statuses were
`semantic_suggestions_only`. The no-answer case was `not_found` for keyword
and still produced semantic-only suggestions; neither ranking nor score
certifies support. This tiny fixture is diagnostic, **not** English-book or
Danish-query quality acceptance; the private 11-query checks remain provisional.

On seven passages, indexing took **375 ms** and eight mixed-mode query checks
**288 ms** on this workstation. A second **618-passage** synthetic owner corpus
indexed all 618 vectors in **15,465 ms**; one older interpretive match behind
617 newer keyword-matching stationery distractors ranked **first** in **119 ms**
without scan truncation after removal of the former 240-eligible cap. These are
single local exact-tip `3619673` observations, **not old-server latency**. The
pre-change test lost that source; a pair of distinct end-of-passage qualifications
also previously produced *identical* 2,048-character-prefix vectors. The new
model key pins the public snapshot, FastEmbed version and 384-token passage-window
pooling; history still has separately labelled prefix-only coverage. At most
2,400 raw reference candidates are scanned, and larger/stale-heavy corpora may
remain incomplete. These labels and scores are **toy synthetic relevance only**:
they do not establish Danish book quality, claim support, calibrated abstention,
CPU/RAM fitness on the old target, or complete real-library coverage. Query and
embedding scoring cannot substitute for a human reading each cited claim.

## Fresh private offline check (content-free summary only)

A separate unserved, newly owned local PostgreSQL/files fixture authenticated
and imported **only the two previously approved immutable packages** (186 +
432 passages), selected them **only inside that disposable fixture**, and
indexed all 618 with the pinned public CPU model and windowed model key on
schema 23. The originals were checked against their prior hashes. No PDF,
query, passage, vector or detailed trace was put in this document, Pi output,
public Git or a provider request. The private detail remains locally 0600
inside a 0700 directory for human inspection; the scratch container and
credential file were removed after ownership checks.

On 11 provisional tests, four mechanical self-lookups hit in both keyword and
hybrid mode; two Danish paraphrases had no keyword match but did produce
semantic-only suggestions. The deliberately absent query had no keyword match
and still produced suggestions (not support). A short two-author keyword query
returned only one author in ten results, while hybrid returned both; this is a
measured ranking limitation, not proof either source supports the question.
Median local elapsed per query was 415 ms keyword and 403 ms hybrid (max 488
and 499 ms); import/index/query together took 183 s on this PC. These numbers
are not target-CPU capacity or an independent Danish relevance judgment.
Full human OCR, locator, source-usefulness and claim-support review remains
required before treating book passages as reliable interpretation. Private
book selection for ordinary ChatGPT reads has a distinct bounded-excerpt
egress/privacy decision, despite source readiness; do not infer consent to
hosted embedding or send an entire book to a model.

The current small corpus cannot answer most natal, house, progression, synastry or
personal questions with interpretive citations. A missing/irrelevant source should
be labelled unavailable or, for semantic-only suggestions, explicitly provisional;
old chat replies are not independent source authority. Retrieval can expose hostile
text as data, never give it write privileges. Long corrected/branched archive,
source/owner collisions, context capacity, cancelled reads and old-backup
non-resurrection are covered by existing isolated suites, not by new live claims.
