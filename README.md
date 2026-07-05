# MCP Auth Project

An MCP (Model Context Protocol) resource server and CIMD-based client CLI, implementing the [MCP authorization spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization): OAuth 2.1 + PKCE, Protected Resource Metadata discovery, CIMD client identity, resource-parameter audience binding, and scope enforcement with step-up auth.

## Layout

- `server/` — MCP resource server (official `mcp` SDK / FastMCP, streamable HTTP). Publishes Protected Resource Metadata, validates audience-bound tokens via Authlete introspection, enforces scope on protected tools.
- `authserver/` — thin AS-frontend wrapping Authlete's API (`/authorize`, `/token`, `/.well-known/oauth-authorization-server`) — Authlete itself has no hosted login/consent UI.
- `client/` — MCP client CLI. Discovers the server's AS via `401` + PRM, authenticates via CIMD + PKCE, calls tools with the resulting token.
- `cimd/` — Static CIMD metadata document (hosted at a public HTTPS URL) that identifies the client.
- `docs/` — [PLAN.md](docs/PLAN.md) (phase checklist), [NOTES.md](docs/NOTES.md) (work log), [WRITEUP.md](docs/WRITEUP.md) (design decisions), [BACKGROUND.md](docs/BACKGROUND.md) (spec prep notes).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`server` and `authserver` both need `AUTHLETE_SERVICE_ID` and `AUTHLETE_SAT` in their environment (an Authlete service's credentials — not committed anywhere in this repo).

## Just running the client

`server` and `authserver` are already deployed and always running — you don't need to start anything to use the client:

```bash
python3 client/main.py get-time
```

This hits the live, deployed services by default. **Free-tier cold start**: if it's been idle for a while (~15 min), the very first request can time out or feel slow instead of failing cleanly — that's Render's free tier spinning the container back up, not a broken deployment. A retry, or waiting roughly a minute, should resolve it.

`python3 client/main.py --help` lists every subcommand (`get-time`, `get-logs`, `probe`, `reset`).

## Running the servers locally (for development)

Only needed if you're modifying `server/` or `authserver/` themselves — pass `--local` to point the client at whichever of these you start instead of the deployed services.

**Option 1 — directly with Python** (fastest edit loop, no build step):

```bash
export AUTHLETE_SERVICE_ID=<your value>
export AUTHLETE_SAT=<your value>
python3 authserver/main.py &   # or a separate terminal, port 8001
python3 server/main.py &       # or a separate terminal, port 8000
python3 client/main.py --local get-time
```

**Option 2 — Docker Compose** (same two services, containerized; exercises the same setup Render deploys from):

```bash
cp .env.example .env
# edit .env, fill in real AUTHLETE_SERVICE_ID / AUTHLETE_SAT
docker compose up --build
```

This builds `server/Dockerfile` and `authserver/Dockerfile`, binds both ports to `localhost` (`8000`, `8001`) same as Option 1, and bind-mounts each service's source with `uvicorn --reload` so edits show up without a rebuild. The client still runs directly on the host either way (`python3 client/main.py --local get-time`) — it's not containerized.

Quick sanity check either way: `curl http://127.0.0.1:8000/healthz` and `curl http://127.0.0.1:8001/healthz` should both return `200 OK` before you try the full client flow.

`docker-compose.yml` is local-dev-only — it's not what's deployed to Render (see `render.yaml` and [docs/PHASE7_PLAN.md](docs/PHASE7_PLAN.md) for that).

## Status

Core auth flow (discovery, CIMD, PKCE, audience binding, scope enforcement + step-up) is complete and containerized; see [docs/PLAN.md](docs/PLAN.md) for the current phase and what's still open (Render deployment, agent-verifiable test scenarios).
