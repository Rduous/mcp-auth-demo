# TODO: this is a throwaway script for Phase 1's plumbing check. Once we
# settle the CLI shape (one-shot vs. login+call), rewrite this as a proper
# CLI tool (click) that handles auth, not just a hardcoded tool call.
import asyncio
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

SERVER_URL = "http://127.0.0.1:8000/mcp"
CIMD_URL = "https://rduous.github.io/mcp-auth-demo/cimd/client-metadata.json"


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


async def handle_redirect(auth_url: str) -> None:
    print(f"Opening browser for authorization:\n{auth_url}")
    webbrowser.open(auth_url)


async def main():
    # Loopback server on an OS-assigned ephemeral port. Our CIMD doc only
    # registers a *portless* redirect_uri (http://127.0.0.1/callback) --
    # this only works if the AS ignores the port for loopback addresses,
    # per RFC 8252 section 7.3. Untested until now.
    callback_server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    callback_server.callback_query = None
    port = callback_server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    async def handle_callback() -> tuple[str, str | None]:
        await asyncio.to_thread(callback_server.handle_request)
        params = callback_server.callback_query
        return params["code"][0], params.get("state", [None])[0]

    oauth_auth = OAuthClientProvider(
        server_url=SERVER_URL,
        client_metadata=OAuthClientMetadata(
            redirect_uris=[redirect_uri],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="mcp:tools",
        ),
        storage=InMemoryTokenStorage(),
        redirect_handler=handle_redirect,
        callback_handler=handle_callback,
        client_metadata_url=CIMD_URL,
    )

    async with streamablehttp_client(SERVER_URL, auth=oauth_auth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_time", {})
            print(result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
