"""Campaigns, ad groups and ads on the Campaign Management endpoints.

These read every campaign type (Manual, Smart+ and Upgraded Smart+; see
`campaign_automation_type`) and change existing ones. New campaigns here are
limited to objectives TikTok keeps on this flow after 1 January 2027: Reach,
Traffic, Video Views, Community Interaction (ENGAGEMENT), Reach & Frequency,
and Search campaigns. Sales, App Promotion and Lead Generation go through the
Upgraded Smart+ tools.
"""

from __future__ import annotations

from typing import Any

from .. import safety
from ..client import TikTokAdsClient
from ._common import (
    BUDGET_FIELDS,
    MANUAL_BID_FIELDS,
    MANUAL_LEVELS,
    SUNSET_NOTE,
    SUNSET_OBJECTIVES,
    change_status,
    check_ids,
    check_items,
    delete_entities,
    fetch_by_ids,
    guard_legacy_parent,
    level_for,
    list_entities,
    merge_extra,
    new_request_id,
    update_budgets,
)

MANUAL_CREATE_OBJECTIVES = frozenset({"REACH", "TRAFFIC", "VIDEO_VIEWS", "ENGAGEMENT", "RF_REACH"})
AUTOMATION_TYPES = ("MANUAL", "SMART_PLUS", "UPGRADED_SMART_PLUS")


def _filtering(base: dict[str, Any] | None, **values: Any) -> dict[str, Any] | None:
    out = dict(base or {})
    for key, value in values.items():
        if value:
            out[key] = value
    return out or None


def _status(enabled: bool) -> str:
    return "ENABLE" if enabled else "DISABLE"


def register(mcp, client: TikTokAdsClient) -> None:
    camp = MANUAL_LEVELS["campaign"]
    adg = MANUAL_LEVELS["ad_group"]
    ad = MANUAL_LEVELS["ad"]

    # ---------------------------------------------------------- campaigns

    @mcp.tool()
    def tiktok_ads_list_campaigns(
        advertiser_id: str | None = None,
        campaign_ids: list[str] | None = None,
        automation_type: str | None = None,
        objective_type: str | None = None,
        primary_status: str | None = None,
        name_contains: str | None = None,
        filtering: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        max_results: int = 200,
    ) -> dict[str, Any]:
        """List campaigns of every type (Manual, Smart+ and Upgraded Smart+).

        automation_type: MANUAL, SMART_PLUS or UPGRADED_SMART_PLUS
        (`campaign_automation_type` in each result says which a campaign is).
        primary_status e.g. STATUS_DELIVERY_OK, STATUS_DISABLE, STATUS_ALL (deleted
        campaigns are hidden unless STATUS_ALL). filtering adds any other filter
        /campaign/get/ accepts; fields limits the returned fields.
        """
        if automation_type and automation_type.upper() not in AUTOMATION_TYPES:
            raise ValueError(f"automation_type must be one of {', '.join(AUTOMATION_TYPES)}.")
        return list_entities(
            client,
            camp,
            advertiser_id=advertiser_id,
            filtering=_filtering(
                filtering,
                campaign_ids=campaign_ids and check_ids(campaign_ids, "campaign_ids", 100),
                campaign_automation_type=automation_type and automation_type.upper(),
                objective_type=objective_type and objective_type.upper(),
                primary_status=primary_status,
                campaign_name=name_contains,
            ),
            fields=fields,
            max_results=max_results,
        )

    @mcp.tool()
    def tiktok_ads_create_campaign(
        campaign_name: str,
        objective_type: str,
        budget_mode: str | None = None,
        budget: float | None = None,
        is_search_campaign: bool = False,
        enabled: bool = False,
        extra: dict[str, Any] | None = None,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Create a campaign on the Campaign Management flow. Changes the live account.

        objective_type: REACH, TRAFFIC, VIDEO_VIEWS, ENGAGEMENT (Community
        interaction) or RF_REACH; or APP_PROMOTION, WEB_CONVERSIONS,
        LEAD_GENERATION or PRODUCT_SALES with is_search_campaign=true. Other Sales,
        App Promotion and Lead Generation campaigns must use
        tiktok_ads_smart_plus_create_campaign (TikTok stops creating them here on
        1 January 2027). budget_mode e.g. BUDGET_MODE_DAY,
        BUDGET_MODE_DYNAMIC_DAILY_BUDGET, BUDGET_MODE_TOTAL or BUDGET_MODE_INFINITE.
        The campaign is created paused (DISABLE) unless enabled=true, which needs
        confirm='APPLY'. extra adds other /campaign/create/ fields, e.g.
        {"budget_optimize_on": true}. A budget over TIKTOK_ADS_MAX_BUDGET needs
        confirm='APPLY'. Rehearse with dry-run first.
        """
        objective = objective_type.strip().upper()
        if objective in SUNSET_OBJECTIVES and not is_search_campaign:
            raise ValueError(
                f"{objective} campaigns can't be created on this flow (only Search campaigns "
                "can). " + SUNSET_NOTE
            )
        if objective not in MANUAL_CREATE_OBJECTIVES | SUNSET_OBJECTIVES:
            raise ValueError(
                "objective_type must be REACH, TRAFFIC, VIDEO_VIEWS, ENGAGEMENT or RF_REACH, "
                "or a Search campaign for APP_PROMOTION, WEB_CONVERSIONS, LEAD_GENERATION or "
                "PRODUCT_SALES."
            )
        aid = client.resolve_advertiser(advertiser_id)
        body: dict[str, Any] = {
            "advertiser_id": aid,
            "campaign_name": campaign_name,
            "objective_type": objective,
            "operation_status": _status(enabled),
            "request_id": new_request_id(),
        }
        if budget_mode:
            body["budget_mode"] = budget_mode.upper()
        if budget is not None:
            body["budget"] = budget
        if is_search_campaign:
            body["is_search_campaign"] = True
        merge_extra(
            body,
            extra,
            protected=("advertiser_id", "objective_type", "operation_status", "is_search_campaign"),
        )
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
        out = client.request("POST", "/campaign/create/", json_body=body, op="create_campaign")
        return safety.annotate(out, decision)

    @mcp.tool()
    def tiktok_ads_update_campaign(
        campaign_id: str,
        campaign_name: str | None = None,
        budget: float | None = None,
        extra: dict[str, Any] | None = None,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Update a Manual or Smart+ campaign's name, budget or other editable fields.

        Upgraded Smart+ campaigns are refused here: use
        tiktok_ads_smart_plus_update_campaign. The current campaign is read first
        and kept in the audit log; a budget rise above TIKTOK_ADS_MAX_INCREASE_PCT,
        or one whose current value can't be read, needs confirm='APPLY'. To pause
        or delete, use tiktok_ads_set_status / tiktok_ads_delete.
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
        if current and current[0].get("campaign_automation_type") == "UPGRADED_SMART_PLUS":
            raise ValueError(
                f"Campaign {cid} is an Upgraded Smart+ campaign; use "
                "tiktok_ads_smart_plus_update_campaign."
            )
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
            "/campaign/update/",
            json_body=body,
            op="update_campaign",
            before=current[0] if current else None,
        )
        return safety.annotate(out, decision)

    # ---------------------------------------------------------- ad groups

    @mcp.tool()
    def tiktok_ads_list_ad_groups(
        advertiser_id: str | None = None,
        campaign_ids: list[str] | None = None,
        adgroup_ids: list[str] | None = None,
        primary_status: str | None = None,
        filtering: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        max_results: int = 200,
    ) -> dict[str, Any]:
        """List ad groups (all campaign types) with their budget, bid, schedule and targeting.

        filtering adds any other /adgroup/get/ filter (e.g. adgroup_name,
        objective_type, optimization_goal); fields limits the returned fields.
        """
        return list_entities(
            client,
            adg,
            advertiser_id=advertiser_id,
            filtering=_filtering(
                filtering,
                campaign_ids=campaign_ids and check_ids(campaign_ids, "campaign_ids", 100),
                adgroup_ids=adgroup_ids and check_ids(adgroup_ids, "adgroup_ids", 100),
                primary_status=primary_status,
            ),
            fields=fields,
            max_results=max_results,
        )

    @mcp.tool()
    def tiktok_ads_create_ad_group(
        campaign_id: str,
        settings: dict[str, Any],
        enabled: bool = False,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Create an ad group in a Campaign Management campaign. Changes the live account.

        settings: the /adgroup/create/ fields, e.g. adgroup_name, placement_type,
        placements, location_ids, age_groups, gender, budget_mode, budget,
        schedule_type, schedule_start_time, optimization_goal, bid_type,
        billing_event, pacing. The ad group is created paused unless enabled=true
        (needs confirm='APPLY'). Budgets or bids over TIKTOK_ADS_MAX_BUDGET /
        TIKTOK_ADS_MAX_BID need confirm='APPLY'. Under non-Search Sales, App
        Promotion or Lead Generation Legacy Manual campaigns this stops working on
        1 January 2027; use the Upgraded Smart+ tools instead.
        """
        cid = check_ids([campaign_id], "campaign_id", 1)[0]
        if not isinstance(settings, dict) or not settings.get("adgroup_name"):
            raise ValueError("settings must be an object with at least adgroup_name.")
        aid = client.resolve_advertiser(advertiser_id)
        body = merge_extra(
            {
                "advertiser_id": aid,
                "campaign_id": cid,
                "operation_status": _status(enabled),
                "request_id": new_request_id(),
            },
            settings,
            protected=("advertiser_id", "campaign_id", "operation_status"),
        )
        warning = guard_legacy_parent(client, aid, cid)
        decision = safety.assess(
            client.config,
            count=1,
            changes=safety.new_values([body], MANUAL_BID_FIELDS),
            creating=True,
            enabling=enabled,
        )
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return {**refused, "warning": warning} if warning else refused
        out = safety.annotate(
            client.request("POST", "/adgroup/create/", json_body=body, op="create_ad_group"),
            decision,
        )
        return {**out, "warning": warning} if warning and isinstance(out, dict) else out

    @mcp.tool()
    def tiktok_ads_update_ad_group(
        adgroup_id: str,
        changes: dict[str, Any],
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Update an ad group's settings: name, targeting, schedule, bid or budget.

        changes: only the /adgroup/update/ fields to change, e.g.
        {"bid_price": 1.2} or {"location_ids": ["2635167"]}. The current ad group
        is read first and kept in the audit log; bid or budget rises above
        TIKTOK_ADS_MAX_INCREASE_PCT (or unknown current values) need
        confirm='APPLY'. For daily budget changes from tomorrow, see
        tiktok_ads_update_ad_group_budgets.
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
                [body], current, id_field="adgroup_id", fields=MANUAL_BID_FIELDS
            ),
        )
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "POST",
            "/adgroup/update/",
            json_body=body,
            op="update_ad_group",
            before=current[0] if current else None,
        )
        return safety.annotate(out, decision)

    @mcp.tool()
    def tiktok_ads_update_ad_group_budgets(
        budgets: list[dict[str, Any]] | None = None,
        scheduled_budgets: list[dict[str, Any]] | None = None,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Change budgets of many ad groups at once (Campaign Management ad groups).

        budgets: [{"adgroup_id": "...", "budget": 50}] for lifetime budgets,
        applied immediately. scheduled_budgets: [{"adgroup_id": "...",
        "scheduled_budget": 50}] for daily or dynamic daily budgets, applied from
        00:00 tomorrow in the account's time zone. Current budgets are read first;
        rises above TIKTOK_ADS_MAX_INCREASE_PCT, unknown current values and more
        than TIKTOK_ADS_BULK_THRESHOLD ad groups need confirm='APPLY'.
        """
        return update_budgets(
            client,
            adg,
            "/adgroup/budget/update/",
            budgets=budgets,
            scheduled_budgets=scheduled_budgets,
            advertiser_id=advertiser_id,
            confirm=confirm,
            op="update_ad_group_budgets",
        )

    # ---------------------------------------------------------- ads

    @mcp.tool()
    def tiktok_ads_list_ads(
        advertiser_id: str | None = None,
        campaign_ids: list[str] | None = None,
        adgroup_ids: list[str] | None = None,
        ad_ids: list[str] | None = None,
        primary_status: str | None = None,
        filtering: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        max_results: int = 200,
    ) -> dict[str, Any]:
        """List ads with their creatives, text, call to action and landing page.

        For Upgraded Smart+ ads this endpoint returns creative-level rows unless you
        filter with {"ad_ids_v2": [...]}; tiktok_ads_smart_plus_list_ads gives the
        ad-level view.
        """
        return list_entities(
            client,
            ad,
            advertiser_id=advertiser_id,
            filtering=_filtering(
                filtering,
                campaign_ids=campaign_ids and check_ids(campaign_ids, "campaign_ids", 100),
                adgroup_ids=adgroup_ids and check_ids(adgroup_ids, "adgroup_ids", 100),
                ad_ids=ad_ids and check_ids(ad_ids, "ad_ids", 100),
                primary_status=primary_status,
            ),
            fields=fields,
            max_results=max_results,
        )

    @mcp.tool()
    def tiktok_ads_create_ads(
        adgroup_id: str,
        creatives: list[dict[str, Any]],
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Create ads in a Campaign Management ad group. Changes the live account.

        creatives: one object per ad, sent as /ad/create/ `creatives`, e.g.
        {"ad_name": "...", "identity_type": "CUSTOMIZED_USER", "identity_id": "...",
        "ad_format": "SINGLE_VIDEO", "video_id": "...", "image_ids": ["..."],
        "ad_text": "...", "call_to_action": "SHOP_NOW", "landing_page_url": "https://..."}.
        Upload media first (tiktok_ads_upload_video / tiktok_ads_upload_image). More
        than TIKTOK_ADS_BULK_THRESHOLD ads need confirm='APPLY'.
        """
        gid = check_ids([adgroup_id], "adgroup_id", 1)[0]
        check_items(creatives, "creatives", 20)
        aid = client.resolve_advertiser(advertiser_id)
        parent = client.snapshot(fetch_by_ids, client, adg, aid, [gid])
        warning = guard_legacy_parent(
            client, aid, str(parent[0].get("campaign_id")) if parent else None
        )
        body = {"advertiser_id": aid, "adgroup_id": gid, "creatives": creatives}
        decision = safety.assess(client.config, count=len(creatives))
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = safety.annotate(
            client.request("POST", "/ad/create/", json_body=body, op="create_ads"), decision
        )
        return {**out, "warning": warning} if warning and isinstance(out, dict) else out

    @mcp.tool()
    def tiktok_ads_update_ads(
        adgroup_id: str,
        creatives: list[dict[str, Any]],
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Update ads in one ad group: text, call to action, landing page or media.

        creatives: one object per ad with its ad_id plus the fields to change. The
        current ads are read first and kept in the audit log. More than
        TIKTOK_ADS_BULK_THRESHOLD ads need confirm='APPLY'.
        """
        gid = check_ids([adgroup_id], "adgroup_id", 1)[0]
        check_items(creatives, "creatives", 20)
        missing = [i for i, c in enumerate(creatives) if not c.get("ad_id")]
        if missing:
            raise ValueError(f"Every creative needs ad_id; missing at index {missing[:10]}.")
        aid = client.resolve_advertiser(advertiser_id)
        ids = [str(c["ad_id"]) for c in creatives]
        current = client.snapshot(fetch_by_ids, client, ad, aid, ids)
        body = {"advertiser_id": aid, "adgroup_id": gid, "creatives": creatives}
        decision = safety.assess(client.config, count=len(creatives))
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "POST", "/ad/update/", json_body=body, op="update_ads", before=current or None
        )
        return safety.annotate(out, decision)

    # ---------------------------------------------------------- status

    @mcp.tool()
    def tiktok_ads_set_status(
        level: str,
        ids: list[str],
        status: str,
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Pause or enable Manual or Smart+ campaigns, ad groups or ads.

        level: campaign, ad_group or ad. status: DISABLE (pause) or ENABLE.
        Enabling starts delivery and spend, so it needs confirm='APPLY'; so does
        changing more than TIKTOK_ADS_BULK_THRESHOLD items. For Upgraded Smart+
        entities use tiktok_ads_smart_plus_set_status.
        """
        lvl = level_for(MANUAL_LEVELS, level)
        return change_status(
            client,
            lvl,
            ids=ids,
            status=status,
            advertiser_id=advertiser_id,
            confirm=confirm,
            op=f"set_{lvl.name}_status",
        )

    @mcp.tool()
    def tiktok_ads_delete(
        level: str,
        ids: list[str],
        advertiser_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Delete Manual or Smart+ campaigns, ad groups or ads. This can't be undone.

        level: campaign, ad_group or ad. Needs confirm='DELETE' after the user
        agrees. Deleting a campaign deletes everything in it. Prefer pausing
        (tiktok_ads_set_status with DISABLE).
        """
        lvl = level_for(MANUAL_LEVELS, level)
        return delete_entities(
            client,
            lvl,
            ids=ids,
            advertiser_id=advertiser_id,
            confirm=confirm,
            op=f"delete_{lvl.name}",
        )
