# Work log

Ongoing log of architecture decisions, corrections, and dead ends. Annotated after each work session — not a blow-by-blow transcript. See [BACKGROUND.md](BACKGROUND.md) for prep notes and [PLAN.md](PLAN.md) for the phase checklist.

Format per entry: `## YYYY-MM-DD — short title`, then a couple of sentences on what happened and why it mattered.

---

## 2026-07-04 — Project kickoff

- Decided on Python (Flask + httpx + authlib/pyjwt + click) over Go: this project's complexity is in OAuth/PKCE/JWT plumbing, not the server, and Python's ecosystem covers that with less hand-rolled code.
- Scaffolded repo structure: `server/`, `client/`, `cimd/`, `docs/`.
- Still open: which authorization server to use (must support CIMD, not just DCR) — this is Phase 0 in [PLAN.md](PLAN.md) and blocks everything else.
