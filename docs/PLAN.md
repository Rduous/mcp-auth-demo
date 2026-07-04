# MCP Auth Project — Execution Plan & Checklist

Spec: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

Stack: Python (Flask for the resource server, httpx for HTTP calls, authlib/pyjwt for OAuth+JWT, click for the CLI).

---

## Open design questions (resolve before/during Phase 0)

- [x] **Which AS?** Shortlisted **Authlete** (top pick) and **WorkOS** (backup) — both SaaS, both claim shipped CIMD support with real engineering-level docs, unlike OSS options (e.g. Ory Hydra) where CIMD is still an open feature request. Provisional pending the Phase 0 spike below. See [NOTES.md](NOTES.md).
- [ ] **Protected tool choice** — keep trivial (e.g. `echo`, `get_time`). Signal is scope enforcement, not tool logic.
- [ ] **"Single command" CLI** — one-shot (browser pops mid-call) vs. `login` + `call` two-step?
- [ ] Confirm log-gating idea (Phase 6) is in scope for submission, or purely a bonus.

---

## Phase 0 — De-risk the AS choice (no app code)

- [ ] Host a CIMD doc at a public HTTPS URL (GitHub Pages / gist-style is fine)
- [ ] Manually drive full auth-code + PKCE flow via curl/Postman against candidate AS
- [ ] Confirm AS fetches & validates the CIMD doc
- [ ] Confirm AS enforces PKCE
- [ ] Confirm `resource` parameter is accepted and issued token's `aud` claim reflects it
- [ ] **Decision point:** if any of the above fail, switch AS now

---

## Phase 1 — Trivial unauthenticated loop

- [ ] Basic MCP server, one tool, no auth
- [ ] Basic MCP client that calls it
- [ ] Confirm base transport/plumbing works end to end

---

## Phase 2 — Add 401 + Protected Resource Metadata

- [ ] Server requires a token, returns `401` + PRM pointing at real AS
- [ ] Client discovers AS from the `401` response (not hardcoded) — **this is graded**

---

## Phase 3 — Full auth handshake

- [ ] Client does CIMD-based `client_id` + PKCE against real AS
- [ ] Client obtains token, calls tool with `Authorization: Bearer`
- [ ] Loopback redirect URI handles random local port correctly

---

## Phase 4 — Resource parameter / audience binding

- [ ] Inspect issued token, confirm `aud` claim = MCP server's canonical URI
- [ ] Don't just eyeball success — this silently "works" even when wrong in single-server demos

---

## Phase 5 — Scope enforcement + step-up

- [ ] Gate protected tool on a scope
- [ ] Demonstrate `403 insufficient_scope` path
- [ ] Demonstrate client re-running a narrow auth request for just that scope

---

## Phase 6 — Polish + log-gating idea

- [ ] Required write-up: ungated, plain markdown, public repo
- [ ] Second tool, gated behind different scope (e.g. `logs:read`), returns extended log
- [ ] Return log content in-band (not a shareable link — link can leak past scope check)
- [ ] Call this pattern out explicitly in the write-up

---

## Wrong-turn / correction log
*(add entries as they happen — a dozen sharp ones beats fifty verbose ones)*

-

## Time-cost observations
*(e.g. % effort on auth plumbing vs. tool logic)*

-
