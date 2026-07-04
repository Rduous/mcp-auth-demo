from datetime import datetime, timezone

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from auth import RESOURCE_URI, AuthleteTokenVerifier

mcp = FastMCP(
    "mcp-auth-demo",
    stateless_http=True,
    json_response=True,
    token_verifier=AuthleteTokenVerifier(),
    auth=AuthSettings(
        issuer_url="https://authlete.com",
        resource_server_url=RESOURCE_URI,
    ),
)


@mcp.tool()
def get_time() -> str:
    """Return the current UTC time."""
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
