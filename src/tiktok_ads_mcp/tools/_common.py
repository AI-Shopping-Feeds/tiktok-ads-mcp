"""Shared building blocks for the tool modules.

Campaigns, ad groups and ads exist in two families that share one shape:

* the Campaign Management endpoints (`/campaign/...`, `/adgroup/...`, `/ad/...`),
  which read every campaign type and still create Reach, Traffic, Video Views,
  Community Interaction and Search campaigns;
* the Upgraded Smart+ endpoints (`/smart_plus/...`), which TikTok makes the
  path for creating Sales (Website Conversions), App Promotion and Lead
  Generation campaigns from 1 January 2027.

`Level` describes one entity level in a family so the list, status, delete and
budget helpers below work the same way for both, with the same guards,
before-snapshots and audit trail.
"""

from __future__ import annotations

import random
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from .. import safety
from ..client import TikTokAdsClient

MAX_FILTER_IDS = 100  # IDs per `filtering` list on get endpoints
MAX_STATUS_BATCH = 20  # IDs per status-update call
MAX_BUDGET_BATCH = 20  # items per budget-update call
MAX_IDS_PER_TOOL = 200

# From 1 January 2027 TikTok's /campaign/create/, /campaign/copy/task/create/,
# /adgroup/create/, /ad/create/ and /ad/aco/create/ no longer create (or copy)
# non-Search Legacy Manual Flow campaigns, or ad groups and ads under them, for
# the Sales, App Promotion and Lead Generation objectives.
MANUAL_FLOW_SUNSET = date(2027, 1, 1)
SUNSET_OBJECTIVES = frozenset(
    {"WEB_CONVERSIONS", "PRODUCT_SALES", "APP_PROMOTION", "LEAD_GENERATION"}
)
SUNSET_NOTE = (
    "From 1 January 2027 TikTok no longer creates non-Search Legacy Manual Flow campaigns, "
    "ad groups or ads for Sales, App Promotion and Lead Generation. Use the Upgraded Smart+ "
    "tools (tiktok_ads_smart_plus_*) for these objectives."
)

MANUAL_BID_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("budget", ("budget",)),
    ("bid", ("bid_price",)),
    ("bid", ("conversion_bid_price",)),
    ("bid", ("deep_cpa_bid",)),
)
BUDGET_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (("budget", ("budget",)),)
# Budget-update items may also carry min/max budgets (ad groups in CBO campaigns).
AD_GROUP_BUDGET_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("budget", ("budget",)),
    ("budget", ("min_budget",)),
    ("budget", ("max_budget",)),
)


def today() -> date:
    return datetime.now(UTC).date()


def new_request_id() -> str:
    """A string form of a positive 64-bit integer, as TikTok's idempotency key expects."""
    return str(random.randint(10**15, 2**63 - 1))


def ids_to_strings(ids: Sequence[Any] | None) -> list[str]:
    return [str(i).strip() for i in (ids or []) if str(i).strip()]


def check_ids(ids: Sequence[Any] | None, what: str, max_items: int = MAX_IDS_PER_TOOL) -> list[str]:
    out = ids_to_strings(ids)
    if not out:
        raise ValueError(f"Pass at least one {what}.")
    if len(out) > max_items:
        raise ValueError(f"At most {max_items} {what} per call; got {len(out)}.")
    bad = [i for i in out if not i.isdigit()]
    if bad:
        raise ValueError(f"{what} must be numeric; got {bad[:5]}.")
    return out


def check_items(items: list[dict[str, Any]] | None, what: str, max_items: int) -> list[dict]:
    if not items:
        raise ValueError(f"Pass at least one {what}.")
    if len(items) > max_items:
        raise ValueError(f"At most {max_items} {what} per call; got {len(items)}.")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{what}[{i}] must be an object.")
    return items


def chunks(seq: Sequence[Any], size: int) -> Iterator[list[Any]]:
    for i in range(0, len(seq), size):
        yield list(seq[i : i + size])


def merge_extra(body: dict[str, Any], extra: dict[str, Any] | None, *, protected: Sequence[str]):
    """Add `extra` fields to a request body without letting them replace `protected` keys."""
    for key, value in (extra or {}).items():
        if key in protected:
            raise ValueError(f"Set {key} with its own argument, not in extra.")
        body[key] = value
    return body


@dataclass(frozen=True)
class Level:
    """One entity level (campaign, ad group or ad) in an endpoint family."""

    name: str  # "campaign", "ad_group" or "ad"
    label: str
    get_path: str
    id_field: str
    filter_key: str
    status_path: str
    status_ids_key: str
    max_page_size: int = 1000


MANUAL_LEVELS: dict[str, Level] = {
    "campaign": Level(
        "campaign",
        "campaigns",
        "/campaign/get/",
        "campaign_id",
        "campaign_ids",
        "/campaign/status/update/",
        "campaign_ids",
    ),
    "ad_group": Level(
        "ad_group",
        "ad groups",
        "/adgroup/get/",
        "adgroup_id",
        "adgroup_ids",
        "/adgroup/status/update/",
        "adgroup_ids",
    ),
    "ad": Level("ad", "ads", "/ad/get/", "ad_id", "ad_ids", "/ad/status/update/", "ad_ids"),
}

SMART_PLUS_LEVELS: dict[str, Level] = {
    "campaign": Level(
        "campaign",
        "Upgraded Smart+ campaigns",
        "/smart_plus/campaign/get/",
        "campaign_id",
        "campaign_ids",
        "/smart_plus/campaign/status/update/",
        "campaign_ids",
    ),
    "ad_group": Level(
        "ad_group",
        "Upgraded Smart+ ad groups",
        "/smart_plus/adgroup/get/",
        "adgroup_id",
        "adgroup_ids",
        "/smart_plus/adgroup/status/update/",
        "adgroup_ids",
    ),
    "ad": Level(
        "ad",
        "Upgraded Smart+ ads",
        "/smart_plus/ad/get/",
        "smart_plus_ad_id",
        "smart_plus_ad_ids",
        "/smart_plus/ad/status/update/",
        "smart_plus_ad_ids",
        max_page_size=100,
    ),
}


def level_for(levels: dict[str, Level], level: str) -> Level:
    key = (level or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = {
        "adgroup": "ad_group",
        "campaigns": "campaign",
        "ad_groups": "ad_group",
        "ads": "ad",
    }.get(key, key)
    if key not in levels:
        raise ValueError("level must be 'campaign', 'ad_group' or 'ad'.")
    return levels[key]


def list_entities(
    client: TikTokAdsClient,
    lvl: Level,
    *,
    advertiser_id: str | None,
    filtering: dict[str, Any] | None = None,
    fields: list[str] | None = None,
    max_results: int = 200,
) -> dict[str, Any]:
    aid = client.resolve_advertiser(advertiser_id)
    params: dict[str, Any] = {"advertiser_id": aid}
    if filtering:
        params["filtering"] = filtering
    if fields:
        params["fields"] = fields
    items, truncated, page_info = client.paginate(
        lvl.get_path,
        params,
        max_results=max(1, max_results),
        max_page_size=lvl.max_page_size,
    )
    return {
        "advertiser_id": aid,
        "count": len(items),
        "total": page_info.get("total_number"),
        "truncated": truncated,
        "list": items,
    }


def fetch_by_ids(
    client: TikTokAdsClient,
    lvl: Level,
    advertiser_id: str,
    ids: Sequence[str],
    *,
    extra_filter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Read entities by ID (for before-snapshots and guard checks)."""
    out: list[dict[str, Any]] = []
    for part in chunks(list(ids), MAX_FILTER_IDS):
        filtering: dict[str, Any] = {lvl.filter_key: part, **(extra_filter or {})}
        items, _, _ = client.paginate(
            lvl.get_path,
            {"advertiser_id": advertiser_id, "filtering": filtering},
            max_results=len(part),
            max_page_size=lvl.max_page_size,
        )
        out.extend(i for i in items if isinstance(i, dict))
    return out


def _by_id(entities: Sequence[dict[str, Any]] | None, id_field: str) -> dict[str, dict[str, Any]]:
    return {str(e.get(id_field)): e for e in (entities or []) if isinstance(e, dict)}


def change_status(
    client: TikTokAdsClient,
    lvl: Level,
    *,
    ids: Sequence[Any],
    status: str,
    advertiser_id: str | None,
    confirm: str,
    op: str,
) -> dict[str, Any]:
    """Pause (DISABLE) or enable (ENABLE) entities, 20 per call, with a before-snapshot."""
    status = (status or "").strip().upper()
    if status not in {"ENABLE", "DISABLE"}:
        raise ValueError(
            "status must be ENABLE or DISABLE (pause). To delete, use the delete tool."
        )
    id_list = check_ids(ids, f"{lvl.name} IDs")
    aid = client.resolve_advertiser(advertiser_id)
    decision = safety.assess(client.config, count=len(id_list), enabling=status == "ENABLE")
    preview = {"level": lvl.name, "ids": id_list, "operation_status": status}
    refused = safety.refusal(client.config, decision, confirm, preview=preview)
    if refused:
        return refused
    before = _by_id(client.snapshot(fetch_by_ids, client, lvl, aid, id_list), lvl.id_field)
    results = []
    for part in chunks(id_list, MAX_STATUS_BATCH):
        results.append(
            client.request(
                "POST",
                lvl.status_path,
                json_body={
                    "advertiser_id": aid,
                    lvl.status_ids_key: part,
                    "operation_status": status,
                },
                op=op,
                before=[before[i] for i in part if i in before] or None,
            )
        )
    return safety.annotate(
        {"level": lvl.name, "operation_status": status, "count": len(id_list), "results": results},
        decision,
    )


def delete_entities(
    client: TikTokAdsClient,
    lvl: Level,
    *,
    ids: Sequence[Any],
    advertiser_id: str | None,
    confirm: str,
    op: str,
) -> dict[str, Any]:
    """Delete entities (operation_status DELETE). Irreversible: needs confirm='DELETE'."""
    id_list = check_ids(ids, f"{lvl.name} IDs")
    aid = client.resolve_advertiser(advertiser_id)
    decision = safety.assess(client.config, count=len(id_list), destructive=safety.DELETE)
    preview = {"level": lvl.name, "ids": id_list, "operation_status": "DELETE"}
    refused = safety.refusal(client.config, decision, confirm, preview=preview)
    if refused:
        return refused
    before = _by_id(client.snapshot(fetch_by_ids, client, lvl, aid, id_list), lvl.id_field)
    results = []
    for part in chunks(id_list, MAX_STATUS_BATCH):
        results.append(
            client.request(
                "POST",
                lvl.status_path,
                json_body={
                    "advertiser_id": aid,
                    lvl.status_ids_key: part,
                    "operation_status": "DELETE",
                },
                op=op,
                before=[before[i] for i in part if i in before] or None,
            )
        )
    return safety.annotate(
        {"level": lvl.name, "deleted_count": len(id_list), "results": results}, decision
    )


def update_budgets(
    client: TikTokAdsClient,
    lvl: Level,
    path: str,
    *,
    budgets: list[dict[str, Any]] | None,
    scheduled_budgets: list[dict[str, Any]] | None,
    advertiser_id: str | None,
    confirm: str,
    op: str,
) -> dict[str, Any]:
    """Change ad group budgets now (`budgets`) or from tomorrow (`scheduled_budgets`)."""
    budgets = list(budgets or [])
    scheduled = list(scheduled_budgets or [])
    if not budgets and not scheduled:
        raise ValueError(
            "Pass budgets=[{adgroup_id, budget}] and/or scheduled_budgets="
            "[{adgroup_id, scheduled_budget}]."
        )
    for name, items, keys in (
        ("budgets", budgets, ("budget", "min_budget", "max_budget")),
        ("scheduled_budgets", scheduled, ("scheduled_budget",)),
    ):
        if items:
            check_items(items, name, MAX_IDS_PER_TOOL)
        for i, item in enumerate(items):
            if not item.get("adgroup_id") or all(item.get(k) is None for k in keys):
                raise ValueError(f"{name}[{i}] needs adgroup_id and {' or '.join(keys)}.")
    aid = client.resolve_advertiser(advertiser_id)
    ids = sorted({str(i["adgroup_id"]) for i in budgets + scheduled})
    current = client.snapshot(fetch_by_ids, client, lvl, aid, ids)
    by_id = _by_id(current, lvl.id_field)
    changes = safety.money_changes(
        budgets, current, id_field="adgroup_id", fields=AD_GROUP_BUDGET_FIELDS
    )
    for item in scheduled:
        eid = str(item["adgroup_id"])
        old = by_id.get(eid, {}).get("budget")
        changes.append(
            safety.MoneyChange(
                eid,
                "budget",
                float(old) if isinstance(old, int | float) else None,
                float(item["scheduled_budget"]),
            )
        )
    decision = safety.assess(client.config, count=len(ids), changes=changes)
    preview = {"budget": budgets, "scheduled_budget": scheduled}
    refused = safety.refusal(client.config, decision, confirm, preview=preview)
    if refused:
        return refused
    results = []
    for name, items in (("budget", budgets), ("scheduled_budget", scheduled)):
        for part in chunks(items, MAX_BUDGET_BATCH):
            results.append(
                client.request(
                    "POST",
                    path,
                    json_body={"advertiser_id": aid, name: part},
                    op=op,
                    before=[
                        by_id[str(i["adgroup_id"])] for i in part if str(i["adgroup_id"]) in by_id
                    ]
                    or None,
                )
            )
    return safety.annotate({"results": results}, decision)


def legacy_flow_check(campaign: dict[str, Any] | None) -> str | None:
    """Return why a create under this campaign hits the Manual Flow sunset, or None."""
    if not campaign:
        return None
    if str(campaign.get("campaign_automation_type") or "MANUAL").upper() != "MANUAL":
        return None
    if campaign.get("is_search_campaign") is True:
        return None
    objective = str(campaign.get("objective_type") or "").upper()
    if objective in SUNSET_OBJECTIVES:
        return objective
    return None


def guard_legacy_parent(
    client: TikTokAdsClient, advertiser_id: str, campaign_id: str | None
) -> str | None:
    """Refuse creates under a sunset Legacy Manual Flow campaign from 1 January 2027.

    Before that date the create goes ahead and a warning is returned instead.
    """
    if not campaign_id:
        return None
    found = client.snapshot(
        fetch_by_ids, client, MANUAL_LEVELS["campaign"], advertiser_id, [str(campaign_id)]
    )
    objective = legacy_flow_check(found[0] if found else None)
    if objective is None:
        return None
    if today() >= MANUAL_FLOW_SUNSET:
        raise ValueError(
            f"Campaign {campaign_id} is a non-Search Legacy Manual Flow {objective} campaign. "
            + SUNSET_NOTE
        )
    return (
        f"Campaign {campaign_id} is a non-Search Legacy Manual Flow {objective} campaign; "
        "creating ad groups or ads under it stops working on 1 January 2027. " + SUNSET_NOTE
    )
