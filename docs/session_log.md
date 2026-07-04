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
