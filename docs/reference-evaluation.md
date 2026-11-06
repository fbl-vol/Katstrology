# Evaluate reference retrieval

[Documentation index](README.md) · [Reference library](reference-library.md)

Evaluate these questions separately. A successful source read is not a useful
interpretation, a high-ranked passage is not claim support, and a literal quote
match is not a rights decision.

| Question | Reproducible suite or method | What it does not establish |
| --- | --- | --- |
| Are originals, rights metadata and identities retained? | `tests.references.test_reference_lifecycle`, `test_book_package`: hashes, exact spans, owner scope, retries, selection/revocation and restore | Automated legal adjudication or OCR accuracy |
| Does retrieval find the independently labelled passage? | `tests.references.test_rag_evaluation`, `test_rag_retrieval`: English/Danish wording, distractors, no-answer cases and conflicting authors | Complete corpus recall, Danish specialist quality or calibrated abstention |
| Is a quote literally from an eligible source? | `m2.references.rag_evaluation.audit_citation`: owned/current edition, passage and exact quote | Whether the quote supports the surrounding claim; audit reports claim support `not_assessed` |
| Do provider reads preserve ownership and durability? | `tests.chat.test_agent_reads`, `test_tool_evidence_budget`, fake-SIWC browser cases | Real-provider tool choice, live grant or answer quality |
| Are numerical facts correct? | Separate `tests.calculation` and `probes` suites with independent anchors | Facts inferred from retrieved prose or validated astrology |
| Is an interpretation useful and supported? | Human passage-level/source and response assessment | An automatic verdict from any test score |

## Run a public synthetic check

Use only the public fixture and authored synthetic passages in the owned runner:

```sh
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile backend --tests tests.references.test_rag_evaluation tests.references.test_rag_retrieval --execute
```

The OpenStax seasons paragraph supports seasonal geometry, not a personalized
forecast, medical/career advice or empirical astrology. Tests contain no private
books, real conversations or live inference.

Define queries and relevance labels before measuring ranks. Keep keyword,
CPU-semantic and bounded hybrid modes distinct. Include exact/paraphrase,
uncertain-time/multi-factor, language-specific, distractor and genuinely absent
queries. An English-only corpus queried in Danish is a different experiment from
a bilingual corpus containing Danish answers. Report the actual rank and cutoff,
not only successful examples.

The regression corpus includes an older relevant passage behind hundreds of newer
keyword distractors and long passages whose decisive qualifications occur beyond
the legacy prefix. Preserve those cases when changing scan/pooling behavior.
The current bounded scan can still miss older semantic-only matches beyond 2,400
raw references or with incomplete indexing. Keyword absence may yield
`not_found`; semantic ranking can still produce `semantic_suggestions_only`, not
support or proof of an answer. Inspect coverage flags alongside scores.

## Assess a real collection separately

A private evaluation needs explicit input/egress scope, verified edition/rights,
OCR and locator review, independent relevance labels and a useful source-selection
decision. Keep query/passage/vector/detail artifacts out of public source and
provider traffic unless that exact use is approved. Local embedding is distinct
from sending bounded excerpts to a hosted model; neither implies whole-book
forwarding permission.

Measure latency on the intended workload and machine rather than presenting a
development-workstation observation as production capacity. Human source
usefulness, conflicting traditions, quote-to-claim support and response quality
remain separate from mechanical integration. Prior chat replies are not
independent reference authority; hostile retrieved text stays data, not a tool
instruction.
