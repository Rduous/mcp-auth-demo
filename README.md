# MCP Auth Project

An MCP (Model Context Protocol) resource server and CIMD-based client CLI, implementing the [MCP authorization spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization): OAuth 2.1 + PKCE, Protected Resource Metadata discovery, CIMD client identity, resource-parameter audience binding, and scope enforcement with step-up auth.

## Layout

- `server/` — MCP resource server (Flask). Publishes Protected Resource Metadata, validates audience-bound tokens, enforces scope on protected tools.
- `client/` — MCP client CLI. Discovers the server's AS via `401` + PRM, authenticates via CIMD + PKCE, calls tools with the resulting token.
- `cimd/` — Static CIMD metadata document (hosted at a public HTTPS URL) that identifies the client.
- `docs/` — [PLAN.md](docs/PLAN.md) (phase checklist), [NOTES.md](docs/NOTES.md) (work log), [BACKGROUND.md](docs/BACKGROUND.md) (spec prep notes).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Status

Early scaffolding — see [docs/PLAN.md](docs/PLAN.md) for current phase.
