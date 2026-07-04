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

## 2026-07-04 — Phase 2: server-side 401 + PRM

- SDK's `mcp.server.auth` already ships RFC 9728 PRM route + `TokenVerifier` protocol (one method: `verify_token(token) -> AccessToken | None`) — didn't need to hand-roll any of the `401`/discovery mechanics.
- `server/auth.py`: `AuthleteTokenVerifier` calls Authlete's `/auth/introspection`, then separately checks our own `RESOURCE_URI` is in `accessTokenResources` — the audience check Authlete won't do for us (Phase 0 finding).
- Confirmed both paths live: no token → `401` + correct PRM naming Authlete; valid, correctly-audience-bound token → `200` + real tool result.
- One false alarm mid-debug: a test looked like it failed due to a bad token, but it was the chat UI auto-masking a long JWT-looking string on display — not a code bug. Worth remembering before assuming a real failure next time this pattern shows up.

## 2026-07-04 — Authlete is backend-API-only; staying anyway, building an AS-frontend

- Real finding, not a bug: `authlete.com/.well-known/openid-configuration` 404s. Authlete has no hosted login/consent UI or live `/authorize`/`/token` endpoints — it's a backend API a real AS-frontend is expected to call. That's exactly why Phase 0 simulated the AS side by hand with curl; it doesn't generalize to a real browser flow.
- Checked WorkOS as the alternative: its AuthKit *does* host real login/consent pages plus live OAuth endpoints, and has a native CIMD toggle. It remains a viable fallback if Authlete becomes a blocker, but we're not switching — we already have validated work on Authlete (introspection wiring, JWT signing) and the missing piece (a thin AS-frontend wrapping 3 already-curl-tested API calls) is small.
- Decision: stay on Authlete, stand up our own minimal AS-frontend (`/authorize`, `/token`, `/.well-known/oauth-authorization-server`). Sign-in will be a **no-op** — auto-approve a single hardcoded demo subject, no real login form. Marked with a TODO in the AS-frontend code once built.
- Added a future refinement (not required by the assignment): swap the no-op sign-in for real Google SSO, with the allowed-subjects check enforced in the **MCP resource server** (same layer as our existing audience check), not the AS-frontend.

## 2026-07-04 — Correction: Authlete's resource check does exist, we just never isolated it

- Earlier finding ("Authlete's `/auth/introspection` doesn't reject a mismatched `resources` value") was wrong — or rather, incomplete. Root cause of the original confusion: those test tokens all had `scope: null`, because the scopes we requested (`mcp:tools`, `logs:read`) were never pre-registered at the service level (Tokens and Claims > Advanced > Scope — a real gotcha, not obvious from the API). With `scope: null`, `sufficient` was unconditionally `false` no matter what `resources` we passed, masking any real signal.
- With scopes properly registered and a token actually carrying `scope: "mcp:tools"`: `sufficient` *does* correctly reflect a resource mismatch even when `resources` is passed alone. And passing `scopes` + `resources` together in the same introspection call makes Authlete hard-reject (`action:FORBIDDEN`, error `A286303`, *"does not cover the necessary combination of scopes and resources"*) — a genuinely combined check, not independent ones.
- Practical upshot: our own resource-server-side audience check (in `server/auth.py`) stays, as defense-in-depth — Phase 2 has no per-tool scope to pass yet, so we only ever get the soft `sufficient` signal, not a hard reject, from Authlete alone. Once Phase 5 adds per-tool required scopes, pass those as `scopes` alongside `resources` on every introspection call to get Authlete's native enforcement too.

## 2026-07-04 — Phase 3 milestone: real end-to-end flow works (library-shortcut path)

- Built `authserver/main.py` (Starlette, 3 routes: `/authorize`, `/token`, `/.well-known/oauth-authorization-server`), wrapping the exact Authlete calls we'd already validated by hand. Pointed the MCP server's `issuer_url` at it instead of the bare Authlete domain.
- Debugging note: hit a real bug (env vars exported in one terminal, `authserver` started in another — `AUTHLETE_SERVICE_ID` empty, produced `api//auth/authorization`, a 400 from Authlete) vs. an expected non-bug (browser `ERR_CONNECTION_REFUSED` on the callback URL — nothing listens on plain port 80 by design; the URL itself, copy-pasted back, is all the client needs).
- First fully real run (not curl-simulated) succeeded end to end: `client/main.py`'s `OAuthClientProvider` discovered the AS via `401`+PRM, did CIMD + PKCE against our AS-frontend, got a token, and `get_time` returned a real timestamp through our server's introspection-based validation.
- Not yet tested: real ephemeral-port loopback redirect handling — current client uses a fixed no-port `redirect_uri` and manual copy-paste of the callback URL. Deferred to the hand-rolled client rewrite (the "option 1" version), which is next.

## 2026-07-04 — Real loopback callback server, no more manual paste-back

- Replaced the "paste the callback URL" step with a real local `http.server.HTTPServer` on an OS-assigned ephemeral port, run in a background thread via `asyncio.to_thread`. Sends the redirect_uri with that real port to the AS.
- This exercised the last untested Phase 3 item: our CIMD doc only registers a *portless* redirect URI, so this only works if Authlete matches ignoring the port for loopback addresses (RFC 8252 §7.3). Confirmed it does — worked on the first try, fully automatic end to end.
- Phase 3 and the "single command CLI" open question are both now genuinely resolved: one `python3 client/main.py` invocation does discovery, CIMD, PKCE, the loopback catch, and the tool call, with no manual steps.

## 2026-07-04 — Phase 4 done: audience rejection proven, not just assumed

- Minted a real token bound to a deliberately wrong resource (`https://wrong-server.example/resource`, confirmed in both `aud` and `accessTokenResources`), then called our actual running MCP server with it: `401`. The same server previously returned `200` for a correctly-bound token. That's the real proof our own resource-server-side check works, not just a matching-case success.

## 2026-07-04 — AS-frontend: interactive consent picker

- Replaced the silent auto-approve in `authserver`'s `/authorize` with a real (if minimal) consent screen: three links ("mcp:tools", "logs:read", "no scope"), each issuing the code with exactly that scope via `/authorize/confirm`. Identity is still a no-op (one hardcoded subject) — only scope *consent* is now an actual interactive choice.
- Side benefit: this doubles as a manual test harness for Phase 5/6 — trivial to mint tokens with different scope outcomes without touching curl each time.
