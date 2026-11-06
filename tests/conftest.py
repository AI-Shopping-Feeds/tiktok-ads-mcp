"""Shared fixtures for the test suite.

All tests run fully offline: HTTP is mocked with respx and no real TikTok
credentials are used.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tiktok_ads_mcp.audit import AuditLog
from tiktok_ads_mcp.client import TikTokAdsClient
from tiktok_ads_mcp.config import Config

ADV = "7000000000000000001"
BC = "7100000000000000001"
BASE = "https://business-api.tiktok.com/open_api/v1.3"
TOKEN = "fake-access-token-0123456789abcdef"
APP_ID = "7200000000000000001"
APP_SECRET = "fake-app-secret-value-123"


def ok(data: Any = None, *, code: int = 0, message: str = "OK") -> dict[str, Any]:
    """A TikTok response envelope."""
    return {"code": code, "message": message, "request_id": "req-1", "data": data or {}}


def page(items: list[Any], *, page_no: int = 1, total_page: int = 1, key: str = "list") -> dict:
    return ok(
        {
            key: items,
            "page_info": {
                "page": page_no,
                "page_size": 100,
                "total_page": total_page,
                "total_number": len(items) * total_page,
            },
        }
    )


class FakeAuth:
    """Stand-in for TokenAuth in tests."""

    account_label = "fake:test"

    def __init__(self) -> None:
        self.invalidated = 0
        self.token = TOKEN

    def access_token(self) -> str:
        return self.token

    def invalidate(self) -> None:
        self.invalidated += 1


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every test away from the real ~/.tiktok-ads-mcp and the user's env."""
    home = tmp_path / "home"
    monkeypatch.setenv("TIKTOK_ADS_HOME", str(home))
    for var in (
        "TIKTOK_ADS_ACCESS_TOKEN",
        "TIKTOK_ADS_APP_ID",
        "TIKTOK_ADS_APP_SECRET",
        "TIKTOK_ADS_ADVERTISER_ID",
        "TIKTOK_ADS_BC_ID",
        "TIKTOK_ADS_ALLOWED_ADVERTISER_IDS",
        "TIKTOK_ADS_TOKEN_FILE",
        "TIKTOK_ADS_AUDIT_LOG",
        "TIKTOK_ADS_TOOL_GROUPS",
        "TIKTOK_ADS_READ_ONLY",
        "TIKTOK_ADS_DRY_RUN",
        "TIKTOK_ADS_TRANSPORT",
        "TIKTOK_ADS_HOST",
        "TIKTOK_ADS_PORT",
        "TIKTOK_ADS_ALLOW_REMOTE",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    return home


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr("tiktok_ads_mcp.client.time.sleep", lambda s: slept.append(s))
    return slept


@pytest.fixture
def tmp_audit_log(tmp_path: Path) -> Path:
    return tmp_path / "logs" / "audit.jsonl"


@pytest.fixture
def config(tmp_audit_log: Path, tmp_path: Path) -> Config:
    return Config(
        access_token=TOKEN,
        app_id=APP_ID,
        app_secret=APP_SECRET,
        advertiser_id=ADV,
        audit_log=tmp_audit_log,
        token_file=tmp_path / "secrets" / "token.json",
        bc_id=BC,
        page_size=100,
        timeout=5.0,
        max_qps=1000.0,
        dry_run=False,
    )


@pytest.fixture
def audit(tmp_audit_log: Path) -> AuditLog:
    return AuditLog(tmp_audit_log)


@pytest.fixture
def fake_auth() -> FakeAuth:
    return FakeAuth()


@pytest.fixture
def client(config: Config, audit: AuditLog, fake_auth: FakeAuth):
    c = TikTokAdsClient(config, fake_auth, audit)
    yield c
    c.close()


def audit_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def body_of(call: Any) -> Any:
    """The JSON body respx recorded for a call."""
    return json.loads(call.request.content or b"null")


def query_of(call: Any) -> dict[str, Any]:
    """Query parameters of a recorded GET, with TikTok's JSON-encoded values decoded."""
    out: dict[str, Any] = {}
    for key, value in call.request.url.params.multi_items():
        out[key] = json.loads(value) if value[:1] in ("[", "{") else value
    return out
