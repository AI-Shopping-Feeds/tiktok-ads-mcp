"""Reports: synchronous pages, async tasks, the run_report flow with progress."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import httpx
import pytest
import respx
from mcp import Client

from tiktok_ads_mcp import server
from tiktok_ads_mcp.config import Config

from .conftest import ADV, BASE, FakeAuth, audit_entries, body_of, ok, query_of


@pytest.fixture(autouse=True)
def _fake_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "load_auth", lambda config: FakeAuth())


@pytest.fixture(autouse=True)
def _no_async_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr("tiktok_ads_mcp.tools.reporting.asyncio.sleep", instant)


async def call(config: Config, name: str, args: dict[str, Any], progress: list | None = None):
    mcp = server.build_server(dataclasses.replace(config))

    async def on_progress(done: float, total: float | None, message: str | None) -> None:
        if progress is not None:
            progress.append((done, message))

    async with Client(mcp) as c:
        result = await c.call_tool(name, args, progress_callback=on_progress)
    text = " ".join(getattr(block, "text", "") for block in result.content)
    if result.is_error:
        return {"_error": text}
    return result.structured_content or json.loads(text)


def sync_page(rows: list[dict[str, Any]], page_no: int, total_page: int) -> httpx.Response:
    return httpx.Response(
        200,
        json=ok(
            {
                "list": rows,
                "page_info": {"page": page_no, "total_page": total_page, "total_number": 3},
                "total_metrics": {"spend": "9.0"},
            }
        ),
    )


@respx.mock
async def test_get_report_pages_and_flattens(config: Config) -> None:
    route = respx.get(f"{BASE}/report/integrated/get/").mock(
        side_effect=[
            sync_page(
                [
                    {"dimensions": {"campaign_id": "1"}, "metrics": {"spend": "1"}},
                    {"dimensions": {"campaign_id": "2"}, "metrics": {"spend": "2"}},
                ],
                1,
                2,
            ),
            sync_page([{"dimensions": {"campaign_id": "3"}, "metrics": {"spend": "6"}}], 2, 2),
        ]
    )
    out = await call(
        config,
        "tiktok_ads_get_report",
        {
            "dimensions": ["campaign_id"],
            "metrics": ["spend"],
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
            "enable_total_metrics": True,
        },
    )
    assert out["rows"] == [
        {"campaign_id": "1", "spend": "1"},
        {"campaign_id": "2", "spend": "2"},
        {"campaign_id": "3", "spend": "6"},
    ]
    assert out["truncated"] is False
    assert out["total_metrics"] == {"spend": "9.0"}
    q = query_of(route.calls[0])
    assert q["report_type"] == "BASIC"
    assert q["data_level"] == "AUCTION_CAMPAIGN"
    assert q["advertiser_id"] == ADV
    assert q["dimensions"] == ["campaign_id"]


@pytest.mark.parametrize(
    ("args", "match"),
    [
        ({"dimensions": ["campaign_id"]}, "start_date"),
        ({"dimensions": ["campaign_id"], "start_date": "1/10/26", "end_date": "x"}, "YYYY-MM-DD"),
        ({"dimensions": [], "query_lifetime": True}, "dimension"),
        ({"dimensions": ["a"], "query_lifetime": True, "report_type": "NOPE"}, "report_type"),
        ({"dimensions": ["a"], "query_lifetime": True, "data_level": "AD"}, "data_level"),
    ],
)
async def test_report_arguments_are_checked(config: Config, args: dict, match: str) -> None:
    out = await call(config, "tiktok_ads_get_report", args)
    assert match in out["_error"]


@respx.mock
async def test_run_report_polls_and_returns_rows_with_progress(config: Config) -> None:
    create = respx.post(f"{BASE}/report/task/create/").mock(
        return_value=httpx.Response(200, json=ok({"task_id": "T1"}))
    )
    respx.get(f"{BASE}/report/task/check/").mock(
        side_effect=[
            httpx.Response(200, json=ok({"status": "QUEUING"})),
            httpx.Response(200, json=ok({"status": "PROCESSING"})),
            httpx.Response(200, json=ok({"status": "SUCCESS"})),
            httpx.Response(200, json=ok({"status": "SUCCESS"})),
        ]
    )
    respx.get(f"{BASE}/report/task/download/").mock(
        return_value=httpx.Response(200, content=b"Campaign ID,Cost\n1,2\n3,4\n")
    )
    progress: list = []
    out = await call(
        config,
        "tiktok_ads_run_report",
        {
            "dimensions": ["campaign_id"],
            "metrics": ["spend"],
            "query_lifetime": True,
            "max_rows": 1,
        },
        progress,
    )
    assert out["task_id"] == "T1"
    assert out["row_count"] == 2
    assert out["rows"] == [{"Campaign ID": "1", "Cost": "2"}]
    assert out["truncated"] is True
    assert body_of(create.calls.last)["query_lifetime"] is True
    steps = [p[0] for p in progress]
    assert steps == sorted(steps) and len(steps) >= 3
    assert audit_entries(config.audit_log) == []  # report tasks aren't writes


@respx.mock
async def test_run_report_returns_failure(config: Config) -> None:
    respx.post(f"{BASE}/report/task/create/").mock(
        return_value=httpx.Response(200, json=ok({"task_id": "T2"}))
    )
    respx.get(f"{BASE}/report/task/check/").mock(
        return_value=httpx.Response(200, json=ok({"status": "FAILED", "message": "bad metric"}))
    )
    out = await call(
        config, "tiktok_ads_run_report", {"dimensions": ["campaign_id"], "query_lifetime": True}
    )
    assert out == {"task_id": "T2", "status": "FAILED", "message": "bad metric"}


@respx.mock
async def test_run_report_times_out_with_task_id(config: Config) -> None:
    respx.post(f"{BASE}/report/task/create/").mock(
        return_value=httpx.Response(200, json=ok({"task_id": "T3"}))
    )
    respx.get(f"{BASE}/report/task/check/").mock(
        return_value=httpx.Response(200, json=ok({"status": "PROCESSING"}))
    )
    out = await call(
        config,
        "tiktok_ads_run_report",
        {"dimensions": ["campaign_id"], "query_lifetime": True, "timeout_seconds": 0},
    )
    assert out["task_id"] == "T3"
    assert out["status"] == "PROCESSING"


@respx.mock
async def test_download_task_not_ready(config: Config) -> None:
    respx.get(f"{BASE}/report/task/check/").mock(
        return_value=httpx.Response(200, json=ok({"status": "QUEUING"}))
    )
    download = respx.get(f"{BASE}/report/task/download/")
    out = await call(config, "tiktok_ads_download_report_task", {"task_id": "T4"})
    assert out["status"] == "QUEUING"
    assert not download.called
