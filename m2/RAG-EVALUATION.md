# Local source and companion evaluation boundary

This phase exercises retrieval, rights, citation identity and read-loop plumbing,
not Kat's source endorsement, interpretive usefulness or a real provider's choice.
The selected **test** source is a single English OpenStax *Astronomy* 4.2
paragraph, CC BY 4.0 (manifest, original and attribution in `data/` and
`THIRD-PARTY-NOTICES.md`). It explains seasonal geometry, not modern Western
interpretation. No private books, real conversations, hosted inference or extra
model training are in the evaluation.

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

The current small corpus cannot answer most natal, house, progression, synastry or
personal questions with interpretive citations. A missing/irrelevant source should
be labelled unavailable or, for semantic-only suggestions, explicitly provisional;
old chat replies are not independent source authority. Retrieval can expose hostile
text as data, never give it write privileges. Long corrected/branched archive,
source/owner collisions, context capacity, cancelled reads and old-backup
non-resurrection are covered by existing isolated suites, not by new live claims.
