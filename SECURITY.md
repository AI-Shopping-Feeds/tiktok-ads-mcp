# Security

This server can create, change, pause and delete TikTok campaigns, ad groups,
ads, audiences and product sets, change budgets and bids (so it can spend
money), upload creatives and read performance data, using a long-term access
token the advertiser granted to your developer app.

## Protect your credentials

- The access token lives in `~/.tiktok-ads-mcp/secrets/tiktok-ads-token.json`
  (folder 0700, file 0600). Keep it that way, and never commit it, paste it into
  chat or put it in a shared client config.
- Keep the developer app's **Secret** in a password manager or in
  `~/.tiktok-ads-mcp/.env`. Anyone with the App ID, Secret and a token can manage
  the authorised ad accounts.
- The token doesn't expire on its own. If a machine is lost or you suspect a leak:
  1. run `tiktok-ads-mcp purge --revoke` (revokes the token at TikTok and deletes
     local copies), or ask the advertiser to remove the app at
     [TikTok For Business → Authorizations](https://ads.tiktok.com/ac/page/authorizations);
  2. reset the app secret under **My Apps** on the
     [TikTok API for Business portal](https://business-api.tiktok.com/portal);
  3. check the audit log (`~/.tiktok-ads-mcp/logs/audit.jsonl`) and TikTok Ads
     Manager's history for changes you didn't make.
- Use `TIKTOK_ADS_READ_ONLY=true` where you only need reports, and
  `TIKTOK_ADS_ALLOWED_ADVERTISER_IDS` to limit which ad accounts it can touch.

## Don't expose the HTTP transport

The `streamable-http` and `sse` transports have no sign-in: anyone who can reach
the port can use your TikTok access. The server refuses to bind to anything but
`127.0.0.1`, `localhost` or `::1` unless you set `TIKTOK_ADS_ALLOW_REMOTE=true`
(or `--allow-remote`). Only do that behind your own authenticating proxy.

## Reporting issues

Report vulnerabilities privately through a
[GitHub private security advisory](https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp/security/advisories/new)
on this repository, or contact the maintainers at
[AI Shopping Feeds](https://github.com/AI-Shopping-Feeds). Don't post working
exploits, tokens or ad account data in a public issue.

If you think TikTok data has been exposed or misused through this server, tell us
the same way. If it involves your own credentials, also disconnect (revoke the
token as above) and report it to TikTok through the
[Developer Ticket Platform](https://business-api.tiktok.com/portal) or your TikTok
representative: TikTok's developer terms ask you to report compromises.
