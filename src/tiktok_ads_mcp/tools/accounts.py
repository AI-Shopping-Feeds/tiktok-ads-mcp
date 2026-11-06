"""Ad accounts (advertisers) and Business Centers the access token can reach."""

from __future__ import annotations

from typing import Any

from ..client import TikTokAdsClient
from ._common import check_ids

BC_ASSET_TYPES = (
    "ADVERTISER",
    "CATALOG",
    "PIXEL",
    "TIKTOK_ACCOUNT",
    "LEAD",
    "COMMON_AUDIENCE",
)


def list_authorized_advertisers(client: TikTokAdsClient) -> list[dict[str, Any]]:
    """Advertisers the access token can manage (needs the app ID and secret)."""
    config = client.config
    if not config.app_id or not config.app_secret:
        raise ValueError(
            "Listing authorised advertisers needs TIKTOK_ADS_APP_ID and TIKTOK_ADS_APP_SECRET "
            "(My Apps -> your app -> Basic Information)."
        )
    data = client.request(
        "GET",
        "/oauth2/advertiser/get/",
        params={"app_id": config.app_id, "secret": config.app_secret},
    )
    items = data.get("list") if isinstance(data, dict) else None
    return [i for i in (items or []) if isinstance(i, dict)]


def register(mcp, client: TikTokAdsClient) -> None:
    @mcp.tool()
    def tiktok_ads_list_advertisers() -> dict[str, Any]:
        """List the ad accounts (advertiser IDs and names) this access token can manage.

        Use an advertiser_id from here in the other tools, or set
        TIKTOK_ADS_ADVERTISER_ID as the default.
        """
        items = list_authorized_advertisers(client)
        allowed = client.config.allowed_advertiser_ids
        return {
            "count": len(items),
            "default_advertiser_id": client.config.advertiser_id,
            "allowed_advertiser_ids": allowed or "all",
            "advertisers": items,
        }

    @mcp.tool()
    def tiktok_ads_get_advertiser_info(
        advertiser_ids: list[str] | None = None, fields: list[str] | None = None
    ) -> dict[str, Any]:
        """Get ad account details: name, status, currency, time zone, balance, company, country.

        advertiser_ids defaults to the default advertiser. Budgets and bids are in
        the account currency; report dates use the account time zone.
        """
        ids = (
            check_ids(advertiser_ids, "advertiser_ids", 100)
            if advertiser_ids
            else [client.resolve_advertiser(None)]
        )
        for aid in ids:
            client.resolve_advertiser(aid)
        params: dict[str, Any] = {"advertiser_ids": ids}
        if fields:
            params["fields"] = fields
        data = client.request("GET", "/advertiser/info/", params=params)
        items = data.get("list") if isinstance(data, dict) else None
        return {"count": len(items or []), "advertisers": items or []}

    @mcp.tool()
    def tiktok_ads_list_business_centers(
        bc_id: str | None = None, max_results: int = 100
    ) -> dict[str, Any]:
        """List the Business Centers the token's user belongs to (IDs, names, role, type)."""
        params: dict[str, Any] = {}
        if bc_id:
            params["bc_id"] = check_ids([bc_id], "bc_id", 1)[0]
        items, truncated, _ = client.paginate(
            "/bc/get/", params, max_results=max_results, max_page_size=50
        )
        return {"count": len(items), "truncated": truncated, "business_centers": items}

    @mcp.tool()
    def tiktok_ads_list_bc_assets(
        asset_type: str,
        bc_id: str | None = None,
        filtering: dict[str, Any] | None = None,
        max_results: int = 200,
    ) -> dict[str, Any]:
        """List assets in a Business Center: ADVERTISER (ad accounts), CATALOG, PIXEL,
        TIKTOK_ACCOUNT, LEAD or COMMON_AUDIENCE.

        bc_id defaults to TIKTOK_ADS_BC_ID. filtering e.g. {"keyword": "shop"}.
        """
        kind = asset_type.strip().upper()
        if kind not in BC_ASSET_TYPES:
            raise ValueError(f"asset_type must be one of {', '.join(BC_ASSET_TYPES)}.")
        params: dict[str, Any] = {"bc_id": client.resolve_bc(bc_id), "asset_type": kind}
        if filtering:
            params["filtering"] = filtering
        items, truncated, _ = client.paginate(
            "/bc/asset/get/", params, max_results=max_results, max_page_size=50
        )
        return {"count": len(items), "truncated": truncated, "assets": items}
