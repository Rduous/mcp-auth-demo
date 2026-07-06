# Phase 7 — Containerize + host both services: detailed plan

Re-scoped from an earlier draft of this phase that went straight to AWS/Terraform.
What evaluation actually needs is narrower: evaluators reach `server`/`authserver`
asynchronously, without me present. They never run those two services
themselves — only `client/main.py`, which holds no secret. That's satisfiable
for free with Docker + Render. The AWS/Terraform work is real, but it's now
purely portfolio/interview value — see `docs/PHASE9_AWS_PLAN.md` (kept locally as personal reference, deliberately gitignored, not part of this repo/submission).

---

## The one thing worth saying up front

**Two services, not one**, and **the Authlete credential never gets checked in
or handed to anyone.**

- `server/main.py` — the MCP resource server. Its `RESOURCE_URI`
  (`server/auth.py:10`) is the canonical resource URI the whole flow hinges on.
- `authserver/main.py` — the thin AS-frontend wrapping Authlete. Its `ISSUER`
  constant (`authserver/main.py:15`) is what ends up in the Protected Resource
  Metadata and what a client fetches `/.well-known/oauth-authorization-server`
  from.

Both currently hardcode `127.0.0.1` + a fixed port, bind only to `127.0.0.1`,
and hold `AUTHLETE_SAT`/`AUTHLETE_SERVICE_ID` (read from env vars already —
see `authserver/main.py:12-13`, `server/auth.py:7-8`). That's good: it means
the secret-handling problem is already "give the running container the right
env vars," not "rewrite how the app reads credentials."

**Why not just share the Authlete credential so evaluators can run everything
locally?** `AUTHLETE_SAT` is a single admin-level Bearer credential for your
whole configured Authlete service — it can mint tokens for any client/subject/
scope and drive the service's config APIs. It isn't scoped per-user, and
there's no lightweight way to carve out a narrower one; the only real
equivalent would be each evaluator standing up their own Authlete account and
re-doing every config gotcha already logged in [NOTES.md](NOTES.md) (PKCE
toggle, scope pre-registration, JWT signing algo). Not "easy to install."
The good news: it's moot, because evaluators only ever run the client, never
these two services.

---

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Container platform | **Docker** (plain Dockerfiles, no Compose orchestration needed in production) | Standard, portable, reusable later for the optional AWS migration |
| Hosting | **Render.com**, free tier, two Web Services | Real always-reachable-enough public HTTPS URLs, zero cost, no AWS account, no domain purchase required |
| Deploy config | **Render Blueprint** (`render.yaml`, checked into git) | Codifies both services' config as text (nice parallel to the Terraform habit) and makes "recreate both services from scratch" one click, useful if you tear them down between sessions |
| Secret handling | `sync: false` env vars in the Blueprint | Render prompts for the actual value once, in its dashboard, at Blueprint-creation time — the value **never** appears in `render.yaml` or git, only the variable *name* does |
| Local dev loop | **Docker Compose**, not deployed anywhere | Fastest local edit loop (bind-mount + `uvicorn --reload`), independent of whatever's live on Render |

---

## Ordered steps

### 1. Add health-check endpoints
`GET /healthz` on both apps, returning a bare `200`. Render's health check
(and, later, an ALB target group if you ever do Phase 9) needs something to
poll. Starlette (`authserver`): one more `Route`. FastMCP (`server`): check
whether it exposes a way to add a plain route, or mount a tiny Starlette
sub-app just for this endpoint.

### 2. Fix host binding
Both `uvicorn.run(app, host="127.0.0.1", ...)` calls → `host="0.0.0.0"`.
Inside a container, `127.0.0.1` only accepts connections *from inside that
same container* — Docker's port mapping (and Render) need `0.0.0.0`.

### 3. Make `RESOURCE_URI`/`ISSUER` env-var-driven
Both are currently hardcoded constants pointing at `127.0.0.1`. Switch to
`os.environ.get(...)` so the same Docker image works locally and on Render —
no rebuild needed when the hostname changes, just a different env var value.

### 4. Write Dockerfiles
One per service (`server/Dockerfile`, `authserver/Dockerfile`) — python slim
base, `pip install -r requirements.txt`, `CMD ["uvicorn", ...]`. Both services
share the repo-root `requirements.txt`, so keep the Docker **build context**
at the repo root even though each Dockerfile lives in its own subdirectory —
avoids duplicating that file per service:

```dockerfile
# server/Dockerfile — built with context = repo root
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ ./server/
WORKDIR /app/server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

(`authserver/Dockerfile` mirrors this, port 8001.)

### 5. Verify locally with Docker Compose before touching Render
A `docker-compose.yml` at repo root running both services together, using a
local `.env` file (gitignored) for `AUTHLETE_SERVICE_ID`/`AUTHLETE_SAT`.
Confirms the containers work exactly as they will in prod, isolating "did I
break the app" from "did I misconfigure hosting." This `docker-compose.yml`
is also your fast pair-coding dev loop afterward — bind-mount the source and
run uvicorn with `--reload` so edits during the interview show up without a
rebuild.

### 6. Render Blueprint (`render.yaml`, repo root)
Two `type: web`, `runtime: docker` services, one per subdirectory:

```yaml
services:
  - type: web
    name: mcp-auth-server
    runtime: docker
    dockerContext: .
    dockerfilePath: ./server/Dockerfile
    healthCheckPath: /healthz
    envVars:
      - key: AUTHLETE_SERVICE_ID
        sync: false
      - key: AUTHLETE_SAT
        sync: false
      - key: RESOURCE_URI
        value: https://mcp-auth-server.onrender.com/mcp

  - type: web
    name: mcp-auth-authserver
    runtime: docker
    dockerContext: .
    dockerfilePath: ./authserver/Dockerfile
    healthCheckPath: /healthz
    envVars:
      - key: AUTHLETE_SERVICE_ID
        sync: false
      - key: AUTHLETE_SAT
        sync: false
      - key: ISSUER
        value: https://mcp-auth-authserver.onrender.com
```

`sync: false` is the whole answer to "I don't want it in the repo": Render
never writes these values into the YAML. The first time you create the
Blueprint from the Render dashboard, it prompts you to type each `sync: false`
value once — from then on the value lives only in Render's encrypted env-var
store, injected into the container at runtime like any other env var.

If you'd rather skip the Blueprint file entirely: create each Web Service
manually in the dashboard (Docker runtime, point at the repo, set the
Dockerfile path) and paste the secret directly into that service's
Environment tab. Equally safe, just not reproducible from a checked-in file.

### 7. First deploy
Push `render.yaml` (no secret values in it), create the Blueprint from the
Render dashboard, fill in the two `sync: false` prompts with your real
Authlete values. Render builds both images and deploys.

### 8. Point the app at its real URLs
The `value:` lines in the Blueprint above already do this, but double check
after first deploy that Render's actual assigned hostnames match what you
put in `RESOURCE_URI`/`ISSUER` — Render lets you pick the service name (hence
the URL) at creation time, so set it deliberately rather than accepting a
randomized one.

### 9. Smoke test end to end
- Same curl check as Phase 2, against the real URL: no token → `401` +
  `www-authenticate` pointing at the real PRM URL.
- Run `client/main.py` against `https://mcp-auth-server.onrender.com/mcp` and
  confirm the full flow — discovery, CIMD/PKCE against the real hosted
  AS-frontend, token, tool call — with nothing localhost involved.
- **Same audience-binding gotcha as ever**: the externally-visible hostname
  must match `RESOURCE_URI` exactly (scheme, host, path). A mismatch fails
  silently as a plain `401` from your own resource-server check
  (`server/auth.py`), indistinguishable from "no token" unless you know to
  check this first.
- **New caveat specific to Render's free tier**: services sleep after ~15 min
  idle and take ~1 min to cold-start on the next request. If an evaluator's
  client has a short timeout, the very first call might fail before the
  container's even up. Worth one line in the write-up about this, and worth
  trying the flow yourself after a period of idleness to see the real
  behavior before assuming it's fine.

### 10. Ongoing: pushes auto-deploy
Render redeploys automatically on every push to the connected branch by
default — after a pair-coding session, pushing the changes *is* the redeploy
step, nothing else to run.

---

## Summary of what changes where

| File | Change |
|---|---|
| `server/main.py` | `host="0.0.0.0"`, add `/healthz` |
| `server/auth.py` | `RESOURCE_URI` from env var |
| `authserver/main.py` | `host="0.0.0.0"`, add `/healthz`, `ISSUER` from env var |
| new: `server/Dockerfile`, `authserver/Dockerfile` | containerize each service, shared root `requirements.txt` |
| new: `docker-compose.yml` | local dev loop, not deployed |
| new: `render.yaml` | Blueprint, secret values marked `sync: false` |
| new: `.env` (gitignored) | local-only Authlete credentials for Compose |
| `cimd/client-metadata.json` | check for any hardcoded resource/server URL references — likely none (it's about the *client*, not the server), but confirm rather than assume |
