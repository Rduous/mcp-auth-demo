# Session Log

A human-written summary of work done with the coding agent on this project, intended to capture key decisions as they're made — not a full transcript.

---

## 2026-07-04

- Established the project repo and selected Python as the language of choice, given its simplicity and easy HTTP server support.
- Decided against OSS auth libraries due to their lack of built-in support for CIMD specifically, and the risk of using OSS given the newness of the spec.
- Settled on Authlete as our SaaS AS provider and confirmed its basic working via curl.
- Chose JWT tokens over opaque tokens to give us the option to skip the verification network hop for simplicity — tradeoff: doing so would mean forgoing Authlete's live revocation check, since that only happens via `/auth/introspection`.
