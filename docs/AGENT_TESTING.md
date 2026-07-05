# Agent-driven scenario verification

**Status: partially implemented.** File-backed token storage, the `probe`
subcommand, structured `RESULT:` output, and a production-by-default
`SERVER_URL` all exist in [client/main.py](../client/main.py) now. Still
missing: the `revoke` subcommand + `authserver`'s `/revoke` route
(Scenario 7), and the `MCP_AUTH_CONSENT`/`MCP_AUTH_CONSENT_RETRY` headless
consent driver (Scenarios 4-8 currently still need a human clicking the
real consent screen). See [TESTING_STRATEGY.md](TESTING_STRATEGY.md) for
why it's shaped this way.

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
- One-time Authlete console setup for Scenario 8 only (expiration) — see
  that scenario's note. Everything else needs no console changes.

## CLI surface

| Command | Behavior |
|---|---|
| `python client/main.py get-time` | Calls `get_time` (needs `mcp:tools`). Full OAuth dance, auto step-up on `403 insufficient_scope`. |
| `python client/main.py get-logs [--topic X]` | Calls `get_logs` (needs `logs:read`). Same auto-step-up behavior. |
| `python client/main.py revoke` | Revokes the currently-stored access token via the AS's `/revoke` endpoint. Requires a token already staged. |
| `python client/main.py probe <get-time\|get-logs>` | Calls the tool using the stored token **without** the SDK's auto-reauth/step-up healing — a bad token surfaces as a clean, unmasked failure instead of being silently repaired. Requires a token already staged; fails fast with a clear message if none exists. |
| `--local` (group-level flag, e.g. `python client/main.py --local get-time`) | Points at `127.0.0.1` instead of the deployed Render service. **Not for agent use** — dev-loop convenience only; every scenario below assumes it's omitted. |

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
**Requires one-time Authlete console setup** (not in git — see
[TESTING_STRATEGY.md](TESTING_STRATEGY.md) for why): register a scope named
`short-lived` with a 10-second token-duration override.
```bash
python client/main.py reset
MCP_AUTH_CONSENT="mcp:tools short-lived" python client/main.py get-time   # expect RESULT: OK
sleep 12
python client/main.py probe get-time                                       # expect RESULT: ERROR 401
```

## Pass criteria

All 8 scenarios produce their expected `RESULT:` line. Report any mismatch
with the actual line seen — don't editorialize about *why* it might have
failed unless it's directly observable from stdout.

## Known noise, not bugs

- **Render free-tier cold start**: services sleep after ~15 min idle and
  take ~1 min to wake. If the very first call in a session times out or
  errors oddly, retry once before treating it as a real failure.
- **Scenario 5's terminal 403 is intentional** — the SDK only attempts
  step-up once per request; a second insufficient-scope response is
  supposed to propagate as a real error, not retry again.
