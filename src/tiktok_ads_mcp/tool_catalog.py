"""Title and MCP annotations for every tiktok_ads_* tool.

`TikTokAdsMCPServer.tool()` looks each tool up here by name, so the tool modules
stay free of metadata. Every tool must have an entry: tests/test_mcp_client.py
fails if a registered tool is missing or an entry has no tool.

Annotation kinds (all API tools are open-world: they call the TikTok API):

* READ: changes nothing in the ad account. Includes read-only POSTs such as
  searches and audience size estimates.
* REPORT: requests a report. Changes nothing in the ad account, but each call
  starts a new report task, so it isn't idempotent.
* WRITE: creates something; repeating it creates it again.
* UPSERT: an update or status change; repeating it changes nothing more.
* DESTRUCTIVE: deletes; deleted entities can't be restored.
* DESTRUCTIVE_ONCE: the raw request tool, which may do anything.
* LOCAL_*: touches only this server (audit log, session settings).
"""

from __future__ import annotations

from typing import NamedTuple

from mcp.types import ToolAnnotations


def _ann(*, read_only: bool, destructive: bool, idempotent: bool, open_world: bool = True):
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


READ = _ann(read_only=True, destructive=False, idempotent=True)
REPORT = _ann(read_only=True, destructive=False, idempotent=False)
WRITE = _ann(read_only=False, destructive=False, idempotent=False)
UPSERT = _ann(read_only=False, destructive=False, idempotent=True)
DESTRUCTIVE = _ann(read_only=False, destructive=True, idempotent=True)
DESTRUCTIVE_ONCE = _ann(read_only=False, destructive=True, idempotent=False)
LOCAL_READ = _ann(read_only=True, destructive=False, idempotent=True, open_world=False)
LOCAL_SETTING = _ann(read_only=False, destructive=False, idempotent=True, open_world=False)


class ToolSpec(NamedTuple):
    title: str
    annotations: ToolAnnotations


# Registered regardless of TIKTOK_ADS_TOOL_GROUPS and TIKTOK_ADS_READ_ONLY.
ALWAYS_REGISTERED = frozenset(
    {
        "tiktok_ads_describe_server",
        "tiktok_ads_health_check",
        "tiktok_ads_audit_lookup",
        "tiktok_ads_audit_tail",
        "tiktok_ads_set_dry_run",
    }
)

_CATALOG: dict[str, tuple[str, ToolAnnotations]] = {
    # server (meta)
    "tiktok_ads_describe_server": ("Describe the server configuration", LOCAL_READ),
    "tiktok_ads_health_check": ("Check the token and list ad accounts", READ),
    "tiktok_ads_audit_lookup": ("Look up an audit log entry", LOCAL_READ),
    "tiktok_ads_audit_tail": ("Show recent audit log entries", LOCAL_READ),
    "tiktok_ads_set_dry_run": ("Turn dry-run mode on or off", LOCAL_SETTING),
    # accounts
    "tiktok_ads_list_advertisers": ("List authorised ad accounts", READ),
    "tiktok_ads_get_advertiser_info": ("Get ad account details", READ),
    "tiktok_ads_list_business_centers": ("List Business Centers", READ),
    "tiktok_ads_list_bc_assets": ("List Business Center assets", READ),
    # campaigns (Campaign Management endpoints)
    "tiktok_ads_list_campaigns": ("List campaigns", READ),
    "tiktok_ads_create_campaign": ("Create a campaign (Reach, Traffic, Views, Search)", WRITE),
    "tiktok_ads_update_campaign": ("Update a campaign", UPSERT),
    "tiktok_ads_list_ad_groups": ("List ad groups", READ),
    "tiktok_ads_create_ad_group": ("Create an ad group", WRITE),
    "tiktok_ads_update_ad_group": ("Update an ad group", UPSERT),
    "tiktok_ads_update_ad_group_budgets": ("Update ad group budgets", UPSERT),
    "tiktok_ads_list_ads": ("List ads", READ),
    "tiktok_ads_create_ads": ("Create ads", WRITE),
    "tiktok_ads_update_ads": ("Update ads", UPSERT),
    "tiktok_ads_set_status": ("Pause or enable campaigns, ad groups or ads", UPSERT),
    "tiktok_ads_delete": ("Delete campaigns, ad groups or ads", DESTRUCTIVE),
    # smart_plus (Upgraded Smart+)
    "tiktok_ads_smart_plus_list_campaigns": ("List Upgraded Smart+ campaigns", READ),
    "tiktok_ads_smart_plus_create_campaign": ("Create an Upgraded Smart+ campaign", WRITE),
    "tiktok_ads_smart_plus_update_campaign": ("Update an Upgraded Smart+ campaign", UPSERT),
    "tiktok_ads_smart_plus_list_ad_groups": ("List Upgraded Smart+ ad groups", READ),
    "tiktok_ads_smart_plus_create_ad_group": ("Create an Upgraded Smart+ ad group", WRITE),
    "tiktok_ads_smart_plus_update_ad_group": ("Update an Upgraded Smart+ ad group", UPSERT),
    "tiktok_ads_smart_plus_update_ad_group_budgets": (
        "Update Upgraded Smart+ ad group budgets",
        UPSERT,
    ),
    "tiktok_ads_smart_plus_list_ads": ("List Upgraded Smart+ ads", READ),
    "tiktok_ads_smart_plus_create_ad": ("Create an Upgraded Smart+ ad", WRITE),
    "tiktok_ads_smart_plus_update_ad": ("Update an Upgraded Smart+ ad", UPSERT),
    "tiktok_ads_smart_plus_set_status": ("Pause or enable Upgraded Smart+ entities", UPSERT),
    "tiktok_ads_smart_plus_delete": ("Delete Upgraded Smart+ entities", DESTRUCTIVE),
    "tiktok_ads_smart_plus_set_creative_status": (
        "Turn creatives in an Upgraded Smart+ ad on or off",
        UPSERT,
    ),
    # creatives
    "tiktok_ads_list_images": ("Look up or search images", READ),
    "tiktok_ads_list_videos": ("Look up or search videos", READ),
    "tiktok_ads_upload_image": ("Upload an image from a URL", WRITE),
    "tiktok_ads_upload_video": ("Upload a video from a URL", WRITE),
    "tiktok_ads_list_identities": ("List ad identities", READ),
    # audiences
    "tiktok_ads_list_audiences": ("List custom and lookalike audiences", READ),
    "tiktok_ads_get_audiences": ("Get audience details", READ),
    "tiktok_ads_create_lookalike_audience": ("Create a lookalike audience", WRITE),
    "tiktok_ads_create_rule_audience": ("Create a rule-based audience", WRITE),
    "tiktok_ads_refresh_lookalike_audiences": ("Refresh lookalike audiences", UPSERT),
    "tiktok_ads_delete_audiences": ("Delete audiences", DESTRUCTIVE),
    # targeting
    "tiktok_ads_search_locations": ("Search location targeting IDs", READ),
    "tiktok_ads_list_regions": ("List targetable locations", READ),
    "tiktok_ads_list_interest_categories": ("List interest categories", READ),
    "tiktok_ads_estimate_audience_size": ("Estimate audience size", READ),
    # pixels
    "tiktok_ads_list_pixels": ("List pixels", READ),
    "tiktok_ads_get_pixel_event_stats": ("Get pixel event counts", READ),
    # catalogs
    "tiktok_ads_list_catalogs": ("List catalogs", READ),
    "tiktok_ads_get_catalog_overview": ("Get a catalog overview", READ),
    "tiktok_ads_list_catalog_products": ("List catalog products", READ),
    "tiktok_ads_list_product_sets": ("List product sets", READ),
    "tiktok_ads_create_product_set": ("Create a product set", WRITE),
    "tiktok_ads_update_product_set": ("Update a product set", UPSERT),
    "tiktok_ads_delete_product_sets": ("Delete product sets", DESTRUCTIVE),
    # reporting
    "tiktok_ads_get_report": ("Run a report now (synchronous)", READ),
    "tiktok_ads_create_report_task": ("Start an asynchronous report task", REPORT),
    "tiktok_ads_get_report_task": ("Check a report task", READ),
    "tiktok_ads_download_report_task": ("Download a finished report task", READ),
    "tiktok_ads_run_report": ("Run a report and return its rows", REPORT),
    # request
    "tiktok_ads_read_request": ("Read from any TikTok Marketing API endpoint", READ),
    "tiktok_ads_request": ("Call any TikTok Marketing API endpoint", DESTRUCTIVE_ONCE),
}

TOOL_SPECS: dict[str, ToolSpec] = {
    name: ToolSpec(title, annotations) for name, (title, annotations) in _CATALOG.items()
}
