---
name: kat-local-activation
description: 'Plan exact-tip Kat local service activation, or execute only after separate scoped approval. Use when preparing a named local service restart, migration check and served-asset verification. Differentiator: clean-commit and aggregate DB checks before and after; never a generic deploy.'
---

# Kat local activation

Plan first: `python3 scripts/activate.py --commit <clean-40-char-sha> --service <named-user.service> --origin http://127.0.0.1:<port>`. A plan does not read a DB, restart a service, build assets or send to a provider. **This batch does not approve execution.** A later user instruction must explicitly scope the exact tip, named service/origin, served `web/dist` write/restart and whether migrations are permitted. `--execute` is not approval: it also requires a private approval receipt (`--approval-file`) with exactly `{"action":"activate-local","commit":"...","service":"...","origin":"...","allow_migrations":false}` and a configured read-only aggregate DB connection in `KAT_LOCAL_ACTIVATION_DSN` (or `--dsn-env` variable). Do not put credentials in arguments or logs.

Execution checks clean exact tip, named user service identity and port, schema and read-only table aggregates, performs the ordinary build into the **configured served** `web/dist` only after approval, restarts that exact service, compares served HTML and one asset to disk, and checks schema/aggregates again. If any post-restart check fails, stop and report it: no automatic rollback or claim of success. This tool does not approve migrations, a provider exchange, publication or deployment elsewhere. Read `kat-isolated-validation` before activation; do not use a historical `/tmp` activation recipe with embedded service, commit or port.
