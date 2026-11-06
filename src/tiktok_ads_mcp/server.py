"""Build the MCP server. Stays import-light so tests can patch pieces individually."""

from __future__ import annotations

import functools
import inspect
import time
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__, tools
from ._logging import configure_default, get_logger
from .audit import AuditLog
from .auth import AuthError, load_auth, redact
from .client import TikTokAdsAPIError, TikTokAdsClient
from .config import API_BASE, Config, load_config
from .tool_catalog import ALWAYS_REGISTERED, TOOL_SPECS
from .tools.accounts import list_authorized_advertisers

logger = get_logger("server")

INSTRUCTIONS = """\
TikTok Marketing API v1.3: ad accounts, campaigns, ad groups, ads, Upgraded Smart+, creatives, audiences, catalogs, reports.
Start with tiktok_ads_describe_server and tiktok_ads_health_check; pick an advertiser_id from tiktok_ads_list_advertisers.
Writes change live ads and spend. Rehearse in dry-run (tiktok_ads_set_dry_run) and show the user what will change first.
Deletes need confirm='DELETE'; enabling delivery, big batches and bid or budget rises above the limit need confirm='APPLY'.
New Sales, App Promotion and Lead Generation campaigns use the tiktok_ads_smart_plus_* tools; new items start paused.
Every write is in the audit log (tiktok_ads_audit_tail) with a before-snapshot where available.
Use TikTok data only to manage and report on these ads: don't share it beyond the user's team or profile individuals.
Tools can be limited with TIKTOK_ADS_TOOL_GROUPS (module names) or TIKTOK_ADS_READ_ONLY=true."""

# Errors whose message helps the agent fix the call (bad arguments, a refusal,
# TikTok API errors, token problems, permissions or config problems).
_EXPECTED_ERRORS = (
    ValueError,
    RuntimeError,
    PermissionError,
    FileNotFoundError,
    TikTokAdsAPIError,
    httpx.HTTPError,
)


def _as_tool_error(fn):
    """Re-raises expected errors as ToolError so MCP SDK 2 shows their message.

    SDK 2 hides the text of any other exception from the client. Messages are
    redacted so tokens and secrets never reach the client.
    """
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except _EXPECTED_ERRORS as exc:
                raise ToolError(redact(str(exc))) from exc

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _EXPECTED_ERRORS as exc:
            raise ToolError(redact(str(exc))) from exc

    return wrapper


class TikTokAdsMCPServer(MCPServer):
    """MCPServer whose tools report expected errors to the client.

    Each tool gets its title and annotations from `tool_catalog.TOOL_SPECS`
    unless the decorator passes them. With `read_only=True`, tools that are not
    annotated read-only are skipped (the meta tools are always registered).
    """

    def __init__(self, *args: Any, read_only: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.read_only = read_only

    def tool(  # type: ignore[override]
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        **kwargs: Any,
    ):
        def decorator(fn):
            tool_name = name or fn.__name__
            spec = TOOL_SPECS.get(tool_name)
            tool_title = title or (spec.title if spec else None)
            tool_annotations = annotations or (spec.annotations if spec else None)
            is_read_only = bool(tool_annotations and tool_annotations.read_only_hint)
            if self.read_only and not is_read_only and tool_name not in ALWAYS_REGISTERED:
                return fn
            register = super(TikTokAdsMCPServer, self).tool(
                name=tool_name,
                title=tool_title,
                description=description,
                annotations=tool_annotations,
                **kwargs,
            )
            register(_as_tool_error(fn))
            return fn

        return decorator


def build_server(config: Config | None = None, env_file: Path | None = None) -> MCPServer:
    """Construct an MCPServer instance with all tiktok_ads_* tools registered."""
    configure_default()
    if config is None:
        config = load_config(env_file=env_file)
    groups = tools.resolve_tool_groups(config.tool_groups)  # fail fast on unknown groups

    auth = load_auth(config)
    audit = AuditLog(config.audit_log, retention_days=config.audit_retention_days)
    pruned = audit.prune()
    if pruned:
        logger.info(
            "pruned %d audit entries older than %d days", pruned, config.audit_retention_days
        )
    client = TikTokAdsClient(config, auth, audit)

    logger.info(
        "starting tiktok-ads-mcp advertiser=%s auth=%s dry_run=%s",
        config.advertiser_id or "-",
        auth.account_label,
        config.dry_run,
    )

    mcp = TikTokAdsMCPServer(
        "tiktok-ads-mcp",
        title="TikTok Ads",
        version=__version__,
        instructions=INSTRUCTIONS,
        read_only=config.read_only,
    )

    @mcp.tool()
    def tiktok_ads_describe_server() -> dict[str, Any]:
        """Show the API version, default ad account and safety settings this server uses."""
        return {
            "version": __version__,
            "api_base": API_BASE,
            "default_advertiser_id": config.advertiser_id,
            "default_bc_id": config.bc_id,
            "allowed_advertiser_ids": config.allowed_advertiser_ids or "all",
            "auth": auth.account_label,
            "app_credentials": bool(config.app_id and config.app_secret),
            "dry_run": config.dry_run,
            "read_only": config.read_only,
            "tool_groups": config.tool_groups or "all",
            "bulk_threshold": config.bulk_threshold,
            "max_increase_pct": config.max_increase_pct,
            "max_budget": config.max_budget,
            "max_bid": config.max_bid,
            "max_qps": config.max_qps,
            "audit_log": str(config.audit_log),
            "audit_retention_days": config.audit_retention_days,
            "max_download_mb": config.max_download_mb,
            "page_size": config.page_size,
            "timeout": config.timeout,
            "transport": config.transport,
        }

    @mcp.tool()
    def tiktok_ads_health_check() -> dict[str, Any]:
        """Check the setup: the access token works and which ad accounts it can reach."""
        checks: list[dict[str, Any]] = []
        advertisers: list[dict[str, Any]] = []
        notes: list[str] = []
        t0 = time.time()
        if config.app_id and config.app_secret:
            try:
                advertisers = list_authorized_advertisers(client)
                checks.append(
                    {"check": "list_advertisers", "ok": True, "ms": int((time.time() - t0) * 1000)}
                )
            except Exception as e:
                checks.append(
                    {"check": "list_advertisers", "ok": False, "error": redact(str(e))[:300]}
                )
        else:
            notes.append(
                "Set TIKTOK_ADS_APP_ID and TIKTOK_ADS_APP_SECRET to list every authorised ad account."
            )
        if config.advertiser_id:
            t0 = time.time()
            try:
                data = client.request(
                    "GET",
                    "/advertiser/info/",
                    params={
                        "advertiser_ids": [config.advertiser_id],
                        "fields": ["advertiser_id", "name", "status", "currency", "timezone"],
                    },
                )
                info = (data.get("list") or [{}])[0] if isinstance(data, dict) else {}
                checks.append(
                    {
                        "check": "default_advertiser",
                        "ok": True,
                        "ms": int((time.time() - t0) * 1000),
                        "advertiser": info,
                    }
                )
            except Exception as e:
                checks.append(
                    {"check": "default_advertiser", "ok": False, "error": redact(str(e))[:300]}
                )
        else:
            notes.append(
                "No default ad account: set TIKTOK_ADS_ADVERTISER_ID or pass advertiser_id."
            )
        if not checks:
            notes.append("Nothing to check yet; the token is only tested by an API call.")
        if config.dry_run:
            notes.append("Dry-run is on: writes are previewed, not sent.")
        return {
            "ok": bool(checks) and all(c["ok"] for c in checks),
            "checks": checks,
            "advertisers": [
                {"advertiser_id": a.get("advertiser_id"), "name": a.get("advertiser_name")}
                for a in advertisers
            ],
            "notes": notes,
        }

    @mcp.tool()
    def tiktok_ads_audit_lookup(audit_id: str) -> dict[str, Any]:
        """Look up an audit log entry by ID: the request, response and before-snapshot of a write."""
        entry = audit.find(audit_id)
        if not entry:
            return {"found": False, "audit_id": audit_id}
        return {"found": True, "entry": entry}

    @mcp.tool()
    def tiktok_ads_audit_tail(limit: int = 20) -> dict[str, Any]:
        """Show the most recent audit log entries (writes and dry-run rehearsals)."""
        entries = audit.tail(limit)
        return {"count": len(entries), "entries": entries}

    @mcp.tool()
    def tiktok_ads_set_dry_run(enabled: bool) -> dict[str, Any]:
        """Turn dry-run on or off for this session. In dry-run, writes are recorded in
        the audit log and returned as a preview but NOT sent to TikTok; reads still work."""
        client.config.dry_run = enabled
        logger.info("dry_run=%s (set via tool)", enabled)
        return {"dry_run": enabled}

    for group in groups:
        getattr(tools, group).register(mcp, client)

    logger.info(
        "registered %d tools (groups=%s read_only=%s)",
        len(mcp._tool_manager.list_tools()),
        ",".join(config.tool_groups) or "all",
        config.read_only,
    )
    return mcp


__all__ = ["INSTRUCTIONS", "AuthError", "build_server"]
