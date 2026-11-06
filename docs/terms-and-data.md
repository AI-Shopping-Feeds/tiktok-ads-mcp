# Terms, data handling and comparisons

Using the TikTok API for Business means accepting TikTok's terms. This page
summarises what they mean for this server, how the server is built to fit them,
and what to check before using it with AI clients, publicly or for clients. It's
a summary, not legal advice: read the terms yourself, and check them again
before relying on this page, because TikTok updates them.

Reviewed on 6 November 2026.

## Which terms apply

| Document | What it covers here |
|---|---|
| [TikTok For Business Commercial Terms of Service](https://ads.tiktok.com/i18n/official/policy/commercial-terms-of-service) | The base agreement for TikTok's business products. Its supplemental-terms list says that if you use the API for Business developer tools, "you agree to the TikTok For Business Developer Terms". Section 7 limits how TikTok Data (performance data and reports) may be used. |
| [TikTok For Business Developer Terms](https://ads.tiktok.com/i18n/official/article?aid=10022349) (last modified 30 September 2024) | The API itself: the developer site, documentation, SDK and Marketing API. Includes an Acceptable Use Policy. |
| [Business Products (Data) Terms](https://ads.tiktok.com/i18n/official/policy/business-products-terms), [Custom Audience (Customer File) Terms](https://ads.tiktok.com/i18n/official/policy/custom-audience-terms), [Lead Generation Terms](https://ads.tiktok.com/i18n/official/policy/lead-gen-terms), [Controller to Controller Data Terms](https://ads.tiktok.com/i18n/official/policy/controller-to-controller), [Jurisdiction Specific Terms](https://ads.tiktok.com/i18n/official/policy/jurisdiction-specific-terms) | Sending events or customer lists to TikTok, and receiving leads. This server's dedicated tools don't do any of these; they're only reachable through the escape hatch. |
| [Advertising Terms](https://ads.tiktok.com/i18n/official/policy/advertising-terms) and [Advertising Policies](https://ads.tiktok.com/help/article?aid=10000962) | The ads you create, and acting as an agent for another advertiser. |
| [TikTok Partner Privacy Policy](https://www.tiktok.com/legal/partner-privacy-policy) | How TikTok handles your data as a business partner. |
| [Creative GenAI Terms](https://ads.tiktok.com/i18n/official/article?aid=10021580) | TikTok's generative AI creative features, if you switch them on (for example automatic creative enhancements in Upgraded Smart+). |

The separate [TikTok Developer Terms of Service](https://www.tiktok.com/legal/page/global/tik-tok-developer-terms-of-service/en)
cover TikTok for Developers (developers.tiktok.com: Login Kit, Content Posting and
so on), not the API for Business. They're mentioned below only where they show
how TikTok thinks about naming.

## What the terms require, and how this server handles it

- **Use the API as documented, within its limits.** The Developer Terms (D.1) tie
  use to TikTok's documentation, "including any request, rate, size and other
  limits". The server only calls documented v1.3 endpoints, spaces requests to
  `TIKTOK_ADS_MAX_QPS` (10, TikTok's Basic level), backs off when TikTok returns a
  throttling code (40100, 40016, 40133) and doesn't resend writes that may have
  gone through.
- **No TikTok materials in the repository.** The Acceptable Use Policy (2(a))
  forbids copying or making derivative works of the "TikTok Technology Services",
  which include the documentation and SDK. This repository contains its own client
  code and tool descriptions only: no API specifications, documentation text, SDK
  code or sample code. It uses `httpx`, not TikTok's SDK.
- **Only TikTok hosts.** The server talks only to `business-api.tiktok.com` and,
  for report files, TikTok-owned hosts (`*.tiktok.com`). No telemetry. The escape
  hatch takes paths, not URLs, and refuses OAuth endpoints so the app secret never
  passes through a tool.
- **Credentials stay confidential.** The Acceptable Use Policy (1(j)) says to keep
  tokens, keys and credentials confidential, and the Commercial Terms (4.5) say not
  to share them. The access token is stored owner-only (0600, folder 0700) in
  `~/.tiktok-ads-mcp/secrets/`; the token and app secret are redacted from logs,
  errors and the audit log; `describe` and `describe_server` never print them.
- **Data use is limited.** Commercial Terms section 7 lets you use TikTok Data
  "solely" to plan and manage your use of TikTok's products, and in aggregated,
  anonymised form to assess their performance; not to share it with third parties
  except people acting for you, de-anonymise it, or build profiles or segments of
  users. The Developer Terms (AUP 2(k)) also forbid building profiles of
  individuals. The server's instructions tell the agent this.
- **Keep data only as long as needed; delete it when access ends.** On termination,
  or when an advertiser removes your access, the Commercial Terms (4.5) and
  Developer Terms (G.1) require deleting TikTok data. The audit log holds only
  write requests, before-snapshots and write responses (never read results or
  report rows), entries older than `TIKTOK_ADS_AUDIT_RETENTION_DAYS` (30) are
  deleted at startup, and reports are parsed in memory and capped at
  `TIKTOK_ADS_MAX_DOWNLOAD_MB`. `tiktok-ads-mcp purge` deletes the audit log and
  token, and `purge --revoke` also revokes the token at TikTok.
- **Report compromises.** The Acceptable Use Policy (1(e)) says to disconnect and
  report to TikTok if you find a compromise. [SECURITY.md](../SECURITY.md) explains
  how, and how to revoke access.
- **No implied endorsement, no logos.** The Acceptable Use Policy (2(q)) forbids
  implying "any inaccurate affiliation, sponsorship, or endorsement". "TikTok" is
  used only to say what the server works with, with a "Not affiliated with or
  endorsed by TikTok" line, and no TikTok logos.
- **No benchmarking.** The Acceptable Use Policy (2(w)) forbids using the API to
  monitor TikTok's availability or performance. `tiktok_ads_health_check` makes one
  call when asked; don't run it on a schedule as an uptime monitor.
- **Retired flows.** TikTok's notice that Legacy Manual Flow creation for Sales, App
  Promotion and Lead Generation ends on 1 January 2027 is built into the tools (see
  [tools.md](tools.md#which-tools-create-what-and-the-2027-change)).

## Things to check before you rely on it

### (a) Using it with AI clients such as Claude

**Not a blocker, but the terms don't address AI clients, so set it up carefully.**

- When your MCP client calls a tool, the result (campaign names, budgets, report
  rows) is sent to the AI model your client uses. The Developer Terms (D.2) say not
  to make TikTok Information available to third parties except the End User it
  relates to, and the Commercial Terms (7.2(a)) allow sharing only with "persons
  acting on your behalf". An AI provider processing your requests under business
  or API terms, as your processor and without training on your inputs, is the
  closest fit. Avoid consumer plans that train on chats.
- The Acceptable Use Policy (2(c)) says not to "combine" TikTok's services with
  software "not authorized by TikTok". Describe the MCP server and AI assistant
  plainly in your developer app description (TikTok approves the app on that
  basis), as the setup guide suggests.
- TikTok itself offers its hosted MCP server for Claude, ChatGPT and Cursor, which
  suggests it accepts agent access to ad data in principle. That's TikTok's own
  product, though, not a permission for third-party servers.

### (b) Making the repository public under a name containing "TikTok"

**Not a blocker for the code; the name is the main risk.**

- The code contains no TikTok materials and is MIT-licensed. That's fine: the
  restriction on distributing "TikTok Technology Services" (AUP 2(a)) covers
  TikTok's own services and documentation, not independent client code.
- The name uses TikTok's trademark descriptively, with a disclaimer and no logos.
  But TikTok's [App Review Guidelines](https://developers.tiktok.com/doc/app-review-guidelines)
  for its developer platform say an app name "should not include a reference to
  social media companies", and TikTok has its own "TikTok for Business MCP Server",
  so a "TikTok Ads MCP Server" could be read as implying a link. Be ready to rename
  (for example to `ads-mcp-for-tiktok`) if TikTok asks, and don't name your
  developer app after TikTok.
- The Acceptable Use Policy (1(h)(g)) says Application Content must not "be placed on
  a search engine or directory" without TikTok's written consent. It's unclear
  whether an open-source tool counts as Application Content, so don't list the
  server in MCP registries or directories (or TikTok's own Agentic Hub, which has
  its own terms) without checking with TikTok first. Publishing on GitHub is how
  the sibling servers are distributed.

### (c) Agencies using it for clients

**Allowed, with paperwork.**

- The Developer Terms also cover companies using the API "on behalf of another
  entity such as an advertiser". Register as an **Agency** developer.
- Only connect ad accounts whose owners have authorised you; acting as an agent,
  you confirm you're authorised to bind the client (Advertising Terms 1.2).
- If you handle personal information for a client (for example leads or audience
  data), you need a written processor agreement with them (Developer Terms D.3),
  and TikTok can ask for a list of your clients and those agreements (D.6, E.3).
- Anyone else you give access to (a sub-agency, freelancer or software vendor) is a
  "Technology Partner" who must "independently" accept the Developer Terms first
  (E.1), and you're responsible for what they do (E.2).
- Use one client's data only for that client (D.4), keep each client's data apart,
  and delete it when they remove your access (Commercial Terms 4.5).
  `TIKTOK_ADS_ALLOWED_ADVERTISER_IDS` limits a server process to one client's
  accounts.

## How this compares with TikTok's MCP server

TikTok's [TikTok for Business MCP Server](https://business-api.tiktok.com/portal/docs/tiktok-ads-mcp-server/v1.3)
is a hosted server (`https://business-api.tiktok.com/open_mcp/tt-ads-mcp-flat`
with about 400 tools, or `.../tt-ads-mcp-layer`, which starts with about 40 and
loads more on demand). It needs only a TikTok For Business account, no developer
app, and is listed in Claude's connector directory. Write tools are included. If
you want TikTok-maintained tools with the least setup, look at it first.

| | This server | TikTok's MCP server |
|---|---|---|
| Where it runs | On your machine (or your own private server) | Hosted by TikTok |
| Setup | Your own developer app (about a week of TikTok reviews) | Sign in with TikTok For Business; no developer app |
| Sign-in | Long-term access token that doesn't expire until revoked | Renewed every 30 days (or use your own API token) |
| Rate limit | Your app's level (Basic: 10 requests a second per endpoint) | 6 requests a second per tool per user |
| Tools | 65, curated, with an escape hatch for the rest | About 400 (or about 40 loaded progressively) |
| Dry-run | Rehearse any write and see exactly what would be sent | Not documented |
| Confirm words and spend guards | Deletes, enabling delivery, bulk changes, bid/budget rises and caps | Not documented |
| Audit log | Every write with a before-snapshot, local JSONL, 30-day retention | Not documented |
| Read-only mode and tool groups | `TIKTOK_ADS_READ_ONLY`, `TIKTOK_ADS_TOOL_GROUPS` | Progressive tool loading |
| Account allowlist | `TIKTOK_ADS_ALLOWED_ADVERTISER_IDS` | Whatever the signed-in user can reach |
| Code | Open source (MIT) | Closed, operated by TikTok |

## TikTok's own SDK

TikTok publishes a [Business API SDK](https://github.com/tiktok/tiktok-business-api-sdk)
(MIT licence, generated with swagger-codegen, Python, JavaScript and Java). Its
Python package isn't on PyPI, depends on `urllib3` and `six`, and covers a subset
of endpoints. This server uses a thin `httpx` client instead, so dry-run, the audit
log, confirm guards, redaction and the escape hatch all go through one request
path. No SDK code is copied here.
