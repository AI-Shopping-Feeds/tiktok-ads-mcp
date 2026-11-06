# Getting TikTok API access

This walks you through getting your own access to the TikTok API for Business
(Marketing API), step by step, without needing to be a developer. Allow about an
hour of your time, spread over **roughly a week** while TikTok reviews things.

Checked against TikTok's API for Business documentation on 6 November 2026. TikTok
changes its portal from time to time, so labels may differ slightly.

| Step | Who | Your time | Waiting |
|---|---|---|---|
| 1. TikTok For Business account | you | 5 minutes | none |
| 2. Register as a developer | you | 15 minutes | up to 3 business days |
| 3. Create a developer app | you | 15 minutes | 2 to 3 business days |
| 4. Authorise your ad accounts | the person who manages the ad accounts | 5 minutes | none |
| 5. Connect the server | you | 10 minutes | none |

**Don't need your own app?** TikTok's hosted
[TikTok for Business MCP Server](https://business-api.tiktok.com/portal/docs/tiktok-ads-mcp-server/v1.3)
needs no developer registration. This server is for when you want it on your own
machine with dry-run, confirm words, spend guards and an audit log. See
[terms-and-data.md](terms-and-data.md#how-this-compares-with-tiktoks-mcp-server).

## What you need first

- **A company.** TikTok doesn't onboard individual developers or personal accounts.
- **A company email address** on your company's own domain, not a free webmail
  address. TikTok suggests a shared alias such as `developers+tiktok@example.com` so
  the account doesn't depend on one person.
- **A public company website** on that same domain, describing your business.
- **Access to the ad accounts** you want to manage: you are an admin or operator
  on them in TikTok Ads Manager or a Business Center, or the person who is will
  do step 4 for you.

## 1. Create a TikTok For Business account

1. Go to the [TikTok API for Business portal](https://business-api.tiktok.com/portal)
   and click the registration button.
2. Enter the company email address (or a phone number) and a password, accept the
   terms, and click **Sign Up**.
3. Enter the verification code TikTok sends you.

If you already use TikTok Ads Manager with a company email, you can log in with
that account instead.

## 2. Register as a developer

1. On the portal, click **Become a Developer**.
2. Fill in your name and your company email, then click **Send Code** and enter the
   code.
3. Choose the type that fits you: **Direct Advertiser** (your own ads),
   **Agency** (ads for clients) or **Technology Company**.
4. Enter your company name and website. They should match your email domain; if
   they don't, explain why in the description.
5. Choose your **primary developer location**: where the people setting this up
   are based.
6. Describe how you'll use the API. Be specific, for example:

   > Example Ltd is an online retailer in the United Kingdom. We use the Marketing
   > API from an internal tool, run by our marketing team through an AI assistant,
   > to report on and manage our own TikTok ad campaigns, with every change
   > previewed and approved by a person first.

7. Click **Submit**. TikTok replies within **three business days**. If it's
   rejected, fix what the email says and resubmit.

## 3. Create a developer app

1. Once approved, log in to the portal and click **Create an App** (or **My Apps →
   Create App**).
2. **App name:** something descriptive about your own tool, for example
   "Example Ltd ads assistant". Don't put "TikTok" in the name.
3. **App description:** what it does and who uses it. For example:

   > Internal tool for Example Ltd's marketing team. It reads campaign data and
   > reports, and creates and edits campaigns, ad groups, ads, creatives and
   > audiences in our own ad accounts. It runs locally as an MCP server used
   > through an AI assistant; access is limited to our staff.

   Mention the AI assistant: TikTok's developer terms ask you to describe your use
   honestly (see [terms-and-data.md](terms-and-data.md)).
4. **Advertiser redirect URL:** add `http://localhost:8765/callback`. You can add up
   to 10. If TikTok rejects a localhost address, add a page on your company website
   instead (for example `https://www.example.com/tiktok-callback`; the page doesn't
   need to do anything) and use the paste method in step 4.
5. **Scope of permission:** tick only what you need. For this server that's usually:
   - **Ad Account Management** (ad account details, and Business Center if you
     manage ad accounts through one)
   - **Ads Management** (campaigns, ad groups, ads, Upgraded Smart+)
   - **Creative Management** (images, videos, identities)
   - **Audience Management** (custom and lookalike audiences)
   - **Reporting**
   - **Pixel Management** and **DPA Catalog Management** if you'll use those tools

   Leave out anything you won't use, such as TikTok Accounts, Lead Management or
   payments.
   You can add more later (**My Apps → your app → Scope of permission**), which
   needs another two-to-three-day review.
6. Click **Confirm**. TikTok reviews the app in **two to three business days**.
   **My Apps → Verification Status** shows where it is.
7. Once approved, open the app and note the **App ID** and **Secret** from **Basic
   Information**. Keep the secret in a password manager; never paste it into chat
   or commit it.

### Rate limits

New apps get TikTok's **Basic** limit: 10 requests a second and 600 a minute per
API endpoint, and 2 report tasks a second. That's plenty for one team. If you hit
it, you can ask for a higher level under **My Apps → your app**; TikTok raises one
level at a time. The server spaces its requests to `TIKTOK_ADS_MAX_QPS` (10).

## 4. Authorise your ad accounts

This gives your app a long-term access token for the ad accounts. It's done by the
TikTok For Business user who manages them (you, a colleague, or a client).

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) (`brew install uv`
on macOS), then run, with your own App ID and secret:

```shell
TIKTOK_ADS_APP_ID=123456789 TIKTOK_ADS_APP_SECRET=your-app-secret \
  uvx --from git+https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp.git tiktok-ads-mcp auth
```

1. A browser opens TikTok's authorisation page. Sign in as the user who manages the
   ad accounts.
2. Review the permissions, accept TikTok's agreement and click **Confirm**.
3. Click **Send Code** and enter the code TikTok emails to that user.
4. The browser goes to `localhost` and the terminal says the token is saved.

The token is saved to `~/.tiktok-ads-mcp/secrets/tiktok-ads-token.json`, readable
only by you, and the command lists the ad account IDs it can manage. The token
**doesn't expire**; it stops working if the advertiser removes your app's access.

**If the redirect doesn't reach your computer** (you used a website redirect URL,
or you're on a remote machine), run with `--manual --redirect-uri
https://www.example.com/tiktok-callback`. After step 3 you land on that page: copy
the whole address from the browser bar and paste it into the terminal. The command
checks the `state` in that address matches before using it.

You can also copy the **Advertiser authorization URL** from **My Apps → your app**
and pass it with `--auth-url '<that URL>'`; the command adds its own `state` to it.

### Agencies and clients

If you manage ads for clients, each client (or the client's Business Center admin)
does step 4, or shares their ad accounts with your Business Center first. Only
connect ad accounts whose owners have agreed, in writing, to you managing them
through the API. TikTok's developer terms also require anyone you share access
with (another agency, a freelancer) to accept those terms themselves. See
[terms-and-data.md](terms-and-data.md#agencies-and-clients).

### Upgraded Smart+

Reading and reporting on Upgraded Smart+ campaigns needs nothing extra. TikTok's
guide says creating and editing them may need your ad account allowlisted: if
`tiktok_ads_smart_plus_create_campaign` returns an allowlist error (code 40118),
ask your TikTok representative.

## 5. Connect the server

Find the IDs you'll need:

- **Ad account ID** (advertiser ID): printed by `auth`, or in TikTok Ads Manager in
  the account switcher (a long number). Set it as `TIKTOK_ADS_ADVERTISER_ID`; the
  server does this for you when the token covers only one account.
- **Business Center ID** (only for catalog tools): in Business Center, under
  **Business settings → Business info**. Set it as `TIKTOK_ADS_BC_ID`.

Check the settings were picked up (no secrets are printed):

```shell
uvx --from git+https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp.git tiktok-ads-mcp describe
```

Then add the server to your MCP client as shown in the
[README](../README.md#3-add-it-to-your-client), start with `TIKTOK_ADS_DRY_RUN=true`,
and ask your agent to "check the TikTok Ads connection".

## Removing access

- `tiktok-ads-mcp purge --revoke` revokes the token at TikTok and deletes the local
  token and audit log.
- The advertiser can remove your app at any time at
  [TikTok For Business → Authorizations](https://ads.tiktok.com/ac/page/authorizations).
- To stop using the API altogether, delete the app under **My Apps**.

## Troubleshooting

| Message | What to do |
|---|---|
| `Redirect Url Not Match` on TikTok's page | The redirect URL you used isn't on the app. Add it under **My Apps** or pass `--redirect-uri` with one that is. |
| `40110` / "Invalid auth code" | Codes last one hour and work once. Run `auth` again. |
| `40105` / "Access token is incorrect" | The advertiser removed access or the token was revoked. Run `auth` again. |
| `40001` / no permission | The app lacks that scope, or the advertiser didn't grant it. Add the scope, then re-authorise. |
| `40100` / requests too frequent | TikTok throttled your app. A per-minute block lasts about 5 minutes, a daily one until 00:00 UTC. |
| `40118` / allowlist | The feature (often Upgraded Smart+ creation) needs your TikTok representative. |
