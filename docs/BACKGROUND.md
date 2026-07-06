# MCP Authorization & CIMD — working notes

Summary of a conversation prepping for a coding exam: build an MCP server (OAuth 2.1 resource server) and a CIMD-based MCP client CLI. Spec reference: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

Conversation name: MCP protocol overview and authorization basics
---

## Why this spec exists

MCP lets an AI client (Claude, an IDE, an agent) talk to external tools/data through a standard interface, instead of every app needing custom integration code per service. Local MCP servers (STDIO transport) need no auth — they just use environment credentials. Remote MCP servers (HTTP transport) do need auth, and that's what this spec covers: a tight profile of OAuth 2.1, so any compliant client can talk to any compliant server without bespoke glue.

## Roles

- **MCP client** = OAuth 2.1 client (e.g. Claude Code, an IDE)
- **MCP server** = OAuth 2.1 resource server (exposes tools, validates tokens)
- **Authorization server (AS)** = issues tokens after the user logs in and consents. May be hosted by the same party as the MCP server, or a separate one (e.g. your company's Okta/Azure AD).

## Key moving parts

**Discovery** — the client has no prior relationship with most servers it'll talk to, so everything is discovered at runtime:
- MCP server returns `401` + Protected Resource Metadata (RFC 9728), pointing to its AS
- Client fetches the AS's own metadata (RFC 8414 / OIDC Discovery) to learn endpoints

**Client identity — CIMD (Client ID Metadata Documents)** — the current preferred registration method (replacing Dynamic Client Registration in most cases):
- The client hosts a static JSON file at an HTTPS URL it controls
- `client_id` in the request *is* that URL
- The `client_id` field inside the JSON must exactly match the URL it's hosted at — this self-reference is the whole trust mechanism
- The AS fetches the doc at auth time, validates it, and checks the request's `redirect_uri` against the doc's `redirect_uris` list (exact match)
- **Why you can't impersonate another client by pointing at their CIMD URL:** the AS fetches *their* real metadata, including *their* real redirect URIs. Your request's redirect_uri won't match anything on that list, so even if a user approves consent, the authorization code is delivered to the real owner's redirect, not yours. Domain ownership = trust anchor for token issuance.
- **What CIMD does *not* protect against:** a self-hosted CIMD doc with a spoofed `client_name` (pure phishing on the consent screen — the AS is expected to also show the actual redirect hostname, not just the friendly name)

**PKCE** — mandatory, not optional. Fixes public clients (no secret) being vulnerable to authorization-code interception:
1. Client generates random `code_verifier`, hashes it (SHA-256) → `code_challenge`
2. `code_challenge` sent with the initial auth request
3. Auth code comes back via redirect
4. Client exchanges code + original `code_verifier` for a token
5. AS re-hashes the verifier and checks it matches step 2's challenge

Ephemeral per auth attempt — not a persistent key.

**Resource parameter / audience binding (RFC 8707)** — every authorization and token request MUST include a `resource` parameter identifying the target MCP server's canonical URI. Servers MUST validate tokens were issued for them specifically. This is the fix for "confused deputy" — a token meant for server A can't be replayed against server B. Easy to omit in a single-server demo since nothing visibly breaks — but it's evaluated/tested behavior, so verify the `aud` claim explicitly.

**Token passthrough is forbidden.** If an MCP server calls a downstream API on the user's behalf, it must use its own credentials for that call — never forward the token it received from the client. Enforcement is "the operator must follow the spec correctly," backstopped structurally by audience binding (a passed-through token gets rejected elsewhere as having the wrong audience).

**Step-up / incremental scopes.** If a token lacks scope for an action, server returns `403` + `insufficient_scope`; client re-runs a narrow auth request for just that scope rather than re-requesting everything.

## Tokens

- **Format**: not mandated by spec. Opaque (needs introspection call) or JWT (self-contained, signed, has an `aud` claim) — JWT is more common at scale.
- **Where they live**: client-side, in local credential storage (ideally OS keychain; in practice often a dotfile/credentials JSON — a known weak point). Server-side: ideally not stored at all if JWT; if opaque/logged, should be hashed, not plaintext.
- **Lifecycle**: short-lived access token (~5–60 min) + longer-lived refresh token (~30–90 days, rotated on use) is the target model. Silent refresh (using the refresh token without bothering the user) is the theory — but as of mid-2026, most real MCP clients, including Claude Code, don't fully implement it yet. Expect to hit re-auth prompts more than the spec's ideal suggests.

## "Session" clarification

Two independent things can be cached:
1. **Browser/IdP SSO session** (you're already logged into your company's identity provider) → skips the username/password screen during the OAuth dance, straight to consent.
2. **Client-side OAuth token** (Claude Code already holds a valid access/refresh token for this server) → skips the *entire* OAuth flow, no browser opens at all.

A pre-existing IdP session caches "I know who you are." A pre-existing client token caches "this app already has permission and doesn't need to ask again."

## Architecture (proof-of-concept scope)

Four components:
- **MCP client (CLI)** — local, public client. Discovers the server, presents its CIMD identity, drives PKCE, stores tokens, calls the protected tool.
- **MCP server** — resource server. Publishes Protected Resource Metadata, validates audience-bound tokens, enforces scope on ≥1 protected tool.
- **Authorization server** — pre-built (OSS or SaaS), not hand-rolled. Handles login, consent, PKCE, CIMD fetch/validation, token issuance.
- **CIMD metadata doc** — static JSON, hosted at a public HTTPS URL you control, describing the client.

Flow: client calls MCP server → `401` + AS location → client authorizes against AS using CIMD `client_id` + PKCE → AS fetches/verifies the CIMD doc → AS issues tokens → client calls MCP server's tool with `Authorization: Bearer <token>`.

## Gotchas / where the coding agent will likely go wrong

**CIMD-specific**
- Check whether your chosen AS actually supports CIMD before committing — this could become your biggest custom-code surface if not.
- CIMD doc must be reachable from the AS's network, not just your laptop — host it early, don't leave it to the end.
- `client_id` must string-match the doc's hosting URL exactly (watch trailing slashes).

**PKCE / redirects**
- Get code_verifier/code_challenge generation right early (base64url, no padding).
- Loopback redirect URIs use a random local port at runtime — make sure registration/CIMD handles that.

**Resource parameter**
- Easy to omit silently in a single-server POC. Test explicitly: inspect a token and confirm the `aud` claim is your MCP server's URI.

**Scope enforcement**
- Actually gate the protected tool on a scope, and have a way to *demonstrate* a 403/insufficient_scope, not just claim it works.

**Discovery order**
- Client should discover the AS via the MCP server's `401` + PRM, not hardcode AS endpoints — that's part of what's being evaluated.

**Likely agent-specific mistakes**
- Defaulting to Dynamic Client Registration instead of CIMD (more represented in older training data)
- Dropping the `resource` parameter since a single-server demo won't visibly break without it
- Conflating opaque vs. JWT token handling
- Losing track of the PKCE `code_verifier` across the local redirect callback
- Skipping step-up/403 handling entirely, treating auth as one-shot

**Suggested build order**: get a token manually (curl/Postman) against your chosen AS first — confirms it actually supports CIMD + PKCE + audience binding before building client and server on top of an unverified assumption.

## Exam prompt — impressions

Well-formed for testing "read a spec, build the full loop, make sane build-vs-buy calls." Explicit requirements: server as resource server (PRM, audience validation, scope enforcement), client as CIMD-driven single-command CLI. Deliberately open: which AS to use (biggest fork in the road), what the protected tool actually does (keep trivial — real signal is scope enforcement, not tool logic), and how literally to take "single command."

In-scope/load-bearing from this conversation: discovery, resource parameter, PKCE, CIMD mechanics, scope/step-up handling, token passthrough prohibition. Background/context, not directly evaluated: session caching mechanics, token lifecycle nuances — good material for the "POV on when this pattern makes sense" section of the write-up, not something to over-engineer.

## Write-up logging approach

- Don't hand-log in parallel with the agent transcript — annotate the transcript after each session instead.
- Keep a `NOTES.md` with only: architecture decisions, agent corrections/wrong turns, dead ends, moments you had to redirect. A dozen sharp entries beats fifty verbose ones.
- Specifically flag any "wrong but plausible" moments (agent conflating token formats, skipping the resource parameter, defaulting to DCR) — this is exactly the "subtle in practice" signal the prompt is testing for.
- Tag time-cost observations (e.g. what % of effort went to auth plumbing vs. the actual tool) — concrete data makes the "when does this pattern make sense" argument land better than a generic claim.

## Idea: gate the extended write-up behind a second scoped tool

Public repo (no private repos on your plan) holds the short required write-up in plain markdown. A second tool on the same MCP server, gated behind a different scope (e.g. `logs:read`), returns the fuller interaction log — demonstrating the access-control pattern on your own submission rather than just describing it.

- Keep the *required* write-up ungated — gate only the extended/raw logs.
- Prefer returning the log content directly from the tool call (in-band) over returning a Google Docs link — a shareable link can leak past the scope check once someone has it; in-band content keeps enforcement exactly where the assignment is testing it.
- Call this out explicitly in the write-up rather than leaving it for the evaluator to stumble onto.
