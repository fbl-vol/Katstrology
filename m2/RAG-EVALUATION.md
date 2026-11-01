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

The current small corpus cannot answer most natal, house, progression, synastry or
personal questions with interpretive citations. A missing/irrelevant source should
be labelled unavailable or, for semantic-only suggestions, explicitly provisional;
old chat replies are not independent source authority. Retrieval can expose hostile
text as data, never give it write privileges. Long corrected/branched archive,
source/owner collisions, context capacity, cancelled reads and old-backup
non-resurrection are covered by existing isolated suites, not by new live claims.
