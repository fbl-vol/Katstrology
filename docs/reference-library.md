# Reference library

[Documentation index](README.md) · [Source coverage](reference-sources.md)

Import, editorial selection, rights and claim support are separate decisions.
An imported edition is not automatically selected or endorsed. Reference text is
untrusted evidence, never instructions granting model/tool authority. Kat does
not fetch provenance URLs, OCR documents or infer printed page mappings.

## Import an explicit edition

The authenticated `m2.fixture_cli` reads only paths you provide. Use an owned
synthetic fixture for development; private library inputs require separate scoped
permission and your rights decision. Example public fixture:

```sh
.venv-swiss/bin/python -m m2.fixture_cli import-reference m2/data/openstax-seasons-manifest.json m2/data/openstax-seasons-excerpt.txt --confirm-rights
.venv-swiss/bin/python -m m2.fixture_cli select-reference openstax-astronomy-seasons-4-2-excerpt-v1
.venv-swiss/bin/python -m m2.fixture_cli get-passage openstax-astronomy-seasons-4-2-excerpt-v1 seasons-distance-axis
```

`--confirm-rights` acknowledges the inspected manifest, not Kat endorsement. The
OpenStax paragraph is an optional attributed CC BY 4.0 import fixture, not an
interpretive edition or an automatic import on installation. Legacy text admission
bounds are 128 KiB original, 32 KiB manifest, 64 passages and 4 KiB UTF-8 per
passage. Exact same-ID retries are idempotent; changed bytes/metadata require a
new immutable edition linked to its predecessor.

For full-book preparation, `prepare-book <raw-source> <extracted-leaves.json>
<metadata.json> <output-root>` and `validate-book <package>` need no database.
The separately authenticated `import-book <package> --confirm-rights` imports
without selecting. Inspect CLI `--help` for exact command syntax.

Package bounds are 16 MiB raw bytes, 4 MiB normalized UTF-8 transcript, 8 MiB
manifest, 1,024 ordered leaves and 512 exact located passages. Each passage is at
most 3,000 characters **and** 16 KiB UTF-8. These book-only bounds require a
validated package record; global Store/message limits do not expand.

Leaves retain text, nondecreasing physical page, nullable printed page, distinct
locator, section/parent and extraction/review status. Extraction is
`unverified_ocr`, `unverified_transcription` or `verified_extraction`; review is
`not_reviewed`, `sampled` or `reviewed`. Metadata retains edition/rights attribution,
processing revision and nullable predecessor/source URL. Unknown printed pages
stay unknown. Section/parent changes fence chunk boundaries and adjacent links.

Preparation is atomic/content-addressed. Canonical transcript JSON, exact slices,
raw/transcript/processing/normalized digests and locators are revalidated. Import
commits the exact validated snapshot rather than reopening mutable paths.
Interrupted or invalid revisions cannot replace a prior package. Preserved raw
bytes are the imported source, not an assertion that remote figures or unimported
sections exist. Backups verify retained raw/normalized hashes.

## Read and evaluate

Source selection is explicit and owner-scoped. Search can filter author,
tradition, technique and language. Passage reads expose bounded 4,096-character
windows with `next_offset`; book reads add page/parent/review and normalized-offset
metadata. Adjacent eligible passages require another explicit read, not automatic
whole-book forwarding. Sources consulted lists actual archived reads, not a
claim-support certificate or current-source guarantee.

The offline English BGE-small model produces 384-dimensional CPU vectors from a
hash-pinned public snapshot; missing/corrupt cache fails before encoding, without
network fallback. Keyword-only retrieval remains available. Reference vectors pool
at most 384-token windows; legacy history vectors cover at most the first 2,048
characters and may truncate. Model revision/window scheme participates in vector
identity, so upgrades require explicit rebuilds.

Hybrid scanning is bounded at 2,400 raw reference passages and 240 current-history
candidates. Rebuild indexes up to ten current references per call and reports scan
truncation. Coverage/partial-index and `incomplete_candidate_scan` flags distinguish
limits from exhaustive absence. Semantic suggestions are not truth or complete
corpus recall. Person history filters selected **turns**, including correction
lineage, not every message in a conversation containing that person. English
embedding performance does not establish Danish or specialist quality; evaluate
retrieval relevance separately from generated-claim support.

## Revoke and delete

`revoke-reference <id>` excludes reads, keyword/vector candidates and dependent
current derivatives while retaining originals. Explicit source deletion follows
conversation dependencies and the independent deletion/revocation journal. Older
backups cannot re-enable revoked/deleted sources when restored with current
authority. Originals, derived indexes and exported copies have different retention
lifetimes; see [archive recovery](archive-and-recovery.md).
