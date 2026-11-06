# Contributing

Thanks for helping improve TikTok Ads MCP.

## Development setup

```bash
git clone https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp.git
cd tiktok-ads-mcp
uv venv && uv pip install -e ".[test,dev]"
```

Or with plain Python 3.11 or later:

```bash
python -m venv .venv && .venv/bin/pip install -e ".[test,dev]"
```

To try it against real ad accounts you need your own approved TikTok developer
app (see [docs/setup-tiktok-ads-api.md](docs/setup-tiktok-ads-api.md)). Keep
`TIKTOK_ADS_DRY_RUN=true` while you experiment.

## Checks

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src/tiktok_ads_mcp
.venv/bin/pytest
```

Tests run offline: HTTP is mocked with `respx`. They never touch a real ad
account. `pre-commit install` runs ruff and mypy on each commit.

## Pull requests

- Keep secrets, tokens, app IDs and ad account data out of commits, tests and
  issues. Use obviously fake values in tests.
- New tools go in the matching module under `src/tiktok_ads_mcp/tools/`, use the
  `tiktok_ads_` prefix, and need an entry in `src/tiktok_ads_mcp/tool_catalog.py`
  (title and annotations) and a row in `docs/tools.md`. The test suite fails if
  either is missing.
- Writes go through `client.request` (so dry-run and the audit log apply), read a
  before-snapshot where they can, and use `safety.assess` / `safety.refusal` for
  confirm words: `DELETE` for deletes, `APPLY` for enabling delivery, bulk
  changes and bid or budget rises.
- Only call `business-api.tiktok.com` (and TikTok hosts for report files).
- Don't paste TikTok's API documentation, specifications, SDK or sample code into
  the repository; TikTok's developer terms don't allow copying them. Describe
  fields in your own words and link to TikTok's docs.
- Update the README, CHANGELOG and skill when tools, settings or setup change.
