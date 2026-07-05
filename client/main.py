import asyncio
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import click
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

SERVER_URL = "http://127.0.0.1:8000/mcp"
CIMD_URL = "https://rduous.github.io/mcp-auth-demo/cimd/client-metadata.json"

# NOTE: it's tempting to set client_metadata.scope per-tool to request only
# what's needed and avoid a step-up round trip -- doesn't work. The first
# 401 happens at session.initialize(), before the client has chosen a tool
# to call, so the SDK's scope-selection fallback (no tool-specific hint
# available yet) requests the AS's full advertised scopes_supported instead
# of anything we set locally. Not worth fighting; see NOTES.md.


class InMemoryTokenStorage(TokenStorage):
    def __init__(self):
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


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
        storage=InMemoryTokenStorage(),
        redirect_handler=handle_redirect,
        callback_handler=handle_callback,
        client_metadata_url=CIMD_URL,
    )

    async with streamablehttp_client(SERVER_URL, auth=oauth_auth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result.content[0].text


@click.group()
def cli():
    """MCP auth demo client -- discovers the AS, authenticates via CIMD, calls a protected tool."""


@cli.command("get-time")
def get_time_cmd():
    """Tell me the time."""
    print(asyncio.run(call_tool("get_time", {})))


@cli.command("get-logs")
@click.option("--topic", default=None, help="Only return log entries mentioning this topic.")
def get_logs_cmd(topic):
    """Tell me more about [topic] -- reads the project's detailed work log."""
    arguments = {"topic": topic} if topic else {}
    print(asyncio.run(call_tool("get_logs", arguments)))


if __name__ == "__main__":
    cli()
