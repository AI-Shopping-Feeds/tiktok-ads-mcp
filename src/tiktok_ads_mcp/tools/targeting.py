"""Targeting helpers: locations, interest categories and audience size estimates."""

from __future__ import annotations

from typing import Any

from ..client import TikTokAdsClient

DEFAULT_PLACEMENTS = ["PLACEMENT_TIKTOK"]


def register(mcp, client: TikTokAdsClient) -> None:
    @mcp.tool()
    def tiktok_ads_search_locations(
        keywords: list[str],
        objective_type: str,
        placements: list[str] | None = None,
        geo_types: list[str] | None = None,
        region_codes: list[str] | None = None,
        advertiser_id: str | None = None,
    ) -> dict[str, Any]:
        """Find location targeting IDs (countries, states, cities, DMAs, postcodes) by name.

        objective_type is the campaign's objective (e.g. TRAFFIC). geo_types e.g.
        ["COUNTRY", "PROVINCE", "CITY"]; region_codes narrows to countries, e.g.
        ["GB"]. Use the returned IDs in location_ids / targeting_spec.
        """
        if not keywords:
            raise ValueError("Pass at least one keyword.")
        aid = client.resolve_advertiser(advertiser_id)
        body: dict[str, Any] = {
            "advertiser_id": aid,
            "objective_type": objective_type.upper(),
            "placements": placements or DEFAULT_PLACEMENTS,
            "search_type": "FUZZY_SEARCH",
            "keywords": [str(k) for k in keywords][:50],
        }
        if geo_types:
            body["geo_types"] = geo_types
        if region_codes:
            body["region_codes"] = region_codes
        return client.request("POST", "/tool/targeting/search/", json_body=body, read_only=True)

    @mcp.tool()
    def tiktok_ads_list_regions(
        objective_type: str,
        placements: list[str] | None = None,
        level_range: str | None = None,
        extra: dict[str, Any] | None = None,
        advertiser_id: str | None = None,
    ) -> dict[str, Any]:
        """List the locations an ad account can target for an objective and placement.

        level_range e.g. TO_COUNTRY or TO_CITY. extra adds other /tool/region/
        parameters (e.g. promotion_type, language).
        """
        aid = client.resolve_advertiser(advertiser_id)
        params: dict[str, Any] = {
            "advertiser_id": aid,
            "objective_type": objective_type.upper(),
            "placements": placements or DEFAULT_PLACEMENTS,
        }
        if level_range:
            params["level_range"] = level_range.upper()
        params.update(extra or {})
        return client.request("GET", "/tool/region/", params=params)

    @mcp.tool()
    def tiktok_ads_list_interest_categories(
        language: str | None = None,
        placements: list[str] | None = None,
        advertiser_id: str | None = None,
    ) -> dict[str, Any]:
        """List interest categories (IDs and names, with their hierarchy) for targeting.

        language e.g. "en". Use the IDs in interest_category_ids.
        """
        aid = client.resolve_advertiser(advertiser_id)
        params: dict[str, Any] = {"advertiser_id": aid}
        if language:
            params["language"] = language
        if placements:
            params["placements"] = placements
        return client.request("GET", "/tool/interest_category/", params=params)

    @mcp.tool()
    def tiktok_ads_estimate_audience_size(
        objective_type: str,
        optimization_goal: str,
        targeting: dict[str, Any],
        advertiser_id: str | None = None,
    ) -> dict[str, Any]:
        """Estimate how many people an ad group's targeting can reach. Changes nothing.

        targeting holds /ad/audience_size/estimate/ fields such as placement_type,
        placements, location_ids, age_groups, gender, languages,
        interest_category_ids and audience_ids.
        """
        if not isinstance(targeting, dict):
            raise ValueError("targeting must be an object.")
        aid = client.resolve_advertiser(advertiser_id)
        body = {
            **targeting,
            "advertiser_id": aid,
            "objective_type": objective_type.upper(),
            "optimization_goal": optimization_goal.upper(),
        }
        return client.request("POST", "/ad/audience_size/estimate/", json_body=body, read_only=True)
