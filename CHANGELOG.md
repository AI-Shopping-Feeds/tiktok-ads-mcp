# Changelog — TikTok Ads MCP (`tiktok-ads-mcp`)

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-06

### Added
- First version on the TikTok API for Business **Marketing API v1.3**: 65 tools
  across 10 groups plus 5 meta tools, on the same architecture as the other AI
  Shopping Feeds MCP servers (MCP SDK 2 `MCPServer`, tool catalog with titles and
  annotations, tool groups, read-only mode, dry-run, JSONL audit log, stdio and
  streamable HTTP transports, progress notifications).
- `tiktok-ads-mcp auth`: advertiser authorisation with a localhost redirect or
  `--manual` paste (the pasted URL must carry the matching `state`), swapping the
  one-hour `auth_code` for TikTok's long-term access token, saved owner-only.
- Ad accounts and Business Centers; Campaign Management campaigns, ad groups and
  ads; Upgraded Smart+ campaigns, ad groups, ads and creative switches; images
  and videos by URL and identities; custom and lookalike audiences; location,
  interest and audience size lookups; pixels; catalogs, products and product
  sets; synchronous reports, report tasks and `tiktok_ads_run_report` with
  progress; raw read and write request tools.
- TikTok's 1 January 2027 Legacy Manual Flow change: Sales, App Promotion and
  Lead Generation campaigns are created through Upgraded Smart+;
  `tiktok_ads_create_campaign` refuses them (except Search campaigns), and
  creates under existing legacy campaigns of those objectives warn until the
  date and are refused after it.
- Safety: confirm words (`DELETE` for deletes; `APPLY` for enabling delivery,
  batches over `TIKTOK_ADS_BULK_THRESHOLD`, bid/budget rises over
  `TIKTOK_ADS_MAX_INCREASE_PCT` (20%) or unknown current values, caps and raw
  writes); before-snapshots; campaigns and ad groups created paused;
  `TIKTOK_ADS_ALLOWED_ADVERTISER_IDS`.
- Client: TikTok's `{code, message, data}` envelope, retries on throttling codes
  (40100, 40016, 40133) and HTTP 429 for every call, on server errors for reads
  only; a client-side `TIKTOK_ADS_MAX_QPS` cap; pagination; report downloads
  parsed in memory and capped at `TIKTOK_ADS_MAX_DOWNLOAD_MB`.
- Data handling: per-user `~/.tiktok-ads-mcp/` folder (secrets and logs 0700,
  files 0600), audit entries redacted and pruned after
  `TIKTOK_ADS_AUDIT_RETENTION_DAYS` (30), `tiktok-ads-mcp purge [--revoke]`,
  only TikTok hosts contacted, HTTP transports refuse non-loopback hosts unless
  `TIKTOK_ADS_ALLOW_REMOTE=true`.
- Docs: setup walkthrough, all tools, terms and data handling, agent skill,
  security policy and contributing guide.
