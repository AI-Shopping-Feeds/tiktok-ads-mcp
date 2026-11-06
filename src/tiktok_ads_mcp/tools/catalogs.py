"""Catalogs, products and product sets (Business Center scoped).

Catalog endpoints take a Business Center ID (bc_id, default TIKTOK_ADS_BC_ID)
instead of an advertiser ID. Product uploads and feed schedules are left to the
escape hatch; product sets can be created, changed and deleted here.
"""

from __future__ import annotations

from typing import Any

from .. import safety
from ..client import TikTokAdsClient
from ._common import check_ids


def register(mcp, client: TikTokAdsClient) -> None:
    def scope(catalog_id: str, bc_id: str | None) -> dict[str, Any]:
        return {
            "bc_id": client.resolve_bc(bc_id),
            "catalog_id": check_ids([catalog_id], "catalog_id", 1)[0],
        }

    def product_sets(params: dict[str, Any]) -> list[dict[str, Any]]:
        data = client.request("GET", "/catalog/set/get/", params=params)
        items = data.get("list") if isinstance(data, dict) else None
        return [i for i in (items or []) if isinstance(i, dict)]

    @mcp.tool()
    def tiktok_ads_list_catalogs(
        bc_id: str | None = None, catalog_id: str | None = None, max_results: int = 100
    ) -> dict[str, Any]:
        """List catalogs in a Business Center: ID, name, type, region and currency."""
        params: dict[str, Any] = {"bc_id": client.resolve_bc(bc_id)}
        if catalog_id:
            params["catalog_id"] = check_ids([catalog_id], "catalog_id", 1)[0]
        items, truncated, _ = client.paginate(
            "/catalog/get/", params, max_results=max_results, max_page_size=500
        )
        return {"count": len(items), "truncated": truncated, "catalogs": items}

    @mcp.tool()
    def tiktok_ads_get_catalog_overview(
        catalog_id: str, bc_id: str | None = None
    ) -> dict[str, Any]:
        """Count a catalog's products by review status (approved, processing, rejected)."""
        data = client.request("GET", "/catalog/overview/", params=scope(catalog_id, bc_id))
        return data if isinstance(data, dict) else {"result": data}

    @mcp.tool()
    def tiktok_ads_list_catalog_products(
        catalog_id: str,
        product_ids: list[str] | None = None,
        sku_ids: list[str] | None = None,
        product_set_ids: list[str] | None = None,
        bc_id: str | None = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """List products in a catalog (title, price, availability, image, review status).

        Filter by product_ids, sku_ids or product_set_ids (products in those sets).
        """
        params = scope(catalog_id, bc_id)
        if product_ids:
            params["product_ids"] = [str(p) for p in product_ids][:500]
        if sku_ids:
            params["sku_ids"] = [str(s) for s in sku_ids][:500]
        if product_set_ids:
            params["product_set_ids"] = check_ids(product_set_ids, "product_set_ids", 20)
        items, truncated, _ = client.paginate(
            "/catalog/product/get/", params, max_results=max_results, max_page_size=500
        )
        return {"count": len(items), "truncated": truncated, "products": items}

    @mcp.tool()
    def tiktok_ads_list_product_sets(
        catalog_id: str,
        product_set_id: str | None = None,
        return_product_count: bool = False,
        bc_id: str | None = None,
    ) -> dict[str, Any]:
        """List a catalog's product sets with their filter conditions."""
        params = scope(catalog_id, bc_id)
        if product_set_id:
            params["product_set_id"] = check_ids([product_set_id], "product_set_id", 1)[0]
        if return_product_count:
            params["return_product_count"] = True
        items = product_sets(params)
        return {"count": len(items), "product_sets": items}

    @mcp.tool()
    def tiktok_ads_create_product_set(
        catalog_id: str,
        product_set_name: str,
        conditions: dict[str, Any],
        bc_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a product set from filter conditions. Changes the catalog.

        conditions e.g. {"and": [{"field": "brand", "operation": "EQ", "value": "Acme"},
        {"field": "price", "operation": "GT", "value": "20"}]}.
        """
        if not isinstance(conditions, dict) or not conditions:
            raise ValueError("conditions must be an object.")
        body = {
            **scope(catalog_id, bc_id),
            "product_set_name": product_set_name,
            "conditions": conditions,
        }
        return client.request(
            "POST", "/catalog/set/create/", json_body=body, op="create_product_set"
        )

    @mcp.tool()
    def tiktok_ads_update_product_set(
        catalog_id: str,
        product_set_id: str,
        product_set_name: str | None = None,
        conditions: dict[str, Any] | None = None,
        bc_id: str | None = None,
    ) -> dict[str, Any]:
        """Rename a product set or replace its conditions. Ads using the set change too."""
        base = scope(catalog_id, bc_id)
        sid = check_ids([product_set_id], "product_set_id", 1)[0]
        body: dict[str, Any] = {**base, "product_set_id": sid}
        if product_set_name is not None:
            body["product_set_name"] = product_set_name
        if conditions is not None:
            body["conditions"] = conditions
        if len(body) == 3:
            raise ValueError("Nothing to change: pass product_set_name or conditions.")
        before = client.snapshot(product_sets, {**base, "product_set_id": sid})
        return client.request(
            "POST", "/catalog/set/update/", json_body=body, op="update_product_set", before=before
        )

    @mcp.tool()
    def tiktok_ads_delete_product_sets(
        catalog_id: str,
        product_set_ids: list[str],
        bc_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Delete product sets from a catalog. This can't be undone.

        Needs confirm='DELETE' after the user agrees.
        """
        base = scope(catalog_id, bc_id)
        ids = check_ids(product_set_ids, "product_set_ids", 100)
        decision = safety.assess(client.config, count=len(ids), destructive=safety.DELETE)
        body = {**base, "product_set_ids": ids}
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        before = client.snapshot(product_sets, base)
        if isinstance(before, list):
            before = [s for s in before if str(s.get("product_set_id")) in ids]
        out = client.request(
            "POST", "/catalog/set/delete/", json_body=body, op="delete_product_sets", before=before
        )
        return safety.annotate(out, decision)
