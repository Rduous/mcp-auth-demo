import os
from enum import Enum, auto

import httpx
from mcp.server.auth.provider import AccessToken, TokenVerifier

AUTHLETE_API_BASE = "https://us.authlete.com/api"
AUTHLETE_SERVICE_ID = os.environ["AUTHLETE_SERVICE_ID"]
AUTHLETE_SAT = os.environ["AUTHLETE_SAT"]

RESOURCE_URI = "http://127.0.0.1:8000/mcp"


class ScopeCheckResult(Enum):
    SUFFICIENT = auto()
    INSUFFICIENT = auto()
    INVALID = auto()


class AuthleteTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AUTHLETE_API_BASE}/{AUTHLETE_SERVICE_ID}/auth/introspection",
                headers={"Authorization": f"Bearer {AUTHLETE_SAT}"},
                json={"token": token},
            )
        data = response.json()

        if data.get("action") != "OK":
            return None

        # Authlete's introspection doesn't reject a mismatched resource itself
        # (confirmed in Phase 0) -- we have to check it ourselves.
        resources = data.get("accessTokenResources") or []
        if RESOURCE_URI not in resources:
            return None

        return AccessToken(
            token=token,
            client_id=str(data.get("clientId")),
            scopes=data.get("scopes") or [],
            expires_at=data.get("expiresAt"),
            resource=RESOURCE_URI,
            subject=data.get("subject"),
        )

    async def check_scope(self, token: str, required_scope: str) -> ScopeCheckResult:
        """Ask Authlete to check this token against our resource *and* the
        given scope in the same introspection call, so its native combined
        check (see NOTES.md's "Correction" entry -- passing `scopes` and
        `resources` together makes Authlete hard-reject with
        `action: FORBIDDEN`) runs as a second, independent enforcement layer
        on top of the app-side checks in `verify_token`/`scope_gate.py`.

        Separate from `verify_token` rather than an extra parameter on it:
        FastMCP calls `verify_token(token)` itself for the base auth check,
        with no notion of a per-tool scope, so introspection there must stay
        scope-agnostic to keep the two callers' introspection requests --
        and hence their real, still-live revocation checks -- independent.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AUTHLETE_API_BASE}/{AUTHLETE_SERVICE_ID}/auth/introspection",
                headers={"Authorization": f"Bearer {AUTHLETE_SAT}"},
                json={"token": token, "scopes": [required_scope], "resources": [RESOURCE_URI]},
            )
        data = response.json()

        action = data.get("action")
        if action == "FORBIDDEN":
            return ScopeCheckResult.INSUFFICIENT
        if action != "OK":
            return ScopeCheckResult.INVALID

        # Same defense-in-depth as verify_token: don't trust Authlete's own
        # resource check as the only line of defense.
        resources = data.get("accessTokenResources") or []
        if RESOURCE_URI not in resources:
            return ScopeCheckResult.INVALID

        scopes = data.get("scopes") or []
        if required_scope not in scopes:
            return ScopeCheckResult.INSUFFICIENT

        return ScopeCheckResult.SUFFICIENT
