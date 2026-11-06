"""Performance reports.

Two ways in: the synchronous integrated report (`/report/integrated/get/`,
paged, best for small queries) and asynchronous report tasks
(`/report/task/create/` -> `/check/` -> `/download/`, for big ones; TikTok
allows 60 task creations a minute). Rows are parsed in memory and returned;
they are never written to disk or the audit log.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from mcp.server.mcpserver import Context

from ..client import TikTokAdsClient
from ._common import check_ids
from ._progress import report, run_blocking

REPORT_TYPES = ("BASIC", "AUDIENCE", "PLAYABLE_MATERIAL", "CATALOG", "BC")
DATA_LEVELS = ("AUCTION_ADVERTISER", "AUCTION_CAMPAIGN", "AUCTION_ADGROUP", "AUCTION_AD")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

EXAMPLES = """\
Common BASIC report set-ups (data_level -> dimensions):
  AUCTION_CAMPAIGN -> ["campaign_id"] or ["campaign_id", "stat_time_day"]
  AUCTION_ADGROUP  -> ["adgroup_id"];  AUCTION_AD -> ["ad_id"]
  AUCTION_ADVERTISER -> ["advertiser_id", "stat_time_day"]
AUDIENCE reports break down by e.g. ["campaign_id", "age", "gender"] or
["adgroup_id", "country_code"].
Typical metrics: spend, impressions, clicks, ctr, cpc, cpm, reach, frequency,
conversion, cost_per_conversion, conversion_rate, result, cost_per_result,
complete_payment_roas, total_purchase_value, video_play_actions,
video_views_p100, campaign_name, adgroup_name, ad_name, currency.
Dates are YYYY-MM-DD in the ad account's time zone (up to 30 days per daily
query); query_lifetime=true ignores them. filtering e.g.
[{"field_name": "campaign_ids", "filter_type": "IN", "filter_value": "[\\"123\\"]"}].
If TikTok rejects a dimension/metric pair, its error names the problem."""


def _params(
    *,
    client: TikTokAdsClient,
    report_type: str,
    data_level: str | None,
    dimensions: list[str],
    metrics: list[str] | None,
    start_date: str | None,
    end_date: str | None,
    query_lifetime: bool,
    filtering: list[dict[str, Any]] | None,
    order_field: str | None,
    order_type: str | None,
    advertiser_id: str | None,
    advertiser_ids: list[str] | None,
    bc_id: str | None,
) -> dict[str, Any]:
    rtype = report_type.strip().upper()
    if rtype not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {', '.join(REPORT_TYPES)}.")
    if not dimensions:
        raise ValueError("Pass at least one dimension, e.g. ['campaign_id'].")
    params: dict[str, Any] = {"report_type": rtype, "dimensions": dimensions}
    if rtype == "BC":
        params["bc_id"] = client.resolve_bc(bc_id)
    elif advertiser_ids:
        ids = check_ids(advertiser_ids, "advertiser_ids", 5)
        for aid in ids:
            client.resolve_advertiser(aid)
        params["advertiser_ids"] = ids
    else:
        params["advertiser_id"] = client.resolve_advertiser(advertiser_id)
    if rtype in {"BASIC", "AUDIENCE", "CATALOG"}:
        level = (data_level or "AUCTION_CAMPAIGN").strip().upper()
        if level not in DATA_LEVELS:
            raise ValueError(f"data_level must be one of {', '.join(DATA_LEVELS)}.")
        params["data_level"] = level
    if metrics:
        params["metrics"] = metrics
    if query_lifetime:
        params["query_lifetime"] = True
    else:
        if not (start_date and end_date):
            raise ValueError("Pass start_date and end_date (YYYY-MM-DD), or query_lifetime=true.")
        if not (_DATE.match(start_date) and _DATE.match(end_date)):
            raise ValueError("Dates must be YYYY-MM-DD.")
        params["start_date"] = start_date
        params["end_date"] = end_date
    if filtering:
        params["filtering"] = filtering
    if order_field:
        params["order_field"] = order_field
        params["order_type"] = (order_type or "DESC").upper()
    return params


def _flatten(row: Any) -> Any:
    """Turn {"dimensions": {...}, "metrics": {...}} into one flat dict."""
    if isinstance(row, dict) and ("dimensions" in row or "metrics" in row):
        return {**(row.get("dimensions") or {}), **(row.get("metrics") or {})}
    return row


def register(mcp, client: TikTokAdsClient) -> None:
    def create_task(params: dict[str, Any]) -> dict[str, Any]:
        data = client.request("POST", "/report/task/create/", json_body=params, read_only=True)
        return data if isinstance(data, dict) else {"result": data}

    def task_status(advertiser_id: str, task_id: str) -> dict[str, Any]:
        data = client.request(
            "GET",
            "/report/task/check/",
            params={"advertiser_id": advertiser_id, "task_id": task_id},
        )
        return data if isinstance(data, dict) else {"result": data}

    def rows_payload(advertiser_id: str, task_id: str, max_rows: int) -> dict[str, Any]:
        rows = client.download_report_task(advertiser_id, task_id)
        return {
            "task_id": task_id,
            "status": "SUCCESS",
            "row_count": len(rows),
            "rows": rows[: max(0, max_rows)],
            "truncated": len(rows) > max_rows,
        }

    @mcp.tool(
        description=(
            "Run a report and get its rows straight away (synchronous integrated report). "
            "Best for up to a few thousand rows; for bigger ones use tiktok_ads_run_report.\n\n"
            "report_type BASIC (default), AUDIENCE, PLAYABLE_MATERIAL, CATALOG or BC "
            "(Business Center, needs bc_id). advertiser_ids (up to 5) reports across ad "
            "accounts. Rows are flattened to {dimension..., metric...}; total_metrics needs "
            "enable_total_metrics=true.\n\n" + EXAMPLES
        )
    )
    def tiktok_ads_get_report(
        dimensions: list[str],
        metrics: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        data_level: str | None = "AUCTION_CAMPAIGN",
        report_type: str = "BASIC",
        query_lifetime: bool = False,
        filtering: list[dict[str, Any]] | None = None,
        order_field: str | None = None,
        order_type: str | None = None,
        enable_total_metrics: bool = False,
        advertiser_id: str | None = None,
        advertiser_ids: list[str] | None = None,
        bc_id: str | None = None,
        max_rows: int = 1000,
    ) -> dict[str, Any]:
        params = _params(
            client=client,
            report_type=report_type,
            data_level=data_level,
            dimensions=dimensions,
            metrics=metrics,
            start_date=start_date,
            end_date=end_date,
            query_lifetime=query_lifetime,
            filtering=filtering,
            order_field=order_field,
            order_type=order_type,
            advertiser_id=advertiser_id,
            advertiser_ids=advertiser_ids,
            bc_id=bc_id,
        )
        if enable_total_metrics:
            params["enable_total_metrics"] = True
        rows: list[Any] = []
        page = 1
        total_metrics = None
        page_info: dict[str, Any] = {}
        size = max(1, min(1000, max_rows, client.config.page_size))
        while True:
            data = client.request(
                "GET", "/report/integrated/get/", params={**params, "page": page, "page_size": size}
            )
            data = data if isinstance(data, dict) else {}
            batch = data.get("list") or []
            page_info = data.get("page_info") or {}
            if total_metrics is None and data.get("total_metrics"):
                total_metrics = data.get("total_metrics")
            rows.extend(_flatten(r) for r in batch)
            total_page = page_info.get("total_page")
            done = not batch or not isinstance(total_page, int) or page >= total_page
            if done or len(rows) >= max_rows:
                break
            page += 1
        return {
            "row_count": len(rows[:max_rows]),
            "total_rows": page_info.get("total_number"),
            "truncated": len(rows) > max_rows or not done,
            "rows": rows[:max_rows],
            "total_metrics": total_metrics,
        }

    @mcp.tool(
        description=(
            "Start an asynchronous report task for large reports. Poll "
            "tiktok_ads_get_report_task until SUCCESS, then call "
            "tiktok_ads_download_report_task (or use tiktok_ads_run_report for all three). "
            "Same arguments as tiktok_ads_get_report, without paging. TikTok allows about 60 "
            "task creations a minute per app.\n\n" + EXAMPLES
        )
    )
    def tiktok_ads_create_report_task(
        dimensions: list[str],
        metrics: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        data_level: str | None = "AUCTION_CAMPAIGN",
        report_type: str = "BASIC",
        query_lifetime: bool = False,
        filtering: list[dict[str, Any]] | None = None,
        order_field: str | None = None,
        order_type: str | None = None,
        advertiser_id: str | None = None,
    ) -> dict[str, Any]:
        params = _params(
            client=client,
            report_type=report_type,
            data_level=data_level,
            dimensions=dimensions,
            metrics=metrics,
            start_date=start_date,
            end_date=end_date,
            query_lifetime=query_lifetime,
            filtering=filtering,
            order_field=order_field,
            order_type=order_type,
            advertiser_id=advertiser_id,
            advertiser_ids=None,
            bc_id=None,
        )
        return {**create_task(params), "advertiser_id": params.get("advertiser_id")}

    @mcp.tool()
    def tiktok_ads_get_report_task(
        task_id: str, advertiser_id: str | None = None
    ) -> dict[str, Any]:
        """Check an asynchronous report task: QUEUING, PROCESSING, SUCCESS, FAILED or CANCELED.

        When SUCCESS, call tiktok_ads_download_report_task.
        """
        aid = client.resolve_advertiser(advertiser_id)
        return {"task_id": task_id, **task_status(aid, task_id)}

    @mcp.tool()
    def tiktok_ads_download_report_task(
        task_id: str, max_rows: int = 1000, advertiser_id: str | None = None
    ) -> dict[str, Any]:
        """Download a finished report task and return its rows (up to max_rows).

        Rows are held in memory only. row_count is the full count; truncated says
        whether rows were cut to max_rows. Files over TIKTOK_ADS_MAX_DOWNLOAD_MB are
        refused.
        """
        aid = client.resolve_advertiser(advertiser_id)
        status = task_status(aid, task_id)
        if status.get("status") != "SUCCESS":
            return {
                "task_id": task_id,
                "status": status.get("status"),
                "message": status.get("message")
                or "Report isn't ready; check again with tiktok_ads_get_report_task.",
            }
        return rows_payload(aid, task_id, max_rows)

    @mcp.tool(
        description=(
            "Run a report end to end: start an asynchronous report task, wait for it with "
            "progress updates, then download and return its rows. Same arguments as "
            "tiktok_ads_create_report_task, plus max_rows (default 1000), timeout_seconds "
            "(default 600) and poll_seconds (default 10). If it times out the task_id is "
            "returned so you can check later with tiktok_ads_get_report_task.\n\n" + EXAMPLES
        )
    )
    async def tiktok_ads_run_report(
        dimensions: list[str],
        metrics: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        data_level: str | None = "AUCTION_CAMPAIGN",
        report_type: str = "BASIC",
        query_lifetime: bool = False,
        filtering: list[dict[str, Any]] | None = None,
        order_field: str | None = None,
        order_type: str | None = None,
        max_rows: int = 1000,
        timeout_seconds: float = 600,
        poll_seconds: float = 10,
        advertiser_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        params = _params(
            client=client,
            report_type=report_type,
            data_level=data_level,
            dimensions=dimensions,
            metrics=metrics,
            start_date=start_date,
            end_date=end_date,
            query_lifetime=query_lifetime,
            filtering=filtering,
            order_field=order_field,
            order_type=order_type,
            advertiser_id=advertiser_id,
            advertiser_ids=None,
            bc_id=None,
        )
        aid = str(params.get("advertiser_id"))
        created = await run_blocking(create_task, params)
        task_id = created.get("task_id")
        if not task_id:
            raise RuntimeError(f"No task_id in TikTok's response: {created}")
        # Total time is unknown, so progress counts steps with no total.
        step = 1
        await report(ctx, step, None, f"Started report task {task_id}")
        deadline = time.monotonic() + timeout_seconds
        while True:
            status = await run_blocking(task_status, aid, task_id)
            state = status.get("status")
            step += 1
            if state == "SUCCESS":
                await report(ctx, step, None, "Report ready; downloading")
                payload = await run_blocking(rows_payload, aid, task_id, max_rows)
                await report(ctx, step + 1, None, f"Downloaded {payload['row_count']} rows")
                return payload
            if state in {"FAILED", "CANCELED"}:
                return {"task_id": task_id, "status": state, "message": status.get("message")}
            if time.monotonic() >= deadline:
                return {
                    "task_id": task_id,
                    "status": state,
                    "message": "Still running. Check later with tiktok_ads_get_report_task.",
                }
            await report(ctx, step, None, f"Report {state}; waiting")
            await asyncio.sleep(max(0.0, poll_seconds))
