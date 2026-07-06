#!/usr/bin/env python3
"""Mint an Authlete access token via a full authorization_code + PKCE flow,
in one command instead of three manual curl round-trips.

Requires AUTHLETE_SERVICE_ID and AUTHLETE_SAT in the environment (the same
credentials server/auth.py and authserver/main.py use).

Examples:
    python3 tools/mint_token.py --scope "mcp:tools"
    python3 tools/mint_token.py --scope "logs:read" --subject demo-user
    python3 tools/mint_token.py --scope "" --resource https://wrong-server.example/resource
    python3 tools/mint_token.py --scope "short-lived"  # Authlete-side: expires in ~10s, for testing expiration
"""
import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTHLETE_API_BASE = "https://us.authlete.com/api"
DEFAULT_CLIENT_ID = "https://rduous.github.io/mcp-auth-demo/cimd/client-metadata.json"
DEFAULT_REDIRECT_URI = "http://127.0.0.1/callback"
DEFAULT_RESOURCE = "http://127.0.0.1:8000/mcp"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def authlete_post(service_id: str, sat: str, path: str, body: dict) -> dict:
    response = httpx.post(
        f"{AUTHLETE_API_BASE}/{service_id}/{path}",
        headers={"Authorization": f"Bearer {sat}"},
        json=body,
        timeout=30,
    )
    return response.json()


def decode_jwt(token: str) -> dict | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    return json.loads(b64url_decode(parts[1]))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--scope", default="mcp:tools",
        help="Space-separated scopes to request and grant (empty string for none). "
             "Includes 'short-lived', Authlete-side configured to expire in ~10s, for testing expiration.",
    )
    parser.add_argument("--resource", default=DEFAULT_RESOURCE, help="Resource (audience) to bind the token to")
    parser.add_argument("--subject", default="test-user-01", help="Subject to issue the token as")
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID, help="CIMD client_id URL")
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI, help="Redirect URI (must match the CIMD doc)")
    args = parser.parse_args()

    service_id = os.environ.get("AUTHLETE_SERVICE_ID")
    sat = os.environ.get("AUTHLETE_SAT")
    if not service_id or not sat:
        print("Set AUTHLETE_SERVICE_ID and AUTHLETE_SAT in your environment first.", file=sys.stderr)
        sys.exit(1)

    verifier = b64url(secrets.token_bytes(32))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())

    auth_params = {
        "response_type": "code",
        "client_id": args.client_id,
        "redirect_uri": args.redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": args.resource,
        "scope": args.scope,
    }

    print(f"--- 1/3: authorization request (scope={args.scope!r}, resource={args.resource!r}) ---")
    auth_result = authlete_post(service_id, sat, "auth/authorization", {"parameters": urlencode(auth_params)})
    print(f"action={auth_result.get('action')} resultCode={auth_result.get('resultCode')} "
          f"resultMessage={auth_result.get('resultMessage')}")
    if auth_result.get("action") != "INTERACTION":
        print(json.dumps(auth_result, indent=2))
        sys.exit(1)
    ticket = auth_result["ticket"]

    scopes = args.scope.split() if args.scope else []
    print(f"\n--- 2/3: issue (subject={args.subject!r}, scopes={scopes!r}) ---")
    issue_result = authlete_post(
        service_id, sat, "auth/authorization/issue",
        {"ticket": ticket, "subject": args.subject, "scopes": scopes},
    )
    print(f"action={issue_result.get('action')} resultCode={issue_result.get('resultCode')} "
          f"resultMessage={issue_result.get('resultMessage')}")
    if issue_result.get("action") != "LOCATION":
        print(json.dumps(issue_result, indent=2))
        sys.exit(1)

    redirect_url = issue_result["responseContent"]
    code = parse_qs(urlparse(redirect_url).query)["code"][0]

    print("\n--- 3/3: token exchange ---")
    token_params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": args.redirect_uri,
        "code_verifier": verifier,
    }
    token_result = authlete_post(
        service_id, sat, "auth/token",
        {"clientId": args.client_id, "parameters": urlencode(token_params)},
    )
    print(f"action={token_result.get('action')} resultCode={token_result.get('resultCode')} "
          f"resultMessage={token_result.get('resultMessage')}")
    if token_result.get("action") != "OK":
        print(json.dumps(token_result, indent=2))
        sys.exit(1)

    body = json.loads(token_result["responseContent"])
    access_token = body["access_token"]

    print("\n=== Access token ===")
    print(access_token)

    claims = decode_jwt(access_token)
    if claims:
        print("\n=== Decoded claims ===")
        print(json.dumps(claims, indent=2))

    print("\n=== Ready to use ===")
    print(f'export TOKEN="{access_token}"')


if __name__ == "__main__":
    main()
