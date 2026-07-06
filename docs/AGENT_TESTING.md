# Agent-driven scenario verification

**Status: fully implemented.** File-backed token storage, the `probe` and
`revoke` subcommands, the `reset` subcommand, structured `RESULT:` output,
a production-by-default `SERVER_URL`, and the `MCP_AUTH_CONSENT`/
`MCP_AUTH_CONSENT_RETRY` headless consent driver all exist in
[client/main.py](../client/main.py) now — every scenario below is
drivable end to end with no human clicking anything. See
[TESTING_STRATEGY.md](TESTING_STRATEGY.md) for why it's shaped this way.

**Important**: every command below runs with no flags, which means it hits
the **live, deployed** `mcp-auth-server`/`mcp-auth-authserver` on Render by
default — never a local server. That's deliberate: the agent has no access
to `server`/`authserver` at all, not even a local copy of them running
somewhere it could theoretically inspect. `client/main.py --local ...`
exists purely as a faster dev-loop convenience for whoever is *building*
this project — it is not part of the agent's toolkit and shouldn't appear
in anything below.

## Who this is for

An agent (or any automated runner) verifying this project's auth behavior
with shell access to this repo's `client/` directory only. You do not have
access to `server/` or `authserver/`'s processes, source internals, or logs
— treat them as opaque, already-running network services, same as a real
deployment. Every verdict below is decided entirely from what
`client/main.py` prints and exits with. If you find yourself wanting to peek
at server-side state to confirm something, that's a sign the scenario is
underspecified — stop and flag it rather than reaching around the client.

## Prerequisites

- Python env set up per [README.md](../README.md) (`venv` + `requirements.txt`).
- Nothing to start, stop, or configure server-side — `client/main.py`
  defaults to the live Render deployment, which is already running.

## CLI surface

Run `python client/main.py --help` (and `python client/main.py <command> --help`)
to discover the full command surface and its options directly — every
command and flag is self-documented there, and that's the authoritative,
always-current source rather than this doc.

Two things `--help` won't tell you, since they're not part of Click's own
help text:

- **Required scope per tool** — `get_time` needs `mcp:tools`, `get_logs`
  needs `logs:read`. Both auto-step-up on `403 insufficient_scope` (see the
  env vars below).
- **`--local` is not for agent use.** It exists purely as a dev-loop
  convenience to point at `127.0.0.1` instead of the deployed Render
  service; every scenario below assumes it's omitted.

| Env var | Meaning |
|---|---|
| `MCP_AUTH_CONSENT` | Which consent-screen link to "click" on the *first* authorization attempt: `mcp:tools`, `logs:read`, `email`, `wrong-resource`, or `mcp:tools short-lived`. **Must be set for every scenario below** — unset falls back to opening a real browser and blocking on a human. |
| `MCP_AUTH_CONSENT_RETRY` | Which link to click on the automatic step-up retry after a `403 insufficient_scope`. Defaults to the same value as `MCP_AUTH_CONSENT` if unset. |

**Reset** (run before any scenario marked "fresh state" below):

```bash
python client/main.py reset
```

Clears the persisted token and registered client info, so the next command
authenticates from scratch. Nothing server-side needs resetting — revocation
and expiration are one-way, per-token state Authlete already tracks; a
freshly-minted token always starts out live.

**Output contract**: every terminal outcome prints exactly one line matching:

```
RESULT: OK <content>
RESULT: ERROR <http-status> <error-code>: <description>
```

Grep for that line and ignore everything else on stdout (auth-attempt/
step-up narration, timestamps) as informational, not part of the pass/fail
signal.

## Scenarios

### 1. Happy path — `mcp:tools`
```bash
python client/main.py reset
MCP_AUTH_CONSENT=mcp:tools python client/main.py get-time
```
Expect: `RESULT: OK ...` (a timestamp).

### 2. Happy path — `logs:read`
```bash
python client/main.py reset
MCP_AUTH_CONSENT=logs:read python client/main.py get-logs
```
Expect: `RESULT: OK ...` (log content).

### 3. Scope differentiation
Reuses Scenario 2's token — run immediately after it, no reset.
```bash
python client/main.py probe get-time
```
Expect: `RESULT: ERROR 403 insufficient_scope ...` — a `logs:read`-only token
must not unlock `get_time`.

### 4. Step-up succeeds
```bash
python client/main.py reset
MCP_AUTH_CONSENT=email MCP_AUTH_CONSENT_RETRY=mcp:tools python client/main.py get-time
```
Expect: `RESULT: OK ...`. Stdout should also show two authorization attempts
(first requesting `email`, second — the automatic step-up — requesting only
`mcp:tools`); informational context if this fails, not part of the verdict.

### 5. Step-up exhausted
```bash
python client/main.py reset
MCP_AUTH_CONSENT=logs:read MCP_AUTH_CONSENT_RETRY=logs:read python client/main.py get-time
```
Expect: `RESULT: ERROR 403 insufficient_scope ...`, terminal — no third
attempt. Proves the client gives up after one step-up retry rather than
looping, per the SDK's documented behavior.

### 6. Wrong audience
```bash
python client/main.py reset
MCP_AUTH_CONSENT=wrong-resource python client/main.py get-time
```
Expect: `RESULT: ERROR 401 ...` — token minted for a different resource must
be rejected.

### 7. Revocation
```bash
python client/main.py reset
MCP_AUTH_CONSENT=mcp:tools python client/main.py get-time   # expect RESULT: OK
python client/main.py revoke                                 # expect RESULT: OK
python client/main.py probe get-time                          # expect RESULT: ERROR 401
```

### 8. Expiration
Relies on a `short-lived` scope already registered on the live Authlete
service, with a 10-second token-duration override (one-time console setup
done during development — not in git, see [TESTING_STRATEGY.md](TESTING_STRATEGY.md)
for why). No action needed here; the scope already exists.
```bash
python client/main.py reset
MCP_AUTH_CONSENT="mcp:tools short-lived" python client/main.py get-time   # expect RESULT: OK
sleep 12
python client/main.py probe get-time                                       # expect RESULT: ERROR 401
```

### 9. Cross-process step-up
```bash
python client/main.py reset
MCP_AUTH_CONSENT=logs:read python client/main.py get-logs   # stage a logs:read-only token, process exits
MCP_AUTH_CONSENT=mcp:tools python client/main.py get-time   # separate process, must still step up correctly
```
Expect: both commands print `RESULT: OK ...`. This differs from Scenario 4
(step-up succeeds): there, the 401-then-403 sequence happens inside one
`client/main.py` process, so the SDK already has the authorization server's
metadata cached in memory by the time it hits the 403. Here the second
command starts as a brand-new process with a *valid* (just under-scoped)
token already on disk from the first — it goes straight to a 403 with no
prior 401 in this process to trigger discovery. Confirmed as a real,
previously-undetected bug (the SDK's step-up path fell back to building the
authorize URL against the resource server's own origin instead of the
authorization server's, producing a 404) and fixed by having `client/main.py`
preload the AS's metadata itself before the first request, regardless of
which status code eventually triggers a redirect.

### Bonus (not one of the 9): scope enforcement is server-side, not a client-side courtesy

Everything above goes through `client/main.py`'s SDK session. This scenario
bypasses the client entirely with a raw `curl` — no MCP session handshake,
no `OAuthClientProvider` — to prove the `403` in Scenario 3 comes from
`server/scope_gate.py`'s middleware, not from anything the client
chooses to enforce on its own.

```bash
python client/main.py reset
MCP_AUTH_CONSENT=logs:read python client/main.py get-logs   # stage a logs:read-only token

TOKEN=$(python3 -c "import json,pathlib; print(json.loads(pathlib.Path('.mcp_auth_state.json').read_text())['tokens']['access_token'])")

curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST "https://mcp-auth-server-06y0.onrender.com/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_time","arguments":{}}}'
```

Expect: `403`, with body `{"error":"insufficient_scope","error_description":"Required scope: mcp:tools"}`.
Verified live 2026-07-05 against the deployed server with a real
`logs:read`-only token and no other flags or headers — the request never
completes an MCP `initialize` handshake, and the middleware still rejects
it before the request reaches FastMCP's own routing.

## Pass criteria

All 9 scenarios produce their expected `RESULT:` line. Report any mismatch
with the actual line seen — don't editorialize about *why* it might have
failed unless it's directly observable from stdout.

## Known noise, not bugs

- **Render free-tier cold start**: services sleep after ~15 min idle and
  take ~1 min to wake. If the very first call in a session times out or
  errors oddly, retry once before treating it as a real failure.
- **Scenario 5's terminal 403 is intentional** — the SDK only attempts
  step-up once per request; a second insufficient-scope response is
  supposed to propagate as a real error, not retry again.
- **`probe`'s error descriptions usually read `(response body unavailable)`,
  not the actual error text** (e.g. `insufficient_scope`) — the streamable-
  HTTP transport reads responses as a stream internally, so by the time
  `probe` catches the error the body is often no longer readable. The
  **status code** (`401`/`403`) is the reliable signal; treat the
  description as best-effort context, not something to assert on.
