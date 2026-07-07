"""ALB OIDC JWT verification.

The ALB authenticates the user via Okta and forwards a signed JWT in the
`x-amzn-oidc-data` header on every request. We verify the signature against
the ALB's per-region public-key endpoint, then expose the user's claims.

When the header is absent (local docker-compose, tests, or anything bypassing
the ALB), we fall back to a configurable dev user. Production safety relies on
the EC2 security group allowing port 8501 only from the ALB's security group —
direct external access is impossible.
"""
import os
import urllib.request
from typing import Optional

import jwt
from fastapi import HTTPException, Request

ALB_REGION = os.getenv("AWS_REGION", "us-east-1")
DEV_USER_EMAIL = os.getenv("DEV_USER_EMAIL", "dev@local")
DEV_USER_NAME = os.getenv("DEV_USER_NAME", "Dev User")

_pubkey_cache: dict = {}


def _fetch_alb_pubkey(kid: str) -> str:
    if kid in _pubkey_cache:
        return _pubkey_cache[kid]
    url = f"https://public-keys.auth.elb.{ALB_REGION}.amazonaws.com/{kid}"
    with urllib.request.urlopen(url, timeout=5) as resp:
        pem = resp.read().decode()
    _pubkey_cache[kid] = pem
    return pem


def _verify_alb_jwt(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Malformed ALB token: {e}")

    kid = header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="ALB token missing kid")

    pem = _fetch_alb_pubkey(kid)
    try:
        return jwt.decode(token, pem, algorithms=["ES256"], options={"verify_aud": False})
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid ALB token: {e}")


def current_user(request: Request) -> dict:
    """FastAPI dependency. Returns {email, name, sub} for the request."""
    token = request.headers.get("x-amzn-oidc-data")
    if not token:
        return {"email": DEV_USER_EMAIL, "name": DEV_USER_NAME, "sub": DEV_USER_EMAIL}
    claims = _verify_alb_jwt(token)
    return {
        "email": claims.get("email") or claims.get("preferred_username") or claims.get("sub", "unknown"),
        "name": claims.get("name", ""),
        "sub": claims.get("sub", ""),
    }
