"""Upgraded Smart+ campaigns, ad groups and ads (`/smart_plus/...`).

TikTok's unified creation path for Sales (WEB_CONVERSIONS), App Promotion and
Lead Generation campaigns, replacing Legacy Manual Flow creation for these
objectives from 1 January 2027 (and the legacy Smart+ /campaign/spc/ API,
which stopped creating campaigns after 31 March 2026). Reading and reporting
need no allowlist; TikTok's guide says creating and editing may need the ad
account allowlisted by your TikTok representative.
"""

from __future__ import annotations

from typing import Any

from .. import safety
from ..client import TikTokAdsClient
from ._common import (
    BUDGET_FIELDS,
    SMART_PLUS_LEVELS,
    change_status,
    check_ids,
    delete_entities,
    fetch_by_ids,
    level_for,
    list_entities,
    merge_extra,
    new_request_id,
    update_budgets,
)

SMART_PLUS_OBJECTIVES = ("APP_PROMOTION", "WEB_CONVERSIONS", "LEAD_GENERATION")
SMART_PLUS_BID_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("budget", ("budget",)),
    ("bid", ("bid_price",)),
    ("bid", ("conversion_bid_price",)),
)


def _filtering(base: dict[str, Any] | None, **values: Any) -> dict[str, Any] | None:
    out = dict(base or {})
    for key, value in values.items():
        if value:
            out[key] = value
    return out or None


def _status(enabled: bool) -> str:
    return "ENABLE" if enabled else "DISABLE"


def register(mcp, client: TikTokAdsClient) -> None:
    camp = SMART_PLUS_LEVELS["campaign"]
    adg = SMART_PLUS_LEVELS["ad_group"]
    ad = SMART_PLUS_LEVELS["ad"]

    @mcp.tool()
    def tiktok_ads_smart_plus_list_campaigns(
        advertiser_id: str | None = None,
        campaign_ids: list[str] | None = None,
        objective_type: str | None = None,
        effective_statuses: list[str] | None = None,
        filtering: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        max_results: int = 200,
    ) -> dict[str, Any]:
        """List Upgraded Smart+ campaigns with budget, objective and status.

        effective_statuses e.g. ["ACTIVE", "PAUSED", "NOT_DELIVERED"]. filtering
        adds other /smart_plus/campaign/get/ filters (campaign_name,
        creative_campaign_type, sales_destination).
        """
        return list_entities(
            client,
            camp,
            advertiser_id=advertiser_id,
            filtering=_filtering(
                filtering,
                campaign_ids=campaign_ids and check_ids(campaign_ids, "campaign_ids", 100),
                objective_type=objective_type and objective_type.upper(),
                effective_statuses=effective_statuses,
            ),
            fields=fields,
            max_results=max_results,
        )

    @mcp.tool()
    def tiktok_ads_smart_plus_create_campaign(
        campaign_name: str,
        objective_type: str,
        budget: float | None = None,
        budget_mode: str | None = None,
        budget_optimize_on: bool | None = None,
        is_search_campaign: bool = False,
        enabled: bool = False,
        extra: dict[str, Any] | None = None,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Create an Upgraded Smart+ campaign. Changes the live account.

        objective_type: WEB_CONVERSIONS (Sales to a website or app), APP_PROMOTION
        or LEAD_GENERATION. budget_mode with campaign budget optimisation (the
        default): BUDGET_MODE_DYNAMIC_DAILY_BUDGET or BUDGET_MODE_TOTAL; without it
        (budget_optimize_on=false): BUDGET_MODE_INFINITE, BUDGET_MODE_DAY or
        BUDGET_MODE_TOTAL. Budget mode can't be changed later. extra adds other
        /smart_plus/campaign/create/ fields (e.g. catalog_enabled, catalog_type,
        sales_destination, app_promotion_type). Created paused unless enabled=true
        (needs confirm='APPLY'); a budget over TIKTOK_ADS_MAX_BUDGET needs
        confirm='APPLY'. An idempotent request_id is generated for you.
        """
        objective = objective_type.strip().upper()
        if objective not in SMART_PLUS_OBJECTIVES:
            raise ValueError(
                f"objective_type must be one of {', '.join(SMART_PLUS_OBJECTIVES)} for "
                "Upgraded Smart+; use tiktok_ads_create_campaign for Reach, Traffic, Video "
                "Views and Community Interaction."
            )
        aid = client.resolve_advertiser(advertiser_id)
        body: dict[str, Any] = {
            "advertiser_id": aid,
            "request_id": new_request_id(),
            "campaign_name": campaign_name,
            "objective_type": objective,
            "operation_status": _status(enabled),
        }
        if budget is not None:
            body["budget"] = budget
        if budget_mode:
            body["budget_mode"] = budget_mode.upper()
        if budget_optimize_on is not None:
            body["budget_optimize_on"] = budget_optimize_on
        if is_search_campaign:
            body["is_search_campaign"] = True
        merge_extra(body, extra, protected=("advertiser_id", "objective_type", "operation_status"))
        decision = safety.assess(
            client.config,
            count=1,
            changes=safety.new_values([body], BUDGET_FIELDS),
            creating=True,
            enabling=enabled,
        )
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "POST", "/smart_plus/campaign/create/", json_body=body, op="smart_plus_create_campaign"
        )
        return safety.annotate(out, decision)

    @mcp.tool()
    def tiktok_ads_smart_plus_update_campaign(
        campaign_id: str,
        campaign_name: str | None = None,
        budget: float | None = None,
        extra: dict[str, Any] | None = None,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Update an Upgraded Smart+ campaign's name, budget or other editable fields.

        extra e.g. {"budget_auto_adjust_strategy": "AUTO_BUDGET_INCREASE"}. The
        current campaign is read first and kept in the audit log; budget rises above
        TIKTOK_ADS_MAX_INCREASE_PCT (or an unknown current budget) need
        confirm='APPLY'.
        """
        cid = check_ids([campaign_id], "campaign_id", 1)[0]
        aid = client.resolve_advertiser(advertiser_id)
        body: dict[str, Any] = {"advertiser_id": aid, "campaign_id": cid}
        if campaign_name is not None:
            body["campaign_name"] = campaign_name
        if budget is not None:
            body["budget"] = budget
        merge_extra(body, extra, protected=("advertiser_id", "campaign_id"))
        if len(body) == 2:
            raise ValueError("Nothing to change: pass campaign_name, budget or extra.")
        current = client.snapshot(fetch_by_ids, client, camp, aid, [cid])
        decision = safety.assess(
            client.config,
            count=1,
            changes=safety.money_changes(
                [body], current, id_field="campaign_id", fields=BUDGET_FIELDS
            ),
        )
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "POST",
            "/smart_plus/campaign/update/",
            json_body=body,
            op="smart_plus_update_campaign",
            before=current[0] if current else None,
        )
        return safety.annotate(out, decision)

    @mcp.tool()
    def tiktok_ads_smart_plus_list_ad_groups(
        advertiser_id: str | None = None,
        campaign_ids: list[str] | None = None,
        adgroup_ids: list[str] | None = None,
        effective_statuses: list[str] | None = None,
        filtering: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        max_results: int = 200,
    ) -> dict[str, Any]:
        """List Upgraded Smart+ ad groups with optimisation goal, bid, budget and targeting."""
        return list_entities(
            client,
            adg,
            advertiser_id=advertiser_id,
            filtering=_filtering(
                filtering,
                campaign_ids=campaign_ids and check_ids(campaign_ids, "campaign_ids", 100),
                adgroup_ids=adgroup_ids and check_ids(adgroup_ids, "adgroup_ids", 100),
                effective_statuses=effective_statuses,
            ),
            fields=fields,
            max_results=max_results,
        )

    @mcp.tool()
    def tiktok_ads_smart_plus_create_ad_group(
        campaign_id: str,
        settings: dict[str, Any],
        enabled: bool = False,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Create an Upgraded Smart+ ad group. Changes the live account.

        settings: the /smart_plus/adgroup/create/ fields, e.g. adgroup_name,
        promotion_type, optimization_goal, bid_type, billing_event, targeting_spec
        (locations, ages, audiences), budget_mode and budget (when the campaign
        doesn't use campaign budget optimisation), schedule_type,
        schedule_start_time, pixel_id/optimization_event or app_id. Created paused
        unless enabled=true (needs confirm='APPLY'). Budgets or bids over
        TIKTOK_ADS_MAX_BUDGET / TIKTOK_ADS_MAX_BID need confirm='APPLY'.
        """
        cid = check_ids([campaign_id], "campaign_id", 1)[0]
        if not isinstance(settings, dict) or not settings.get("adgroup_name"):
            raise ValueError("settings must be an object with at least adgroup_name.")
        aid = client.resolve_advertiser(advertiser_id)
        body = merge_extra(
            {
                "advertiser_id": aid,
                "request_id": new_request_id(),
                "campaign_id": cid,
                "operation_status": _status(enabled),
            },
            settings,
            protected=("advertiser_id", "campaign_id", "operation_status"),
        )
        decision = safety.assess(
            client.config,
            count=1,
            changes=safety.new_values([body], SMART_PLUS_BID_FIELDS),
            creating=True,
            enabling=enabled,
        )
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "POST", "/smart_plus/adgroup/create/", json_body=body, op="smart_plus_create_ad_group"
        )
        return safety.annotate(out, decision)

    @mcp.tool()
    def tiktok_ads_smart_plus_update_ad_group(
        adgroup_id: str,
        changes: dict[str, Any],
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Update an Upgraded Smart+ ad group: name, bid, budget, schedule or targeting.

        changes: only the /smart_plus/adgroup/update/ fields to change, e.g.
        {"conversion_bid_price": 12.5} or {"targeting_spec": {...}}. The current ad
        group is read first and kept in the audit log; bid or budget rises above
        TIKTOK_ADS_MAX_INCREASE_PCT (or unknown current values) need confirm='APPLY'.
        """
        gid = check_ids([adgroup_id], "adgroup_id", 1)[0]
        if not isinstance(changes, dict) or not changes:
            raise ValueError("changes must be an object with at least one field.")
        aid = client.resolve_advertiser(advertiser_id)
        body = merge_extra(
            {"advertiser_id": aid, "adgroup_id": gid},
            changes,
            protected=("advertiser_id", "adgroup_id"),
        )
        current = client.snapshot(fetch_by_ids, client, adg, aid, [gid])
        decision = safety.assess(
            client.config,
            count=1,
            changes=safety.money_changes(
                [body], current, id_field="adgroup_id", fields=SMART_PLUS_BID_FIELDS
            ),
        )
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "POST",
            "/smart_plus/adgroup/update/",
            json_body=body,
            op="smart_plus_update_ad_group",
            before=current[0] if current else None,
        )
        return safety.annotate(out, decision)

    @mcp.tool()
    def tiktok_ads_smart_plus_update_ad_group_budgets(
        budgets: list[dict[str, Any]] | None = None,
        scheduled_budgets: list[dict[str, Any]] | None = None,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Change budgets of many Upgraded Smart+ ad groups at once.

        budgets: [{"adgroup_id": "...", "budget": 50}] applied immediately (for ad
        groups in campaign-budget-optimised campaigns pass min_budget/max_budget in
        each item instead). scheduled_budgets: [{"adgroup_id": "...",
        "scheduled_budget": 50}] applied from tomorrow. Rises above
        TIKTOK_ADS_MAX_INCREASE_PCT, unknown current values and more than
        TIKTOK_ADS_BULK_THRESHOLD ad groups need confirm='APPLY'.
        """
        return update_budgets(
            client,
            adg,
            "/smart_plus/adgroup/budget/update/",
            budgets=budgets,
            scheduled_budgets=scheduled_budgets,
            advertiser_id=advertiser_id,
            confirm=confirm,
            op="smart_plus_update_ad_group_budgets",
        )

    @mcp.tool()
    def tiktok_ads_smart_plus_list_ads(
        advertiser_id: str | None = None,
        campaign_ids: list[str] | None = None,
        adgroup_ids: list[str] | None = None,
        smart_plus_ad_ids: list[str] | None = None,
        effective_statuses: list[str] | None = None,
        filtering: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """List Upgraded Smart+ ads with their creative, text, CTA and landing page lists."""
        return list_entities(
            client,
            ad,
            advertiser_id=advertiser_id,
            filtering=_filtering(
                filtering,
                campaign_ids=campaign_ids and check_ids(campaign_ids, "campaign_ids", 100),
                adgroup_ids=adgroup_ids and check_ids(adgroup_ids, "adgroup_ids", 100),
                smart_plus_ad_ids=smart_plus_ad_ids
                and check_ids(smart_plus_ad_ids, "smart_plus_ad_ids", 100),
                effective_statuses=effective_statuses,
            ),
            fields=fields,
            max_results=max_results,
        )

    @mcp.tool()
    def tiktok_ads_smart_plus_create_ad(
        adgroup_id: str,
        settings: dict[str, Any],
        enabled: bool = False,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Create an Upgraded Smart+ ad (one ad with many creatives). Changes the live account.

        settings: the /smart_plus/ad/create/ fields, e.g. ad_name, creative_list
        (videos/images by ID with identity), ad_text_list, call_to_action_list,
        landing_page_url_list, ad_configuration. Upload media first. Created paused
        unless enabled=true (needs confirm='APPLY').
        """
        gid = check_ids([adgroup_id], "adgroup_id", 1)[0]
        if not isinstance(settings, dict) or not settings:
            raise ValueError("settings must be an object with the ad's fields.")
        aid = client.resolve_advertiser(advertiser_id)
        body = merge_extra(
            {"advertiser_id": aid, "adgroup_id": gid, "operation_status": _status(enabled)},
            settings,
            protected=("advertiser_id", "adgroup_id", "operation_status"),
        )
        decision = safety.assess(client.config, count=1, creating=True, enabling=enabled)
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "POST", "/smart_plus/ad/create/", json_body=body, op="smart_plus_create_ad"
        )
        return safety.annotate(out, decision)

    @mcp.tool()
    def tiktok_ads_smart_plus_update_ad(
        smart_plus_ad_id: str,
        changes: dict[str, Any],
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Update an Upgraded Smart+ ad: name, creative_list, ad_text_list, call_to_action_list,
        landing_page_url_list or other /smart_plus/ad/update/ fields.

        Lists you pass replace the ad's current list, so read the ad first
        (tiktok_ads_smart_plus_list_ads) and send the full list you want. The
        current ad is kept in the audit log.
        """
        sid = check_ids([smart_plus_ad_id], "smart_plus_ad_id", 1)[0]
        if not isinstance(changes, dict) or not changes:
            raise ValueError("changes must be an object with at least one field.")
        aid = client.resolve_advertiser(advertiser_id)
        body = merge_extra(
            {"advertiser_id": aid, "smart_plus_ad_id": sid},
            changes,
            protected=("advertiser_id", "smart_plus_ad_id"),
        )
        current = client.snapshot(fetch_by_ids, client, ad, aid, [sid])
        decision = safety.assess(client.config, count=1)
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "POST",
            "/smart_plus/ad/update/",
            json_body=body,
            op="smart_plus_update_ad",
            before=current[0] if current else None,
        )
        return safety.annotate(out, decision)

    @mcp.tool()
    def tiktok_ads_smart_plus_set_status(
        level: str,
        ids: list[str],
        status: str,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Pause or enable Upgraded Smart+ campaigns, ad groups or ads.

        level: campaign, ad_group or ad (ad IDs are smart_plus_ad_id). status:
        DISABLE (pause) or ENABLE. Enabling starts delivery and spend, so it needs
        confirm='APPLY'; so does changing more than TIKTOK_ADS_BULK_THRESHOLD items.
        """
        lvl = level_for(SMART_PLUS_LEVELS, level)
        return change_status(
            client,
            lvl,
            ids=ids,
            status=status,
            advertiser_id=advertiser_id,
            confirm=confirm,
            op=f"smart_plus_set_{lvl.name}_status",
        )

    @mcp.tool()
    def tiktok_ads_smart_plus_delete(
        level: str,
        ids: list[str],
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Delete Upgraded Smart+ campaigns, ad groups or ads. This can't be undone.

        level: campaign, ad_group or ad. Needs confirm='DELETE' after the user
        agrees. Prefer pausing (tiktok_ads_smart_plus_set_status with DISABLE).
        """
        lvl = level_for(SMART_PLUS_LEVELS, level)
        return delete_entities(
            client,
            lvl,
            ids=ids,
            advertiser_id=advertiser_id,
            confirm=confirm,
            op=f"smart_plus_delete_{lvl.name}",
        )

    @mcp.tool()
    def tiktok_ads_smart_plus_set_creative_status(
        smart_plus_ad_id: str,
        ad_material_ids: list[str],
        status: str,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Turn individual creatives inside an Upgraded Smart+ ad off (DISABLE) or on (ENABLE).

        ad_material_ids come from tiktok_ads_smart_plus_list_ads (creative_list).
        Enabling needs confirm='APPLY', as does changing more than
        TIKTOK_ADS_BULK_THRESHOLD creatives.
        """
        sid = check_ids([smart_plus_ad_id], "smart_plus_ad_id", 1)[0]
        mids = check_ids(ad_material_ids, "ad_material_ids", 100)
        status = (status or "").strip().upper()
        if status not in {"ENABLE", "DISABLE"}:
            raise ValueError("status must be ENABLE or DISABLE.")
        aid = client.resolve_advertiser(advertiser_id)
        body = {
            "advertiser_id": aid,
            "smart_plus_ad_id": sid,
            "ad_material_ids": mids,
            "operation_status": status,
        }
        decision = safety.assess(client.config, count=len(mids), enabling=status == "ENABLE")
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        current = client.snapshot(fetch_by_ids, client, ad, aid, [sid])
        out = client.request(
            "POST",
            "/smart_plus/ad/material_status/update/",
            json_body=body,
            op="smart_plus_set_creative_status",
            before=current[0] if current else None,
        )
        return safety.annotate(out, decision)
