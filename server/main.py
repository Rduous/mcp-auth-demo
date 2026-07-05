from datetime import datetime, timezone

import uvicorn
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from auth import RESOURCE_URI, AuthleteTokenVerifier
from scope_gate import ScopeEnforcementMiddleware

mcp = FastMCP(
    "mcp-auth-demo",
    stateless_http=True,
    json_response=True,
    token_verifier=AuthleteTokenVerifier(),
    auth=AuthSettings(
        issuer_url="http://127.0.0.1:8001",
        resource_server_url=RESOURCE_URI,
    ),
)


@mcp.tool()
def get_time() -> str:
    """Return the current UTC time."""
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    app = mcp.streamable_http_app()
    app.add_middleware(ScopeEnforcementMiddleware)
    uvicorn.run(app, host="127.0.0.1", port=8000)
