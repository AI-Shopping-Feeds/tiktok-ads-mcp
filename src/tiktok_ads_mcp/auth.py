"""TikTok API for Business access tokens.

The Marketing API uses a long-term access token per developer app and
authorising TikTok For Business user. TikTok's docs say it does not expire; it
stops working when the advertiser removes the authorisation or the token is
revoked with /oauth2/revoke_token/. There is no refresh token.

`tiktok-ads-mcp auth` swaps a one-time `auth_code` (valid for one hour) for
that token and stores it in an owner-only (0600) file. Secrets are never
logged: use `redact()` on anything that might contain one.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Protocol

import httpx

from .config import API_BASE, Config, ensure_private_dir

ACCESS_TOKEN_PATH = "/oauth2/access_token/"
REVOKE_TOKEN_PATH = "/oauth2/revoke_token/"

_SECRET_KEYS = {
    "access_token",
    "access-token",
    "secret",
    "app_secret",
    "client_secret",
    "auth_code",
    "authorization",
    "password",
    "refresh_token",
}
# Secrets that can appear inside URLs or free text (query strings, error bodies).
_QUERY_SECRET_RE = re.compile(
    r"((?:access_token|secret|app_secret|auth_code|refresh_token)=)[^&\s\"']+",
    re.IGNORECASE,
)
_extra_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember a secret value (token, app secret) so redact() hides it everywhere."""
    if value and len(value) >= 8:
        _extra_secrets.add(value)


def redact(value: Any) -> Any:
    """Return a copy of value with tokens and known secrets replaced by '***'."""
    if isinstance(value, str):
        out = _QUERY_SECRET_RE.sub(r"\1***", value)
        for secret in _extra_secrets:
            out = out.replace(secret, "***")
        return out
    if isinstance(value, dict):
        return {
            k: ("***" if str(k).lower() in _SECRET_KEYS and v else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


class Auth(Protocol):
    @property
    def account_label(self) -> str: ...

    def access_token(self) -> str: ...

    def invalidate(self) -> None: ...


class AuthError(RuntimeError):
    """TikTok refused an auth code, a token or a revoke."""


class TokenAuth:
    """Holds the long-term Marketing API access token."""

    def __init__(self, token: str, *, app_id: str | None = None):
        if not token:
            raise AuthError("No access token. Run `tiktok-ads-mcp auth` first.")
        self._token = token
        self.app_id = app_id
        register_secret(token)

    @property
    def account_label(self) -> str:
        app = f"app ...{self.app_id[-4:]}" if self.app_id else "app unknown"
        return f"long-term token ({app})"

    def access_token(self) -> str:
        return self._token

    def invalidate(self) -> None:
        """Nothing to refresh: TikTok issues no refresh token for the Marketing API."""


def load_auth(config: Config) -> TokenAuth:
    if not config.access_token:
        raise RuntimeError("No access token configured. Run `tiktok-ads-mcp auth` first.")
    register_secret(config.app_secret)
    return TokenAuth(config.access_token, app_id=config.app_id)


def save_token_file(path: Path, data: dict[str, Any]) -> None:
    """Write (or merge into) the token file: folder 0700, file 0600."""
    ensure_private_dir(path.parent)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            existing = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            existing = {}
    existing.update(data)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    if sys.platform != "win32":
        os.chmod(path, 0o600)


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"_raw": resp.text[:500]}


def exchange_auth_code(
    *, app_id: str, secret: str, auth_code: str, timeout: float = 30.0
) -> dict[str, Any]:
    """Swap a one-time auth_code for a long-term access token.

    Returns TikTok's `data`: access_token, advertiser_ids and scope.
    """
    register_secret(secret)
    register_secret(auth_code)
    try:
        resp = httpx.post(
            f"{API_BASE}{ACCESS_TOKEN_PATH}",
            json={"app_id": app_id, "secret": secret, "auth_code": auth_code},
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        raise AuthError(f"Could not reach TikTok's token endpoint: {redact(str(e))}") from e
    payload = _safe_json(resp)
    data = payload.get("data") if isinstance(payload, dict) else None
    if (
        resp.status_code != 200
        or not isinstance(payload, dict)
        or payload.get("code") != 0
        or not isinstance(data, dict)
        or not data.get("access_token")
    ):
        raise AuthError(
            f"TikTok refused the authorisation code (HTTP {resp.status_code}): "
            f"{redact(payload)}. Codes last one hour and work once; run the command again."
        )
    register_secret(data["access_token"])
    return data


def revoke_token(*, app_id: str, secret: str, access_token: str, timeout: float = 30.0) -> None:
    """Invalidate a long-term access token at TikTok."""
    register_secret(secret)
    register_secret(access_token)
    try:
        resp = httpx.post(
            f"{API_BASE}{REVOKE_TOKEN_PATH}",
            json={"app_id": app_id, "secret": secret, "access_token": access_token},
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        raise AuthError(f"Could not reach TikTok's revoke endpoint: {redact(str(e))}") from e
    payload = _safe_json(resp)
    if resp.status_code != 200 or not isinstance(payload, dict) or payload.get("code") != 0:
        raise AuthError(
            f"TikTok refused to revoke the token (HTTP {resp.status_code}): {redact(payload)}"
        )
