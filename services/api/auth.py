"""Authentication for FastAPI: Cognito in production, an explicit header stub for local dev.

AUTH_MODE must be set to "cognito" or "local". There is no default, so a forgotten variable
stops the API instead of silently trusting the X-User-Id header.
"""

import os
import time
from functools import lru_cache

from fastapi import Header, HTTPException, status
from pydantic import BaseModel


class AuthUser(BaseModel):
    user_id: str
    email: str
    cognito_sub: str | None = None


def auth_mode() -> str:
    mode = os.environ.get("AUTH_MODE", "").lower()
    if mode not in {"cognito", "local"}:
        raise RuntimeError('AUTH_MODE must be set to "cognito" or "local".')
    return mode


def _cognito_get_user(token: str) -> dict:
    """Ask Cognito to validate the access token. It checks signature, expiry and revocation for us.

    The call is public (no AWS credentials), so the client is created unsigned.
    """
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    client = boto3.client(
        "cognito-idp",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=Config(signature_version=UNSIGNED),
    )
    return client.get_user(AccessToken=token)


@lru_cache(maxsize=512)
def _verified_user(token: str, minute: int) -> AuthUser:
    # `minute` only exists so a cached verdict expires after about a minute (revoked tokens stop working).
    resp = _cognito_get_user(token)
    attrs = {a["Name"]: a["Value"] for a in resp.get("UserAttributes", [])}
    sub = attrs.get("sub", resp["Username"])
    return AuthUser(user_id=sub, email=attrs.get("email", ""), cognito_sub=sub)


def get_current_user(
    authorization: str | None = Header(None),
    x_user_id: str | None = Header(None),
) -> AuthUser:
    if auth_mode() == "cognito":
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid Bearer authorization header.")
        token = authorization.split(" ", 1)[1]
        try:
            return _verified_user(token, int(time.time() // 60))
        except Exception as exc:  # any Cognito error (expired, revoked, malformed) means not logged in
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.") from exc

    user_id = x_user_id or "default_test_user"
    return AuthUser(user_id=user_id, email=f"{user_id}@example.com", cognito_sub=f"sub_{user_id}")
