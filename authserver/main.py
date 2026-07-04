import json
import os
from urllib.parse import urlencode

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

AUTHLETE_API_BASE = "https://us.authlete.com/api"
AUTHLETE_SERVICE_ID = os.environ["AUTHLETE_SERVICE_ID"]
AUTHLETE_SAT = os.environ["AUTHLETE_SAT"]

ISSUER = "http://127.0.0.1:8001"

# TODO: no-op sign-in. Every authorization request is auto-approved as this
# single hardcoded subject -- no real login/consent screen. Real identity
# (Google SSO + allow-list) is a labeled future refinement, see Phase 8.
DEMO_SUBJECT = "demo-user"


async def authlete_post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AUTHLETE_API_BASE}/{AUTHLETE_SERVICE_ID}/{path}",
            headers={"Authorization": f"Bearer {AUTHLETE_SAT}"},
            json=body,
        )
    return response.json()


async def well_known(request):
    return JSONResponse(
        {
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/authorize",
            "token_endpoint": f"{ISSUER}/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "client_id_metadata_document_supported": True,
            "scopes_supported": ["mcp:tools", "logs:read"],
        }
    )


async def authorize(request):
    auth_result = await authlete_post(
        "auth/authorization", {"parameters": str(request.url.query)}
    )

    if auth_result.get("action") != "INTERACTION":
        # Something's wrong with the request itself (bad client_id, missing
        # PKCE, etc). Authlete has already built the right error response.
        return JSONResponse(auth_result, status_code=400)

    issue_result = await authlete_post(
        "auth/authorization/issue",
        {"ticket": auth_result["ticket"], "subject": DEMO_SUBJECT},
    )
    return RedirectResponse(issue_result["responseContent"], status_code=302)


async def token(request):
    form = dict(await request.form())
    client_id = form.pop("client_id", None)

    token_result = await authlete_post(
        "auth/token",
        {"clientId": client_id, "parameters": urlencode(form)},
    )
    status = 200 if token_result.get("action") == "OK" else 400
    try:
        content = json.loads(token_result["responseContent"])
    except (KeyError, json.JSONDecodeError):
        content = {"error": "server_error", "error_description": token_result.get("resultMessage")}
    return JSONResponse(content, status_code=status)


app = Starlette(
    routes=[
        Route("/.well-known/oauth-authorization-server", well_known),
        Route("/authorize", authorize),
        Route("/token", token, methods=["POST"]),
    ]
)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
