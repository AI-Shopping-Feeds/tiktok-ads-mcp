"""The HTTP client: headers, scoping, envelope, retries, dry-run, audit, downloads."""

from __future__ import annotations

import httpx
import pytest
import respx

from tiktok_ads_mcp.client import TikTokAdsAPIError, TikTokAdsClient, encode_params

from .conftest import ADV, BASE, TOKEN, audit_entries, body_of, ok, page, query_of


def test_encode_params_json_encodes_lists_and_objects() -> None:
    out = encode_params(
        {"advertiser_id": ADV, "filtering": {"campaign_ids": ["1"]}, "fields": ["a"], "x": None}
    )
    assert out == {
        "advertiser_id": ADV,
        "filtering": '{"campaign_ids":["1"]}',
        "fields": '["a"]',
    }
    assert encode_params({"flag": True}) == {"flag": "true"}


@respx.mock
def test_get_sends_access_token_and_json_params(client: TikTokAdsClient) -> None:
    route = respx.get(f"{BASE}/campaign/get/").mock(return_value=httpx.Response(200, json=ok()))
    client.request(
        "GET", "/campaign/get/", params={"advertiser_id": ADV, "filtering": {"campaign_ids": ["9"]}}
    )
    sent = route.calls.last.request
    assert sent.headers["Access-Token"] == TOKEN
    assert "Authorization" not in sent.headers
    assert query_of(route.calls.last) == {
        "advertiser_id": ADV,
        "filtering": {"campaign_ids": ["9"]},
    }


@respx.mock
def test_post_sends_json_body(client: TikTokAdsClient) -> None:
    route = respx.post(f"{BASE}/campaign/update/").mock(
        return_value=httpx.Response(200, json=ok({"campaign_id": "1"}))
    )
    out = client.request("POST", "/campaign/update/", json_body={"advertiser_id": ADV, "x": 1})
    assert route.calls.last.request.headers["Content-Type"] == "application/json"
    assert body_of(route.calls.last) == {"advertiser_id": ADV, "x": 1}
    assert out["campaign_id"] == "1"
    assert out["tiktok_request_id"] == "req-1"
    assert out["audit_id"]


def test_resolve_advertiser(client: TikTokAdsClient) -> None:
    assert client.resolve_advertiser(None) == ADV
    assert client.resolve_advertiser("123") == "123"
    with pytest.raises(ValueError, match="numeric"):
        client.resolve_advertiser("abc")
    client.config.advertiser_id = None
    with pytest.raises(ValueError, match="advertiser_id"):
        client.resolve_advertiser(None)


@respx.mock
def test_allowed_advertisers_are_enforced(client: TikTokAdsClient) -> None:
    client.config.allowed_advertiser_ids = [ADV]
    route = respx.get(f"{BASE}/campaign/get/").mock(return_value=httpx.Response(200, json=ok()))
    with pytest.raises(PermissionError, match="ALLOWED"):
        client.resolve_advertiser("999")
    with pytest.raises(PermissionError):
        client.request("GET", "/campaign/get/", params={"advertiser_id": "999"})
    assert not route.called
    client.request("GET", "/campaign/get/", params={"advertiser_id": ADV})
    assert route.called


def test_resolve_bc(client: TikTokAdsClient) -> None:
    assert client.resolve_bc(None) == client.config.bc_id
    client.config.bc_id = None
    with pytest.raises(ValueError, match="bc_id"):
        client.resolve_bc(None)


@pytest.mark.parametrize(
    "path", ["https://evil.example/x", "campaign/get/", "/../x/", "/a/?x=1", "/a\\b"]
)
def test_bad_paths_are_rejected(client: TikTokAdsClient, path: str) -> None:
    with pytest.raises(ValueError):
        client.request("GET", path)


@respx.mock
def test_dry_run_skips_network_and_audits(client: TikTokAdsClient) -> None:
    client.config.dry_run = True
    route = respx.post(f"{BASE}/campaign/update/").mock(return_value=httpx.Response(200, json=ok()))
    out = client.request(
        "POST", "/campaign/update/", json_body={"advertiser_id": ADV, "budget": 5}, op="t"
    )
    assert out["_dry_run"] is True
    assert out["advertiser_id"] == ADV
    assert not route.called
    [entry] = audit_entries(client.audit.path)
    assert entry["dry_run"] is True
    assert entry["request_body"] == {"advertiser_id": ADV, "budget": 5}


@respx.mock
def test_dry_run_still_reads_and_read_only_posts(client: TikTokAdsClient) -> None:
    client.config.dry_run = True
    respx.get(f"{BASE}/campaign/get/").mock(return_value=httpx.Response(200, json=ok({"a": 1})))
    est = respx.post(f"{BASE}/ad/audience_size/estimate/").mock(
        return_value=httpx.Response(200, json=ok({"size": 5}))
    )
    assert client.request("GET", "/campaign/get/") == {"a": 1}
    assert client.request("POST", "/ad/audience_size/estimate/", json_body={}, read_only=True) == {
        "size": 5
    }
    assert est.called
    assert audit_entries(client.audit.path) == []


@respx.mock
def test_write_is_audited_with_before_and_response(client: TikTokAdsClient) -> None:
    respx.post(f"{BASE}/adgroup/update/").mock(
        return_value=httpx.Response(200, json=ok({"adgroup_id": "5"}))
    )
    out = client.request(
        "POST",
        "/adgroup/update/",
        json_body={"advertiser_id": ADV, "adgroup_id": "5", "bid_price": 1},
        op="update_ad_group",
        before={"adgroup_id": "5", "bid_price": 0.5},
    )
    [entry] = audit_entries(client.audit.path)
    assert out["audit_id"] == entry["audit_id"]
    assert entry["op"] == "update_ad_group"
    assert entry["before"] == {"adgroup_id": "5", "bid_price": 0.5}
    assert entry["advertiser_id"] == ADV
    assert entry["response_body"]["data"] == {"adgroup_id": "5"}


@respx.mock
def test_api_error_raises_with_hint_and_audits_writes(client: TikTokAdsClient) -> None:
    respx.post(f"{BASE}/campaign/update/").mock(
        return_value=httpx.Response(200, json=ok(code=40105, message="Access token is incorrect"))
    )
    with pytest.raises(TikTokAdsAPIError) as exc_info:
        client.request("POST", "/campaign/update/", json_body={"advertiser_id": ADV})
    assert exc_info.value.code == 40105
    assert "tiktok-ads-mcp auth" in str(exc_info.value)
    assert "req-1" in str(exc_info.value)
    [entry] = audit_entries(client.audit.path)
    assert entry["error"] == "code 40105"


@respx.mock
def test_error_messages_are_redacted(client: TikTokAdsClient) -> None:
    respx.get(f"{BASE}/x/").mock(
        return_value=httpx.Response(200, json=ok(code=40002, message=f"bad token {TOKEN}"))
    )
    from tiktok_ads_mcp.auth import register_secret

    register_secret(TOKEN)
    with pytest.raises(TikTokAdsAPIError) as exc_info:
        client.request("GET", "/x/")
    assert TOKEN not in str(exc_info.value)


@respx.mock
def test_throttle_code_is_retried_even_for_writes(
    client: TikTokAdsClient, _no_sleep: list[float]
) -> None:
    route = respx.post(f"{BASE}/campaign/update/").mock(
        side_effect=[
            httpx.Response(200, json=ok(code=40100, message="Requests made too frequently")),
            httpx.Response(200, json=ok({"campaign_id": "1"})),
        ]
    )
    out = client.request("POST", "/campaign/update/", json_body={"advertiser_id": ADV})
    assert out["campaign_id"] == "1"
    assert route.call_count == 2
    assert _no_sleep  # backed off


@respx.mock
def test_server_error_code_retried_for_reads_only(client: TikTokAdsClient) -> None:
    read = respx.get(f"{BASE}/campaign/get/").mock(
        side_effect=[httpx.Response(200, json=ok(code=50000)), httpx.Response(200, json=ok())]
    )
    client.request("GET", "/campaign/get/")
    assert read.call_count == 2
    write = respx.post(f"{BASE}/campaign/update/").mock(
        return_value=httpx.Response(200, json=ok(code=50000, message="System error"))
    )
    with pytest.raises(TikTokAdsAPIError):
        client.request("POST", "/campaign/update/", json_body={})
    assert write.call_count == 1


@respx.mock
def test_http_5xx_not_retried_for_writes_but_429_is(client: TikTokAdsClient) -> None:
    write = respx.post(f"{BASE}/a/").mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(TikTokAdsAPIError):
        client.request("POST", "/a/", json_body={})
    assert write.call_count == 1
    throttled = respx.post(f"{BASE}/b/").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(200, json=ok()),
        ]
    )
    client.request("POST", "/b/", json_body={})
    assert throttled.call_count == 2


@respx.mock
def test_transport_error_on_write_is_not_resent(client: TikTokAdsClient) -> None:
    route = respx.post(f"{BASE}/a/").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(httpx.ConnectError):
        client.request("POST", "/a/", json_body={})
    assert route.call_count == 1


@respx.mock
def test_partial_success_is_returned_with_flag(client: TikTokAdsClient) -> None:
    respx.post(f"{BASE}/a/").mock(
        return_value=httpx.Response(200, json=ok({"ids": [1]}, code=20001, message="partly"))
    )
    out = client.request("POST", "/a/", json_body={})
    assert out["partial_success"] is True
    assert out["message"] == "partly"


@respx.mock
def test_paginate_follows_pages_and_truncates(client: TikTokAdsClient) -> None:
    route = respx.get(f"{BASE}/campaign/get/").mock(
        side_effect=[
            httpx.Response(200, json=page([{"id": 1}, {"id": 2}], page_no=1, total_page=3)),
            httpx.Response(200, json=page([{"id": 3}, {"id": 4}], page_no=2, total_page=3)),
        ]
    )
    items, truncated, _ = client.paginate("/campaign/get/", {"advertiser_id": ADV}, max_results=3)
    assert [i["id"] for i in items] == [1, 2, 3]
    assert truncated is True
    assert query_of(route.calls[1])["page"] == "2"


@respx.mock
def test_paginate_stops_at_last_page(client: TikTokAdsClient) -> None:
    respx.get(f"{BASE}/x/").mock(return_value=httpx.Response(200, json=page([{"id": 1}])))
    items, truncated, info = client.paginate("/x/", {}, max_results=50)
    assert items == [{"id": 1}]
    assert truncated is False
    assert info["total_page"] == 1


@respx.mock
def test_download_report_csv_stream(client: TikTokAdsClient) -> None:
    respx.get(f"{BASE}/report/task/download/").mock(
        return_value=httpx.Response(
            200,
            content="﻿Campaign ID,Cost\n1,2.5\n2,3\n".encode(),
            headers={"Content-Type": "text/csv"},
        )
    )
    rows = client.download_report_task(ADV, "t1")
    assert rows == [{"Campaign ID": "1", "Cost": "2.5"}, {"Campaign ID": "2", "Cost": "3"}]


@respx.mock
def test_download_report_via_tiktok_url(client: TikTokAdsClient) -> None:
    respx.get(f"{BASE}/report/task/download/").mock(
        return_value=httpx.Response(
            200, json=ok({"download_url": "https://ads.tiktok.com/wsos_v2/x?sign=s"})
        )
    )
    file_route = respx.get("https://ads.tiktok.com/wsos_v2/x").mock(
        return_value=httpx.Response(200, content=b"a,b\n1,2\n")
    )
    assert client.download_report_task(ADV, "t1") == [{"a": "1", "b": "2"}]
    assert "Access-Token" not in file_route.calls.last.request.headers


@respx.mock
def test_download_refuses_other_hosts(client: TikTokAdsClient) -> None:
    respx.get(f"{BASE}/report/task/download/").mock(
        return_value=httpx.Response(200, json=ok({"download_url": "https://evil.example/r.csv"}))
    )
    with pytest.raises(ValueError, match="non-TikTok host"):
        client.download_report_task(ADV, "t1")


@respx.mock
def test_download_size_is_capped(client: TikTokAdsClient) -> None:
    client.config.max_download_mb = 1
    respx.get(f"{BASE}/report/task/download/").mock(
        return_value=httpx.Response(200, content=b"x" * (1024 * 1024 + 10))
    )
    with pytest.raises(ValueError, match="TIKTOK_ADS_MAX_DOWNLOAD_MB"):
        client.download_report_task(ADV, "t1")


def test_rate_limiter_spaces_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    from tiktok_ads_mcp import client as client_mod

    slept: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: slept.append(s))
    clock = iter([100.0, 100.0, 100.0])
    monkeypatch.setattr(client_mod.time, "monotonic", lambda: next(clock))
    limiter = client_mod._RateLimiter(10)
    limiter.wait()
    limiter.wait()
    limiter.wait()
    assert slept == pytest.approx([0.1, 0.2])
