# Kat workspace routing

Before non-trivial implementation or review, follow the central engineering knowledge consultation workflow in `~/repos/engineering-knowledge/AGENTS.md`. This checkout's scripts and skills are local, not global agent settings.

For UI, interaction, user-facing copy and perceived-performance work, read `.local/UX-MANIFEST.md` when present. It records the user's local UX direction for already-authorized changes; it does not expand feature, data-access, review or runtime authority.

For local synthetic verification use `.agents/skills/kat-isolated-validation/SKILL.md`; for model-requested read/Responses regressions use `.agents/skills/kat-provider-continuation-regression/SKILL.md`. Before any separately approved local service activation use `.agents/skills/kat-local-activation/SKILL.md`; before a separately approved single real-provider check use `.agents/skills/kat-approved-live-check/SKILL.md`. All four default to non-mutating plans; executing a script or supplying a flag is not itself user approval.

Never substitute the live app/port 8765, real provider, user/private fixtures, or served `web/dist` for isolated tests. Do not push, deploy, activate or send live traffic without the user's direct scoped instruction. Preserve the existing branch's exact-tip, immutable archive and ownership checks.
