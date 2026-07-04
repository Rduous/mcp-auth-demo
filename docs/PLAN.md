# MCP Auth Project — Execution Plan & Checklist

Spec: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

Stack: Python (official `mcp` SDK for server + client, httpx for direct AS calls, pyjwt for token decoding, click for the CLI).

---

## Open design questions (resolve before/during Phase 0)

- [x] **Which AS?** Shortlisted **Authlete** (top pick) and **WorkOS** (backup) — both SaaS, both claim shipped CIMD support with real engineering-level docs, unlike OSS options (e.g. Ory Hydra) where CIMD is still an open feature request. Provisional pending the Phase 0 spike below. See [NOTES.md](NOTES.md).
- [x] **Protected tool choice** — `get_time` (no args). Will need a second tool (`logs:read`-gated, per Phase 6) to actually demonstrate scope *differentiation* — one tool alone can only show authenticated-vs-not, not that different scopes unlock different things.
- [ ] **"Single command" CLI** — one-shot (browser pops mid-call) vs. `login` + `call` two-step?
- [ ] Confirm log-gating idea (Phase 6) is in scope for submission, or purely a bonus.

---

## Phase 0 — De-risk the AS choice (no app code)

- [x] Host a CIMD doc at a public HTTPS URL (GitHub Pages / gist-style is fine) — live at https://rduous.github.io/mcp-auth-demo/cimd/client-metadata.json
- [x] Manually drive full auth-code + PKCE flow via curl/Postman against candidate AS — done against Authlete, see [NOTES.md](NOTES.md)
- [x] Confirm AS fetches & validates the CIMD doc — confirmed twice: discovery shows `client_id_metadata_document_supported: true`, and the live authorization response showed `metadataDocumentUsed:true` / `clientSource:METADATA_DOCUMENT`
- [x] Confirm AS enforces PKCE — enabled Require PKCE + Require S256 in console's Authorization tab; a request without `code_challenge` is now rejected (`A124301`)
- [x] Confirm `resource` parameter is accepted — switched service to JWT access tokens (ES256); decoded token's `aud` claim is exactly `["https://rduous.github.io/mcp-auth-demo/resource"]`. See [NOTES.md](NOTES.md).
- [x] **Resource enforcement isn't automatic on Authlete's side** — `/auth/introspection` doesn't reject a mismatched `resources` value (confirmed via a scope-check control, which does correctly reject). Our MCP resource server must check `aud`/`accessTokenResources` itself. Doesn't block staying on Authlete; changes what Phase 4 builds (see below).
- [ ] **Decision point:** if any of the above fail, switch AS now — resolved: staying on Authlete. CIMD and resource-acceptance are solid; PKCE enforcement is a config fix, and audience checking will be handled in our own server code either way.

---

## Phase 1 — Trivial unauthenticated loop

- [x] Basic MCP server, one tool (`get_time`), no auth — [server/main.py](../server/main.py), official `mcp` SDK (`FastMCP`, streamable-http)
- [x] Basic MCP client that calls it — [client/main.py](../client/main.py)
- [x] Confirm base transport/plumbing works end to end — ran both locally, client got a real timestamp back

---

## Phase 2 — Add 401 + Protected Resource Metadata

- [x] Pick a placeholder canonical resource URI for local dev — `http://127.0.0.1:8000/mcp`, in [server/auth.py](../server/auth.py) as `RESOURCE_URI`, not hardcoded elsewhere
- [x] Server requires a token, returns `401` + PRM pointing at real AS — verified via curl: `401` + `www-authenticate` → `.well-known/oauth-protected-resource/mcp` → names `https://authlete.com/`
- [ ] Client discovers AS from the `401` response (not hardcoded) — **this is graded**
- [x] **Checkpoint:** decided — call Authlete's `/auth/introspection` (network hop, live revocation check). See [server/auth.py](../server/auth.py) and [session_log.md](session_log.md).

---

## Phase 3 — Full auth handshake

- [ ] Stand up a thin AS-frontend wrapping Authlete's API — `/authorize`, `/token`, `/.well-known/oauth-authorization-server`. Required because Authlete has no hosted login/consent UI (confirmed: it 404s at the well-known endpoint) — see [NOTES.md](NOTES.md). Sign-in is a **no-op** (auto-approve one demo subject) — TODO in code, real identity is a later refinement (Phase 8).
- [ ] Client does CIMD-based `client_id` + PKCE against real AS
- [ ] Client obtains token, calls tool with `Authorization: Bearer`
- [ ] Loopback redirect URI handles random local port correctly

---

## Phase 4 — Resource parameter / audience binding

- [ ] Reuse the Phase 2 placeholder resource URI here and in Phase 3's `resource` param — not a new decision, just confirming it's read from the one config value everywhere
- [ ] Server checks `aud`/resource itself on every request regardless of Authlete's own check (see corrected finding in [NOTES.md](NOTES.md)) — defense-in-depth, not the only line of defense
- [ ] Negative test: a token issued for a different resource must be rejected by our server (`401 invalid_token`) — this is the real proof, not just a matching-case success
- [ ] Once Phase 5 adds a per-tool required scope, also pass it as `scopes` alongside `resources` in the introspection call — Authlete's combined scope+resource check then genuinely enforces both natively

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

## Phase 7 — Deploy to AWS (nice-to-have, not required by the assignment)

Sequenced after Phase 6, not before: deployment is portfolio/interview value, not graded, and doing it after the second tool exists avoids redeploying infra once `logs:read` shows up.

- [ ] Swap the Phase 2 placeholder for the real public HTTPS canonical resource URI (needs a real domain/DNS/TLS to exist first — this is the one point where the value actually changes)
- [ ] Move the Authlete Service Access Token into a real secret store (AWS Secrets Manager / SSM), not an env file
- [ ] Containerize the server; bind to `0.0.0.0`, add a health-check endpoint for k8s probes
- [ ] Terraform for AWS infra; k8s manifests for the deployment
- [ ] TLS termination (ALB/ingress + cert) — confirm the externally-visible hostname matches the canonical resource URI exactly (internal vs. public hostname mismatch breaks audience binding silently)

---

## Phase 8 — Real sign-in: Google SSO + allow-list (nice-to-have, refines Phase 3's no-op)

- [ ] AS-frontend's `/authorize` becomes a Google OAuth client itself — redirect to Google, get a verified email back, use it as the `subject` passed to Authlete instead of the hardcoded demo value
- [ ] Allow-list of permitted Google emails enforced in the **MCP resource server** (check `subject` from introspection, same layer as our existing audience check) — not just at the AS-frontend
- [ ] Optional: also reject at the AS-frontend for better UX (fail before issuing a code at all), in addition to the resource-server check

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
