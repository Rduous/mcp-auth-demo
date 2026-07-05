import json
import os
from urllib.parse import parse_qsl, urlencode

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

AUTHLETE_API_BASE = "https://us.authlete.com/api"
AUTHLETE_SERVICE_ID = os.environ["AUTHLETE_SERVICE_ID"]
AUTHLETE_SAT = os.environ["AUTHLETE_SAT"]

ISSUER = os.environ.get("ISSUER", "http://127.0.0.1:8001")

# TODO: identity is still a no-op -- every request is approved as this one
# hardcoded subject, no real login. Real identity (Google SSO + allow-list)
# is a labeled future refinement, see Phase 8.
#
# Scope *consent*, though, is now a real interactive choice (see `authorize`
# below) rather than auto-approved -- a tester picks what to grant, which
# doubles as an easy way to trigger the different Phase 5/6 test cases.
DEMO_SUBJECT = "demo-user"

# label -> the scope(s) to grant if this option is picked
SCOPE_CHOICES = {
    "Sign in with mcp:tools scope": "mcp:tools",
    "Sign in with logs:read scope": "logs:read",
    # NOTE: Authlete's /auth/authorization/issue ignores an *empty* scopes
    # array override (falls back to the originally-requested scope --
    # contradicts its own docs, confirmed via a clean isolated curl test).
    # A genuine narrower non-empty override works fine, though, so we use
    # one of Authlete's built-in default scopes -- satisfies neither of our
    # gated tools' requirements, so it still triggers a real 403.
    "Sign in with unrelated scope (email) -- expect failure": "email",
    # Combined with mcp:tools rather than requested alone, so the resulting
    # token is actually usable against get_time -- Authlete's per-scope
    # token-duration override takes the *shortest* duration among all
    # granted scopes, so mcp:tools stays full-length while this scope's
    # short override (see NOTES.md) collapses the whole token's lifetime.
    "Sign in with mcp:tools + short-lived scope -- test expiration": "mcp:tools short-lived",
}

# A resource this MCP server does not recognize -- for the "wrong audience"
# test case, done as a genuinely fresh authorization request rather than an
# issue-time override (Authlete's issue API has no 'resources' override,
# unlike 'scopes').
WRONG_RESOURCE = "https://wrong-server.example/resource"


async def authlete_post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AUTHLETE_API_BASE}/{AUTHLETE_SERVICE_ID}/{path}",
            headers={"Authorization": f"Bearer {AUTHLETE_SAT}"},
            json=body,
        )
    return response.json()


async def healthz(request):
    return PlainTextResponse("OK")


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
            # Authlete's /auth/authorization/issue can only *narrow* the
            # scope carried by the original /authorize request, never add to
            # it (confirmed via their KB: "cannot include additional scopes
            # that you did not request at the /auth/authorization API").
            # Our client has no per-tool scope hint yet at the point it
            # builds that first request, so it falls back to requesting
            # everything advertised here -- short-lived has to be listed for
            # the consent screen's combined-scope choice to be grantable at
            # all, not just registered as a service-level scope.
            "scopes_supported": ["mcp:tools", "logs:read", "short-lived"],
        }
    )


async def authorize(request):
    original_query = str(request.url.query)
    auth_result = await authlete_post(
        "auth/authorization", {"parameters": original_query}
    )

    if auth_result.get("action") != "INTERACTION":
        # Something's wrong with the request itself (bad client_id, missing
        # PKCE, etc). Authlete has already built the right error response.
        return JSONResponse(auth_result, status_code=400)

    ticket = auth_result["ticket"]
    print(f"[authserver] DEBUG /authorize requested scope in query: {request.query_params.get('scope')!r}")
    print(f"[authserver] DEBUG ticket issued: {ticket!r}")
    links = "".join(
        f'<p><a href="/authorize/confirm?{urlencode({"ticket": ticket, "scope": scope})}">{label}</a></p>'
        for label, scope in SCOPE_CHOICES.items()
    )
    links += (
        f'<p><a href="/authorize/wrong-resource?{urlencode({"original_query": original_query})}">'
        f"Sign in for a different resource -- expect failure</a></p>"
    )
    return HTMLResponse(f"<html><body><h3>Choose what to grant (demo consent screen)</h3>{links}</body></html>")


async def wrong_resource(request):
    original_query = request.query_params["original_query"]
    params = dict(parse_qsl(original_query))
    params["resource"] = WRONG_RESOURCE
    print(f"[authserver] DEBUG /authorize/wrong-resource overriding resource to: {WRONG_RESOURCE!r}")

    auth_result = await authlete_post("auth/authorization", {"parameters": urlencode(params)})
    if auth_result.get("action") != "INTERACTION":
        return JSONResponse(auth_result, status_code=400)

    issue_result = await authlete_post(
        "auth/authorization/issue",
        {"ticket": auth_result["ticket"], "subject": DEMO_SUBJECT},
    )
    print(f"[authserver] DEBUG issue_result: {issue_result!r}")
    return RedirectResponse(issue_result["responseContent"], status_code=302)


async def confirm(request):
    ticket = request.query_params["ticket"]
    scope = request.query_params.get("scope", "")
    # Split on whitespace (RFC 6749 §3.3 scope format) rather than treating
    # the whole param as one scope -- needed now that a choice can request
    # more than one scope at once (see the short-lived combo above).
    scopes = scope.split() if scope else []
    print(f"[authserver] DEBUG /authorize/confirm ticket={ticket!r} raw scope param={scope!r} scopes sent to issue={scopes!r}")

    issue_result = await authlete_post(
        "auth/authorization/issue",
        {"ticket": ticket, "subject": DEMO_SUBJECT, "scopes": scopes},
    )
    print(f"[authserver] DEBUG issue_result: {issue_result!r}")
    return RedirectResponse(issue_result["responseContent"], status_code=302)


async def token(request):
    form = dict(await request.form())
    client_id = form.pop("client_id", None)
    print(f"[authserver] DEBUG /token form={form!r} client_id={client_id!r}")

    token_result = await authlete_post(
        "auth/token",
        {"clientId": client_id, "parameters": urlencode(form)},
    )
    print(f"[authserver] DEBUG /token token_result={token_result!r}")
    status = 200 if token_result.get("action") == "OK" else 400
    try:
        content = json.loads(token_result["responseContent"])
    except (KeyError, json.JSONDecodeError):
        content = {"error": "server_error", "error_description": token_result.get("resultMessage")}
    print(f"[authserver] DEBUG /token responseContent parsed={content!r}")
    return JSONResponse(content, status_code=status)


app = Starlette(
    routes=[
        Route("/healthz", healthz),
        Route("/.well-known/oauth-authorization-server", well_known),
        Route("/authorize", authorize),
        Route("/authorize/confirm", confirm),
        Route("/authorize/wrong-resource", wrong_resource),
        Route("/token", token, methods=["POST"]),
    ]
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
