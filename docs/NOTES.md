# Work log

Ongoing log of architecture decisions, corrections, and dead ends. Annotated after each work session — not a blow-by-blow transcript. See [BACKGROUND.md](BACKGROUND.md) for prep notes and [PLAN.md](PLAN.md) for the phase checklist.

Format per entry: `## YYYY-MM-DD — short title`, then a couple of sentences on what happened and why it mattered.

---

## 2026-07-04 — Project kickoff

- Decided on Python (Flask + httpx + authlib/pyjwt + click) over Go: this project's complexity is in OAuth/PKCE/JWT plumbing, not the server, and Python's ecosystem covers that with less hand-rolled code.
- Scaffolded repo structure: `server/`, `client/`, `cimd/`, `docs/`.
- Still open: which authorization server to use (must support CIMD, not just DCR) — this is Phase 0 in [PLAN.md](PLAN.md) and blocks everything else.

## 2026-07-04 — AS shortlist: Authlete + WorkOS (SaaS over OSS)

- Ruled out open-source ASes (e.g. Ory Hydra): mature MCP tooling exists, but it's built around Dynamic Client Registration — CIMD support is an open, unresolved GitHub feature request, not a shipped capability. CIMD is a very new spec addition (IETF draft reached working-group status October 2025; MCP adopted it as the recommended default November 2025), so support is concentrated in vendors who built specifically for the MCP/agent ecosystem rather than general-purpose OAuth infra.
- Evaluated SaaS candidates on concrete signals of shipped, tested CIMD support (not marketing prose): versioned/opt-in feature flags, dev-mode metadata re-fetch controls, depth of security-mechanics documentation (self-reference validation, redirect URI matching), MCP-specific (not generic OAuth) framing.
- Shortlisted **Authlete** (CIMD as an explicit versioned, opt-in service flag with a documented forced-refetch mechanism for dev — reads as a shipped, testable feature) and **WorkOS** (close second; deepest write-up on CIMD security mechanics, MCP-aware docs).
- Both picks are **provisional pending the Phase 0 spike** — documentation depth is a proxy for implementation quality, not a substitute for actually driving a PKCE + CIMD flow via curl against each.
