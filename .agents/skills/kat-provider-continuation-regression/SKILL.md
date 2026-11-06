---
name: kat-provider-continuation-regression
description: 'Select synthetic Kat Responses streaming and model-requested read regressions, including many reads, ID/order/capacity, cancellation and browser archive replay. Use after changes to provider continuation or tool evidence. Differentiator: focused tests through owned local fixture, never a real-provider exchange.'
---

# Kat provider continuation regression

Plan: `python3 scripts/regress.py --case all`. Available cases: `stream`, `identity`, `many-reads`, `capacity`, `browser`, `all`. With local isolated-test authorization, append `--execute`. It delegates to `kat-isolated-validation` for an owned ephemeral PostgreSQL fixture and, for `browser`, the synthetic fake-plan/SIWC route. It never opens a real provider or points at port 8765. The browser case uses a title filter; a test rename requires updating that filter and verifying tests were actually selected.

Read `tests/provider/test_provider_output_compat.py`, `tests/chat/test_agent_reads.py`, `tests/chat/test_tool_evidence_budget.py`, and `web/tests/provider/siwc.spec.ts` before extending regression coverage. Protect completed native tool IDs and call/result order, model-directed reads without a count ceiling, byte/context guards, cancellation, archive refusal and replay. Output reports only selected tests, their bounded result summaries and ignored synthetic log paths. This is not approval to activate, run a live check or change prompt policy.
