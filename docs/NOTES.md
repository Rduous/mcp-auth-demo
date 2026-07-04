# Work log

Ongoing log of architecture decisions, corrections, and dead ends. A dozen sharp entries beats fifty verbose ones. See [BACKGROUND.md](BACKGROUND.md) for prep notes and [PLAN.md](PLAN.md) for the phase checklist.

---

## 2026-07-04 — Project kickoff

- Python (Flask + httpx + authlib/pyjwt + click) over Go — auth/JWT plumbing is the hard part, Python's ecosystem covers it with less code.
- Scaffolded `server/`, `client/`, `cimd/`, `docs/`.

## 2026-07-04 — AS shortlist: Authlete + WorkOS

- Ruled out OSS (e.g. Ory Hydra): mature MCP tooling, but CIMD support is an open GitHub issue, not shipped. CIMD is too new (spec Nov 2025) for general OAuth infra to have caught up.
- Shortlisted **Authlete** (top pick — versioned CIMD flag, documented dev-mode refetch) and **WorkOS** (backup — deepest CIMD security write-up). Both provisional pending a manual spike.

## 2026-07-04 — Skipped Authlete's FAPI Profile toggle

- Left disabled. FAPI mandates PAR/signed request objects/mTLS-DPoP and disallows our plain public-client pattern — none of it is in the MCP spec, just added failure risk.

## 2026-07-04 — Phase 0 curl spike against Authlete

- CIMD confirmed real end-to-end: authorization response showed `metadataDocumentUsed:true`, `clientSource:METADATA_DOCUMENT` — Authlete fetched our hosted doc, didn't use a pre-registered client.
- Tokens are **opaque, not JWT** — resource server will validate via `/auth/introspection`, not local JWT decode.
- `pkceRequired` is `false` by default — PKCE was honored only because we chose to send it. Needs to be turned on (open item, see below).
- **Resource/audience enforcement is not automatic.** `/auth/introspection` returned identical `action:OK` whether `resources` matched, mismatched, or was omitted. A control test (bogus `scopes`) correctly triggered `FORBIDDEN`, proving the request mechanism works — the gap is specific to resource matching. Decision: our own MCP server must check `accessTokenResources` itself rather than trust Authlete to reject cross-audience tokens.
- Initially misread a `"responseContent":"Bearer error=\"invalid_request\""` string as a real error — it's a fixed placeholder Authlete always returns when `action:OK` (confirmed in `IntrospectionResponse` docs), not a computed error. `action` is the field that matters. Doesn't change the finding above, but flagging the correction since it was a plausible misread.

## 2026-07-04 — PKCE now enforced

- Setting was under the console's **Authorization** tab, not Metadata/CIMD. Enabled Require PKCE + Require S256. Verified: a request without `code_challenge` is now rejected (`A124301`).

## 2026-07-04 — Switched to JWT access tokens

- Registered an ES256 JWK Set (Key Management) and set Access Token Signature Algorithm (Tokens and Claims > Access Token). Re-ran the flow: token is now a real JWT (`typ:at+jwt`), decoded `aud` = `["https://.../resource"]`, matching the `resource` param exactly.
- Enforcement design unchanged: still validating via `/auth/introspection`, not local JWT verification — Authlete's own `/auth/introspection` handles JWT access tokens the same way (looks up by `jti`), so this was a config-only change. JWT format mainly buys a literal `aud` claim to show in the write-up. Phase 0 is now fully closed.

## 2026-07-04 — Phase 1: trivial unauthenticated loop

- Switched planned server stack from Flask to the official `mcp` Python SDK — it already ships the RFC 9728 `401`/PRM route and a `TokenVerifier` interface we'll need for Phase 2, so no reason to hand-roll that on Flask.
- SDK requires Python 3.10+; the system Python was 3.9, so installed 3.12 via Homebrew and rebuilt the venv.
- Built `server/main.py` (`FastMCP`, one `get_time` tool, streamable-http) and `client/main.py` (plain `ClientSession` calling the tool, no CLI framework yet — kept minimal per the "don't add abstraction before it's needed" steer). Ran both locally, confirmed a real round trip.
