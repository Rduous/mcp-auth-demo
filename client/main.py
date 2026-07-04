# TODO: this is a throwaway script for Phase 1's plumbing check. Once we
# settle the CLI shape (one-shot vs. login+call), rewrite this as a proper
# CLI tool (click) that handles auth, not just a hardcoded tool call.
import asyncio
import webbrowser
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


async def handle_redirect(auth_url: str) -> None:
    print(f"Opening browser for authorization:\n{auth_url}")
    webbrowser.open(auth_url)


async def handle_callback() -> tuple[str, str | None]:
    # No local server catching the redirect yet -- the browser will fail to
    # load http://127.0.0.1/callback?..., but the URL itself has what we need.
    # Real loopback-port handling is deferred to the hand-rolled version below.
    callback_url = input("Paste the full callback URL here: ")
    params = parse_qs(urlparse(callback_url).query)
    return params["code"][0], params.get("state", [None])[0]


# --- Option 2: let the SDK's OAuthClientProvider handle discovery + CIMD + PKCE ---
oauth_auth = OAuthClientProvider(
    server_url=SERVER_URL,
    client_metadata=OAuthClientMetadata(
        redirect_uris=["http://127.0.0.1/callback"],
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


async def main():
    async with streamablehttp_client(SERVER_URL, auth=oauth_auth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_time", {})
            print(result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
