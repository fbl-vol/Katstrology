# Backend development

[Documentation index](../docs/README.md)

Kat is one Python process with a serialized Store worker, PostgreSQL and private
files. It supports a local CLI/MCP server, same-origin browser server and packaged
HTTPS deployment. These are alternative entry points, not concurrent independent
writers to the same archive. Schema migrations currently end at **024**.

## Find the owner

| Package | Responsibility |
| --- | --- |
| `archive/` | Store/transactions, conversations, revisions/provenance, attachments, deletion and backup |
| `chat/` | Turn scheduling, context/compaction, read tools, evidence, prompts/tones and title work |
| `calculation/` | Saved charts and numerical techniques, Swiss/time primitives and source qualification |
| `people/` | People, birth generation, offline places, insights, saved timing and private records |
| `references/` | Edition/package admission, bounded retrieval, embedding cache and citation audit |
| `provider/` | Optional local model, ChatGPT authorization, Responses and capacity contracts |
| `http_boundary/` | Authentication, Host/Origin/CSRF, routes and single-worker runtime lifecycle |
| `operations/` | Application clock/policy, local fixture access and synthetic walkthrough/evaluation |
| `../tests/` | Capability-grouped backend/release suites; shared database/template support |

Root entries have concrete consumers: `web_server.py` is the server/enrollment
CLI and packaged CMD; `cli.py`, `fixture_cli.py`, `mcp_server.py` and
`maintenance.py` are supported local commands. `deployment_backup.py`,
`deployment_credentials.py`, `release_drain.py` and `release_schema.py` are
packaged operational contracts. The sole internal compatibility shim,
`deletion.py`, preserves `m2.deletion.Tombstones` for the immutable installed
release helper's embedded retention script; application imports use
`m2.archive.deletion`. Requirements, model license, `migrations/`, `data/` and
owned-fixture start/stop scripts keep their externally consumed resource paths.
No second Store, deletion journal, sender or transaction boundary is introduced.

## Prepare a new development environment

Prerequisites are Python 3.11, Docker, Node/npm and Chromium. The locked backend
dependencies are in `m2/requirements.txt`; Swiss setup and exact public ephemeris
hashes are in the [probe guide](../probes/README.md). Provision dependencies only
for your intended new environment, not by modifying an existing runtime:

```sh
umask 077
uv pip install --python .venv-swiss/bin/python -r m2/requirements.txt
```

The optional Qwen fixture additionally needs its local model/native binding;
hosted-only startup does not import or require that binding. Missing Qwen is
never a browser fallback. Public embedding inputs are separately hash-pinned;
see [deployment preparation](../deploy/README.md). No private text or credentials
are required to prepare those public files.

## Test in isolation

Use [synthetic validation](../docs/testing.md), not a running archive:

```sh
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile backend
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile backend --execute --tests tests.archive.test_store
python3 .agents/skills/kat-isolated-validation/scripts/validate.py --profile all --execute
```

Execution requires approved local synthetic scope. The runner owns PostgreSQL,
per-test databases/files, build outputs and cleanup. Backend discovery recursively
loads `tests/` plus repository skill tests; probes stay separate. Direct unittest
collection must use the repository top level (`-s tests -t .`) so imported helpers
and discovered modules have the same identity. Never substitute a shared DSN,
live provider or served assets for missing fixture prerequisites.

## Use a separate local instance

Only for a new, owned standalone instance, with no existing fixture metadata:

```sh
./m2/start_local_postgres.sh
.venv-swiss/bin/python -m m2.web_server enroll
# After deliberately building web/dist for this instance:
OPENBLAS_NUM_THREADS=2 .venv-swiss/bin/python -m m2.web_server serve
# Stop the server before retiring its ephemeral PostgreSQL fixture:
./m2/stop_local_postgres.sh
```

The default local server binds loopback port 8765. Do not proxy local mode onto a
LAN. Packaged deployment has its own explicit origin/security configuration.
The fixture scripts own one uniquely named PG16 container, dynamic loopback port,
0600 password file and no host mounts; stopping it discards its database, not
independent snapshots/journals. `--state-directory`, `--served-dist` and `--port`
allow explicit server paths. Existing archives require a scoped backup/preflight:
Store construction applies migrations and interrupted-turn recovery.

## CLI and MCP

`m2.fixture_cli` prompts for local credentials and resolves only its owned fixture
without printing the DSN. `enroll demo` creates an account there; `demo`,
`chat <conversation-id> --synthetic`, `read`, `replay`, `search`, `rebuild` and
`index` exercise synthetic conversations. `--help` lists exact arguments.
Replay uses archived events without loading a model or rerunning tools.

The CLI supports branch selection, original-preserving correction/withdrawal,
attachments, private JSONL export, bounded evidence reads and explicit reference
import/selection. See [archive and recovery](../docs/archive-and-recovery.md)
and [reference library](../docs/reference-library.md) before using those operations.
`repair-continuity` is a separately authorized, owner-scoped paged repair, never
startup work. Synthetic seed/evaluation commands now live at
`m2.operations.walkthrough` and `m2.operations.evaluate`; inspect their `--help`
and use newly owned output paths.

`m2.mcp_server` is an authenticated stdio adapter with a controlling TTY for
password entry, no network listener or arbitrary shell/file tool. It shares
qualified chart/reference services, not automatic capture of an external host's
whole conversation. Model reads have a narrower read-only authority than CLI/MCP.
See [provider/context contracts](../docs/provider-and-context.md),
[natal methods](NATAL-CHART.md) and [advanced methods](ADVANCED-TECHNIQUES.md).
