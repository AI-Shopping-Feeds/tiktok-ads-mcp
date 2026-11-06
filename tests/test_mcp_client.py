"""End-to-end tests through `mcp.Client` against the real server (fake auth, mocked HTTP)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import Tool

from tiktok_ads_mcp import __version__, server, tools
from tiktok_ads_mcp.client import TikTokAdsClient
from tiktok_ads_mcp.config import API_BASE, Config, load_config
from tiktok_ads_mcp.tool_catalog import ALWAYS_REGISTERED, TOOL_SPECS

from .conftest import ADV, BASE, TOKEN, FakeAuth, ok

META_TOOLS = [
    "tiktok_ads_describe_server",
    "tiktok_ads_health_check",
    "tiktok_ads_audit_lookup",
    "tiktok_ads_audit_tail",
    "tiktok_ads_set_dry_run",
]
EXPECTED_TOOL_COUNT = 65


@pytest.fixture(autouse=True)
def _fake_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "load_auth", lambda config: FakeAuth())


def _build(config: Config, **changes: Any) -> MCPServer:
    return server.build_server(dataclasses.replace(config, **changes))


async def _tools(mcp: MCPServer) -> list[Tool]:
    async with Client(mcp) as c:
        return (await c.list_tools()).tools


def _group_tool_names(client: TikTokAdsClient) -> dict[str, list[str]]:
    """Tool names per group, by registering each module on its own server."""
    out: dict[str, list[str]] = {}
    for group in tools.TOOL_GROUPS:
        mcp = MCPServer("probe")
        getattr(tools, group).register(mcp, client)
        out[group] = list(mcp._tool_manager._tools)
    return out


# ---------------------------------------------------------------- metadata


async def test_server_reports_version_and_instructions(config: Config) -> None:
    async with Client(_build(config)) as c:
        assert c.server_info is not None
        assert c.server_info.name == "tiktok-ads-mcp"
        assert c.server_info.version == __version__
        assert c.instructions
        assert "tiktok_ads_describe_server" in c.instructions
        assert "dry-run" in c.instructions
        assert "TIKTOK_ADS_TOOL_GROUPS" in c.instructions
        assert "smart_plus" in c.instructions
        assert "profile individuals" in c.instructions
        assert 4 <= len(c.instructions.splitlines()) <= 8


async def test_every_tool_has_a_catalog_entry(config: Config) -> None:
    listed = await _tools(_build(config))
    assert len(listed) == EXPECTED_TOOL_COUNT
    for tool in listed:
        assert tool.name.startswith("tiktok_ads_"), tool.name
        assert tool.name in TOOL_SPECS, f"{tool.name} has no tool_catalog entry"
        assert tool.title, tool.name
        assert tool.title[0].isupper(), tool.name
        assert tool.description, tool.name
        a = tool.annotations
        assert a is not None, tool.name
        assert a.read_only_hint is not None, tool.name
        assert a.destructive_hint is not None, tool.name
        assert a.idempotent_hint is not None, tool.name
        assert a.open_world_hint is not None, tool.name
    # The catalog has no stale entries either.
    assert {t.name for t in listed} == set(TOOL_SPECS)


async def test_annotations_are_plausible(config: Config) -> None:
    by_name = {t.name: t.annotations for t in await _tools(_build(config))}
    read_only = {n for n, a in by_name.items() if a and a.read_only_hint}
    destructive = {n for n, a in by_name.items() if a and a.destructive_hint}
    assert not read_only & destructive
    for name in by_name:
        verb_part = name.removeprefix("tiktok_ads_").removeprefix("smart_plus_")
        verb = verb_part.split("_")[0]
        if verb in {"list", "get", "search", "estimate", "download", "read"}:
            assert name in read_only, name
        if verb == "delete":
            assert name in destructive, name
        if verb in {"create", "update", "set", "upload", "refresh"} and name not in {
            "tiktok_ads_create_report_task",
            "tiktok_ads_set_dry_run",
        }:
            assert name not in read_only, name
    assert "tiktok_ads_request" in destructive
    assert {"tiktok_ads_run_report", "tiktok_ads_read_request"} <= read_only
    closed = {n for n, a in by_name.items() if a and a.open_world_hint is False}
    assert closed == set(META_TOOLS) - {"tiktok_ads_health_check"}


async def test_tools_list_order_is_deterministic(config: Config, client: TikTokAdsClient) -> None:
    first = [t.name for t in await _tools(_build(config))]
    second = [t.name for t in await _tools(_build(config))]
    assert first == second
    per_group = _group_tool_names(client)
    expected = META_TOOLS + [n for g in tools.TOOL_GROUPS for n in per_group[g]]
    assert first == expected


# ---------------------------------------------------------------- filtering


async def test_tool_groups_limit_registration(config: Config, client: TikTokAdsClient) -> None:
    names = [t.name for t in await _tools(_build(config, tool_groups=["reporting", "accounts"]))]
    per_group = _group_tool_names(client)
    assert names == META_TOOLS + per_group["accounts"] + per_group["reporting"]


async def test_read_only_registers_only_read_tools(config: Config) -> None:
    listed = await _tools(_build(config, read_only=True))
    names = {t.name for t in listed}
    assert set(META_TOOLS) <= names
    for tool in listed:
        if tool.name not in ALWAYS_REGISTERED:
            assert tool.annotations and tool.annotations.read_only_hint, tool.name
    assert "tiktok_ads_update_campaign" not in names
    assert "tiktok_ads_smart_plus_create_campaign" not in names
    assert "tiktok_ads_request" not in names
    assert "tiktok_ads_list_campaigns" in names
    assert "tiktok_ads_run_report" in names
    expected = {n for n, s in TOOL_SPECS.items() if s.annotations.read_only_hint}
    assert names == expected | set(META_TOOLS)


async def test_read_only_combines_with_groups(config: Config) -> None:
    names = {
        t.name for t in await _tools(_build(config, tool_groups=["smart_plus"], read_only=True))
    }
    assert names == set(META_TOOLS) | {
        "tiktok_ads_smart_plus_list_campaigns",
        "tiktok_ads_smart_plus_list_ad_groups",
        "tiktok_ads_smart_plus_list_ads",
    }


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **values: str) -> Path:
    monkeypatch.setenv("TIKTOK_ADS_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("TIKTOK_ADS_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    return tmp_path / "missing.env"


async def test_env_vars_filter_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = _env(
        monkeypatch,
        tmp_path,
        TIKTOK_ADS_TOOL_GROUPS="accounts,pixels",
        TIKTOK_ADS_READ_ONLY="1",
    )
    names = {t.name for t in await _tools(server.build_server(env_file=env_file))}
    assert names == set(META_TOOLS) | {
        "tiktok_ads_list_advertisers",
        "tiktok_ads_get_advertiser_info",
        "tiktok_ads_list_business_centers",
        "tiktok_ads_list_bc_assets",
        "tiktok_ads_list_pixels",
        "tiktok_ads_get_pixel_event_stats",
    }


def test_unknown_group_fails_at_startup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = _env(monkeypatch, tmp_path, TIKTOK_ADS_TOOL_GROUPS="accounts,nope")
    with pytest.raises(RuntimeError) as exc_info:
        server.build_server(env_file=env_file)
    message = str(exc_info.value)
    assert "nope" in message
    for group in tools.TOOL_GROUPS:
        assert group in message


def test_load_config_normalises_group_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = _env(monkeypatch, tmp_path, TIKTOK_ADS_TOOL_GROUPS="Reporting, smart-plus")
    assert load_config(env_file=env_file).tool_groups == ["smart_plus", "reporting"]


# ---------------------------------------------------------------- calls


@respx.mock
async def test_api_error_reaches_the_client_redacted(config: Config) -> None:
    respx.get(f"{BASE}/campaign/get/").mock(
        return_value=httpx.Response(
            200, json=ok(code=40001, message=f"No permission for token {TOKEN}")
        )
    )
    async with Client(_build(config)) as c:
        result = await c.call_tool("tiktok_ads_list_campaigns", {})
    assert result.is_error
    text = " ".join(getattr(block, "text", "") for block in result.content)
    assert "TikTok API error 40001" in text
    assert "permission" in text
    assert TOKEN not in text


async def test_describe_server_reports_settings(config: Config) -> None:
    async with Client(_build(config, tool_groups=["reporting"], read_only=True)) as c:
        result = await c.call_tool("tiktok_ads_describe_server", {})
    payload = result.structured_content or json.loads(result.content[0].text)
    assert payload["tool_groups"] == ["reporting"]
    assert payload["read_only"] is True
    assert payload["api_base"] == API_BASE
    assert payload["default_advertiser_id"] == ADV
    assert payload["version"] == __version__
    dumped = json.dumps(payload).lower()
    assert "secret-value" not in dumped
    assert TOKEN not in dumped


@respx.mock
async def test_health_check_lists_advertisers_and_default(config: Config) -> None:
    respx.get(f"{BASE}/oauth2/advertiser/get/").mock(
        return_value=httpx.Response(
            200, json=ok({"list": [{"advertiser_id": ADV, "advertiser_name": "Example Shop"}]})
        )
    )
    respx.get(f"{BASE}/advertiser/info/").mock(
        return_value=httpx.Response(
            200, json=ok({"list": [{"advertiser_id": ADV, "currency": "GBP"}]})
        )
    )
    async with Client(_build(config)) as c:
        result = await c.call_tool("tiktok_ads_health_check", {})
    payload = result.structured_content or json.loads(result.content[0].text)
    assert payload["ok"] is True
    assert [c["check"] for c in payload["checks"]] == ["list_advertisers", "default_advertiser"]
    assert payload["advertisers"] == [{"advertiser_id": ADV, "name": "Example Shop"}]


@respx.mock
async def test_health_check_reports_bad_token(config: Config) -> None:
    respx.get(f"{BASE}/oauth2/advertiser/get/").mock(
        return_value=httpx.Response(200, json=ok(code=40105, message="Access token is incorrect"))
    )
    respx.get(f"{BASE}/advertiser/info/").mock(
        return_value=httpx.Response(200, json=ok(code=40105, message="Access token is incorrect"))
    )
    async with Client(_build(config)) as c:
        result = await c.call_tool("tiktok_ads_health_check", {})
    payload = result.structured_content or json.loads(result.content[0].text)
    assert payload["ok"] is False
    assert "auth" in payload["checks"][0]["error"]


async def test_set_dry_run_and_audit_tail(config: Config) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BASE}/campaign/create/").mock(return_value=httpx.Response(200, json=ok()))
        async with Client(_build(config)) as c:
            await c.call_tool("tiktok_ads_set_dry_run", {"enabled": True})
            created = await c.call_tool(
                "tiktok_ads_create_campaign",
                {"campaign_name": "x", "objective_type": "REACH", "budget": 5},
            )
            tail = await c.call_tool("tiktok_ads_audit_tail", {"limit": 5})
            lookup_id = json.loads(created.content[0].text)["audit_id"]
            found = await c.call_tool("tiktok_ads_audit_lookup", {"audit_id": lookup_id})
    assert json.loads(created.content[0].text)["_dry_run"] is True
    assert json.loads(tail.content[0].text)["count"] == 1
    assert json.loads(found.content[0].text)["found"] is True


def test_version_matches_pyproject() -> None:
    root = Path(__file__).resolve().parent.parent
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert f'\nversion = "{__version__}"\n' in pyproject


def test_docs_list_every_tool() -> None:
    root = Path(__file__).resolve().parent.parent
    docs = (root / "docs" / "tools.md").read_text(encoding="utf-8")
    missing = [name for name in TOOL_SPECS if f"`{name}`" not in docs]
    assert not missing, f"docs/tools.md is missing {missing}"
    assert f"**{len(TOOL_SPECS)} tools" in docs
