import os

import httpx
from mcp.server.auth.provider import AccessToken, TokenVerifier

AUTHLETE_API_BASE = "https://us.authlete.com/api"
AUTHLETE_SERVICE_ID = os.environ["AUTHLETE_SERVICE_ID"]
AUTHLETE_SAT = os.environ["AUTHLETE_SAT"]

RESOURCE_URI = "http://127.0.0.1:8000/mcp"


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
