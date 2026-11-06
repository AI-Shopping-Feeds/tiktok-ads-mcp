"""Tool behaviour through the MCP client: guards, sunset rules, snapshots, endpoints."""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from typing import Any

import httpx
import pytest
import respx
from mcp import Client

from tiktok_ads_mcp import server
from tiktok_ads_mcp.config import Config
from tiktok_ads_mcp.tools import _common

from .conftest import ADV, BASE, BC, FakeAuth, audit_entries, body_of, ok, page, query_of


@pytest.fixture(autouse=True)
def _fake_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "load_auth", lambda config: FakeAuth())


async def call(config: Config, name: str, args: dict[str, Any], **changes: Any) -> Any:
    mcp = server.build_server(dataclasses.replace(config, **changes))
    async with Client(mcp) as c:
        result = await c.call_tool(name, args)
    text = " ".join(getattr(block, "text", "") for block in result.content)
    if result.is_error:
        return {"_error": text}
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc) if set(sc) == {"result"} else sc
    return json.loads(text)


def campaigns(*items: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=page(list(items)))


# ---------------------------------------------------------------- campaigns


@respx.mock
async def test_create_campaign_is_paused_with_request_id(config: Config) -> None:
    route = respx.post(f"{BASE}/campaign/create/").mock(
        return_value=httpx.Response(200, json=ok({"campaign_id": "11"}))
    )
    out = await call(
        config,
        "tiktok_ads_create_campaign",
        {
            "campaign_name": "Spring traffic",
            "objective_type": "traffic",
            "budget_mode": "BUDGET_MODE_DAY",
            "budget": 50,
        },
    )
    assert out["campaign_id"] == "11"
    sent = body_of(route.calls.last)
    assert sent["operation_status"] == "DISABLE"
    assert sent["objective_type"] == "TRAFFIC"
    assert sent["advertiser_id"] == ADV
    assert sent["request_id"].isdigit()
    assert out["audit_id"]


@pytest.mark.parametrize("objective", ["WEB_CONVERSIONS", "APP_PROMOTION", "LEAD_GENERATION"])
@respx.mock
async def test_create_campaign_refuses_sunset_objectives(config: Config, objective: str) -> None:
    route = respx.post(f"{BASE}/campaign/create/").mock(return_value=httpx.Response(200, json=ok()))
    out = await call(
        config, "tiktok_ads_create_campaign", {"campaign_name": "x", "objective_type": objective}
    )
    assert "smart_plus" in out["_error"]
    assert "1 January 2027" in out["_error"]
    assert not route.called


@respx.mock
async def test_create_search_campaign_for_sales_is_allowed(config: Config) -> None:
    route = respx.post(f"{BASE}/campaign/create/").mock(return_value=httpx.Response(200, json=ok()))
    await call(
        config,
        "tiktok_ads_create_campaign",
        {"campaign_name": "x", "objective_type": "WEB_CONVERSIONS", "is_search_campaign": True},
    )
    assert body_of(route.calls.last)["is_search_campaign"] is True


@respx.mock
async def test_enabling_at_create_needs_apply(config: Config) -> None:
    route = respx.post(f"{BASE}/campaign/create/").mock(return_value=httpx.Response(200, json=ok()))
    args = {"campaign_name": "x", "objective_type": "REACH", "enabled": True}
    refused = await call(config, "tiktok_ads_create_campaign", args)
    assert refused["refused"] is True
    assert refused["required_confirm"] == "APPLY"
    assert not route.called
    await call(config, "tiktok_ads_create_campaign", {**args, "confirm": "APPLY"})
    assert body_of(route.calls.last)["operation_status"] == "ENABLE"


async def test_extra_cannot_override_protected_fields(config: Config) -> None:
    out = await call(
        config,
        "tiktok_ads_create_campaign",
        {"campaign_name": "x", "objective_type": "REACH", "extra": {"operation_status": "ENABLE"}},
    )
    assert "operation_status" in out["_error"]


@respx.mock
async def test_update_campaign_budget_rise_needs_apply_and_keeps_before(config: Config) -> None:
    get = respx.get(f"{BASE}/campaign/get/").mock(
        return_value=campaigns(
            {"campaign_id": "11", "budget": 100.0, "campaign_automation_type": "MANUAL"}
        )
    )
    upd = respx.post(f"{BASE}/campaign/update/").mock(return_value=httpx.Response(200, json=ok()))
    refused = await call(config, "tiktok_ads_update_campaign", {"campaign_id": "11", "budget": 150})
    assert refused["required_confirm"] == "APPLY"
    assert refused["money_changes"][0]["change_pct"] == 50.0
    assert not upd.called
    assert query_of(get.calls.last)["filtering"] == {"campaign_ids": ["11"]}
    out = await call(
        config,
        "tiktok_ads_update_campaign",
        {"campaign_id": "11", "budget": 150, "confirm": "APPLY"},
    )
    assert out["audit_id"]
    [entry] = audit_entries(config.audit_log)
    assert entry["before"]["budget"] == 100.0
    small = await call(config, "tiktok_ads_update_campaign", {"campaign_id": "11", "budget": 110})
    assert "refused" not in small


@respx.mock
async def test_update_campaign_refuses_upgraded_smart_plus(config: Config) -> None:
    respx.get(f"{BASE}/campaign/get/").mock(
        return_value=campaigns(
            {"campaign_id": "11", "budget": 1.0, "campaign_automation_type": "UPGRADED_SMART_PLUS"}
        )
    )
    out = await call(config, "tiktok_ads_update_campaign", {"campaign_id": "11", "budget": 1})
    assert "smart_plus_update_campaign" in out["_error"]


@respx.mock
async def test_update_ad_group_bid_rise_needs_apply(config: Config) -> None:
    respx.get(f"{BASE}/adgroup/get/").mock(
        return_value=campaigns({"adgroup_id": "22", "bid_price": 1.0, "budget": 20})
    )
    upd = respx.post(f"{BASE}/adgroup/update/").mock(return_value=httpx.Response(200, json=ok()))
    refused = await call(
        config, "tiktok_ads_update_ad_group", {"adgroup_id": "22", "changes": {"bid_price": 2}}
    )
    assert refused["required_confirm"] == "APPLY"
    await call(
        config,
        "tiktok_ads_update_ad_group",
        {"adgroup_id": "22", "changes": {"location_ids": ["1"]}},
    )
    assert body_of(upd.calls.last) == {
        "advertiser_id": ADV,
        "adgroup_id": "22",
        "location_ids": ["1"],
    }


@respx.mock
async def test_update_ad_group_budgets_compares_scheduled(config: Config) -> None:
    respx.get(f"{BASE}/adgroup/get/").mock(
        return_value=campaigns({"adgroup_id": "1", "budget": 10}, {"adgroup_id": "2", "budget": 10})
    )
    upd = respx.post(f"{BASE}/adgroup/budget/update/").mock(
        return_value=httpx.Response(200, json=ok())
    )
    args = {
        "budgets": [{"adgroup_id": "1", "budget": 11}],
        "scheduled_budgets": [{"adgroup_id": "2", "scheduled_budget": 30}],
    }
    refused = await call(config, "tiktok_ads_update_ad_group_budgets", args)
    assert refused["required_confirm"] == "APPLY"
    assert any("2 rises from 10.0 to 30.0" in r for r in refused["reasons"])
    await call(config, "tiktok_ads_update_ad_group_budgets", {**args, "confirm": "APPLY"})
    bodies = [body_of(c) for c in upd.calls]
    assert bodies == [
        {"advertiser_id": ADV, "budget": [{"adgroup_id": "1", "budget": 11}]},
        {"advertiser_id": ADV, "scheduled_budget": [{"adgroup_id": "2", "scheduled_budget": 30}]},
    ]


@respx.mock
async def test_set_status_pause_batches_of_20(config: Config) -> None:
    respx.get(f"{BASE}/ad/get/").mock(return_value=campaigns())
    upd = respx.post(f"{BASE}/ad/status/update/").mock(return_value=httpx.Response(200, json=ok()))
    ids = [str(i) for i in range(1, 26)]
    refused = await call(
        config, "tiktok_ads_set_status", {"level": "ad", "ids": ids, "status": "DISABLE"}
    )
    assert refused["required_confirm"] == "APPLY"  # 25 > bulk threshold
    out = await call(
        config,
        "tiktok_ads_set_status",
        {"level": "ads", "ids": ids, "status": "disable", "confirm": "APPLY"},
    )
    assert out["count"] == 25
    sizes = [len(body_of(c)["ad_ids"]) for c in upd.calls]
    assert sizes == [20, 5]
    assert body_of(upd.calls[0])["operation_status"] == "DISABLE"


@respx.mock
async def test_set_status_enable_needs_apply(config: Config) -> None:
    respx.get(f"{BASE}/campaign/get/").mock(return_value=campaigns())
    upd = respx.post(f"{BASE}/campaign/status/update/").mock(
        return_value=httpx.Response(200, json=ok())
    )
    refused = await call(
        config, "tiktok_ads_set_status", {"level": "campaign", "ids": ["1"], "status": "ENABLE"}
    )
    assert refused["required_confirm"] == "APPLY"
    assert not upd.called
    small = await call(
        config, "tiktok_ads_set_status", {"level": "campaign", "ids": ["1"], "status": "DISABLE"}
    )
    assert "refused" not in small
    bad = await call(
        config, "tiktok_ads_set_status", {"level": "campaign", "ids": ["1"], "status": "DELETE"}
    )
    assert "delete tool" in bad["_error"]


@respx.mock
async def test_delete_needs_delete_word(config: Config) -> None:
    respx.get(f"{BASE}/adgroup/get/").mock(return_value=campaigns({"adgroup_id": "5"}))
    upd = respx.post(f"{BASE}/adgroup/status/update/").mock(
        return_value=httpx.Response(200, json=ok())
    )
    refused = await call(
        config, "tiktok_ads_delete", {"level": "ad_group", "ids": ["5"], "confirm": "APPLY"}
    )
    assert refused["required_confirm"] == "DELETE"
    assert not upd.called
    out = await call(
        config, "tiktok_ads_delete", {"level": "ad_group", "ids": ["5"], "confirm": "DELETE"}
    )
    assert out["deleted_count"] == 1
    assert body_of(upd.calls.last)["operation_status"] == "DELETE"
    [entry] = audit_entries(config.audit_log)
    assert entry["before"] == [{"adgroup_id": "5"}]


@respx.mock
async def test_dry_run_rehearses_delete_without_confirm(config: Config) -> None:
    respx.get(f"{BASE}/ad/get/").mock(return_value=campaigns({"ad_id": "5"}))
    upd = respx.post(f"{BASE}/ad/status/update/").mock(return_value=httpx.Response(200, json=ok()))
    out = await call(config, "tiktok_ads_delete", {"level": "ad", "ids": ["5"]}, dry_run=True)
    assert out["safety"]["required_confirm"] == "DELETE"
    assert out["results"][0]["_dry_run"] is True
    assert not upd.called


# ---------------------------------------------------------------- sunset guard


def _legacy_sales_campaign() -> httpx.Response:
    return campaigns(
        {
            "campaign_id": "11",
            "objective_type": "WEB_CONVERSIONS",
            "campaign_automation_type": "MANUAL",
            "is_search_campaign": False,
        }
    )


@respx.mock
async def test_ad_group_under_legacy_sales_campaign_warns_before_sunset(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_common, "today", lambda: date(2026, 12, 1))
    respx.get(f"{BASE}/campaign/get/").mock(return_value=_legacy_sales_campaign())
    create = respx.post(f"{BASE}/adgroup/create/").mock(
        return_value=httpx.Response(200, json=ok({"adgroup_id": "22"}))
    )
    out = await call(
        config,
        "tiktok_ads_create_ad_group",
        {"campaign_id": "11", "settings": {"adgroup_name": "a", "budget": 10}},
    )
    assert "1 January 2027" in out["warning"]
    assert body_of(create.calls.last)["operation_status"] == "DISABLE"


@respx.mock
async def test_ad_group_under_legacy_sales_campaign_refused_after_sunset(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_common, "today", lambda: date(2027, 1, 1))
    respx.get(f"{BASE}/campaign/get/").mock(return_value=_legacy_sales_campaign())
    create = respx.post(f"{BASE}/adgroup/create/").mock(return_value=httpx.Response(200, json=ok()))
    out = await call(
        config,
        "tiktok_ads_create_ad_group",
        {"campaign_id": "11", "settings": {"adgroup_name": "a"}},
    )
    assert "Upgraded Smart+" in out["_error"]
    assert not create.called


@respx.mock
async def test_ads_under_traffic_campaign_have_no_warning(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_common, "today", lambda: date(2027, 6, 1))
    respx.get(f"{BASE}/adgroup/get/").mock(
        return_value=campaigns({"adgroup_id": "22", "campaign_id": "11"})
    )
    respx.get(f"{BASE}/campaign/get/").mock(
        return_value=campaigns(
            {"campaign_id": "11", "objective_type": "TRAFFIC", "campaign_automation_type": "MANUAL"}
        )
    )
    create = respx.post(f"{BASE}/ad/create/").mock(
        return_value=httpx.Response(200, json=ok({"ad_ids": ["33"]}))
    )
    out = await call(
        config,
        "tiktok_ads_create_ads",
        {"adgroup_id": "22", "creatives": [{"ad_name": "a", "video_id": "v"}]},
    )
    assert "warning" not in out
    assert body_of(create.calls.last)["creatives"] == [{"ad_name": "a", "video_id": "v"}]


# ---------------------------------------------------------------- smart+


@respx.mock
async def test_smart_plus_create_campaign(config: Config) -> None:
    route = respx.post(f"{BASE}/smart_plus/campaign/create/").mock(
        return_value=httpx.Response(200, json=ok({"campaign_id": "1"}))
    )
    bad = await call(
        config,
        "tiktok_ads_smart_plus_create_campaign",
        {"campaign_name": "x", "objective_type": "TRAFFIC"},
    )
    assert "tiktok_ads_create_campaign" in bad["_error"]
    out = await call(
        config,
        "tiktok_ads_smart_plus_create_campaign",
        {"campaign_name": "x", "objective_type": "web_conversions", "budget": 40},
    )
    sent = body_of(route.calls.last)
    assert sent["objective_type"] == "WEB_CONVERSIONS"
    assert sent["operation_status"] == "DISABLE"
    assert sent["request_id"].isdigit()
    assert out["campaign_id"] == "1"


@respx.mock
async def test_smart_plus_status_uses_smart_plus_ids(config: Config) -> None:
    get = respx.get(f"{BASE}/smart_plus/ad/get/").mock(return_value=campaigns())
    upd = respx.post(f"{BASE}/smart_plus/ad/status/update/").mock(
        return_value=httpx.Response(200, json=ok())
    )
    await call(
        config,
        "tiktok_ads_smart_plus_set_status",
        {"level": "ad", "ids": ["9"], "status": "DISABLE"},
    )
    assert body_of(upd.calls.last)["smart_plus_ad_ids"] == ["9"]
    assert query_of(get.calls.last)["filtering"] == {"smart_plus_ad_ids": ["9"]}
    assert query_of(get.calls.last)["page_size"] == "1"


@respx.mock
async def test_smart_plus_ad_group_budget_rise(config: Config) -> None:
    respx.get(f"{BASE}/smart_plus/adgroup/get/").mock(
        return_value=campaigns({"adgroup_id": "1", "budget": 100})
    )
    upd = respx.post(f"{BASE}/smart_plus/adgroup/budget/update/").mock(
        return_value=httpx.Response(200, json=ok())
    )
    refused = await call(
        config,
        "tiktok_ads_smart_plus_update_ad_group_budgets",
        {"budgets": [{"adgroup_id": "1", "budget": 200}]},
    )
    assert refused["required_confirm"] == "APPLY"
    assert not upd.called


@respx.mock
async def test_smart_plus_cbo_ad_group_max_budget(config: Config) -> None:
    respx.get(f"{BASE}/smart_plus/adgroup/get/").mock(
        return_value=campaigns({"adgroup_id": "1", "max_budget": 100})
    )
    upd = respx.post(f"{BASE}/smart_plus/adgroup/budget/update/").mock(
        return_value=httpx.Response(200, json=ok())
    )
    small = await call(
        config,
        "tiktok_ads_smart_plus_update_ad_group_budgets",
        {"budgets": [{"adgroup_id": "1", "max_budget": 110}]},
    )
    assert "refused" not in small
    assert body_of(upd.calls.last)["budget"] == [{"adgroup_id": "1", "max_budget": 110}]
    big = await call(
        config,
        "tiktok_ads_smart_plus_update_ad_group_budgets",
        {"budgets": [{"adgroup_id": "1", "max_budget": 300}]},
    )
    assert big["required_confirm"] == "APPLY"
    empty = await call(
        config, "tiktok_ads_smart_plus_update_ad_group_budgets", {"budgets": [{"adgroup_id": "1"}]}
    )
    assert "max_budget" in empty["_error"]


@respx.mock
async def test_smart_plus_creative_status(config: Config) -> None:
    respx.get(f"{BASE}/smart_plus/ad/get/").mock(return_value=campaigns())
    upd = respx.post(f"{BASE}/smart_plus/ad/material_status/update/").mock(
        return_value=httpx.Response(200, json=ok())
    )
    await call(
        config,
        "tiktok_ads_smart_plus_set_creative_status",
        {"smart_plus_ad_id": "9", "ad_material_ids": ["1", "2"], "status": "DISABLE"},
    )
    assert body_of(upd.calls.last)["ad_material_ids"] == ["1", "2"]


# ---------------------------------------------------------------- other groups


@respx.mock
async def test_list_advertisers_needs_app_credentials(config: Config) -> None:
    route = respx.get(f"{BASE}/oauth2/advertiser/get/").mock(
        return_value=httpx.Response(
            200, json=ok({"list": [{"advertiser_id": ADV, "advertiser_name": "Example Shop"}]})
        )
    )
    out = await call(config, "tiktok_ads_list_advertisers", {})
    assert out["advertisers"][0]["advertiser_id"] == ADV
    assert route.calls.last.request.url.params["app_id"] == config.app_id
    missing = await call(config, "tiktok_ads_list_advertisers", {}, app_secret=None)
    assert "TIKTOK_ADS_APP_SECRET" in missing["_error"]


@respx.mock
async def test_upload_image_by_url(config: Config) -> None:
    route = respx.post(f"{BASE}/file/image/ad/upload/").mock(
        return_value=httpx.Response(200, json=ok({"image_id": "img1"}))
    )
    out = await call(config, "tiktok_ads_upload_image", {"image_url": "https://example.com/a.jpg"})
    assert out["image_id"] == "img1"
    assert body_of(route.calls.last) == {
        "advertiser_id": ADV,
        "upload_type": "UPLOAD_BY_URL",
        "image_url": "https://example.com/a.jpg",
    }
    bad = await call(config, "tiktok_ads_upload_image", {"image_url": "file:///etc/passwd"})
    assert "_error" in bad


@respx.mock
async def test_list_videos_by_id_and_search(config: Config) -> None:
    info = respx.get(f"{BASE}/file/video/ad/info/").mock(
        return_value=httpx.Response(200, json=ok({"list": [{"video_id": "v1"}]}))
    )
    search = respx.get(f"{BASE}/file/video/ad/search/").mock(
        return_value=httpx.Response(200, json=page([{"video_id": "v2"}]))
    )
    by_id = await call(config, "tiktok_ads_list_videos", {"video_ids": ["1"]})
    assert by_id["list"] == [{"video_id": "v1"}]
    assert query_of(info.calls.last)["video_ids"] == ["1"]
    found = await call(config, "tiktok_ads_list_videos", {})
    assert found["list"] == [{"video_id": "v2"}]
    assert search.called


@respx.mock
async def test_delete_audiences_needs_delete(config: Config) -> None:
    respx.get(f"{BASE}/dmp/custom_audience/get/").mock(
        return_value=httpx.Response(200, json=ok({"list": [{"custom_audience_id": "1"}]}))
    )
    route = respx.post(f"{BASE}/dmp/custom_audience/delete/").mock(
        return_value=httpx.Response(200, json=ok())
    )
    refused = await call(config, "tiktok_ads_delete_audiences", {"custom_audience_ids": ["1"]})
    assert refused["required_confirm"] == "DELETE"
    await call(
        config, "tiktok_ads_delete_audiences", {"custom_audience_ids": ["1"], "confirm": "DELETE"}
    )
    assert route.called


@respx.mock
async def test_catalog_tools_use_bc_id(config: Config) -> None:
    route = respx.get(f"{BASE}/catalog/get/").mock(
        return_value=httpx.Response(200, json=page([{"catalog_id": "c1"}]))
    )
    out = await call(config, "tiktok_ads_list_catalogs", {})
    assert out["catalogs"] == [{"catalog_id": "c1"}]
    assert query_of(route.calls.last)["bc_id"] == BC
    delete = respx.post(f"{BASE}/catalog/set/delete/").mock(
        return_value=httpx.Response(200, json=ok())
    )
    respx.get(f"{BASE}/catalog/set/get/").mock(
        return_value=httpx.Response(200, json=ok({"list": [{"product_set_id": "5"}]}))
    )
    refused = await call(
        config, "tiktok_ads_delete_product_sets", {"catalog_id": "1", "product_set_ids": ["5"]}
    )
    assert refused["required_confirm"] == "DELETE"
    assert not delete.called


@respx.mock
async def test_estimate_audience_size_is_a_read(config: Config) -> None:
    route = respx.post(f"{BASE}/ad/audience_size/estimate/").mock(
        return_value=httpx.Response(200, json=ok({"user_count": 1000}))
    )
    out = await call(
        config,
        "tiktok_ads_estimate_audience_size",
        {
            "objective_type": "traffic",
            "optimization_goal": "click",
            "targeting": {"age_groups": []},
        },
        dry_run=True,
    )
    assert out["user_count"] == 1000
    assert route.called
    assert audit_entries(config.audit_log) == []


# ---------------------------------------------------------------- escape hatch


@respx.mock
async def test_read_request_refuses_writes(config: Config) -> None:
    respx.get(f"{BASE}/campaign/copy/task/check/").mock(return_value=httpx.Response(200, json=ok()))
    ok_out = await call(
        config,
        "tiktok_ads_read_request",
        {"method": "GET", "path": "/campaign/copy/task/check/", "query": {"advertiser_id": ADV}},
    )
    assert "_error" not in ok_out
    refused = await call(
        config, "tiktok_ads_read_request", {"method": "POST", "path": "/campaign/update/"}
    )
    assert "tiktok_ads_request" in refused["_error"]


@pytest.mark.parametrize(
    "path", ["https://example.com/x", "/../oauth2/x/", "/oauth2/advertiser/get/"]
)
async def test_request_rejects_bad_paths(config: Config, path: str) -> None:
    out = await call(config, "tiktok_ads_request", {"method": "GET", "path": path})
    assert "_error" in out


@respx.mock
async def test_raw_write_needs_apply_and_is_audited(config: Config) -> None:
    route = respx.post(f"{BASE}/catalog/product/update/").mock(
        return_value=httpx.Response(200, json=ok())
    )
    args = {"method": "POST", "path": "/catalog/product/update/", "body": {"bc_id": BC}}
    refused = await call(config, "tiktok_ads_request", args)
    assert refused["required_confirm"] == "APPLY"
    assert not route.called
    out = await call(config, "tiktok_ads_request", {**args, "confirm": "APPLY"})
    assert out["audit_id"]
    [entry] = audit_entries(config.audit_log)
    assert entry["op"] == "request POST /catalog/product/update/"
