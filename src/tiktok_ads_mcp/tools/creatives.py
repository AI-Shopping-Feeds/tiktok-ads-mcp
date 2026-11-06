"""Creative library: images, videos (upload by URL, look up, search) and identities."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ..client import TikTokAdsClient
from ._common import check_ids


def _check_media_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Pass a public http(s) URL that TikTok can fetch the file from.")
    return url.strip()


def register(mcp, client: TikTokAdsClient) -> None:
    def lookup_or_search(
        *,
        info_path: str,
        search_path: str,
        ids_key: str,
        ids: list[str] | None,
        filtering: dict[str, Any] | None,
        advertiser_id: str | None,
        max_results: int,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        aid = client.resolve_advertiser(advertiser_id)
        if ids:
            id_list = check_ids(ids, ids_key, 100)
            data = client.request("GET", info_path, params={"advertiser_id": aid, ids_key: id_list})
            items = data.get("list") if isinstance(data, dict) else None
            return {"count": len(items or []), "list": items or []}
        params: dict[str, Any] = {"advertiser_id": aid, **(extra or {})}
        if filtering:
            params["filtering"] = filtering
        items, truncated, page_info = client.paginate(
            search_path, params, max_results=max_results, max_page_size=100
        )
        return {
            "count": len(items),
            "total": page_info.get("total_number"),
            "truncated": truncated,
            "list": items,
        }

    @mcp.tool()
    def tiktok_ads_list_images(
        image_ids: list[str] | None = None,
        filtering: dict[str, Any] | None = None,
        advertiser_id: str | None = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """Look up images in the ad account's creative library by ID, or search them.

        With image_ids, returns those images (size, format, URL). Otherwise searches;
        filtering e.g. {"image_ids": [...], "material_ids": [...], "width": 1080}.
        """
        return lookup_or_search(
            info_path="/file/image/ad/info/",
            search_path="/file/image/ad/search/",
            ids_key="image_ids",
            ids=image_ids,
            filtering=filtering,
            advertiser_id=advertiser_id,
            max_results=max_results,
        )

    @mcp.tool()
    def tiktok_ads_list_videos(
        video_ids: list[str] | None = None,
        filtering: dict[str, Any] | None = None,
        advertiser_id: str | None = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """Look up videos in the ad account's creative library by ID, or search them.

        With video_ids, returns those videos (duration, size, cover, allowed
        placements). Otherwise searches; filtering e.g. {"video_ids": [...],
        "displayable": true}.
        """
        return lookup_or_search(
            info_path="/file/video/ad/info/",
            search_path="/file/video/ad/search/",
            ids_key="video_ids",
            ids=video_ids,
            filtering=filtering,
            advertiser_id=advertiser_id,
            max_results=max_results,
        )

    @mcp.tool()
    def tiktok_ads_upload_image(
        image_url: str,
        file_name: str | None = None,
        advertiser_id: str | None = None,
    ) -> dict[str, Any]:
        """Upload an image to the ad account's creative library from a public URL.

        TikTok fetches the file itself (JPG/PNG, under 50 MB). file_name must be
        unique in the account; add a timestamp if TikTok says it's taken. Returns
        the image_id to use in ads. Changes the account's library (dry-run aware).
        """
        aid = client.resolve_advertiser(advertiser_id)
        body: dict[str, Any] = {
            "advertiser_id": aid,
            "upload_type": "UPLOAD_BY_URL",
            "image_url": _check_media_url(image_url),
        }
        if file_name:
            body["file_name"] = file_name
        return client.request("POST", "/file/image/ad/upload/", json_body=body, op="upload_image")

    @mcp.tool()
    def tiktok_ads_upload_video(
        video_url: str,
        file_name: str | None = None,
        flaw_detect: bool = False,
        auto_fix_enabled: bool = False,
        auto_bind_enabled: bool = False,
        advertiser_id: str | None = None,
    ) -> dict[str, Any]:
        """Upload a video to the ad account's creative library from a public URL.

        TikTok fetches the file itself. flaw_detect checks for issues such as low
        resolution; auto_fix_enabled fixes them and auto_bind_enabled adds the fixed
        video to the library. Returns the video_id to use in ads (processing may
        take a moment; check with tiktok_ads_list_videos).
        """
        aid = client.resolve_advertiser(advertiser_id)
        body: dict[str, Any] = {
            "advertiser_id": aid,
            "upload_type": "UPLOAD_BY_URL",
            "video_url": _check_media_url(video_url),
        }
        if file_name:
            body["file_name"] = file_name
        if flaw_detect:
            body["flaw_detect"] = True
            body["auto_fix_enabled"] = auto_fix_enabled
            body["auto_bind_enabled"] = auto_bind_enabled
        return client.request("POST", "/file/video/ad/upload/", json_body=body, op="upload_video")

    @mcp.tool()
    def tiktok_ads_list_identities(
        identity_type: str | None = None,
        filtering: dict[str, Any] | None = None,
        advertiser_id: str | None = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """List identities ads can run as: CUSTOMIZED_USER (custom name and avatar),
        AUTH_CODE, TT_USER or BC_AUTH_TT (TikTok accounts).

        Ads need an identity_id and identity_type.
        """
        aid = client.resolve_advertiser(advertiser_id)
        params: dict[str, Any] = {"advertiser_id": aid}
        if identity_type:
            params["identity_type"] = identity_type.upper()
        if filtering:
            params["filtering"] = filtering
        items, truncated, _ = client.paginate(
            "/identity/get/",
            params,
            max_results=max_results,
            max_page_size=100,
            items_key="identity_list",
        )
        return {"count": len(items), "truncated": truncated, "identities": items}
