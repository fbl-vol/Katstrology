---
name: kat-approved-live-check
description: 'Plan or, only with separate exact-scope user approval, attempt one prefilled Kat UI send and inspect archived metadata. Use for an approved single live provider continuation check. Differentiator: durable one-attempt guard before click; never resends an ambiguous attempt.'
---

# Kat approved live check

**No live send is authorized by this skill or the current batch.** Plan with `python3 scripts/live_check.py send --commit <clean-sha> --origin http://127.0.0.1:<port> --session <existing-playwright-cli-session> --question-sha256 <digest> --model-slug <slug>`. No browser opens during a plan. The already-authorized browser session must be signed in, on an existing conversation with its draft entered and selected chart scope; this helper never logs in, pastes text, selects an account/chart, reads credentials or touches browser storage. Do not create a session on the live app as a shortcut.

A later user instruction must approve the exact tip, origin, existing session, **one question digest**, model and selected person/current-chart IDs. Record that approval in a private `.local` JSON receipt with exactly `{"action":"one-live-send","approval_id":"unique-token-8+chars","commit":"...","origin":"...","session":"...","question_sha256":"...","model_slug":"...","scope":[["person-id","current-chart-id-or-null"]]}`. `--execute --approval-file <receipt>` is only a gate for that separate approval, not authorization by itself. The helper checks UI readiness and hashes of the prefilled draft and selection, then atomically persists a one-send guard **before** a single click. It exits with status 2 for an ambiguous attempt, including when a click succeeds but ACK is not verified. A timeout, lost response or exception must **never** trigger another send with that approval. Never delete or reset the guard to replay.

Run `observe` with the same arguments, receipt and `--execute` in a separate invocation to read only archived event/count/status metadata through the same session. It may return `ack-unknown`, `open`, `error` or `empty-or-inconsistent-answer`; none proves success. It never calls send. No raw question, answer, chart result, provider payload, cookie or account details are reported. Use only after exact-tip activation is independently approved and complete; synthetic checks are not live-provider evidence.
