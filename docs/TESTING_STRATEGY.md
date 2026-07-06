# Testing strategy: agent-verifiable scenarios

Design record for how this project gets verified by an automated evaluation
agent instead of (or alongside) unit tests. Operational counterpart —
what the agent actually runs — is [AGENT_TESTING.md](AGENT_TESTING.md).
Status: design agreed, fully implemented and verified against production
(see Phase 10 in [PLAN.md](PLAN.md)). Kept as a design record, not a live
TODO list — the "Decisions" and "Rejected alternatives" below are the
useful, load-bearing part now.

## Problem

Chatting with Tom gave me a sense that unit testing is not the preferred
approach at GA, so I chose not to implement a unit test suite. Instead I
focused on writing instructions for an agent to evaluate the system, using
testing scenarios and observable behavior to judge the system's
correctness. I may have over-indexed on one conversation, but it was a fun
learning process! Per [PHASE7_PLAN.md](PHASE7_PLAN.md), that agent only
ever gets `client/main.py` — never `server`/`authserver` themselves, their
processes, or their logs. Two things stood in the way of that being
verifiable at all:

1. Several required scenarios (token revocation, expiration, wrong
   audience, exhausted step-up) don't arise from normal client use — they
   need to be deliberately staged, and staging can't lean on server-side
   access the agent doesn't have.
2. The auth flow assumes a human with a browser (`webbrowser.open`,
   [client/main.py:62](../client/main.py)) — no display, no human, in an
   agent's environment.

## Key realization

The AS-frontend's consent screen ([authserver/main.py](../authserver/main.py))
is static HTML — no JS, no cookies/session, one hardcoded demo subject.
Each "choice" is a plain `<a href>` to a GET endpoint that 302s to the
client's own loopback redirect URI. That means the entire flow is walkable
by a plain HTTP client; it never needed a real browser, or browser
automation (Playwright/Selenium) — those would add a heavy dependency and a
display requirement to solve a problem that doesn't exist here.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Where hooks live | Extend `client/main.py` in place, all additions off by default | It's the one artifact the agent is guaranteed to run (Phase 7's framing). A separate harness script would need to import or duplicate its OAuth setup anyway, and risks the doc describing behavior the actual evaluated artifact doesn't have. |
| Headless consent | New env vars (`MCP_AUTH_CONSENT`, `MCP_AUTH_CONSENT_RETRY`) select which link the client "clicks" itself via `httpx`, instead of `webbrowser.open` | No new server behavior, no browser automation dependency. Unset → today's real-browser demo path, unchanged. |
| Cross-invocation state | Swap `InMemoryTokenStorage` for a file-backed `TokenStorage` | Multi-step scenarios (stage a token, revoke it, retry) need the token to survive across separate CLI invocations — it currently doesn't. Also a general CLI-quality fix, not test-only. |
| Revocation staging | Real `/revoke` endpoint on `authserver`, wrapping Authlete's native `/auth/revocation` (RFC 7009) | Standard OAuth capability, not a test backdoor. Safe to expose publicly: a caller can only revoke a token it already holds, same trust model as `/token` already has for a public client. |
| Expiration staging | One new Authlete-console scope (`short-lived`, short duration override) combined with `mcp:tools` in a request — Authlete's "shortest duration wins" rule collapses the combined token's lifetime | One new consent-picker dict entry in `authserver`, no new server logic. Deterministic and fast (~10s) instead of waiting out whatever the real default token lifetime is. |
| Masking by auto-reauth | New `probe` subcommand: same session machinery, but a **static** bearer header instead of `OAuthClientProvider` | `OAuthClientProvider` auto-heals a 401/403 by silently re-authenticating — exactly right for the real demo, exactly wrong for verifying "this specific token now fails." `probe` bypasses that so a revoked/expired/wrong-audience/insufficient-scope token surfaces as a clean, unmasked result. |
| Verifiable output | One structured `RESULT: OK ...` / `RESULT: ERROR <status> <code>: ...` line per terminal outcome, non-zero exit on error | Today an unrecovered auth failure raises an uncaught exception/traceback — a real client-quality bug independent of testing, fixed as part of this work. Structured output gives the agent an exact substring to check instead of parsing prose or a stack trace. |

## What doesn't change

- `server/main.py`, `server/auth.py`, `server/scope_gate.py` — untouched.
  Nothing about token/scope/audience enforcement becomes test-aware.
- `authserver`'s `/authorize`, `/authorize/confirm`, `/token` — unchanged.
  A headless client walking the consent links is indistinguishable, from
  the server's perspective, from a human clicking them in a real browser.
- Default `client/main.py` behavior (no env vars set) — identical to today.

## Rejected alternatives

- **Browser automation (Playwright/Selenium)** — unnecessary given the
  consent screen has no JS/session to drive; adds a heavy dependency and a
  display requirement to solve a problem the static-HTML design already
  avoids.
- **Separate test-harness script** — would duplicate or import
  `client/main.py`'s OAuth setup, adds a second entry point that could
  drift from what the doc describes, and cuts against Phase 7's framing
  that the client is the one thing evaluators (and their agents) actually run.
- **Handing the agent `AUTHLETE_SAT`** so it can revoke/expire tokens
  directly against Authlete's admin API — exactly the credential Phase 7
  already decided never to hand out (single admin-level credential for the
  whole service, not scoped per-user). Would also let the agent do far more
  than test the client with it.
- **Relying on real wall-clock token expiry** for the expiration scenario —
  whatever the default duration is, waiting it out is slow and not
  something to hardcode a sleep against. The per-scope duration override
  makes it deterministic and short instead.

## Open items (resolved)

All items below were open questions at design time; each was resolved
during Phase 10 (see [PLAN.md](PLAN.md) and [NOTES.md](NOTES.md) for the
concrete findings):

- Authlete's `/auth/revocation` API was confirmed enabled by default —
  no console toggle needed.
- The SDK's `streamablehttp_client` does accept a plain `headers=` bearer
  header in place of `OAuthClientProvider`, used as-is by `probe`.
- The `RESULT: ERROR` handler catches `BaseExceptionGroup`/`httpx.HTTPStatusError`
  specifically (see `_describe_error` in [client/main.py](../client/main.py)),
  not a bare `except Exception`.
