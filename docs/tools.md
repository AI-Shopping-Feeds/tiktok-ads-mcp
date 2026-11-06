# All tools

**65 tools: 60 across 10 groups + 5 meta tools.**

Groups are the modules in `src/tiktok_ads_mcp/tools`; `TIKTOK_ADS_TOOL_GROUPS`
selects some of them. `TIKTOK_ADS_READ_ONLY=true` keeps only the tools marked
*read* below. The meta tools are always registered.

"Kind" comes from each tool's MCP annotations: *read* changes nothing in the ad
account, *write* creates or updates, *destructive* deletes (or, for
`tiktok_ads_request`, may do anything).

Every API tool takes an optional `advertiser_id` (default
`TIKTOK_ADS_ADVERTISER_ID`), except the catalog tools, which take `bc_id`
(default `TIKTOK_ADS_BC_ID`). Budgets and bids are in the ad account's currency.

## Confirm words

| Change | Needs |
|---|---|
| Delete campaigns, ad groups, ads, audiences or product sets | `confirm="DELETE"` |
| Enable delivery: status `ENABLE`, `enabled=true` on a create, or turning on Smart+ creatives | `confirm="APPLY"` |
| More than `TIKTOK_ADS_BULK_THRESHOLD` items (default 10) | `confirm="APPLY"` |
| A bid or budget rising more than `TIKTOK_ADS_MAX_INCREASE_PCT` (default 20%), or whose current value couldn't be read | `confirm="APPLY"` |
| A bid or budget above `TIKTOK_ADS_MAX_BID` / `TIKTOK_ADS_MAX_BUDGET` (if set) | `confirm="APPLY"` |
| Any write through `tiktok_ads_request` | `confirm="APPLY"` |

Without the right word a guarded write returns `refused: true`, the reasons and
the bid/budget changes it would make, and sends nothing. In dry-run mode
nothing is sent anyway, so guards don't block; the preview says which confirm a
real run would need. New campaigns and ad groups are created paused
(`operation_status: DISABLE`) unless you pass `enabled=true`.

## Which tools create what (and the 2027 change)

TikTok's notice on the API for Business docs says that from **1 January 2027**
`/campaign/create/`, `/campaign/copy/task/create/`, `/adgroup/create/`,
`/ad/create/` and `/ad/aco/create/` no longer create or copy non-Search Legacy
Manual Flow campaigns, or ad groups and ads under them, for the Sales, App
Promotion and Lead Generation objectives. So:

| You want | Use |
|---|---|
| Sales (`WEB_CONVERSIONS`), App Promotion or Lead Generation | `tiktok_ads_smart_plus_create_campaign`, `..._create_ad_group`, `..._create_ad` |
| Reach, Traffic, Video Views, Community Interaction (`ENGAGEMENT`), Reach & Frequency | `tiktok_ads_create_campaign`, `tiktok_ads_create_ad_group`, `tiktok_ads_create_ads` |
| A Search campaign for Sales, App Promotion or Lead Generation | `tiktok_ads_create_campaign` with `is_search_campaign=true`, or the Smart+ tools |
| Change, pause or delete existing Manual or Smart+ items | `tiktok_ads_update_*`, `tiktok_ads_set_status`, `tiktok_ads_delete` |
| Change, pause or delete Upgraded Smart+ items | `tiktok_ads_smart_plus_update_*`, `..._set_status`, `..._delete` |

`tiktok_ads_create_campaign` refuses non-Search Sales, App Promotion and Lead
Generation campaigns. Creating ad groups or ads under an existing campaign of
that kind returns a warning until 31 December 2026 and is refused from
1 January 2027. TikTok's Upgraded Smart+ guide is broader: it says
`/campaign/create/` stops creating any Manual campaign after 31 December 2026.
If TikTok rejects a create for a Reach, Traffic or Video Views campaign, use the
Upgraded Smart+ tools or check TikTok's current notice. The legacy Smart+ API
(`/campaign/spc/...`) stopped creating campaigns on 31 March 2026 and isn't
used. TikTok's guide also says creating and editing Upgraded Smart+ campaigns
may need your ad account allowlisted by your TikTok representative; reading and
reporting don't.

## meta (5)

Always registered, whatever `TIKTOK_ADS_TOOL_GROUPS` and `TIKTOK_ADS_READ_ONLY` say.

| Tool | What it does | Kind |
|---|---|---|
| `tiktok_ads_describe_server` | Describe the server configuration | read |
| `tiktok_ads_health_check` | Check the token and list ad accounts | read |
| `tiktok_ads_audit_lookup` | Look up an audit log entry | read |
| `tiktok_ads_audit_tail` | Show recent audit log entries | read |
| `tiktok_ads_set_dry_run` | Turn dry-run mode on or off | write |

## accounts (4)

Ad accounts (advertisers) and Business Centers the token can reach.

| Tool | What it does | Kind |
|---|---|---|
| `tiktok_ads_list_advertisers` | List authorised ad accounts | read |
| `tiktok_ads_get_advertiser_info` | Get ad account details | read |
| `tiktok_ads_list_business_centers` | List Business Centers | read |
| `tiktok_ads_list_bc_assets` | List Business Center assets | read |

## campaigns (12)

Campaigns, ad groups and ads on the Campaign Management endpoints. Reads every campaign type; creates Reach, Traffic, Video Views, Community Interaction, Reach & Frequency and Search campaigns.

| Tool | What it does | Kind |
|---|---|---|
| `tiktok_ads_list_campaigns` | List campaigns | read |
| `tiktok_ads_create_campaign` | Create a campaign (Reach, Traffic, Views, Search) | write |
| `tiktok_ads_update_campaign` | Update a campaign | write |
| `tiktok_ads_list_ad_groups` | List ad groups | read |
| `tiktok_ads_create_ad_group` | Create an ad group | write |
| `tiktok_ads_update_ad_group` | Update an ad group | write |
| `tiktok_ads_update_ad_group_budgets` | Update ad group budgets | write |
| `tiktok_ads_list_ads` | List ads | read |
| `tiktok_ads_create_ads` | Create ads | write |
| `tiktok_ads_update_ads` | Update ads | write |
| `tiktok_ads_set_status` | Pause or enable campaigns, ad groups or ads | write |
| `tiktok_ads_delete` | Delete campaigns, ad groups or ads | **destructive** |

## smart_plus (13)

Upgraded Smart+ campaigns, ad groups and ads: the creation path for Sales (Website Conversions), App Promotion and Lead Generation.

| Tool | What it does | Kind |
|---|---|---|
| `tiktok_ads_smart_plus_list_campaigns` | List Upgraded Smart+ campaigns | read |
| `tiktok_ads_smart_plus_create_campaign` | Create an Upgraded Smart+ campaign | write |
| `tiktok_ads_smart_plus_update_campaign` | Update an Upgraded Smart+ campaign | write |
| `tiktok_ads_smart_plus_list_ad_groups` | List Upgraded Smart+ ad groups | read |
| `tiktok_ads_smart_plus_create_ad_group` | Create an Upgraded Smart+ ad group | write |
| `tiktok_ads_smart_plus_update_ad_group` | Update an Upgraded Smart+ ad group | write |
| `tiktok_ads_smart_plus_update_ad_group_budgets` | Update Upgraded Smart+ ad group budgets | write |
| `tiktok_ads_smart_plus_list_ads` | List Upgraded Smart+ ads | read |
| `tiktok_ads_smart_plus_create_ad` | Create an Upgraded Smart+ ad | write |
| `tiktok_ads_smart_plus_update_ad` | Update an Upgraded Smart+ ad | write |
| `tiktok_ads_smart_plus_set_status` | Pause or enable Upgraded Smart+ entities | write |
| `tiktok_ads_smart_plus_delete` | Delete Upgraded Smart+ entities | **destructive** |
| `tiktok_ads_smart_plus_set_creative_status` | Turn creatives in an Upgraded Smart+ ad on or off | write |

## creatives (5)

Images and videos in the ad account's creative library (upload by URL, look up, search) and ad identities.

| Tool | What it does | Kind |
|---|---|---|
| `tiktok_ads_list_images` | Look up or search images | read |
| `tiktok_ads_list_videos` | Look up or search videos | read |
| `tiktok_ads_upload_image` | Upload an image from a URL | write |
| `tiktok_ads_upload_video` | Upload a video from a URL | write |
| `tiktok_ads_list_identities` | List ad identities | read |

## audiences (6)

Custom and lookalike audiences.

| Tool | What it does | Kind |
|---|---|---|
| `tiktok_ads_list_audiences` | List custom and lookalike audiences | read |
| `tiktok_ads_get_audiences` | Get audience details | read |
| `tiktok_ads_create_lookalike_audience` | Create a lookalike audience | write |
| `tiktok_ads_create_rule_audience` | Create a rule-based audience | write |
| `tiktok_ads_refresh_lookalike_audiences` | Refresh lookalike audiences | write |
| `tiktok_ads_delete_audiences` | Delete audiences | **destructive** |

## targeting (4)

Location and interest lookups and audience size estimates for building ad groups.

| Tool | What it does | Kind |
|---|---|---|
| `tiktok_ads_search_locations` | Search location targeting IDs | read |
| `tiktok_ads_list_regions` | List targetable locations | read |
| `tiktok_ads_list_interest_categories` | List interest categories | read |
| `tiktok_ads_estimate_audience_size` | Estimate audience size | read |

## pixels (2)

Pixels and their event counts (read only).

| Tool | What it does | Kind |
|---|---|---|
| `tiktok_ads_list_pixels` | List pixels | read |
| `tiktok_ads_get_pixel_event_stats` | Get pixel event counts | read |

## catalogs (7)

Catalogs, products and product sets in a Business Center.

| Tool | What it does | Kind |
|---|---|---|
| `tiktok_ads_list_catalogs` | List catalogs | read |
| `tiktok_ads_get_catalog_overview` | Get a catalog overview | read |
| `tiktok_ads_list_catalog_products` | List catalog products | read |
| `tiktok_ads_list_product_sets` | List product sets | read |
| `tiktok_ads_create_product_set` | Create a product set | write |
| `tiktok_ads_update_product_set` | Update a product set | write |
| `tiktok_ads_delete_product_sets` | Delete product sets | **destructive** |

## reporting (5)

Synchronous reports and asynchronous report tasks, plus a tool that runs one end to end with progress.

| Tool | What it does | Kind |
|---|---|---|
| `tiktok_ads_get_report` | Run a report now (synchronous) | read |
| `tiktok_ads_create_report_task` | Start an asynchronous report task | read |
| `tiktok_ads_get_report_task` | Check a report task | read |
| `tiktok_ads_download_report_task` | Download a finished report task | read |
| `tiktok_ads_run_report` | Run a report and return its rows | read |

## request (2)

Escape hatch for any other Marketing API v1.3 endpoint.

| Tool | What it does | Kind |
|---|---|---|
| `tiktok_ads_read_request` | Read from any TikTok Marketing API endpoint | read |
| `tiktok_ads_request` | Call any TikTok Marketing API endpoint | **destructive** |

## Left to the escape hatch

`tiktok_ads_read_request` (reads only) and `tiktok_ads_request` (writes, needs
`confirm="APPLY"`) reach any other path under
`https://business-api.tiktok.com/open_api/v1.3`, for example: GMV Max campaigns,
campaign copy tasks, Spark Ads authorisation, catalog product uploads and
feeds, customer-file audiences, Events API, Business Center members, payments
and billing, creative tools, split tests, Reach & Frequency orders, comments,
leads and the TikTok accounts (organic) APIs. OAuth endpoints are blocked there
so the app secret is never sent through a tool. Only GET and POST are allowed
(TikTok's API uses no other methods), and paths can't point at another host.
