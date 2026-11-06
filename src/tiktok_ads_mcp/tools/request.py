"""Escape hatch: call any TikTok Marketing API v1.3 endpoint on business-api.tiktok.com."""

from __future__ import annotations

import re
from typing import Any

from .. import safety
from ..client import TikTokAdsClient

# POST endpoints that only read or estimate: searches, estimates,
# recommendations, previews, diagnoses, checks and report tasks.
_READ_POST = re.compile(
    r"(/search/$|/estimate/$|/recommend/$|/preview/$|/diagnosis/|/check/$"
    r"|^/report/task/create/$|^/report/task/cancel/$|^/smart_plus/material_report/)",
    re.IGNORECASE,
)
# Endpoints that need the app secret; refused so the secret is never sent
# through these tools.
_BLOCKED = ("/oauth2/",)


def _classify(method: str, path: str) -> tuple[str, bool]:
    method = method.upper()
    if method not in {"GET", "POST"}:
        raise ValueError("method must be GET or POST (TikTok's API uses only these).")
    TikTokAdsClient.check_path(path)
    if path.startswith(_BLOCKED):
        raise ValueError("OAuth endpoints aren't available here; use the tiktok-ads-mcp CLI.")
    is_read = method == "GET" or bool(_READ_POST.search(path))
    return method, is_read


def register(mcp, client: TikTokAdsClient) -> None:
    @mcp.tool()
    def tiktok_ads_read_request(
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Read from any TikTok Marketing API endpoint the other tools don't cover.

        Only GET, and POSTs to search/estimate/recommend/preview/diagnosis/check
        and report-task endpoints, are allowed; use tiktok_ads_request for
        writes. path is relative to https://business-api.tiktok.com/open_api/v1.3,
        e.g. '/campaign/copy/task/check/'. For GET, put parameters in query; lists
        and objects are sent as JSON as TikTok expects. Include advertiser_id (or
        bc_id) yourself.
        """
        method, is_read = _classify(method, path)
        if not is_read:
            raise ValueError(f"{method} {path} may change the account; use tiktok_ads_request.")
        return client.request(method, path, params=query, json_body=body, read_only=True)

    @mcp.tool()
    def tiktok_ads_request(
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        confirm: str = "",
    ) -> Any:
        """Call any TikTok Marketing API endpoint the other tools don't cover.

        path is relative to https://business-api.tiktok.com/open_api/v1.3 and
        starts with '/', e.g. '/catalog/product/update/'. GET calls and read-only
        POSTs (searches, estimates, report tasks) are reads. Every other POST is a
        write: it is audited, follows dry-run and needs confirm='APPLY', because
        this tool can't check what it changes. TikTok may reject creates on
        retired flows (see docs/tools.md).
        """
        method, is_read = _classify(method, path)
        if not is_read:
            decision = safety.Decision(
                required=safety.APPLY,
                reasons=["raw write through tiktok_ads_request; its effect isn't checked"],
            )
            refused = safety.refusal(
                client.config,
                decision,
                confirm,
                preview={"method": method, "path": path, "query": query, "body": body},
            )
            if refused:
                return refused
        return client.request(
            method,
            path,
            params=query,
            json_body=body,
            read_only=is_read,
            op=f"request {method} {path}",
        )
