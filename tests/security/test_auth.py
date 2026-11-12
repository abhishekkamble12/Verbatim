import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.api import auth
from services.api.main import app


def _bearer(token):
    return auth.get_current_user(authorization=f"Bearer {token}", x_user_id="attacker")


def test_cognito_mode_rejects_unverified_token(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cognito")

    def reject(token):
        raise ValueError("NotAuthorizedException")

    monkeypatch.setattr(auth, "_cognito_get_user", reject)
    with pytest.raises(HTTPException) as exc:
        _bearer("ANYTHING-I-TYPE")
    assert exc.value.status_code == 401


def test_cognito_mode_uses_verified_sub_and_ignores_header(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cognito")
    monkeypatch.setattr(
        auth,
        "_cognito_get_user",
        lambda t: {"Username": "u1", "UserAttributes": [{"Name": "sub", "Value": "sub-123"}, {"Name": "email", "Value": "a@b.c"}]},
    )
    user = _bearer("good-token")
    assert user.user_id == "sub-123"  # not "attacker" from X-User-Id


def test_cognito_mode_requires_bearer_header(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cognito")
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(authorization=None, x_user_id="attacker")
    assert exc.value.status_code == 401


def test_api_refuses_to_start_without_auth_mode(monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setattr("services.api.main.load_env_file", lambda: None)  # a developer's .env must not mask this
    with pytest.raises(RuntimeError), TestClient(app):
        pass
