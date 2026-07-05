# MCP Auth Project — Execution Plan & Checklist

Spec: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

Stack: Python (official `mcp` SDK for server + client, httpx for direct AS calls, pyjwt for token decoding, click for the CLI).

---

## Open design questions (resolve before/during Phase 0)

- [x] **Which AS?** Shortlisted **Authlete** (top pick) and **WorkOS** (backup) — both SaaS, both claim shipped CIMD support with real engineering-level docs, unlike OSS options (e.g. Ory Hydra) where CIMD is still an open feature request. Provisional pending the Phase 0 spike below. See [NOTES.md](NOTES.md).
- [x] **Protected tool choice** — `get_time` (no args). Will need a second tool (`logs:read`-gated, per Phase 6) to actually demonstrate scope *differentiation* — one tool alone can only show authenticated-vs-not, not that different scopes unlock different things.
- [x] **"Single command" CLI** — one-shot. `python3 client/main.py` does everything: discovers the AS, opens the browser, catches the redirect on a real ephemeral-port loopback server, exchanges the code, calls the tool. No separate `login` step, no manual paste-back.
- [x] Confirm log-gating idea (Phase 6) is in scope for submission, or purely a bonus — resolved: it's a bonus, and it's built. Turned out not to need Phase 7 after all — the write-up's actual design (in-repo content, served in-band) works fine locally.

---

## Phase 0 — De-risk the AS choice (no app code)

- [x] Host a CIMD doc at a public HTTPS URL (GitHub Pages / gist-style is fine) — live at https://rduous.github.io/mcp-auth-demo/cimd/client-metadata.json
- [x] Manually drive full auth-code + PKCE flow via curl/Postman against candidate AS — done against Authlete, see [NOTES.md](NOTES.md)
- [x] Confirm AS fetches & validates the CIMD doc — confirmed twice: discovery shows `client_id_metadata_document_supported: true`, and the live authorization response showed `metadataDocumentUsed:true` / `clientSource:METADATA_DOCUMENT`
- [x] Confirm AS enforces PKCE — enabled Require PKCE + Require S256 in console's Authorization tab; a request without `code_challenge` is now rejected (`A124301`)
- [x] Confirm `resource` parameter is accepted — switched service to JWT access tokens (ES256); decoded token's `aud` claim is exactly `["https://rduous.github.io/mcp-auth-demo/resource"]`. See [NOTES.md](NOTES.md).
- [x] **Resource enforcement isn't automatic on Authlete's side** — `/auth/introspection` doesn't reject a mismatched `resources` value (confirmed via a scope-check control, which does correctly reject). Our MCP resource server must check `aud`/`accessTokenResources` itself. Doesn't block staying on Authlete; changes what Phase 4 builds (see below).
- [x] **Decision point:** if any of the above fail, switch AS now — resolved: staying on Authlete. CIMD and resource-acceptance are solid; PKCE enforcement is a config fix, and audience checking will be handled in our own server code either way.

---

## Phase 1 — Trivial unauthenticated loop

- [x] Basic MCP server, one tool (`get_time`), no auth — [server/main.py](../server/main.py), official `mcp` SDK (`FastMCP`, streamable-http)
- [x] Basic MCP client that calls it — [client/main.py](../client/main.py)
- [x] Confirm base transport/plumbing works end to end — ran both locally, client got a real timestamp back

---

## Phase 2 — Add 401 + Protected Resource Metadata

- [x] Pick a placeholder canonical resource URI for local dev — `http://127.0.0.1:8000/mcp`, in [server/auth.py](../server/auth.py) as `RESOURCE_URI`, not hardcoded elsewhere
- [x] Server requires a token, returns `401` + PRM pointing at real AS — verified via curl: `401` + `www-authenticate` → `.well-known/oauth-protected-resource/mcp` → names `https://authlete.com/`
- [x] Client discovers AS from the `401` response (not hardcoded) — **this is graded**. Confirmed via the SDK's `OAuthClientProvider` source: on `401` it discovers Protected Resource Metadata, then the AS's own metadata, before ever attempting authorization. Verified live in Phase 3's testing.
- [x] **Checkpoint:** decided — call Authlete's `/auth/introspection` (network hop, live revocation check). See [server/auth.py](../server/auth.py) and [session_log.md](session_log.md).

---

## Phase 3 — Full auth handshake

- [x] Stand up a thin AS-frontend wrapping Authlete's API — `/authorize`, `/token`, `/.well-known/oauth-authorization-server`. Required because Authlete has no hosted login/consent UI (confirmed: it 404s at the well-known endpoint) — see [NOTES.md](NOTES.md). Sign-in is a **no-op** (auto-approve one demo subject) — TODO in code, real identity is a later refinement (Phase 8). Live at `authserver/main.py`.
- [x] Client does CIMD-based `client_id` + PKCE against real AS — confirmed end-to-end using the SDK's `OAuthClientProvider` + `client_metadata_url` (the "library shortcut" / option 2 path)
- [x] Client obtains token, calls tool with `Authorization: Bearer` — confirmed, real `get_time` result returned through the full chain
- [x] Loopback redirect URI handles random local port correctly — real local HTTP server on an OS-assigned port, no manual paste-back. Confirmed Authlete matches the port-bearing `redirect_uri` against our CIMD doc's portless registration (RFC 8252 §7.3 loopback exception), fully automatic end to end.

---

## Phase 4 — Resource parameter / audience binding

- [x] Reuse the Phase 2 placeholder resource URI here and in Phase 3's `resource` param — confirmed, single `RESOURCE_URI` constant in `server/auth.py`, used consistently
- [x] Server checks `aud`/resource itself on every request regardless of Authlete's own check (see corrected finding in [NOTES.md](NOTES.md)) — defense-in-depth, not the only line of defense
- [x] Negative test: a token issued for a different resource must be rejected by our server (`401 invalid_token`) — confirmed. Minted a real token with `aud`/`accessTokenResources` = `https://wrong-server.example/resource`, called our server, got `401`. Same server previously returned `200` for a correctly-bound token.
- [x] Once Phase 5 adds a per-tool required scope, also pass it as `scopes` alongside `resources` in the introspection call — Authlete's combined scope+resource check then genuinely enforces both natively. `AuthleteTokenVerifier.check_scope` in `server/auth.py`, wired into `scope_gate.py`. Confirmed live: a `logs:read`-only token calling `get_time` produced a real Authlete `action: FORBIDDEN` on the combined `scopes`+`resources` introspection call (not just our own app-side scope comparison), correctly surfaced as `403 insufficient_scope`.

---

## Phase 5 — Scope enforcement + step-up

- [x] Gate protected tool on a scope — `get_time` requires `mcp:tools`, enforced by `server/scope_gate.py`'s `ScopeEnforcementMiddleware` (custom middleware, per the design decision logged in [NOTES.md](NOTES.md))
- [x] Demonstrate `403 insufficient_scope` path — confirmed with a real `logs:read`-only token and an `email`-only token, both correctly rejected
- [x] Demonstrate client re-running a narrow auth request for just that scope — the SDK's `OAuthClientProvider` does this **automatically** on `403 insufficient_scope`, once our middleware's `WWW-Authenticate` header included a proper `scope="..."` field (RFC 6750 §3.1). Confirmed live: second auth attempt requested exactly `mcp:tools`, nothing else, and the retried tool call succeeded.

---

## Phase 6 — Polish + log-gating idea

- [x] Required write-up: ungated, plain markdown, public repo — [docs/WRITEUP.md](WRITEUP.md)
- [x] Second tool, gated behind different scope (`logs:read`) — `get_logs` in `server/main.py`, gated in `server/scope_gate.py`'s `TOOL_SCOPES`. The write-up's described version (in-repo content, no external hosting) didn't actually need Phase 7 after all. Verified live: a `logs:read`-only token succeeds on `get_logs` and gets a real `403` on `get_time` — genuine differentiation, not just "any scope works."
- [x] Return log content in-band (not a shareable link — link can leak past scope check) — reads `docs/NOTES.md` directly and returns its text as the tool result
- [x] Call this pattern out explicitly in the write-up — the design reasoning (why in-band, not a link) is already in `WRITEUP.md`'s design-decisions section, ahead of actually building the tool

---

## Phase 7 — Containerize + host both services (Docker + Render)

Re-scoped from the original "deploy to AWS" plan once we worked out what grading actually requires: graders need to reach `server`/`authserver` asynchronously, without me present — they never run those two themselves (only `client/main.py`, which holds no secret). That's satisfiable for free with Docker + Render, no AWS/Terraform needed. This phase is now the one that actually unblocks async grading, not pure portfolio value — see Phase 9 for where the AWS/Terraform work went.

Detailed ELI5 step-by-step plan (Docker, Render Blueprint, credential handling, pair-coding dev loop): [PHASE7_PLAN.md](PHASE7_PLAN.md).

- [x] Add `/healthz` to both `server/main.py` and `authserver/main.py`, bind both to `0.0.0.0` — used FastMCP's `@mcp.custom_route` decorator for the server side (its own docstring suggested exactly this for health checks). Verified live locally: both return `200`, and the server's pre-existing `401`-without-token behavior is unchanged.
- [x] Make `RESOURCE_URI` (`server/auth.py`) and `ISSUER` (`authserver/main.py`) read from env vars instead of hardcoded `127.0.0.1` constants — also found and fixed a third hardcoded spot the original plan missed: `server/main.py`'s `AuthSettings(issuer_url=...)`, the resource server's own pointer to where the AS lives, needed the same treatment or it'd keep telling clients to discover an AS at localhost post-deploy.
- [x] Write a `Dockerfile` per service (shared root-level `requirements.txt`, so build context stays repo root, `dockerfilePath` points into the subdir) — surfaced a real bug while doing this: `server/main.py` only built its Starlette `app` inside `if __name__ == "__main__":`, which `uvicorn main:app` (what the Dockerfile's `CMD` needs) never executes. Moved `app` construction to module level, matching how `authserver/main.py` already did it.
- [ ] Verify both containers locally via `docker compose up` before touching Render — `docker-compose.yml` + `.env.example` written; blocked on Docker Desktop being installed locally
- [ ] Render: two Web Services (Docker runtime), via a `render.yaml` Blueprint checked into git — `AUTHLETE_SERVICE_ID`/`AUTHLETE_SAT` marked `sync: false` so the values are typed once into Render's dashboard and never appear in the repo — `render.yaml` written; account/Blueprint creation still to do
- [ ] Point `RESOURCE_URI`/`ISSUER` env vars at the real `*.onrender.com` hostnames Render assigns
- [ ] Smoke test end to end against the real URLs (same 401+PRM curl check as Phase 2, then a full `client/main.py` run) — watch for the free tier's ~1 min cold-start on first hit after idle
- [ ] Note the cold-start caveat in the write-up in case a grader's client has a short timeout

---

## Phase 8 — Real sign-in: Google SSO + allow-list (nice-to-have, refines Phase 3's no-op)

- [ ] AS-frontend's `/authorize` becomes a Google OAuth client itself — redirect to Google, get a verified email back, use it as the `subject` passed to Authlete instead of the hardcoded demo value
- [ ] Allow-list of permitted Google emails enforced in the **MCP resource server** (check `subject` from introspection, same layer as our existing audience check) — not just at the AS-frontend
- [ ] Optional: also reject at the AS-frontend for better UX (fail before issuing a code at all), in addition to the resource-server check

---

## Phase 9 — Migrate to AWS/Terraform (optional, portfolio/interview value only — not required for grading)

Phase 7 (Render) already satisfies the actual grading requirement for free. This phase is purely "show real AWS/Terraform skill" for the follow-up interview — do it only if there's time and interest left over.

Detailed ELI5 step-by-step plan (decisions, ordering, Terraform primer) lives in `docs/PHASE9_AWS_PLAN.md` — kept locally as personal reference, deliberately gitignored, **not part of this repo/submission**. Decided: **ECS Fargate**, not EKS/k8s.

- [ ] Register a real domain (Route 53) — the one thing that changes vs. Render's free `*.onrender.com` hostnames
- [ ] Move the Authlete Service Access Token into SSM Parameter Store (`SecureString`), not an env file
- [ ] Reuse the Phase 7 Dockerfiles/health-check endpoints as-is — no rework needed there
- [ ] Terraform for AWS infra: ECS Fargate cluster/services, ECR, one shared ALB with host-header routing
- [ ] TLS termination (ALB + ACM cert) — confirm the externally-visible hostname matches the canonical resource URI exactly (internal vs. public hostname mismatch breaks audience binding silently)
- [ ] For fast local iteration on the Terraform itself during pair-coding, consider LocalStack's free Hobby plan (Terraform-compatible AWS emulator) instead of applying against a real account every time

---

## Phase 10 — Agent-verifiable test scenarios

Grading leans on an agent driving the real system and observing behavior, not a unit-test suite — and per Phase 7, that agent only ever runs `client/main.py`, never `server`/`authserver` or their logs. Several required scenarios (revocation, expiration, exhausted step-up, wrong audience) don't arise from normal client use, so the client itself needs to become a scriptable harness for staging and observing them. Design doc: [TESTING_STRATEGY.md](TESTING_STRATEGY.md). Agent-facing instructions: [AGENT_TESTING.md](AGENT_TESTING.md).

- [ ] Fix `client/main.py`'s uncaught-exception-on-terminal-auth-failure bug; print structured `RESULT: OK/ERROR ...` lines instead
- [ ] Headless consent driver in `client/main.py` (`MCP_AUTH_CONSENT`/`MCP_AUTH_CONSENT_RETRY` env vars), off by default — real-browser demo path unchanged when unset
- [ ] File-backed `TokenStorage` so tokens persist across separate CLI invocations, not just within one process
- [ ] New `revoke` subcommand + `authserver` `/revoke` route wrapping Authlete's `/auth/revocation` (RFC 7009)
- [ ] New `probe` subcommand (static bearer token, bypasses the SDK's auto-reauth) — the actual verification primitive for revoked/expired/mis-scoped tokens
- [ ] One-time Authlete console setup: `short-lived` scope with a short duration override, for deterministic expiration testing
- [ ] Verify all 8 scenarios in `AGENT_TESTING.md` produce their documented `RESULT:` line

---

## Wrong-turn / correction log
*(add entries as they happen — a dozen sharp ones beats fifty verbose ones)*

- Assumed "SaaS AS" meant fully hosted, turnkey, like Auth0 — Authlete turned out to be backend-API-only (no live `/authorize`, confirmed via 404 at its well-known endpoint), requiring us to build our own thin AS-frontend. Not wrong to pick Authlete, but wrong to assume the SaaS category was uniform.
- Concluded "Authlete's introspection doesn't enforce resource/audience matching" — actually a confounded test. Every token we'd minted had `scope: null` because `mcp:tools`/`logs:read` were never pre-registered at the service level (a real, non-obvious config step). With `sufficient` unconditionally `false` from scope-insufficiency alone, we couldn't see whether resources mattered at all. Root-caused and re-verified: the check is real, and combined with scope.
- Misread a fixed placeholder string (`responseContent: "Bearer error=\"invalid_request\""`, always present when `action:OK`) as a real error on a successful introspection call. `action` is the field that matters; `responseContent` only carries real content on non-OK actions.
- Three failed token mints in a row before realizing scopes need explicit pre-registration in the console (Tokens and Claims > Advanced > Scope) — passing `"scopes": [...]` to `/auth/authorization/issue` silently no-ops if the scope isn't recognized, rather than erroring.

## Time-cost observations
*(e.g. % effort on auth plumbing vs. tool logic)*

-
