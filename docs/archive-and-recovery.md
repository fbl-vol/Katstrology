# Archive and recovery

[Documentation index](README.md) · [Packaged deployment](../deploy/README.md)

## Durable originals and ownership

One Store owns the PostgreSQL advisory lock and one serialized worker/connection.
Startup applies transactional migrations through schema24, verifies referenced
files and deletion authority, and marks open turns interrupted without rerunning
inference. HTTP requests do not create independent Stores. CLI/MCP are not safe
concurrent writers to the browser's live archive.

Sessions derive ownership from password verification, not caller-provided owner
IDs. Composite owner/conversation/turn and attachment identities preserve colliding
IDs across accounts. Direct database-superuser/code access is outside this API
boundary; database RLS and file-level tenant isolation are not claimed.

Input commits before inference; tool results, output chunks and terminal state
commit before delivery. Same-ID replay checks request identity and never reruns a
tool/provider call. Only completed turns advance the active head. Read pages have
at most 256 events and expose the next offset; JSONL export streams all originals,
not just the displayed page. Export is a sensitive independent copy, not a log.

Corrections, withdrawal and branch changes retain originals but invalidate current
search, summaries, vectors and source-linked derivatives transitively. New replies
snapshot the selected parent's correction revision. Legacy unknown revisions fail
closed. Historical user questions can remain dialogue while old assistant/chart
facts are excluded as current evidence. `repair-continuity` repairs pre-existing
cached derivatives in owner-scoped batches of at most ten with `next_after`; it
requires separate repair authority and does not rewrite turns or run at startup.

Keyword search defaults to ten/max twenty results, 200-character snippets and
80-character queries. Stale epoch indexes stay invisible; pending rebuilds remain
visible as unfinished work. A derivative failure never removes originals.

## Files and deletion

Authorize an owner-scoped reference before resolving its SHA-256 blob path. Blob
hashes are checked at startup; missing/corrupt bytes fail closed. A shared blob is
removed only after its last reference. Physical deduplication is not file-level
tenant isolation. Current browser person-file ingress is closed; retained legacy
files still participate in backup, original attribution and deletion reconciliation.

The identifier-only deletion journal is fsynced before database deletion; its
separately fsynced `.tip` attests length/hash. Journal/tip failures block serving
until reconciled. Missing or truncated authority cannot be silently recreated.
Deleted identities cannot be reused while their tombstones remain.

Delete dependent conversations before referenced people/sources. For cycles, the
CLI's explicit `delete-conversations` selects up to twenty IDs atomically; any
dependency outside that group still blocks deletion. No unrelated thread is
silently erased. Independent exports and older offline snapshots may retain bytes
after live deletion; remove those copies according to your retention policy.

## Local owned-fixture backup and restore

Quiesce writers first. Use the matching files and existing independent journal,
new output paths and only your intended owned fixture:

```sh
umask 077
.venv-swiss/bin/python -m m2.maintenance backup .local/synthetic-snapshot-new \
  --files .local/m2-runtime/files --ledger .local/m2-runtime/deletions.jsonl
.venv-swiss/bin/python -m m2.maintenance restore .local/synthetic-snapshot-new \
  --files .local/synthetic-restored-files --ledger .local/m2-runtime/deletions.jsonl
```

These are stateful operations, not source-validation commands. The adapter invokes
PG16 dump/restore inside the exact owned fixture, not a host client with a different
major version. Restore creates a new database/files target, verifies dump/blob and
reference-package hashes and journal identity/prefix/current tip, then replays
newer tombstones **before** returning an accessible Store. Existing targets are
not overwritten; partial failed targets are not exposed. The command reports the
new database identity for explicit inspection/cleanup.

Keep the independently protected journal **and current tip** while any older
snapshot may be restored. Never use only a snapshot-time journal as current
authority. A pre-tip journal requires independent evidence and an explicit
migration, not an invented tip. Joint rollback of journal and tip cannot be
detected by this local scheme; independent retention remains essential.

Packaged backup/drain/schema transitions use different installed contracts and
explicit runtime paths; follow the [deployment guide](../deploy/README.md).
Synthetic restart/restore tests are not proof of your real backup destination,
off-server recovery, retention policy or private-data authorization.
