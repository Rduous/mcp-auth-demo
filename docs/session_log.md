# Session Log

A human-written summary of work done with the coding agent on this project, intended to capture key decisions as they're made — not a full transcript.

---

## 2026-07-04

- Established the project repo and selected Python as the language of choice, given its simplicity and easy HTTP server support.
- Decided against OSS auth libraries due to their lack of built-in support for CIMD specifically, and the risk of using OSS given the newness of the spec.
- Settled on Authlete as our SaaS AS provider and confirmed its basic working via curl.
- Chose JWT tokens over opaque tokens to give us the option to skip the verification network hop for simplicity — tradeoff: doing so would mean forgoing Authlete's live revocation check, since that only happens via `/auth/introspection`.
- Added authentication to our MCP tool server and verified CIMD discovery.
- Discovered that Authlete is a backend-only solution (no hosted login/consent UI). Evaluated switching to a fully-hosted SaaS alternative (WorkOS), but decided to stand up our own auth server frontend instead — staying with the same provider is faster, and building the server ourselves gives us good learning/extension opportunities.
- Decided to start with a no-op "always approve the demo user" sign-in for now, with a plan to expand to real sign-in later.
- Figured out how to get Authlete's scope validation working.
- Got the auth flow (with a manual step standing in for a working callback hook) working end-to-end.

---

## 2026-07-05

- Refined the story around facilitating evaluation: re-scoped the earlier AWS/Terraform containerization plan down to Docker + Render, since evaluators only ever need to reach `server`/`authserver` asynchronously — they never run those two themselves, and never need the Authlete credential. Free, real HTTPS URLs, no AWS account required to satisfy evaluation; kept the AWS/Terraform work as a separate, optional portfolio-only plan.
- Drafted a plan for agent-led testing and verification, since evaluation leans on an agent driving the real system rather than a unit-test suite, and that agent only ever gets `client/main.py` — never the servers or their logs.
  - Realized the "browser popup" auth step isn't actually a blocker: the consent screen is static HTML with no JS or session state, so it's walkable by a plain HTTP client instead of needing real browser automation.
  - Designed: headless, env-var-driven consent selection in the client; file-backed token storage so state survives across separate CLI invocations; a real `/revoke` endpoint (RFC 7009) to stage revocation; an Authlete short-lived-scope trick to stage expiration deterministically; and a `probe` subcommand that bypasses the SDK's auto-reauth so failures surface cleanly instead of being silently healed.
  - Wrote up the design rationale (`TESTING_STRATEGY.md`) and the agent-facing scenario instructions (`AGENT_TESTING.md`), and added a new Phase 10 to the plan tracking the (not yet built) implementation.
- Added file system storage of tokens to allow auth-once behavior and enable testing of token expiration.
- Deployed servers to Render.
- Executed agent test suite against production servers.
