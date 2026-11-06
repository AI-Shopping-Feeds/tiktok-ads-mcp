# TikTok Ads MCP Server (read + write)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

An [MCP](https://modelcontextprotocol.io) server for the
[TikTok API for Business](https://business-api.tiktok.com/portal/docs) (Marketing API v1.3).
Use it from Claude, ChatGPT, Cursor, Codex or any MCP client to report on TikTok
ad accounts, build and change campaigns, ad groups and ads (including Upgraded
Smart+), upload creatives, and manage audiences, pixels and catalogs.

It's maintained by [AI Shopping Feeds](https://github.com/AI-Shopping-Feeds) and offers:

- **the advertiser workflow on the current API:** ad accounts and Business Centers, campaigns, ad groups and ads, Upgraded Smart+, creatives, audiences, targeting lookups, pixels, catalogs and reports
- **safety for real budgets:** dry-run, confirm words, spend guards, before-snapshots, an audit log, read-only mode and tool groups
- **an escape hatch** for every other Marketing API endpoint, with writes behind a confirm word

TikTok runs its own hosted [TikTok for Business MCP Server](https://business-api.tiktok.com/portal/docs/tiktok-ads-mcp-server/v1.3)
(about 400 tools, no developer app needed, sign-in renewed every 30 days, 6 requests a second per tool).
This one runs on your machine with your own developer app, and adds dry-run, confirm words, spend guards,
an audit log, read-only mode and a smaller tool set. More in [docs/terms-and-data.md](docs/terms-and-data.md#how-this-compares-with-tiktoks-mcp-server).
Not affiliated with or endorsed by TikTok.

Part of the AI Shopping Feeds MCP family: [Google Ads](https://github.com/AI-Shopping-Feeds/google-ads-mcp) · [Google Merchant Centre](https://github.com/AI-Shopping-Feeds/google-merchant-centre-mcp) · [Google Analytics](https://github.com/AI-Shopping-Feeds/google-analytics-mcp) · [YouTube Studio](https://github.com/AI-Shopping-Feeds/youtube-studio-mcp) · [Amazon Ads](https://github.com/AI-Shopping-Feeds/amazon-ads-mcp) · [Apple Ads](https://github.com/AI-Shopping-Feeds/apple-ads-mcp) · [Microsoft Ads](https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp) · **[TikTok Ads](https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp)** · [Pinterest Ads](https://github.com/AI-Shopping-Feeds/pinterest-ads-mcp) · [Snapchat Ads](https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp) · [OpenAI Ads](https://github.com/AI-Shopping-Feeds/openai-ads-mcp) · [AppLovin](https://github.com/AI-Shopping-Feeds/applovin-mcp).

## Let your agent set it up

Paste this into Claude Code, Codex, Cursor or any agent that can read web pages and edit files:

```text
Set up the TikTok Ads MCP server for me by following https://raw.githubusercontent.com/AI-Shopping-Feeds/tiktok-ads-mcp/main/skills/tiktok-ads-mcp/SKILL.md
```

The agent checks whether it's already connected, installs the runner if you
agree, walks you through the TikTok developer account, developer app and
advertiser authorisation, adds the server to your client's config without
touching your other servers, and checks it works by calling
`tiktok_ads_health_check`.

The same file is an [Agent Skill](https://agentskills.io), so your agent can keep it as a guide to using the tools well. For Claude Code, copy the folder into your skills:

```bash
git clone --depth 1 https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp.git /tmp/tiktok-ads-mcp
cp -r /tmp/tiktok-ads-mcp/skills/tiktok-ads-mcp ~/.claude/skills/
```

Other agents that support skills load the same `skills/tiktok-ads-mcp` folder from their own skills directory.

## What it can do

65 tools, all prefixed `tiktok_ads_`. The full list is in [docs/tools.md](docs/tools.md).

### Read

| Area | Tools |
|---|---|
| Accounts | `list_advertisers`, `get_advertiser_info`, `list_business_centers`, `list_bc_assets` |
| Campaigns, ad groups, ads | `list_campaigns` (every campaign type), `list_ad_groups`, `list_ads`, `smart_plus_list_campaigns`, `smart_plus_list_ad_groups`, `smart_plus_list_ads` |
| Creatives | `list_images`, `list_videos`, `list_identities` |
| Audiences and targeting | `list_audiences`, `get_audiences`, `search_locations`, `list_regions`, `list_interest_categories`, `estimate_audience_size` |
| Pixels and catalogs | `list_pixels`, `get_pixel_event_stats`, `list_catalogs`, `get_catalog_overview`, `list_catalog_products`, `list_product_sets` |
| Reports | `get_report` (synchronous), `run_report` (async task with progress), `create_report_task`, `get_report_task`, `download_report_task` |
| Anything else | `read_request` |

### Write

| Area | Tools |
|---|---|
| Upgraded Smart+ (Sales, App Promotion, Lead Generation) | `smart_plus_create_campaign`, `smart_plus_create_ad_group`, `smart_plus_create_ad`, `smart_plus_update_*`, `smart_plus_update_ad_group_budgets`, `smart_plus_set_status`, `smart_plus_set_creative_status`, `smart_plus_delete` |
| Campaign Management (Reach, Traffic, Video Views, Community Interaction, Search) | `create_campaign`, `create_ad_group`, `create_ads`, `update_campaign`, `update_ad_group`, `update_ads`, `update_ad_group_budgets`, `set_status`, `delete` |
| Creatives | `upload_image`, `upload_video` (from a URL) |
| Audiences | `create_lookalike_audience`, `create_rule_audience`, `refresh_lookalike_audiences`, `delete_audiences` |
| Catalogs | `create_product_set`, `update_product_set`, `delete_product_sets` |
| Any endpoint | `request` |

**Upcoming TikTok change:** from 1 January 2027 TikTok's Campaign Management
endpoints stop creating non-Search Legacy Manual Flow campaigns, ad groups and
ads for Sales, App Promotion and Lead Generation. This server already creates
those through Upgraded Smart+, and can still read, change, pause and delete
legacy campaigns. Details in [docs/tools.md](docs/tools.md#which-tools-create-what-and-the-2027-change).

### Safety

- **Dry-run** (`TIKTOK_ADS_DRY_RUN=true` or `tiktok_ads_set_dry_run`) records writes in the audit log and returns what would be sent, without sending it. Reads and reports still work.
- **Confirm words.** Deletes need `confirm="DELETE"`. Enabling delivery, batches over `TIKTOK_ADS_BULK_THRESHOLD` (10), bid or budget rises over `TIKTOK_ADS_MAX_INCREASE_PCT` (20%) or unknown current values, values over `TIKTOK_ADS_MAX_BID` / `TIKTOK_ADS_MAX_BUDGET`, and raw writes need `confirm="APPLY"`. Without it nothing is sent and the agent gets the reasons and before/after values to show you.
- **Paused by default.** New campaigns and ad groups are created paused unless you ask otherwise.
- **Audit log** of every write with a before-snapshot, in `~/.tiktok-ads-mcp/logs/audit.jsonl` (owner-only), pruned after `TIKTOK_ADS_AUDIT_RETENTION_DAYS` (30). `tiktok-ads-mcp purge` deletes it and the stored token (`--revoke` also revokes the token at TikTok).
- **Read-only mode** (`TIKTOK_ADS_READ_ONLY=true`) and **tool groups** (`TIKTOK_ADS_TOOL_GROUPS`) limit what's loaded; `TIKTOK_ADS_ALLOWED_ADVERTISER_IDS` limits which ad accounts it touches.
- **Rate limits:** requests are spaced to `TIKTOK_ADS_MAX_QPS` (10, TikTok's Basic level) and throttled calls back off and retry.
- **Local only by default:** the HTTP transports refuse non-loopback addresses unless `TIKTOK_ADS_ALLOW_REMOTE=true`.
- Terms, data handling and what to check before using it for clients: [docs/terms-and-data.md](docs/terms-and-data.md).

## Supported clients

| Client | Works? | How |
|---|---|---|
| Claude Code | ✅ | Local server, `claude mcp add` (below) |
| Claude Desktop | ✅ | Local server, `claude_desktop_config.json` |
| Cursor | ✅ | Local server, `~/.cursor/mcp.json` |
| VS Code (Copilot) | ✅ | Local server, `.vscode/mcp.json` (uses `servers` instead of `mcpServers`) |
| Codex | ✅ | Local server, `~/.codex/config.toml` |
| Gemini CLI | ✅ | Local server, `~/.gemini/settings.json` |
| Windsurf and other local clients | ✅ | Local server, same JSON entry |
| Claude.ai and ChatGPT | ❌ not yet | These need a remote server with sign-in. This server's HTTP transports have no sign-in, so don't expose them publicly. Use a local client. |

## Setup

### 1. Install uv

The server runs with `uvx` from [uv](https://docs.astral.sh/uv/getting-started/installation/)
(`brew install uv` on macOS) and needs Python 3.11 or later. It installs straight
from this repository:

```shell
uvx --from git+https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp.git tiktok-ads-mcp version
```

Pin a release by adding `@vX.Y.Z` to the URL.

### 2. Get credentials

1. **TikTok For Business account** and **developer registration** at the
   [TikTok API for Business portal](https://business-api.tiktok.com/portal). TikTok reviews
   developers in about three business days and needs a company email and website.
2. **Developer app** with the scopes you need and the advertiser redirect URL
   `http://localhost:8765/callback`. App review takes two to three business days.
   Note the **App ID** and **Secret**.
3. **Authorise** with the TikTok For Business user that manages the ad accounts:

   ```shell
   TIKTOK_ADS_APP_ID=123456789 TIKTOK_ADS_APP_SECRET=your-app-secret \
     uvx --from git+https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp.git tiktok-ads-mcp auth
   ```

   It saves a long-term access token to `~/.tiktok-ads-mcp/secrets/tiktok-ads-token.json`
   (owner-only) and lists the ad account IDs it can manage.

Step by step, with timings: [docs/setup-tiktok-ads-api.md](docs/setup-tiktok-ads-api.md).

### 3. Add it to your client

Replace the placeholders. Keep your other servers in each file. The token is
read from `~/.tiktok-ads-mcp/secrets/` (or set `TIKTOK_ADS_TOKEN_FILE`), so it
doesn't go in the client config.

**Claude Code**

```bash
claude mcp add --scope user tiktok-ads \
  --env TIKTOK_ADS_APP_ID=123456789 \
  --env TIKTOK_ADS_APP_SECRET=your-app-secret \
  --env TIKTOK_ADS_ADVERTISER_ID=123456789 \
  --env TIKTOK_ADS_DRY_RUN=true \
  -- uvx --from git+https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp.git tiktok-ads-mcp
```

**Claude Desktop, Cursor, Gemini CLI, Windsurf** (and VS Code under `servers`)

```json
{
  "mcpServers": {
    "tiktok-ads": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp.git", "tiktok-ads-mcp"],
      "env": {
        "TIKTOK_ADS_APP_ID": "123456789",
        "TIKTOK_ADS_APP_SECRET": "your-app-secret",
        "TIKTOK_ADS_ADVERTISER_ID": "123456789",
        "TIKTOK_ADS_DRY_RUN": "true"
      }
    }
  }
}
```

Desktop apps often can't find `uvx` on the PATH; if the server doesn't start, use
the full path from `which uvx` as the `command`. To keep the secret out of client
configs, put the variables in `~/.tiktok-ads-mcp/.env` instead.

**Codex** (`~/.codex/config.toml`)

```toml
[mcp_servers.tiktok-ads]
command = "uvx"
args = ["--from", "git+https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp.git", "tiktok-ads-mcp"]
env = { TIKTOK_ADS_APP_ID = "123456789", TIKTOK_ADS_APP_SECRET = "your-app-secret", TIKTOK_ADS_ADVERTISER_ID = "123456789", TIKTOK_ADS_DRY_RUN = "true" }
```

### 4. Check it works

Restart or reload the client, then ask it to "check the TikTok Ads connection and
list my ad accounts". It should call `tiktok_ads_health_check`. When you're happy
with the previews, set `TIKTOK_ADS_DRY_RUN=false`.

## Configuration

| Variable | Required | What it does |
|---|---|---|
| `TIKTOK_ADS_APP_ID`, `TIKTOK_ADS_APP_SECRET` | for `auth`, listing ad accounts and `purge --revoke` | Developer app credentials (My Apps → your app → Basic Information) |
| `TIKTOK_ADS_TOKEN_FILE` | no | Token file written by `auth` (default `~/.tiktok-ads-mcp/secrets/tiktok-ads-token.json`) |
| `TIKTOK_ADS_ACCESS_TOKEN` | no | The access token itself, instead of the file |
| `TIKTOK_ADS_ADVERTISER_ID` | no | Default ad account (set automatically when the token has only one) |
| `TIKTOK_ADS_BC_ID` | no | Default Business Center for catalog tools |
| `TIKTOK_ADS_ALLOWED_ADVERTISER_IDS` | no | Comma-separated ad accounts the server may touch (default all the token can reach) |
| `TIKTOK_ADS_DRY_RUN` | no | `true` previews writes without sending them |
| `TIKTOK_ADS_READ_ONLY` | no | `true` registers only read-only tools |
| `TIKTOK_ADS_TOOL_GROUPS` | no | Comma-separated groups: `accounts`, `campaigns`, `smart_plus`, `creatives`, `audiences`, `targeting`, `pixels`, `catalogs`, `reporting`, `request`. Unknown names stop the server at startup |
| `TIKTOK_ADS_BULK_THRESHOLD` | no | Items per write before `confirm="APPLY"` is needed (default 10) |
| `TIKTOK_ADS_MAX_INCREASE_PCT` | no | Bid/budget rise that needs `confirm="APPLY"` (default 20) |
| `TIKTOK_ADS_MAX_BUDGET`, `TIKTOK_ADS_MAX_BID` | no | Optional absolute caps in the account currency |
| `TIKTOK_ADS_AUDIT_LOG` | no | Audit log path (default `~/.tiktok-ads-mcp/logs/audit.jsonl`) |
| `TIKTOK_ADS_AUDIT_RETENTION_DAYS` | no | Days to keep audit entries, pruned at startup (default 30; 0 keeps them) |
| `TIKTOK_ADS_MAX_QPS` | no | Requests per second this server sends (default 10) |
| `TIKTOK_ADS_MAX_DOWNLOAD_MB` | no | Largest report file it will download (default 200) |
| `TIKTOK_ADS_PAGE_SIZE`, `TIKTOK_ADS_TIMEOUT` | no | List page size (100) and request timeout in seconds (30) |
| `TIKTOK_ADS_HOME` | no | Folder for secrets, logs and `.env` (default `~/.tiktok-ads-mcp`) |
| `TIKTOK_ADS_TRANSPORT`, `TIKTOK_ADS_HOST`, `TIKTOK_ADS_PORT` | no | `stdio` (default), `streamable-http` (at `http://HOST:PORT/mcp`) or `sse` (deprecated by the MCP spec), and its bind address (default `127.0.0.1:8000`) |
| `TIKTOK_ADS_ALLOW_REMOTE` | no | `true` (or `--allow-remote`) lets HTTP transports bind to a non-loopback address. The server has no sign-in, so only do this behind your own authenticating proxy |
| `TIKTOK_ADS_LOG_LEVEL` | no | `DEBUG`, `INFO`, `WARNING` or `ERROR` (logs go to stderr) |

Settings are read from the environment, then `--env FILE` or `./.env`, then
`~/.tiktok-ads-mcp/.env`. CLI: `tiktok-ads-mcp run` (default), `auth`, `purge`,
`describe`, `version`.

## Example prompts

```text
Which TikTok campaigns spent the most last week, and what was their cost per result?
```

```text
Pause every ad group in the "Summer sale" campaign with a cost per purchase above 40. Dry-run first and show me the table.
```

```text
Create an Upgraded Smart+ Sales campaign for example.com with a 50 a day budget, paused, using the three newest videos.
```

```text
Raise the daily budget of my best-performing Traffic ad group by 15% from tomorrow.
```

## More docs

- [All tools, confirm words and the 2027 change](docs/tools.md)
- [Getting TikTok API access, step by step](docs/setup-tiktok-ads-api.md)
- [Terms, data handling and comparison with TikTok's MCP server](docs/terms-and-data.md)
- [Agent skill](skills/tiktok-ads-mcp/SKILL.md): setup and usage guide for agents
- [Changelog](CHANGELOG.md) and [security policy](SECURITY.md)

## Contributing and licence

Issues and pull requests are welcome on [this repository](https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp). See
[CONTRIBUTING.md](CONTRIBUTING.md).

Licensed under the [MIT License](LICENSE).

---

Try out [AI Shopping Feeds](https://aishoppingfeeds.com/), our shopping feed management tool (including Google Shopping feeds).
