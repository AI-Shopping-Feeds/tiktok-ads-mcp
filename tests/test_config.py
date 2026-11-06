"""Configuration: per-user folder, .env lookup, token file, validation."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from tiktok_ads_mcp import config as config_mod
from tiktok_ads_mcp.config import ensure_private_dir, load_config

from .conftest import ADV


def test_defaults_live_in_the_user_folder(_isolated_home: Path) -> None:
    assert config_mod.token_file_path() == _isolated_home / "secrets" / "tiktok-ads-token.json"
    assert config_mod.audit_log_path() == _isolated_home / "logs" / "audit.jsonl"


def test_default_home_is_dot_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TIKTOK_ADS_HOME")
    monkeypatch.setattr(config_mod.Path, "home", classmethod(lambda cls: tmp_path))
    assert config_mod.app_home() == tmp_path / ".tiktok-ads-mcp"


def test_missing_token_is_a_clear_error() -> None:
    with pytest.raises(RuntimeError, match="tiktok-ads-mcp auth"):
        load_config()
    assert load_config(require_token=False).access_token is None


def test_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIKTOK_ADS_ACCESS_TOKEN", "tok-from-env")
    monkeypatch.setenv("TIKTOK_ADS_ADVERTISER_ID", ADV)
    cfg = load_config()
    assert cfg.access_token == "tok-from-env"
    assert cfg.advertiser_id == ADV
    assert cfg.max_increase_pct == 20
    assert cfg.audit_retention_days == 30
    assert cfg.bulk_threshold == 10


def test_token_file_and_single_advertiser_default(_isolated_home: Path) -> None:
    path = _isolated_home / "secrets" / "tiktok-ads-token.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"access_token": "tok-file", "advertiser_ids": [ADV]}))
    cfg = load_config()
    assert cfg.access_token == "tok-file"
    assert cfg.advertiser_id == ADV


def test_home_env_file_is_read(_isolated_home: Path) -> None:
    _isolated_home.mkdir(parents=True)
    (_isolated_home / ".env").write_text(
        "TIKTOK_ADS_ACCESS_TOKEN=tok-home\nTIKTOK_ADS_DRY_RUN=true\n"
    )
    cfg = load_config()
    assert cfg.access_token == "tok-home"
    assert cfg.dry_run is True


def test_explicit_env_file_wins(tmp_path: Path, _isolated_home: Path) -> None:
    _isolated_home.mkdir(parents=True)
    (_isolated_home / ".env").write_text("TIKTOK_ADS_ACCESS_TOKEN=tok-home\n")
    env = tmp_path / "custom.env"
    env.write_text("TIKTOK_ADS_ACCESS_TOKEN=tok-custom\n")
    assert load_config(env_file=env).access_token == "tok-custom"


@pytest.mark.parametrize(
    ("var", "value", "match"),
    [
        ("TIKTOK_ADS_ADVERTISER_ID", "abc", "numeric"),
        ("TIKTOK_ADS_APP_ID", "x1", "numeric"),
        ("TIKTOK_ADS_BC_ID", "nope", "numeric"),
        ("TIKTOK_ADS_TRANSPORT", "carrier-pigeon", "TRANSPORT"),
        ("TIKTOK_ADS_PAGE_SIZE", "5000", "PAGE_SIZE"),
        ("TIKTOK_ADS_MAX_BUDGET", "lots", "number"),
        ("TIKTOK_ADS_ALLOWED_ADVERTISER_IDS", "1,x", "numeric"),
        ("TIKTOK_ADS_TOOL_GROUPS", "campaigns,nope", "nope"),
    ],
)
def test_validation(monkeypatch: pytest.MonkeyPatch, var: str, value: str, match: str) -> None:
    monkeypatch.setenv("TIKTOK_ADS_ACCESS_TOKEN", "tok")
    monkeypatch.setenv(var, value)
    with pytest.raises(RuntimeError, match=match):
        load_config()


def test_default_advertiser_must_be_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIKTOK_ADS_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("TIKTOK_ADS_ADVERTISER_ID", "1")
    monkeypatch.setenv("TIKTOK_ADS_ALLOWED_ADVERTISER_IDS", "2,3")
    with pytest.raises(RuntimeError, match="ALLOWED"):
        load_config()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_private_dir_is_0700(tmp_path: Path) -> None:
    d = ensure_private_dir(tmp_path / "a" / "b")
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
