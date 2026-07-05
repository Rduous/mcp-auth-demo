import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from auth import RESOURCE_URI, AuthleteTokenVerifier
from scope_gate import ScopeEnforcementMiddleware

# FastMCP's default DNS-rebinding protection only allows loopback Host
# headers (127.0.0.1/localhost/::1) -- correct for a server that's normally
# run locally, but it silently 421s every request once actually deployed
# under a real hostname. Derive the extra allowed host from RESOURCE_URI
# (already the canonical source of truth for this service's
# externally-visible identity) rather than hardcoding the Render hostname
# a second time.
_resource = urlparse(RESOURCE_URI)
_transport_security = TransportSecuritySettings(
    allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", _resource.netloc],
    allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*", f"{_resource.scheme}://{_resource.netloc}"],
)

mcp = FastMCP(
    "mcp-auth-demo",
    stateless_http=True,
    json_response=True,
    token_verifier=AuthleteTokenVerifier(),
    auth=AuthSettings(
        issuer_url=os.environ.get("ISSUER", "http://127.0.0.1:8001"),
        resource_server_url=RESOURCE_URI,
    ),
    transport_security=_transport_security,
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
