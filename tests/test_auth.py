"""Tokens: redaction, storage, exchange and revoke."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import httpx
import pytest
import respx

from tiktok_ads_mcp.auth import (
    AuthError,
    TokenAuth,
    exchange_auth_code,
    redact,
    register_secret,
    revoke_token,
    save_token_file,
)
from tiktok_ads_mcp.config import Config

from .conftest import APP_ID, APP_SECRET, BASE, body_of, ok


def test_redact_keys_query_strings_and_registered_values() -> None:
    register_secret("registered-secret-123")
    out = redact(
        {
            "Access-Token": "abc",
            "secret": "s",
            "auth_code": "c",
            "code": 40105,
            "msg": "x registered-secret-123 y",
            "url": "https://h/p?app_id=1&secret=topsecret&auth_code=zz",
            "nested": [{"access_token": "t"}],
        }
    )
    assert out["Access-Token"] == "***"
    assert out["secret"] == "***"
    assert out["auth_code"] == "***"
    assert out["code"] == 40105  # TikTok's response code is not a secret
    assert "registered-secret-123" not in out["msg"]
    assert "topsecret" not in out["url"] and "zz" not in out["url"]
    assert out["nested"][0]["access_token"] == "***"


def test_short_values_are_not_registered() -> None:
    register_secret("abc")
    assert redact("abc") == "abc"


def test_token_auth() -> None:
    auth = TokenAuth("a-long-term-token", app_id="7200000000001234")
    assert auth.access_token() == "a-long-term-token"
    auth.invalidate()  # nothing to refresh, must not fail
    assert "1234" in auth.account_label
    assert "a-long-term-token" not in auth.account_label
    assert redact("x a-long-term-token") == "x ***"
    with pytest.raises(AuthError):
        TokenAuth("")


def test_load_auth_requires_token(config: Config) -> None:
    from tiktok_ads_mcp.auth import load_auth

    config.access_token = None
    with pytest.raises(RuntimeError, match="auth"):
        load_auth(config)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_save_token_file_is_owner_only_and_merges(tmp_path: Path) -> None:
    path = tmp_path / "secrets" / "token.json"
    save_token_file(path, {"access_token": "a"})
    save_token_file(path, {"advertiser_ids": ["1"]})
    assert json.loads(path.read_text()) == {"access_token": "a", "advertiser_ids": ["1"]}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@respx.mock
def test_exchange_auth_code() -> None:
    route = respx.post(f"{BASE}/oauth2/access_token/").mock(
        return_value=httpx.Response(
            200,
            json=ok({"access_token": "new-token-xyz-123", "advertiser_ids": ["1"], "scope": [4]}),
        )
    )
    data = exchange_auth_code(app_id=APP_ID, secret=APP_SECRET, auth_code="code-123456789")
    assert data["access_token"] == "new-token-xyz-123"
    assert body_of(route.calls.last) == {
        "app_id": APP_ID,
        "secret": APP_SECRET,
        "auth_code": "code-123456789",
    }
    assert redact("new-token-xyz-123") == "***"


@respx.mock
def test_exchange_auth_code_refused() -> None:
    respx.post(f"{BASE}/oauth2/access_token/").mock(
        return_value=httpx.Response(200, json=ok(code=40110, message="Invalid auth_code"))
    )
    with pytest.raises(AuthError, match="one hour"):
        exchange_auth_code(app_id=APP_ID, secret=APP_SECRET, auth_code="bad-code-0000")


@respx.mock
def test_revoke_token() -> None:
    route = respx.post(f"{BASE}/oauth2/revoke_token/").mock(
        return_value=httpx.Response(200, json=ok())
    )
    revoke_token(app_id=APP_ID, secret=APP_SECRET, access_token="tok-to-revoke-1")
    assert body_of(route.calls.last)["access_token"] == "tok-to-revoke-1"
    respx.post(f"{BASE}/oauth2/revoke_token/").mock(
        return_value=httpx.Response(200, json=ok(code=40105))
    )
    with pytest.raises(AuthError):
        revoke_token(app_id=APP_ID, secret=APP_SECRET, access_token="tok-to-revoke-1")
