import os
import re
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from auth import RESOURCE_URI, AuthleteTokenVerifier
from scope_gate import ScopeEnforcementMiddleware

mcp = FastMCP(
    "mcp-auth-demo",
    stateless_http=True,
    json_response=True,
    token_verifier=AuthleteTokenVerifier(),
    auth=AuthSettings(
        issuer_url=os.environ.get("ISSUER", "http://127.0.0.1:8001"),
        resource_server_url=RESOURCE_URI,
    ),
)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


@mcp.tool()
def get_time() -> str:
    """Return the current UTC time."""
    return datetime.now(timezone.utc).isoformat()


NOTES_PATH = Path(__file__).parent.parent / "docs" / "NOTES.md"


@mcp.tool()
def get_logs(topic: str | None = None) -> str:
    """Return the project's detailed work log. Gated behind logs:read.

    If `topic` is given, only returns log entries whose *heading* mentions
    it (case-insensitive substring match), instead of the whole file.
    Matching against headings only, not full section bodies, keeps this
    selective -- a broad term like "scope" appears in nearly every entry's
    body text, which would defeat the point of a focused excerpt.
    """
    text = NOTES_PATH.read_text()
    if not topic:
        return text

    sections = re.split(r"\n(?=## )", text)
    matches = [s for s in sections if topic.lower() in s.split("\n", 1)[0].lower()]
    if not matches:
        return f"No log entries found matching topic: {topic!r}"
    return "\n\n".join(matches)


app = mcp.streamable_http_app()
app.add_middleware(ScopeEnforcementMiddleware)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
