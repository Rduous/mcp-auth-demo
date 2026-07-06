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

## 2026-07-05 — Docker Compose verified locally

- `brew install docker` only gets the client CLI, no daemon — `docker info` failed with no socket found, no Docker Desktop app installed, nothing running. Went with **colima** instead of Docker Desktop (lighter, CLI-only, no GUI): `brew install colima && colima start`, then `brew install docker-compose` for the `docker compose` plugin (needed one extra step — add `cliPluginsExtraDirs` pointing at Homebrew's `cli-plugins` dir in `~/.docker/config.json`, or the `docker` CLI doesn't find the plugin at all).
- With that in place: `docker compose up --build` built both images and booted both containers clean on the first try. `/healthz` returns `200` on both; `POST /mcp` with no token still correctly returns `401` — the containerized versions behave identically to the bare `python3 main.py` versions, no Docker-specific regressions.
- Tested against dummy Authlete credentials (`AUTHLETE_SERVICE_ID=dummy`, `AUTHLETE_SAT=dummy` in a throwaway `.env`, deleted after) — enough to prove the container plumbing itself (paths, host binding, port mapping, `uvicorn main:app` resolving correctly now that `app` is module-level) is sound. Haven't yet run a real end-to-end OAuth flow *through* the containers with real credentials — that's still open before calling Phase 7 fully done.

## 2026-07-05 — Consent picker: combined scope for expiration testing

- Added a `short-lived` scope in the Authlete console (Tokens and Claims > Advanced > Scope > Scope Attributes: key `access_token.duration`, value `10`) — confirmed via a direct `GET /api/{serviceId}/service/get` curl check that it's registered with that attribute, not just assumed from the console UI.
- Added a consent-picker choice in `authserver/main.py`'s `SCOPE_CHOICES`: `"mcp:tools short-lived"`, granting both together rather than `short-lived` alone, since a token needs `mcp:tools` to actually be usable against `get_time` — Authlete's per-scope duration override takes the *shortest* duration among all granted scopes, so this yields a real, usable, ~10s-lived token.
- **Bug found and fixed while wiring this up**: `confirm()`'s `scopes = [scope] if scope else []` wrapped the entire query-param string as a single list element — fine for every existing single-word choice, but would have sent Authlete `["mcp:tools short-lived"]` (one malformed scope name containing a space) instead of two real scopes. Changed to `scope.split()` (RFC 6749 §3.3 scope format is whitespace-separated). Verified the round-trip in isolation: `urlencode` → query param → `.split()` correctly reproduces `["mcp:tools", "short-lived"]`.

## 2026-07-05 — Client: persistent token storage + `probe`, for manual and agent-driven testing alike

- Trigger: tried to manually test the new short-lived-scope expiration case and realized the client had no way to support it. `call_tool()` built a fresh `InMemoryTokenStorage()` on every single CLI invocation — `get-time` now, wait, `get-time` again would run two entirely separate OAuth dances, not the same token surviving a wait. Also a real trap for a same-process version of this test: our `client_metadata` requests `refresh_token` as a grant type, so even keeping one session open across a `sleep()` risked the SDK silently refreshing the token underneath us on expiry, rather than surfacing a clean failure.
- Replaced `InMemoryTokenStorage` with `FileTokenStorage` (`client/main.py`), backed by `.mcp_auth_state.json` (gitignored, new `.gitignore` entry). Verified the actual round-trip, not just that it doesn't crash: a token saved via one `FileTokenStorage` instance is read back correctly by a *fresh* instance — simulates exactly what two separate `python client/main.py ...` invocations need.
- Added a `probe` subcommand: same session machinery as `get-time`/`get-logs`, but passes a plain static `Authorization: Bearer <token>` header (`streamablehttp_client`'s existing `headers=` param — no custom `httpx.Auth` class needed) instead of an `OAuthClientProvider`. Deliberately no auto-reauth/step-up: that healing is right for the real demo path, wrong for verification, since it would quietly replace a revoked/expired/wrong-audience token with a fresh working one and mask the very failure being tested. Reads the token straight from `FileTokenStorage`; errors clearly if none is staged yet.
- Also fixed the client's other outstanding bug while touching this code: an unrecovered auth failure (e.g. a terminal `403` after step-up is exhausted) used to raise an uncaught exception/traceback. Both `get-time`/`get-logs` and the new `probe` now funnel through one `_run()` helper that prints a single structured `RESULT: OK ...` / `RESULT: ERROR <status> <detail>` line and exits non-zero on failure — a real client-quality fix, and also what makes `probe`'s output actually parseable by an agent instead of a stack trace.
- Confirmed live (no server running yet): `probe` on a fresh checkout with no staged token fails immediately with `RESULT: ERROR No stored token in .mcp_auth_state.json -- run get-time or get-logs first to stage one.`, exit code 1 — not a crash.
- Still open: `revoke` subcommand + `authserver`'s `/revoke` route, and the headless `MCP_AUTH_CONSENT` consent driver — tracked in `PLAN.md`'s Phase 10.

**Behavior change worth flagging clearly, separate from the bug fixes above:** the CLI was originally designed (see `PLAN.md`'s "Single command CLI" decision) as one-shot — every invocation does the full discover-auth-call sequence from scratch, every time. That's no longer true. Persisting tokens means the browser/consent screen now only appears on the *first* run against a given identity; every later run silently reuses the cached token as long as it's valid, which in practice (given the no-op AS grants full `scopes_supported` on first auth) means indefinitely. Not a regression — it's how a real CLI should behave, and it's what makes `probe`'s wait-and-retry testing possible at all — but it changes what a human demo or an evaluator actually *sees* on a second run: no popup, just an instant result. `python client/main.py reset` (added as a real subcommand, replacing the earlier `rm -f .mcp_auth_state.json` instruction — nicer than telling a user to manually delete a file) is now the way to force a fresh run and see the real flow again.

## 2026-07-05 — Two follow-up fixes to `FileTokenStorage`

- **Path was cwd-relative, not repo-relative.** `STATE_FILE = Path(".mcp_auth_state.json")` resolved against whatever directory the process happened to be launched from — running the CLI from inside `client/` instead of the repo root would've silently created a second, disconnected state file there, rather than sharing the one at the root. Anchored it to the script's own location instead: `Path(__file__).resolve().parent.parent / ".mcp_auth_state.json"`. Verified live: running from inside `client/` still resolves to the repo-root file.
- **File had default OS permissions.** A live bearer token now sits on disk between invocations (it never did before — in-memory only, gone when the process exited); `Path.write_text()` left it at whatever the umask gives, typically group/world-readable on a shared machine. Added `self.path.chmod(0o600)` after every write, matching how `~/.aws/credentials`/`~/.netrc` handle the same problem. Verified: `ls -la` shows `-rw-------`.

## 2026-07-05 — Correction: the short-lived-scope fix was CIMD's scope field, not really

- The short-lived combo (`mcp:tools short-lived`) kept minting a full-duration, `mcp:tools`-only token even when the consent screen correctly received and forwarded both scopes to `auth/authorization/issue` (confirmed via the new `/token` debug prints — Authlete accepted the override uncomplaining at issue-time, then the final `/auth/token` result showed `scopes: ['mcp:tools']`, `accessTokenDuration: 86400`).
- First theory: `cimd/client-metadata.json`'s declared `"scope": "mcp:tools logs:read"` was acting as this CIMD client's allowed-scope set, silently filtering out `short-lived`. Plausible-looking (matches the project's own "Authlete silently ignores what it doesn't expect" pattern), added `short-lived` to that file, pushed it — **but a web search while waiting on GitHub Pages' cache to expire turned up Authlete's own KB stating this isn't how the override works at all**: "this function only narrows down the scopes originally requested at `/auth/authorization` API. The scopes parameter cannot include additional scopes that you did not request at the `/auth/authorization` API." A standard narrow-only OAuth invariant, not a CIMD-specific behavior.
- **Actual root cause**: the very first `GET /authorize` log line already showed `scope=mcp%3Atools+logs%3Aread` — `short-lived` was never in the *original* authorization request at all, so no consent-time override could add it back, regardless of what the CIMD doc says. That original request scope comes from `authserver/main.py`'s `well_known()` → `scopes_supported`, which the client SDK falls back to verbatim (per the already-documented quirk: no per-tool scope hint yet at `session.initialize()`).
- **Real fix**: added `short-lived` to `scopes_supported` in `well_known()`. Left the CIMD doc's edit in place too (harmless, arguably more accurate metadata) but it was not the fix — noting this so a future read of this file doesn't credit the wrong change.

## 2026-07-05 — Client now defaults to the deployed Render URL, not localhost

- Original plan (env-var override, defaulting to `127.0.0.1`) had the default backwards for this project's actual goal. The client's real audience is an evaluator (or an agent on their behalf) who only ever runs `client/main.py`, with no access to `server`/`authserver` — that was the premise for all of Phase 10's design, not a new idea, but `AGENT_TESTING.md`'s scenario commands and the client's own `SERVER_URL` default had drifted from it (defaulting to localhost, requiring an override to reach the thing an evaluator actually hits).
- Flipped it: `client/main.py` now has `PROD_SERVER_URL` (the live `mcp-auth-server-06y0.onrender.com`) as the real default, and a group-level `--local` flag (`python client/main.py --local get-time`) for our own dev-loop iteration only. `call_tool`/`probe_tool` take `server_url` as a parameter instead of closing over a module constant, threaded through via Click's `ctx.obj`.
- Updated `AGENT_TESTING.md` to match: every documented scenario command already omits `--local`, so no command text needed to change, only the doc's framing — it now says explicitly that these hit the live deployment by default and that `--local` is not part of the agent's toolkit.

## 2026-07-05 — First real run against Render: 421 from the SDK's own DNS-rebinding protection

- First live end-to-end run (`client/main.py get-time` against `mcp-auth-server-06y0.onrender.com`) got all the way through discovery, PKCE, the real consent screen, and a successful `/token` exchange — then the actual tool call came back `421 Misdirected Request`. Confirmed via `httpx`/`httpcore` debug logging that it wasn't a client-side connection-reuse bug: fresh TCP + TLS to the correct host with correct SNI, same result. A raw request bypassing the SDK's streaming transport surfaced the real body: `"Invalid Host header"`.
- That's not Cloudflare or Render — it's the MCP SDK's own `TransportSecurityMiddleware` (DNS-rebinding protection, on by default). `FastMCP`'s `Settings.transport_security` defaults to `allowed_hosts=['127.0.0.1:*', 'localhost:*', '[::1]:*']` — sensible for a server that's normally run locally, but it rejects every request once actually deployed under a real hostname, since that hostname was never in the allow-list. Confirmed directly: `mcp.settings.transport_security.allowed_hosts` printed exactly that loopback-only list before the fix.
- **Fix**: `server/main.py` now builds an explicit `TransportSecuritySettings`, keeping the loopback defaults (so local dev is unaffected — verified live, still `401` not `421`) and adding the host/origin derived from `RESOURCE_URI` (already the canonical source of truth for this service's public identity, so no new env var needed).
- This is exactly the kind of gotcha that can't surface until a real, non-localhost deploy exists — matches the project's own pattern of things that only break once you leave the loopback-only comfort zone (audience binding was the same story back in Phase 4).

## 2026-07-05 — `reset` subcommand replaces the `rm -f` instruction

- Prompted by actually using the CLI for real (re-verifying expiration against production): telling a user "delete this file to clear your session" is worse than just giving them a verb for it. Added `python client/main.py reset` — deletes `.mcp_auth_state.json` if present, prints `RESULT: OK` either way (whether or not there was anything to clear), same output contract as every other command.
- Updated every place that told a human or an agent to `rm -f .mcp_auth_state.json` directly: `AGENT_TESTING.md`'s reset instructions and all 8 scenarios, plus the two mentions in `PLAN.md`/this file. `--help` picks up the new command automatically via its docstring.

## 2026-07-05 — Remaining Phase 10 items: `/revoke` and the headless consent driver

- **`/revoke`** (`authserver/main.py`): wraps Authlete's `/auth/revocation` (RFC 7009), same shape as the existing `/token` handler (`clientId` + form-encoded `parameters`). Mapped Authlete's `RevocationResponse.action` to HTTP status precisely this time (`OK`→200, `INVALID_CLIENT`/`BAD_REQUEST`→400, else 500) rather than the coarser binary mapping `/token` uses, since we'd already looked up the real enum. Also added `revocation_endpoint` to `well_known()`'s metadata for spec completeness. Client-side: `revoke_token()` + a `revoke` subcommand, plain `httpx` POST (not the MCP transport — this isn't an MCP protocol call), reading the stored `access_token` + `client_id` straight from `FileTokenStorage`. Deliberately does not clear local state after revoking — `probe` needs the now-dead token to still be sitting there to prove it actually stopped working.
- **Headless consent driver** (`MCP_AUTH_CONSENT`/`MCP_AUTH_CONSENT_RETRY`): `_auto_consent()` GETs the consent screen, regexes out every `/authorize/confirm?...` link, decodes each one's `scope` query param and matches it against the env var (or matches the `/authorize/wrong-resource` link by path when the choice is `"wrong-resource"`), then GETs the matching link with `httpx.AsyncClient(follow_redirects=True)` — which lands the resulting 302 straight on our own already-listening loopback callback server, exactly as if a browser had clicked it. `handle_redirect` now checks these env vars first and only falls back to `webbrowser.open` when neither is set, so the real human-demo path is unchanged by default.
- Both needed for `AGENT_TESTING.md`'s scenarios to actually be agent-drivable end to end rather than needing a human at the consent screen — next step is running all 8 for real against the live deployment.

## 2026-07-05 — Actually running all 8 scenarios found three real bugs

Ran every scenario in `AGENT_TESTING.md` for real against the live Render deployment, playing the agent's role exactly as designed. Worth doing, not a formality — it surfaced two genuine bugs neither manual spot-testing nor code review had caught:

- **Deadlock in `_auto_consent`, Scenario 1.** First attempt hung until `httpx.ReadTimeout`. Root cause: the SDK does `await redirect_handler(auth_url)` and only *after* it returns does it invoke `callback_handler()` (which is what starts our loopback server actually listening). A real browser works because `webbrowser.open()` returns almost instantly — the human's actual click happens later, once the loopback server is already listening. My first `_auto_consent` tried to synchronously complete the *whole* flow, including following the final redirect into our own loopback URL, inside `redirect_handler` itself — nothing was listening on that port yet at that point. Fixed by firing the final "click the confirm link" request as a background `asyncio.create_task` instead of awaiting it, mirroring `webbrowser.open()`'s fire-and-forget nature exactly. The pending TCP connection queues safely at the OS level until `callback_handler` starts accepting moments later.
- **`get_logs` 404 in production, Scenario 2.** `server/Dockerfile` only ever `COPY`'d `server/`, never `docs/`, even though `get_logs` reads `docs/NOTES.md` straight off disk. Never caught before because prior container testing only exercised `/healthz` and `401`-without-token, never a real authenticated `get_logs` call. Fixed the Dockerfile, and added `docs/NOTES.md` to `mcp-auth-server`'s build filter — it's baked into the image at build time, not fetched live, so a future NOTES.md edit needs a redeploy too or the deployed tool would silently go stale forever.
- **Revoked token still worked, Scenario 7.** `revoke` returned `RESULT: OK`, but `probe` right after still showed `RESULT: OK` too — the token kept working. Confirmed via a raw curl that Authlete's `/auth/revocation` really did return `200` with an empty body (a legitimate "OK" per RFC 7009, which mandates 200 even for an unrecognized token — so "OK" alone doesn't prove anything actually got revoked). Root cause, found via a docs search: **for JWT-format access tokens (which is what this project uses), Authlete's revocation endpoint needs the token's `jti` claim, not the raw JWT string.** We were sending the full JWT. Fixed in `authserver/main.py`'s `/revoke` handler — decode the JWT (`pyjwt`, already a dependency, no signature verification needed since we're only reading a claim) and forward the `jti` instead. Deliberately fixed server-side, not client-side: a real RFC 7009 client only ever knows the actual `access_token` it was issued, so this Authlete-specific quirk belongs hidden behind our endpoint, not leaked into the client's `revoke_token()`.
- Scenarios 3, 4, 5, 6 passed cleanly on the first real attempt, no fixes needed.

## 2026-07-06 — Friend testing found a 9th bug: cross-process step-up 404s

A tester running a clean install hit "Not found" on step-up: calling `get-logs` (staging a `logs:read`-only token), then separately calling `get-time` in a new invocation. Scenarios 4/5 never caught this because they trigger step-up *within* one `client/main.py` process (401 first, then 403) — the SDK's `OAuthClientProvider` only runs PRM/AS discovery on a `401`, so by the time the in-process 403 hits, `oauth_metadata` is already cached from the earlier 401. A separate process starting with a *valid* (just under-scoped) token skips the 401 entirely and goes straight to 403 with no AS metadata discovered yet — the SDK's fallback in that case builds the authorize URL from the resource server's own origin (`get_authorization_base_url(server_url)`), not the authorization server's, which naturally 404s since the resource server has no `/authorize` route.

Reproduced with the tester's own failing URL shape before fixing, then confirmed the old code hits the identical 404 and the fix resolves it. Fix: `client/main.py` now proactively fetches and caches the AS's `.well-known/oauth-authorization-server` metadata (`_preload_oauth_metadata`) before the first request of every invocation, so the 403 branch always has the real `authorization_endpoint` on hand regardless of whether a 401 happened first in this process. Added as Scenario 9 in `AGENT_TESTING.md`; all 9 scenarios re-verified live afterward.

## 2026-07-06 — `check_scope` mislabeled wrong-audience as insufficient-scope

Asked directly: is there a live code path that actually exercises Authlete's combined scopes+resources check (the one from the "Correction" entry above)? Tracing it: both our tools are scope-gated, so every real tool call goes through `check_scope`, which does pass `scopes` and `resources` together — so yes, live. But `check_scope` treated Authlete's `action:FORBIDDEN` as always meaning insufficient scope, when Authlete doesn't distinguish *why* it forbade — a resource mismatch and a scope mismatch both come back as the identical `FORBIDDEN`.

Verified live against prod, not just reasoned about: minted a token via `tools/mint_token.py --scope "mcp:tools" --resource "https://wrong-server.example/resource"` (valid scope, wrong resource) and called `get_time` on the deployed server. Got `403 insufficient_scope, "Required scope: mcp:tools"` — mentioning scope specifically, for a token whose scope was genuinely fine. Not a security hole (the wrong-audience token is still correctly rejected either way), but a real regression against the Phase 4 write-up claim ("a token issued for a different resource gets `401 invalid_token`") — that stopped being accurate the moment `check_scope` started intercepting scope-gated calls before `verify_token`'s own audience check ever ran, since `ScopeEnforcementMiddleware` sits outermost and short-circuits first.

Fixed in `server/auth.py`: `check_scope` now checks `accessTokenResources` *before* trusting `action:FORBIDDEN` as a scope verdict — that field is present in the response whether or not the action is `FORBIDDEN`, so a wrong-audience token now falls through to `ScopeCheckResult.INVALID` (→ passes through to `verify_token`'s own 401) instead of being mislabeled `INSUFFICIENT` (→ 403 "insufficient_scope"). Restores the original Phase 4 behavior for scope-gated tools, not just ungated ones.
