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

## Open items

- [ ] Find/set `pkceRequired` (+ `pkceS256Required`) on the Authlete service — not visible under the console's CIMD/Metadata section, still hunting for the right settings tab.
