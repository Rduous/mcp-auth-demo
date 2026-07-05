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

<a name="phase-0-curl-spike"></a>
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

<a name="correction-audience-check"></a>
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

## 2026-07-04 — Design decision: per-tool scope enforcement via custom middleware, not separate servers

*(write-up material — good "design decision + tradeoff + why" candidate)*

- MCP's client-server relationship is 1:1 per session; multiplicity (a host juggling several servers) lives one layer up, in the host application. Given the assignment's wording — "an MCP server... enforces scopes on at least one protected tool," "point at your server... call your protected MCP tool" — the intended shape is one server, several tools, at least one scope-gated, not multiple servers split by permission tier.
- Modeled our expected real-world deployment accordingly: a Claude-based agent (the host) running on a user's laptop, our CLI (the client) installed locally, and our MCP server hosted remotely — a single client-server session, matching how a real user would actually run this.
- Chose custom middleware that inspects each `tools/call` request and checks that specific tool's required scope, over splitting scope tiers across separate FastMCP mounts, so the step-up story (call a tool, get `403`, re-authenticate narrowly for just that scope, retry) stays within one continuous session rather than requiring a second connection to a differently-scoped server.

<a name="phase-5-step-up"></a>
## 2026-07-04 — Phase 5 complete: scope enforcement, and step-up came almost for free

- Built `ScopeEnforcementMiddleware` (does its own token verification, independent of FastMCP's internal auth pipeline, so it doesn't depend on middleware ordering). Gated `get_time` on `mcp:tools`.
- Consent picker got two more test buttons: an unrelated built-in scope (`email` — satisfies neither of our gated tools, sidesteps a real Authlete quirk below) and a genuinely fresh "different resource" authorization request (Authlete's issue API has no `resources` override, unlike `scopes`, so this needed its own route rather than reusing the existing ticket).
- **Real Authlete quirk found:** passing an empty `scopes: []` array at `/auth/authorization/issue` is silently ignored — falls back to the originally-requested scopes, contradicting Authlete's own documented behavior ("even an empty array should replace the original scopes"). Confirmed three ways (through the authserver, an isolated curl test, and by contrast with a genuine non-empty override which *does* work correctly). Not a blocker — proving `insufficient_scope` doesn't require a truly zero-scope token, just an insufficient one.
- **Bigger discovery:** the SDK's `OAuthClientProvider` already implements the step-up mechanic Phase 5 asks us to demonstrate — on `403` with `error="insufficient_scope"`, it automatically parses a `scope="..."` field out of `WWW-Authenticate` and re-runs authorization for exactly that scope. We weren't including that field, so it silently degraded to "omit scope" on retry. One header fix, and step-up started working automatically — the client had to become resilient to a second callback round too (was crashing on `KeyError: 'code'` since our loopback handler wasn't written to expect being called twice).
- Confirmed live: `email`-only token → `403` → automatic second browser popup requesting *only* `mcp:tools` → success, no manual intervention.
- Predicted and verified a related edge: granting `logs:read` instead of `mcp:tools` on that step-up retry still isn't sufficient, and the SDK only attempts step-up once per request — the second `403` propagates as a real client-side error rather than looping. Deliberate, sane behavior (prevents an infinite retry loop), not a bug.

## 2026-07-04 — Phase 6: second tool built, no AWS needed after all

- Added `get_logs` (`server/main.py`), gated on `logs:read` in `server/scope_gate.py`. Reads and returns `docs/NOTES.md` verbatim — the in-repo, in-band design from `WRITEUP.md`, not the more elaborate externally-hosted version considered and paused earlier.
- Verified real differentiation, not just "some scope works for everything": a `logs:read`-only token succeeds on `get_logs` and gets a genuine `403 insufficient_scope` on `get_time`.

## 2026-07-04 — Rewrote client as a real CLI; a scope-selection quirk explained

- `client/main.py` was a hardcoded single-purpose script since Phase 1 — rewrote it as a `click`-based CLI (`get-time`, `get-logs --topic`) so it's actually usable by an outside agent, not just our own testing.
- Tried an optimization: set `client_metadata.scope` per-tool before each call, to request only the needed scope and skip a step-up round trip. Doesn't work, and it's not a bug — `session.initialize()` triggers the *first* `401` before the client has chosen which tool to call, so the SDK's scope-selection fallback has no tool-specific hint yet and requests the AS's full advertised `scopes_supported` instead (both scopes, always). Removed the dead optimization rather than leave misleading code behind.
- Consequence: with our no-op auto-approve AS, the first token issued in normal CLI use is now always fully-scoped — step-up won't naturally trigger through the CLI anymore, since nothing comes back under-scoped to begin with. (Already proven working in Phase 5 via the consent picker's deliberately-restricted scope choices; this doesn't undo that, just means the CLI itself won't organically demonstrate it.)
- Added real visibility instead: the client now prints which scope is actually being requested on each authorization attempt, and explicitly labels a second attempt within one call as "step-up re-authorization" rather than leaving it to be inferred from a raw URL.

## 2026-07-05 — Phase 4's deferred item: Authlete's native combined scope+resource check now actually invoked

- `AuthleteTokenVerifier.check_scope(token, required_scope)` (new, `server/auth.py`) calls `/auth/introspection` with `scopes` *and* `resources` in the same request, instead of `verify_token`'s bare `{"token": token}`. Per the earlier [correction](#correction-audience-check), that combination is what makes Authlete hard-reject with `action: FORBIDDEN` when the token doesn't cover both — a second, Authlete-side enforcement layer on top of the existing app-side checks, not a replacement for them.
- Deliberately a separate method from `verify_token`, not an added parameter on it. FastMCP calls `verify_token(token)` itself for the base auth check and has no notion of per-tool scopes — keeping that call scope-agnostic means its introspection request (and hence its own live revocation check) stays independent of `scope_gate.py`'s.
- `scope_gate.py` now calls `check_scope` instead of `verify_token` + a Python-side `in access_token.scopes` comparison. Returns a 3-state `ScopeCheckResult` (`SUFFICIENT`/`INSUFFICIENT`/`INVALID`) rather than reusing `AccessToken | None` — collapsing "invalid token" and "valid token, insufficient scope" into the same `None` would have silently broken the 403 step-up path (the middleware would fall through to FastMCP's own scope-agnostic `verify_token` call, which would then authorize the request anyway).
- Verified the branching logic against mocked Authlete responses (`OK`+sufficient, `FORBIDDEN`, `OK`+wrong resource, `OK`+wrong scope, `BAD_REQUEST`) — all five map to the intended result.
- **Confirmed live**: minted a `logs:read`-only token via the consent picker, called `get_time` (requires `mcp:tools`). Temporary debug logging showed Authlete's own introspection genuinely returning `action: 'FORBIDDEN'` for the combined `scopes=['mcp:tools'], resources=[RESOURCE_URI]` request — not just our own app-side scope comparison — correctly surfaced as `403 insufficient_scope`. Held on both the original attempt and the SDK's one automatic step-up retry (same under-scoped token offered again on purpose), matching the already-documented "second `403` propagates as a real client-side error" edge case from Phase 5. Sufficient-scope (`get_time` with `mcp:tools`) and differentiation (`get_logs` with `logs:read`) both still succeed directly, no regressions.

## 2026-07-05 — Phase 7: containerization code changes (Docker + Render prep)

- Added `/healthz` to both services — FastMCP ships a built-in `@mcp.custom_route` decorator (its own docstring even shows a `/health` example) for `server/main.py`; a plain `Route` for `authserver/main.py`. Both bound to `0.0.0.0` instead of `127.0.0.1` — a container's port mapping needs it, since `127.0.0.1` only accepts connections from inside the same container.
- Made `RESOURCE_URI` (`server/auth.py`) and `ISSUER` (`authserver/main.py`) env-var-driven, defaulting to today's `127.0.0.1` values. Found a third hardcoded spot the original Phase 7 plan missed: `server/main.py`'s own `AuthSettings(issuer_url=...)` — the resource server's pointer to where the AS lives — needed the same treatment, or it'd keep telling clients to discover an AS at localhost after the AS itself moves to Render.
- **Real bug found and fixed while writing `server/Dockerfile`**: `server/main.py` only ever built its Starlette `app` inside `if __name__ == "__main__":`. `uvicorn main:app` — what the Dockerfile's `CMD` needs — imports the module rather than running it as a script, so that guard never executes and `app` wouldn't exist. Moved `app = mcp.streamable_http_app()` / `app.add_middleware(...)` to module level, matching how `authserver/main.py` already did it.
- Wrote `server/Dockerfile`, `authserver/Dockerfile` (shared root `requirements.txt`, build context = repo root per both Dockerfiles), `docker-compose.yml` (bind-mount + `--reload` dev loop, not deployed anywhere), `.env.example`, and `render.yaml` (Blueprint, `AUTHLETE_SERVICE_ID`/`AUTHLETE_SAT` marked `sync: false`).
- Verified locally with dummy Authlete credentials (`/healthz` never touches Authlete, so this doesn't need real ones): both services boot cleanly, `/healthz` returns `200` on each, and the pre-existing `401`-without-token behavior on `/mcp` is unchanged — no regression from the refactor.
- Not yet done: real `docker compose up` verification (Docker wasn't installed locally yet at the time), and the actual Render Blueprint/account creation — tracked in `PLAN.md`'s Phase 7 checklist.
