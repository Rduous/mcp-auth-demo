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

## 2026-07-04 — Skipped Authlete's FAPI Profile toggle

- Authlete's service-creation flow surfaces a "FAPI Profile" toggle (enables FAPI 1.0/2.0 settings). Left it disabled: FAPI is a banking-grade profile that typically mandates PAR, signed request objects, and mTLS/DPoP sender-constrained tokens, and generally disallows the plain public-client (`token_endpoint_auth_method: none`) pattern our CIMD client relies on. None of that is part of the MCP auth spec — enabling it would add failure modes unrelated to what's actually being built/graded. Flagged as a "more security settings ≠ better fit" trap worth calling out in the write-up.

## 2026-07-04 — Phase 0 curl spike against Authlete: CIMD confirmed, resource enforcement is NOT automatic

- Drove the full auth-code + PKCE flow by hand against Authlete's API (simulating the AS side via curl, per their tutorial pattern — Authlete doesn't run its own AS frontend, you call `/auth/authorization`, `/auth/authorization/issue`, `/auth/token` directly). Full trace in chat history; summary below.
- **CIMD works end-to-end and is provably not a stub**: the authorization response showed `"metadataDocumentUsed":true` and `"client":{"clientSource":"METADATA_DOCUMENT", ...}` — Authlete genuinely fetched and resolved our hosted `client-metadata.json`, not a manually pre-registered client.
- **Access tokens are opaque, not JWT**, by default on this service (no dots in the token string). Means our resource server will validate via Authlete's `/auth/introspection` API on every call, not by decoding a JWT locally. Worth deciding explicitly rather than assuming JWT later (a named failure mode in our own background notes).
- **`pkceRequired` is `false`** on the service/client by default — PKCE was honored because we voluntarily sent `code_challenge`, but nothing currently forces it. Need to flip `pkceRequired` (and ideally `pkceS256Required`) to `true` before calling Phase 0's "confirm AS enforces PKCE" done.
- **Resource/audience enforcement is the big finding.** Called `/auth/introspection` three times: no `resources` param, matching `resources`, and a deliberately wrong `resources` value. All three returned byte-identical output (`usable:true`, same `resultCode`) — the mismatched case was **not** rejected. Ran a control test (bogus `scopes` value) to rule out "our JSON calls aren't being read" — that one correctly came back `action:FORBIDDEN` / `insufficient_scope`, proving the mechanism works in general and the gap is specific to resource checking (at least when called with our broad Service Access Token, which may not carry the same identity as a real resource server's own credential — unconfirmed).
- **Conclusion / decision**: don't rely on Authlete's introspection API to reject cross-audience tokens on our behalf. The token response does reliably return `accessTokenResources` regardless of match, so our own MCP resource server code will do the audience check itself (reject unless `accessTokenResources` contains our exact canonical URI) — defense in depth, and this was the actual spec requirement all along ("servers MUST validate tokens were issued for them specifically"), not something safe to outsource to a convenience flag we hadn't verified.
- **Self-correction**: initially misread `"responseContent":"Bearer error=\"invalid_request\""` (present on all three introspection calls) as boilerplate without checking — got called out for that, correctly. Verified against the actual `IntrospectionResponse` docs: when `action:OK`, Authlete *always* returns that exact fixed string for `responseContent` regardless of request specifics (a safety fallback for callers who forget to check `action` first) — it's not a computed error about our request. `action` is the authoritative field; `responseContent` only carries real per-request error text on non-OK actions. This doesn't change the resource-enforcement finding above, but it was worth verifying rather than assuming — same category of mistake this project is meant to surface.
