# Explicit human-signed schema transitions

[Documentation index](../README.md) · [Release operation](releases.md)

The manual transition lane extends protocol-4 admission and the shared phase
engine; it is not a second release mechanism or CI enrollment. The retained lane
below is specifically schema23→24. It is **not applicable to an already-schema24
installation**, cannot be replayed after completion and is not a general schema
upgrade switch. Unextended installed helpers refuse it.

## Exact admission contract

Same-schema plans/signatures retain their shape. A transition adds
`manual_transition` to the signed plan:

```json
{
  "lane": {
    "from": 23,
    "to": 24,
    "migrations": {
      "024_account_tones.sql": "523775c5caa77b398d2f8804711f12029a7c810031f66ad4505003486feb8a71"
    },
    "added_tables": ["account_tones"],
    "added_columns": {}
  },
  "old_image": "sha256:<exact installed old runtime image>",
  "old_source_sha256": "<exact installed old source hash>",
  "settled_existing_work": true
}
```

The whole object is bound by a fresh attempt's `kat-release-approval-v1` signature.
Protected policy must admit the identical lane while its baseline is still23.
Existing target/signer/namespace, archive bounds, helper/Compose pins, forced
command and exclusive lock remain mandatory. Root-owned admission freezes policy
and transition identity; clients cannot inject admission witnesses or bootstrap
permits. CI rejects manual-transition manifests.

The kernel checks immutable001–023 hashes and exact024 bytes, allowing only the
declared empty-table/nullable-no-default additions. This migration creates only
`account_tones`; missing preferences resolve to quiet-wonder/revision0 at read
time. No existing-user backfill occurs.

## Old runtime without a maintenance socket

The human signer must freshly attest settled work and maintain it until stop.
This is an operational prerequisite, not evidence of mechanical drain. If it
cannot be maintained, do not execute the direct lane.

Admission checks actual old image, selected image, source, schema/history and
complete effective Compose ownership. After old-owner stop, the candidate seeds
a persistent attempt fence without opening Store. The **old image** produces its
schema23 backup; independent deletion authority is retained. Existing
`m2.release_schema` applies only the admitted lane and records preservation and
post-migration baselines before promotion.

The candidate starts fenced. Local checks, coherent source/image promotion and
client/server public checks precede reopening. Ambiguous migration is stop-only,
even if schema24 committed but acknowledgement was lost. Retain stopped owner,
active attempt, fence, original env/source and snapshot. Never retry the migration,
restart schema23 code on24 or restore old data. After reopening, uncertain receipt
completion must not kill newly admitted work. Recovery is a separate instructed,
evidence-backed action.

## Synthetic qualification and offline preparation

Use [isolated validation](../testing.md) with `tests.deploy.test_manual_transition`,
`tests.deploy.test_manual_install`, the release suites and
`tests.operations.test_release_schema`. Build a clean immutable candidate and run
native archive qualification before transition smoke:

```sh
python -m deploy.smoke_manual_transition --old-receipt <retained-compatible-schema23-receipt> --receipt <candidate-receipt> --output <new-owned-directory> --execute
```

Two owned projects exercise native signatures/admission, real23→24 migration,
old-image backup, empty-target restores with newer independent deletions, tone
default/saved preference and fencing; the second injects lost acknowledgement
after commit and checks no replay/restore. Root ownership and public TLS routing
use explicit synthetic adapters: this proves neither installed root protection
nor live SSH/Caddy/provider/private-data behavior.

`deploy.prepare_manual_transition` prepares an offline pinned bundle from clean
candidate and compatible retained-old receipts plus current policy/image metadata.
The installer is plan-only by default. Separately authorized installation may
replace only the three exact helpers and add the lane while preserving target,
signer/keys, baseline and Compose bytes under the shared lock. It retains originals
and never blindly retries/rolls back uncertain installation.

The draft sets `settled_existing_work:false` and cannot be admitted until fresh
settlement is established. Prepare a new attempt with `deploy.release_pipeline`
using `--prepare-dir` and `--manual-transition`, then obtain a new signature.
Historical consent, CI witness, a schema-number edit or standalone root SQL cannot
substitute. After completion, finalize the consumed lane before current-baseline
CI adoption; the schema23 bootstrap no longer applies.
