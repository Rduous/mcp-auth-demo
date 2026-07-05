import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth import AuthleteTokenVerifier

# Which scope each protected tool requires. A tool not listed here needs no
# scope beyond a plain valid, audience-bound token.
TOOL_SCOPES = {
    "get_time": "mcp:tools",
    "get_logs": "logs:read",
}

_verifier = AuthleteTokenVerifier()


class ScopeEnforcementMiddleware(BaseHTTPMiddleware):
    """Per-tool scope check, independent of FastMCP's own auth pipeline.

    Does its own token verification rather than relying on request.scope
    being populated by other middleware -- avoids depending on exact
    middleware ordering.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/mcp" and request.method == "POST":
            body = await request.body()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None

            if isinstance(payload, dict) and payload.get("method") == "tools/call":
                tool_name = (payload.get("params") or {}).get("name")
                required_scope = TOOL_SCOPES.get(tool_name)

                if required_scope:
                    auth_header = request.headers.get("authorization", "")
                    if auth_header.lower().startswith("bearer "):
                        token = auth_header[7:]
                        access_token = await _verifier.verify_token(token)
                        if access_token and required_scope not in access_token.scopes:
                            # `scope=` here is what lets an MCP-spec-aware client
                            # (e.g. the SDK's OAuthClientProvider) automatically
                            # step up and re-request just this scope -- RFC 6750 §3.1.
                            return JSONResponse(
                                {
                                    "error": "insufficient_scope",
                                    "error_description": f"Required scope: {required_scope}",
                                },
                                status_code=403,
                                headers={
                                    "WWW-Authenticate": (
                                        f'Bearer error="insufficient_scope", '
                                        f'scope="{required_scope}", '
                                        f'error_description="Required scope: {required_scope}"'
                                    )
                                },
                            )
                    # No/invalid token: let it through -- FastMCP's own auth
                    # middleware already returns the correct 401 for that case.

        return await call_next(request)
