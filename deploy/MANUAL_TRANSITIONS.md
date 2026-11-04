# Explicit human-signed schema transition

This extends the existing protocol4 manual controller/access/shared phase engine.
It is not a second release mechanism, CI enrollment, an installation instruction,
or approval to operate a server. Unextended installed helpers still refuse23→24.

## Admission

Legacy same-schema plans and signatures keep their exact shape. A transition
plan additionally contains `manual_transition`:

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
  "old_source_sha256": "<exact installed old corresponding source hash>",
  "settled_existing_work": true
}
```

The whole object participates in the ordinary plan hash and fresh attempt-bound
`kat-release-approval-v1` signature. The protected manual policy must contain
exactly one identical lane in `manual_transitions`; its baseline remains23. All
original target, signer/principal/namespace, archive bounds, helper/Compose pins,
forced-command restrictions and exclusive attempt lock remain enforced. A
root-owned admission record freezes the full policy identity and signed transition
for subsequent phases. The client cannot supply `manual_admission`, `ci_admission`
or a bootstrap permit. CI rejects a manual-transition manifest.

The existing kernel checks immutable001–023 source hashes and exact024 SQL bytes,
then permits only the declared empty-table/nullable-no-default-column additions.
The tones migration creates only `account_tones`; missing preference rows mean
quiet-wonder/revision0 at read time. No backfill or migration of existing user rows.

## Direct old094 boundary and containment

Old094 has no maintenance socket. The same pinned human signer must freshly attest
that its work is settled and keep that condition until the old owner is stopped.
This is an operational condition, **not proof of a mechanically drained old
runtime**. If work cannot be kept settled, the direct lane must not execute.

Before stop, admission verifies the actual old image, selected image, schema,
source offer, immutable migration history and complete effective Compose owner.
After the old owner stops, the candidate seeds the persistent attempt fence in
shared state without opening the Store. The shared lifecycle then invokes the
**old image** for a schema23 backup, retains the independent deletion authority,
and invokes existing `m2.release_schema` with the exact admitted lane. It preserves
state fingerprints and records a post-migration baseline before promotion.

The new24 runtime starts fenced. Actual local checks, source/image promotion and
both client/server public checks precede reopening. Any ambiguous migration is
stop-only—even when the database committed24 but acknowledgement was lost. Keep
the stopped owner, active attempt, fence, original env/source and old snapshot.
Never retry migration, restart094 on24 or restore old data over current data.
After reopen, uncertain durable completion remains completion-unconfirmed rather
than killing new work. Recovery requires separate evidence and instruction.

## Local preparation and evidence

Use the isolated-validation skill and existing execution lock for tests. Relevant
suites: `deploy.test_manual_transition`, `deploy.test_manual_install`, existing
release access/pipeline/promotion/readiness/CI tests and `m2.test_release_schema`.

Build an exact clean package using `deploy.build_local`; preserve all prior
immutable packages. `deploy.smoke_local` qualifies actual archive import/native
startup. `deploy.smoke_manual_transition --old-receipt OLD094 --receipt NEW
--output NEW_OWNED_DIRECTORY --execute` runs two fresh synthetic projects:

- Real OpenSSH signatures through actual manual admission/controller/phases;
  real094→24 migration, old23 backup, new24 and old23 empty-target restores with
  newer independent deletions, default/saved tone and normal fence reopening.
- A real committed migration with injected lost acknowledgement; verifies the
  old owner remains stopped, selected env/source remain old and no replay/restore.

Root ownership is represented by a bounded owned-file adapter. Public-response
checks use a synthetic redirect/TLS-to-loopback adapter. Those substitutions are
reported explicitly: the test claims neither installed root protection nor live
TLS/Caddy/production assets. No SSH/server/provider/private-fixture access occurs.

`deploy.prepare_manual_transition` prepares a pinned offline bundle from clean
candidate/retained094 receipts and supplied current policy/runtime-image metadata.
It does not read or change a server. The bundled installer is plan-only by default;
only a separately authorized root invocation can replace the three exact helpers
and add the allowlist. It preserves the original target/signer/keys, policy23
baseline and Compose bytes, holds the shared lock and retains original files.
Partial/uncertain installation is not automatically retried or rolled back.

The draft transition deliberately has `settled_existing_work:false`; it cannot
be admitted until that fresh condition is established. Prepare a new attempt
with `deploy.release_pipeline --prepare-dir NEW_DIRECTORY --manual-transition FILE`, then obtain a
new signature. Historical094 consent/signature does not carry forward. No CI
witness, schema-number bump, standalone root SQL or bootstrap may substitute.

A successful manual24 release is not unattended-release proof. CI enrollment
remains separate; the23-only bootstrap no longer applies after direct24.
