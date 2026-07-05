import re
from datetime import datetime, timezone
from pathlib import Path

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


NOTES_PATH = Path(__file__).parent.parent / "docs" / "NOTES.md"


@mcp.tool()
def get_logs(topic: str | None = None) -> str:
    """Return the project's detailed work log. Gated behind logs:read.

    If `topic` is given, only returns log entries whose heading or body
    mention it (case-insensitive substring match), instead of the whole file.
    """
    text = NOTES_PATH.read_text()
    if not topic:
        return text

    sections = re.split(r"\n(?=## )", text)
    matches = [s for s in sections if topic.lower() in s.lower()]
    if not matches:
        return f"No log entries found matching topic: {topic!r}"
    return "\n\n".join(matches)


if __name__ == "__main__":
    app = mcp.streamable_http_app()
    app.add_middleware(ScopeEnforcementMiddleware)
    uvicorn.run(app, host="127.0.0.1", port=8000)
