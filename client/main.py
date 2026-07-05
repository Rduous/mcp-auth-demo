import asyncio
import json
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
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

SERVER_URL = "http://127.0.0.1:8000/mcp"
CIMD_URL = "https://rduous.github.io/mcp-auth-demo/cimd/client-metadata.json"

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


async def call_tool(tool_name: str, arguments: dict) -> str:
    attempt_count = 0

    async def handle_redirect(auth_url: str) -> None:
        nonlocal attempt_count
        attempt_count += 1
        scope = parse_qs(urlparse(auth_url).query).get("scope", ["(none)"])[0]
        label = "Step-up re-authorization" if attempt_count > 1 else "Authorization"
        print(f"{label} (attempt {attempt_count}) -- requesting scope: {scope}")
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
        server_url=SERVER_URL,
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

    async with streamablehttp_client(SERVER_URL, auth=oauth_auth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result.content[0].text


async def probe_tool(tool_name: str, arguments: dict) -> str:
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
    async with streamablehttp_client(SERVER_URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result.content[0].text


def _describe_error(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return _describe_error(exc.exceptions[0])
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        try:
            body = response.json()
            detail = body.get("error_description") or body.get("error") or response.text
        except ValueError:
            detail = response.text
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
def cli():
    """MCP auth demo client -- discovers the AS, authenticates via CIMD, calls a protected tool."""


@cli.command("get-time")
def get_time_cmd():
    """Tell me the time."""
    _run(call_tool("get_time", {}))


@cli.command("get-logs")
@click.option("--topic", default=None, help="Only return log entries mentioning this topic.")
def get_logs_cmd(topic):
    """Tell me more about [topic] -- reads the project's detailed work log."""
    arguments = {"topic": topic} if topic else {}
    _run(call_tool("get_logs", arguments))


@cli.command("probe")
@click.argument("tool", type=click.Choice(["get-time", "get-logs"]))
@click.option("--topic", default=None, help="Only used with get-logs.")
def probe_cmd(tool, topic):
    """Call TOOL with the currently stored token, bypassing auto-reauth --
    the way to verify a revoked/expired/mis-scoped token cleanly."""
    tool_name = tool.replace("-", "_")
    arguments = {"topic": topic} if (tool_name == "get_logs" and topic) else {}
    _run(probe_tool(tool_name, arguments))


if __name__ == "__main__":
    cli()
