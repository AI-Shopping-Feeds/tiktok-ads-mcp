"""Custom and lookalike audiences (`/dmp/custom_audience/...`).

Customer-file audiences (hashed contact lists) are left to the escape hatch on
purpose: uploading contact details is governed by TikTok's Custom Audience
(Customer File) Terms and needs care this server doesn't automate.
"""

from __future__ import annotations

from typing import Any

from .. import safety
from ..client import TikTokAdsClient
from ._common import check_ids


def register(mcp, client: TikTokAdsClient) -> None:
    def fetch(aid: str, ids: list[str]) -> list[dict[str, Any]]:
        data = client.request(
            "GET",
            "/dmp/custom_audience/get/",
            params={"advertiser_id": aid, "custom_audience_ids": ids},
        )
        items = data.get("list") if isinstance(data, dict) else None
        return [i for i in (items or []) if isinstance(i, dict)]

    @mcp.tool()
    def tiktok_ads_list_audiences(
        custom_audience_ids: list[str] | None = None,
        advertiser_id: str | None = None,
        max_results: int = 200,
    ) -> dict[str, Any]:
        """List custom and lookalike audiences: ID, name, type, size, status, expiry."""
        aid = client.resolve_advertiser(advertiser_id)
        params: dict[str, Any] = {"advertiser_id": aid}
        if custom_audience_ids:
            params["custom_audience_ids"] = check_ids(
                custom_audience_ids, "custom_audience_ids", 100
            )
        items, truncated, _ = client.paginate(
            "/dmp/custom_audience/list/", params, max_results=max_results, max_page_size=100
        )
        return {"count": len(items), "truncated": truncated, "audiences": items}

    @mcp.tool()
    def tiktok_ads_get_audiences(
        custom_audience_ids: list[str], advertiser_id: str | None = None
    ) -> dict[str, Any]:
        """Get audience details, including the rule or lookalike spec and recent history."""
        aid = client.resolve_advertiser(advertiser_id)
        items = fetch(aid, check_ids(custom_audience_ids, "custom_audience_ids", 100))
        return {"count": len(items), "audiences": items}

    @mcp.tool()
    def tiktok_ads_create_lookalike_audience(
        custom_audience_name: str,
        lookalike_spec: dict[str, Any],
        advertiser_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a lookalike audience from a source audience. Changes the account.

        lookalike_spec e.g. {"source_audience_id": "...", "location_ids": ["2635167"],
        "audience_size": "NARROW", "placements": ["PLACEMENT_TIKTOK"]}. Returns
        custom_audience_id; TikTok builds it in the background.
        """
        if not isinstance(lookalike_spec, dict) or not lookalike_spec:
            raise ValueError("lookalike_spec must be an object.")
        aid = client.resolve_advertiser(advertiser_id)
        body = {
            "advertiser_id": aid,
            "custom_audience_name": custom_audience_name,
            "lookalike_spec": lookalike_spec,
        }
        return client.request(
            "POST",
            "/dmp/custom_audience/lookalike/create/",
            json_body=body,
            op="create_lookalike_audience",
        )

    @mcp.tool()
    def tiktok_ads_create_rule_audience(
        custom_audience_name: str,
        audience_type: str,
        rule_spec: dict[str, Any],
        audience_sub_type: str | None = None,
        retention_in_days: int | None = None,
        is_auto_refresh: bool | None = None,
        advertiser_id: str | None = None,
    ) -> dict[str, Any]:
        """Create an audience from a rule (engagement, app or website activity, etc.).

        audience_type e.g. ENGAGEMENT, APP, PIXEL (website traffic), LEAD_GENERATION
        or BUSINESS_ACCOUNT. rule_spec holds the inclusion/exclusion rules, e.g.
        {"inclusion_rule_set": {"operation": "OR", "rules": [{"event_source_ids":
        ["<pixel_id>"], "retention_days": 30, "filter_set": {...}}]}}.
        """
        if not isinstance(rule_spec, dict) or not rule_spec:
            raise ValueError("rule_spec must be an object.")
        aid = client.resolve_advertiser(advertiser_id)
        body: dict[str, Any] = {
            "advertiser_id": aid,
            "custom_audience_name": custom_audience_name,
            "audience_type": audience_type.upper(),
            "rule_spec": rule_spec,
        }
        if audience_sub_type:
            body["audience_sub_type"] = audience_sub_type.upper()
        if retention_in_days is not None:
            body["retention_in_days"] = retention_in_days
        if is_auto_refresh is not None:
            body["is_auto_refresh"] = is_auto_refresh
        return client.request(
            "POST", "/dmp/custom_audience/rule/create/", json_body=body, op="create_rule_audience"
        )

    @mcp.tool()
    def tiktok_ads_refresh_lookalike_audiences(
        custom_audience_ids: list[str], advertiser_id: str | None = None
    ) -> dict[str, Any]:
        """Rebuild lookalike audiences from their current source audiences."""
        aid = client.resolve_advertiser(advertiser_id)
        ids = check_ids(custom_audience_ids, "custom_audience_ids", 100)
        return client.request(
            "POST",
            "/dmp/custom_audience/lookalike/update/",
            json_body={"advertiser_id": aid, "custom_audience_ids": ids},
            op="refresh_lookalike_audiences",
        )

    @mcp.tool()
    def tiktok_ads_delete_audiences(
        custom_audience_ids: list[str],
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Delete custom or lookalike audiences. This can't be undone.

        Ad groups using them lose that targeting. Needs confirm='DELETE' after the
        user agrees.
        """
        aid = client.resolve_advertiser(advertiser_id)
        ids = check_ids(custom_audience_ids, "custom_audience_ids", 100)
        decision = safety.assess(client.config, count=len(ids), destructive=safety.DELETE)
        body = {"advertiser_id": aid, "custom_audience_ids": ids}
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        before = client.snapshot(fetch, aid, ids)
        out = client.request(
            "POST",
            "/dmp/custom_audience/delete/",
            json_body=body,
            op="delete_audiences",
            before=before,
        )
        return safety.annotate(out, decision)
