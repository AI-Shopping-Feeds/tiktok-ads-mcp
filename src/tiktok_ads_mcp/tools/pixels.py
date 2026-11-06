"""Pixels and their event statistics (read only).

Sending events (Events API) is out of scope: it carries end-user data under
TikTok's Business Products (Data) Terms and belongs in your site or server.
"""

from __future__ import annotations

from typing import Any

from ..client import TikTokAdsClient
from ._common import check_ids


def register(mcp, client: TikTokAdsClient) -> None:
    @mcp.tool()
    def tiktok_ads_list_pixels(
        pixel_id: str | None = None,
        code: str | None = None,
        name: str | None = None,
        advertiser_id: str | None = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """List pixels in the ad account with their code, events and setup status."""
        aid = client.resolve_advertiser(advertiser_id)
        params: dict[str, Any] = {"advertiser_id": aid}
        if pixel_id:
            params["pixel_id"] = check_ids([pixel_id], "pixel_id", 1)[0]
        if code:
            params["code"] = code
        if name:
            params["name"] = name
        items, truncated, _ = client.paginate(
            "/pixel/list/", params, max_results=max_results, max_page_size=20, items_key="pixels"
        )
        return {"count": len(items), "truncated": truncated, "pixels": items}

    @mcp.tool()
    def tiktok_ads_get_pixel_event_stats(
        pixel_ids: list[str],
        start_date: str,
        end_date: str,
        advertiser_id: str | None = None,
    ) -> dict[str, Any]:
        """Count events each pixel received per event type between two dates (YYYY-MM-DD).

        Useful to check a pixel fires before optimising for its events.
        """
        aid = client.resolve_advertiser(advertiser_id)
        data = client.request(
            "GET",
            "/pixel/event/stats/",
            params={
                "advertiser_id": aid,
                "pixel_ids": check_ids(pixel_ids, "pixel_ids", 20),
                "date_range": {"start_date": start_date, "end_date": end_date},
            },
        )
        return data if isinstance(data, dict) else {"result": data}
