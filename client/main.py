import asyncio
import json
import os
import re
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import click
import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)

# Production is the default -- this client's real audience is an evaluator (or
# an agent acting on their behalf) who only ever runs this file, with no
# access to the two servers or their logs, against the actually-deployed
# services. --local exists purely for our own faster dev-loop iteration.
PROD_SERVER_URL = "https://mcp-auth-server-06y0.onrender.com/mcp"
LOCAL_SERVER_URL = "http://127.0.0.1:8000/mcp"
PROD_AS_URL = "https://mcp-auth-authserver.onrender.com"
LOCAL_AS_URL = "http://127.0.0.1:8001"
CIMD_URL = "https://rduous.github.io/mcp-auth-demo/cimd/client-metadata.json"

# Raw OAuth scope names aren't self-explanatory to someone watching the CLI
# output -- shown alongside the tool they unlock instead (see handle_redirect).
SCOPE_LABELS = {
    "mcp:tools": "get-time",
    "logs:read": "read-logs",
}

# Persisted across separate CLI invocations (not just within one process) --
# needed so a scenario can stage a token in one command (get-time) and
# reuse the *same* token in a later one (probe), e.g. after a wait to test
# expiration. Gitignored; delete it to force a fresh identity.
#
# Anchored to this file's own location (repo root), not the process's
# working directory -- running the CLI from client/ instead of the repo
# root would otherwise silently create a second, disconnected state file
# there instead of reusing the one at the root.
STATE_FILE = Path(__file__).resolve().parent.parent / ".mcp_auth_state.json"

# NOTE: it's tempting to set client_metadata.scope per-tool to request only
# what's needed and avoid a step-up round trip -- doesn't work. The first
# 401 happens at session.initialize(), before the client has chosen a tool
# to call, so the SDK's scope-selection fallback (no tool-specific hint
# available yet) requests the AS's full advertised scopes_supported instead
# of anything we set locally. Not worth fighting; see NOTES.md.


class FileTokenStorage(TokenStorage):
    """Same role as the SDK's in-memory example storage, but backed by a
    JSON file so state survives across separate `python client/main.py ...`
    invocations, not just within one process.
    """

    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        try:
            self._state: dict = json.loads(path.read_text())
        except FileNotFoundError:
            self._state = {}

    async def get_tokens(self) -> OAuthToken | None:
        data = self._state.get("tokens")
        return OAuthToken.model_validate(data) if data else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._state["tokens"] = tokens.model_dump(mode="json")
        self._save()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        data = self._state.get("client_info")
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._state["client_info"] = client_info.model_dump(mode="json")
        self._save()

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._state, indent=2))
        # Holds a live bearer token -- restrict to owner-only, same as e.g.
        # ~/.aws/credentials, rather than leaving it at the default umask.
        self.path.chmod(0o600)


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.callback_query = parse_qs(urlparse(self.path).query)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body>Authorized. You can close this tab.</body></html>")

    def log_message(self, format, *args):
        pass  # silence the default request logging


_background_tasks: set[asyncio.Task] = set()


async def _click_confirm_link(url: str) -> None:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        try:
            await client.get(url)
        except httpx.HTTPError:
            # Best-effort -- a real problem here surfaces as the loopback
            # callback never arriving (handle_callback keeps waiting)
            # rather than as an exception anyone here could usefully catch.
            pass


async def _auto_consent(auth_url: str, choice: str) -> None:
    """Drive the demo consent screen ourselves via plain HTTP instead of a
    real browser -- safe because that screen is static HTML with no JS or
    session state (confirmed in TESTING_STRATEGY.md). Walks the same links
    a human would click, then fires the resulting redirect off in the
    background rather than awaiting it.

    That last part matters: the SDK only starts listening on our loopback
    callback server *after* this function (standing in for redirect_handler)
    returns -- exactly mirroring how a real browser works, since
    webbrowser.open() also returns immediately rather than waiting for a
    human to finish clicking through. Awaiting the final redirect-follow
    request here ourselves would deadlock: nothing would be listening on
    the loopback port yet. The pending TCP connection queues safely at the
    OS level until callback_handler starts accepting.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        page = await client.get(auth_url)
        page.raise_for_status()

        if choice == "wrong-resource":
            match = re.search(r'href="(/authorize/wrong-resource\?[^"]*)"', page.text)
            link = match.group(1) if match else None
        else:
            link = None
            for m in re.finditer(r'href="(/authorize/confirm\?[^"]*)"', page.text):
                candidate = m.group(1)
                if parse_qs(urlparse(candidate).query).get("scope", [""])[0] == choice:
                    link = candidate
                    break

        if link is None:
            raise RuntimeError(f"No consent-screen link found for MCP_AUTH_CONSENT={choice!r}")

        base = f"{urlparse(auth_url).scheme}://{urlparse(auth_url).netloc}"

    task = asyncio.create_task(_click_confirm_link(base + link))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _preload_oauth_metadata(oauth_auth: OAuthClientProvider, as_url: str) -> None:
    """Warm the SDK's in-memory AS metadata cache before the first request,
    as a workaround for a gap in the SDK's own step-up handling -- NOT a
    substitute for real discovery.

    The assignment's actual discovery contract still runs untouched: a
    request with no (or an invalid) token gets a 401, the SDK reads the
    resource server's WWW-Authenticate header, fetches Protected Resource
    Metadata, resolves the AS from `authorization_servers[0]`, and fetches
    *that* AS's own oauth-authorization-server metadata -- all per RFC 9728,
    with `_validate_resource_match` checking the PRM's `resource` against
    ours. CIMD then supplies the client_id in that same flow. None of that
    is bypassed, and if a real 401 does occur, the SDK's own discovery
    *overwrites* whatever we set here with what it actually discovered.

    What this function papers over is a narrower problem: the SDK's client
    (mcp/client/auth/oauth2.py) only runs that discovery sequence in the 401
    branch. Its 403 (insufficient_scope) branch has no discovery step of its
    own -- it assumes `self.context.oauth_metadata` is already populated
    from an earlier 401 in the *same* OAuthClientProvider instance, and if
    it isn't, falls back to guessing an authorize endpoint off the resource
    server's own URL, which 404s (see NOTES.md's cross-process step-up entry,
    and AGENT_TESTING.md's Scenario 9, which exercises exactly this path and
    regresses with a 404 if this function is removed).

    That assumption holds for a long-lived client that keeps one
    OAuthClientProvider in memory for a whole session. It doesn't hold for
    us: each `python client/main.py ...` invocation is a fresh process, and
    we deliberately persist tokens to disk (FileTokenStorage) so a scenario
    can stage a token in one invocation and reuse it in the next (needed for
    `probe`, revocation, expiration). A fresh process can attach a
    still-valid-but-under-scoped stored token to its first request and get a
    403 with no 401 ever occurring in that process, hitting the SDK's gap.

    This is scoped as narrowly as possible: it hardcodes the same as_url
    this file already treats as known out-of-band (PROD_AS_URL/LOCAL_AS_URL,
    also used by revoke_token() and --local) rather than inventing new
    trust, and it only ever affects the no-401-in-this-process case -- real
    discovery, when it runs, always wins. A more spec-purist alternative
    would be to persist the AS metadata *discovered* by a real 401 into
    FileTokenStorage (same way the token itself is persisted) and rehydrate
    it here instead of re-deriving it from our own constant -- that would
    make this cache-of-a-discovery rather than an assumption. Not done here
    because it adds a second piece of cross-process state for a gap that,
    per RFC 9728, a compliant client isn't supposed to hit in the first
    place (the spec doesn't anticipate discovery state resetting between a
    401 and a later 403 for the same logical session).
    """
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{as_url}/.well-known/oauth-authorization-server")
        response.raise_for_status()
    oauth_auth.context.oauth_metadata = OAuthMetadata.model_validate(response.json())
    oauth_auth.context.auth_server_url = as_url


async def call_tool(tool_name: str, arguments: dict, server_url: str, as_url: str) -> str:
    attempt_count = 0

    async def handle_redirect(auth_url: str) -> None:
        nonlocal attempt_count
        attempt_count += 1
        scopes = parse_qs(urlparse(auth_url).query).get("scope", [""])[0].split()
        labeled = [f"{SCOPE_LABELS.get(s, s)} ({s})" for s in scopes]
        label = "Step-up re-authorization" if attempt_count > 1 else "Authorization"

        if len(labeled) <= 1:
            # A single requested scope means the SDK already knows exactly
            # what this call needs (a tool-specific 403 step-up, not the
            # scope-agnostic first-ever 401 -- see the note above on why
            # that one asks for everything the AS advertises).
            what = labeled[0] if labeled else "(none)"
            print(f"{label} (attempt {attempt_count}) -- authorize for {what}")
        else:
            print(
                f"{label} (attempt {attempt_count}) -- requesting auth for possible "
                f"scopes: {', '.join(labeled)} (only one may be needed for this call)"
            )

        choice = os.environ.get("MCP_AUTH_CONSENT")
        if attempt_count > 1:
            choice = os.environ.get("MCP_AUTH_CONSENT_RETRY", choice)

        if choice:
            await _auto_consent(auth_url, choice)
        else:
            print("You need to authenticate -- check your browser window (opened automatically).")
            webbrowser.open(auth_url)

    # Loopback server on an OS-assigned ephemeral port. Our CIMD doc only
    # registers a *portless* redirect_uri (http://127.0.0.1/callback) --
    # this only works because the AS ignores the port for loopback addresses,
    # per RFC 8252 section 7.3 (confirmed working).
    callback_server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    callback_server.callback_query = None
    port = callback_server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    async def handle_callback() -> tuple[str, str | None]:
        # Called again on step-up (e.g. after a 403 insufficient_scope), so
        # this must tolerate stray requests (favicon, etc.) rather than
        # crashing on the first thing that isn't the real redirect.
        while True:
            callback_server.callback_query = None
            await asyncio.to_thread(callback_server.handle_request)
            params = callback_server.callback_query or {}
            if "code" in params:
                return params["code"][0], params.get("state", [None])[0]

    oauth_auth = OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            redirect_uris=[redirect_uri],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=FileTokenStorage(),
        redirect_handler=handle_redirect,
        callback_handler=handle_callback,
        client_metadata_url=CIMD_URL,
    )

    await _preload_oauth_metadata(oauth_auth, as_url)

    async with streamablehttp_client(server_url, auth=oauth_auth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result.content[0].text


async def probe_tool(tool_name: str, arguments: dict, server_url: str) -> str:
    """Call a tool with whatever token is currently on disk, using a plain
    static bearer header instead of OAuthClientProvider -- deliberately no
    auto-reauth/step-up healing. That healing is exactly right for
    `call_tool`'s real-demo path, and exactly wrong here: it would silently
    replace a revoked/expired/wrong-audience token with a fresh working one,
    masking the failure this command exists to observe cleanly.
    """
    tokens = await FileTokenStorage().get_tokens()
    if tokens is None:
        raise RuntimeError(f"No stored token in {STATE_FILE} -- run get-time or get-logs first to stage one.")

    headers = {"Authorization": f"Bearer {tokens.access_token}"}
    async with streamablehttp_client(server_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result.content[0].text


async def revoke_token(as_url: str) -> str:
    """Revoke the currently-stored access token via the AS's /revoke
    endpoint (RFC 7009). Deliberately does not clear local state -- probe
    needs the now-dead token to still be readable afterwards, to prove it
    actually stopped working rather than just vanishing from our own cache.
    """
    storage = FileTokenStorage()
    tokens = await storage.get_tokens()
    client_info = await storage.get_client_info()
    if tokens is None:
        raise RuntimeError(f"No stored token in {STATE_FILE} -- run get-time or get-logs first to stage one.")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{as_url}/revoke",
            data={
                "token": tokens.access_token,
                "client_id": client_info.client_id if client_info else "",
            },
        )
        response.raise_for_status()
    return "token revoked"


def _describe_error(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return _describe_error(exc.exceptions[0])
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        try:
            body = response.json()
            detail = body.get("error_description") or body.get("error") or response.text
        except Exception:
            # The streamable-HTTP transport reads this response as a stream
            # internally -- by the time we get here its body may no longer
            # be accessible at all (httpx.ResponseNotRead), not just
            # malformed JSON. Status code alone is still fine to report.
            detail = "(response body unavailable)"
        return f"{response.status_code} {detail}"
    return str(exc)


def _run(coro) -> None:
    try:
        result = asyncio.run(coro)
    except Exception as e:
        print(f"RESULT: ERROR {_describe_error(e)}")
        sys.exit(1)
    else:
        print(f"RESULT: OK {result}")


@click.group()
@click.option(
    "--local",
    is_flag=True,
    help="Hit the local dev server (127.0.0.1) instead of the deployed Render service.",
)
@click.pass_context
def cli(ctx, local):
    """MCP auth demo client -- discovers the AS, authenticates via CIMD, calls a protected tool."""
    ctx.obj = {
        "server_url": LOCAL_SERVER_URL if local else PROD_SERVER_URL,
        "as_url": LOCAL_AS_URL if local else PROD_AS_URL,
    }


@cli.command("get-time")
@click.pass_context
def get_time_cmd(ctx):
    """Tell me the time."""
    _run(call_tool("get_time", {}, ctx.obj["server_url"], ctx.obj["as_url"]))


@cli.command("get-logs")
@click.option("--topic", default=None, help="Only return log entries mentioning this topic.")
@click.pass_context
def get_logs_cmd(ctx, topic):
    """Tell me more about [topic] -- reads the project's detailed work log."""
    arguments = {"topic": topic} if topic else {}
    _run(call_tool("get_logs", arguments, ctx.obj["server_url"], ctx.obj["as_url"]))


@cli.command("probe")
@click.argument("tool", type=click.Choice(["get-time", "get-logs"]))
@click.option("--topic", default=None, help="Only used with get-logs.")
@click.pass_context
def probe_cmd(ctx, tool, topic):
    """Call TOOL with the currently stored token, bypassing auto-reauth --
    the way to verify a revoked/expired/mis-scoped token cleanly."""
    tool_name = tool.replace("-", "_")
    arguments = {"topic": topic} if (tool_name == "get_logs" and topic) else {}
    _run(probe_tool(tool_name, arguments, ctx.obj["server_url"]))


@cli.command("revoke")
@click.pass_context
def revoke_cmd(ctx):
    """Revoke the currently-stored access token via the AS's /revoke endpoint."""
    _run(revoke_token(ctx.obj["as_url"]))


@cli.command("reset")
def reset_cmd():
    """Clear the cached token and client identity, so the next command
    authenticates from scratch instead of silently reusing what's stored."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print(f"RESULT: OK cleared {STATE_FILE}")
    else:
        print(f"RESULT: OK nothing to clear ({STATE_FILE} doesn't exist)")


if __name__ == "__main__":
    cli()
