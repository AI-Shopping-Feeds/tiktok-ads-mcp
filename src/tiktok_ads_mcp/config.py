"""Configuration from environment variables (and optional .env files).

Local files live in a per-user folder, `~/.tiktok-ads-mcp/` by default (or
TIKTOK_ADS_HOME), so nothing depends on where the package is installed:

* `secrets/tiktok-ads-token.json`: the access token saved by `tiktok-ads-mcp auth`
  (folder 0700, file 0600);
* `logs/audit.jsonl`: the audit log of writes (folder 0700, file 0600);
* `.env`: optional settings, read after `--env` and `./.env`.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

APP_DIR_NAME = ".tiktok-ads-mcp"
DEFAULT_AUDIT_LOG_NAME = "audit.jsonl"
DEFAULT_TOKEN_NAME = "tiktok-ads-token.json"

# TikTok API for Business, Marketing API v1.3 (the current version).
API_HOST = "https://business-api.tiktok.com"
API_VERSION = "v1.3"
API_BASE = f"{API_HOST}/open_api/{API_VERSION}"
# Page where an advertiser grants a developer app access (the "Advertiser
# authorization URL" in My Apps points here).
AUTHORIZE_URL = f"{API_HOST}/portal/auth"

# "sse" (HTTP+SSE) is deprecated by the MCP spec; prefer "streamable-http".
TRANSPORTS = ("stdio", "streamable-http", "sse")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def app_home() -> Path:
    """The per-user folder for secrets and logs (TIKTOK_ADS_HOME, default ~/.tiktok-ads-mcp)."""
    raw = os.environ.get("TIKTOK_ADS_HOME", "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.home() / APP_DIR_NAME


def ensure_private_dir(path: Path) -> Path:
    """Create a folder (and parents) readable only by the current user (0700)."""
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        with contextlib.suppress(OSError):
            os.chmod(path, 0o700)
    return path


def parse_tool_groups(raw: str | None) -> list[str]:
    """Split a comma-separated TIKTOK_ADS_TOOL_GROUPS value and check every name.

    Names are case-insensitive and may use '-' for '_'. Empty means all groups.
    """
    from .tools import resolve_tool_groups  # local: tools imports this module

    names = [p.strip().lower().replace("-", "_") for p in (raw or "").split(",")]
    names = [n for n in names if n]
    return resolve_tool_groups(names) if names else []


def _id_list(name: str) -> list[str]:
    values = [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]
    for v in values:
        if not v.isdigit():
            raise RuntimeError(f"{name} must be a comma-separated list of numeric IDs, got '{v}'.")
    return values


@dataclass
class Config:
    access_token: str | None
    app_id: str | None
    app_secret: str | None
    advertiser_id: str | None
    audit_log: Path
    token_file: Path | None = None
    bc_id: str | None = None
    # If set, tools refuse any advertiser not in this list.
    allowed_advertiser_ids: list[str] = field(default_factory=list)
    page_size: int = 100
    timeout: float = 30.0
    # Client-side cap on requests per second (TikTok's Basic level allows 10).
    max_qps: float = 10.0
    dry_run: bool = False
    log_level: str = "INFO"
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    allow_remote: bool = False
    # Tool modules to register; empty means all (see tiktok_ads_mcp.tools.TOOL_GROUPS).
    tool_groups: list[str] = field(default_factory=list)
    # Register only tools annotated read-only (plus the meta tools).
    read_only: bool = False
    # Writes touching more than this many entities need confirm='APPLY'.
    bulk_threshold: int = 10
    # Bid or budget increases above this percentage need confirm='APPLY'.
    max_increase_pct: float = 20.0
    # Optional absolute caps; values above them need confirm='APPLY'.
    max_budget: float | None = None
    max_bid: float | None = None
    # Audit entries older than this are pruned at startup; 0 keeps them.
    audit_retention_days: int = 30
    # Report downloads larger than this are refused.
    max_download_mb: int = 200

    @property
    def api_base(self) -> str:
        return API_BASE


def _path_or_none(raw: str | None) -> Path | None:
    if not raw or not raw.strip():
        return None
    return Path(raw).expanduser().resolve()


def _float_or_none(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as e:
        raise RuntimeError(f"{name} must be a number, got '{raw}'") from e


def token_file_path() -> Path:
    """Where `tiktok-ads-mcp auth` stores the access token.

    TIKTOK_ADS_TOKEN_FILE, default ~/.tiktok-ads-mcp/secrets/tiktok-ads-token.json.
    """
    return _path_or_none(os.environ.get("TIKTOK_ADS_TOKEN_FILE")) or (
        app_home() / "secrets" / DEFAULT_TOKEN_NAME
    )


def audit_log_path() -> Path:
    """The audit log (TIKTOK_ADS_AUDIT_LOG, default ~/.tiktok-ads-mcp/logs/audit.jsonl)."""
    return _path_or_none(os.environ.get("TIKTOK_ADS_AUDIT_LOG")) or (
        app_home() / "logs" / DEFAULT_AUDIT_LOG_NAME
    )


def read_token_file(path: Path) -> dict:
    """Return what `tiktok-ads-mcp auth` stored ({} if there is no file)."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RuntimeError(f"Could not read the token file {path}: {e}") from e
    return data if isinstance(data, dict) else {}


def load_env(env_file: Path | None = None) -> None:
    """Load .env files without overriding variables that are already set.

    Order: --env (if given), ./.env, then ~/.tiktok-ads-mcp/.env.
    """
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    else:
        load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    home_env = app_home() / ".env"
    if home_env.is_file():
        load_dotenv(dotenv_path=home_env, override=False)


def load_config(env_file: Path | None = None, *, require_token: bool = True) -> Config:
    """Read configuration from the environment (and .env files).

    Raises RuntimeError with actionable messages on misconfiguration."""
    load_env(env_file)

    app_id = os.environ.get("TIKTOK_ADS_APP_ID", "").strip() or None
    app_secret = os.environ.get("TIKTOK_ADS_APP_SECRET", "").strip() or None
    if app_id and not app_id.isdigit():
        raise RuntimeError(f"TIKTOK_ADS_APP_ID must be numeric, got '{app_id}'.")

    token_file = token_file_path()
    access_token = os.environ.get("TIKTOK_ADS_ACCESS_TOKEN", "").strip() or None
    stored = {} if access_token else read_token_file(token_file)
    if access_token is None:
        access_token = str(stored.get("access_token") or "").strip() or None
    if access_token is None and require_token:
        raise RuntimeError(
            "No TikTok access token configured. Either:\n"
            "  - run `tiktok-ads-mcp auth` once (saves it to "
            f"{token_file}), or\n"
            "  - set TIKTOK_ADS_ACCESS_TOKEN to a Marketing API access token, or\n"
            "  - set TIKTOK_ADS_TOKEN_FILE to the file `tiktok-ads-mcp auth` wrote.\n"
            "See docs/setup-tiktok-ads-api.md for how to get one."
        )

    advertiser_id = os.environ.get("TIKTOK_ADS_ADVERTISER_ID", "").strip() or None
    if advertiser_id is None:
        ids = stored.get("advertiser_ids") if isinstance(stored, dict) else None
        if isinstance(ids, list) and len(ids) == 1:
            advertiser_id = str(ids[0])
    if advertiser_id and not advertiser_id.isdigit():
        raise RuntimeError(f"TIKTOK_ADS_ADVERTISER_ID must be numeric, got '{advertiser_id}'.")
    bc_id = os.environ.get("TIKTOK_ADS_BC_ID", "").strip() or None
    if bc_id and not bc_id.isdigit():
        raise RuntimeError(f"TIKTOK_ADS_BC_ID must be numeric, got '{bc_id}'.")
    allowed = _id_list("TIKTOK_ADS_ALLOWED_ADVERTISER_IDS")
    if advertiser_id and allowed and advertiser_id not in allowed:
        raise RuntimeError(
            "TIKTOK_ADS_ADVERTISER_ID is not in TIKTOK_ADS_ALLOWED_ADVERTISER_IDS; "
            "add it there or change the default."
        )

    transport = os.environ.get("TIKTOK_ADS_TRANSPORT", "stdio").strip().lower()
    if transport not in TRANSPORTS:
        raise RuntimeError(
            f"TIKTOK_ADS_TRANSPORT must be one of {', '.join(TRANSPORTS)}, got '{transport}'."
        )

    def _int(name: str, default: str) -> int:
        try:
            return int(os.environ.get(name, default))
        except ValueError as e:
            raise RuntimeError(f"{name} must be an integer") from e

    def _float(name: str, default: str) -> float:
        try:
            return float(os.environ.get(name, default))
        except ValueError as e:
            raise RuntimeError(f"{name} must be a number") from e

    page_size = _int("TIKTOK_ADS_PAGE_SIZE", "100")
    if not 1 <= page_size <= 1000:
        raise RuntimeError("TIKTOK_ADS_PAGE_SIZE must be between 1 and 1000.")
    max_qps = _float("TIKTOK_ADS_MAX_QPS", "10")
    if max_qps <= 0:
        raise RuntimeError("TIKTOK_ADS_MAX_QPS must be greater than 0.")

    return Config(
        access_token=access_token,
        app_id=app_id,
        app_secret=app_secret,
        advertiser_id=advertiser_id,
        audit_log=audit_log_path(),
        token_file=token_file,
        bc_id=bc_id,
        allowed_advertiser_ids=allowed,
        page_size=page_size,
        timeout=_float("TIKTOK_ADS_TIMEOUT", "30"),
        max_qps=max_qps,
        dry_run=_truthy(os.environ.get("TIKTOK_ADS_DRY_RUN")),
        log_level=os.environ.get("TIKTOK_ADS_LOG_LEVEL", "INFO").upper(),
        transport=transport,
        host=os.environ.get("TIKTOK_ADS_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_int("TIKTOK_ADS_PORT", "8000"),
        allow_remote=_truthy(os.environ.get("TIKTOK_ADS_ALLOW_REMOTE")),
        tool_groups=parse_tool_groups(os.environ.get("TIKTOK_ADS_TOOL_GROUPS")),
        read_only=_truthy(os.environ.get("TIKTOK_ADS_READ_ONLY")),
        bulk_threshold=_int("TIKTOK_ADS_BULK_THRESHOLD", "10"),
        max_increase_pct=_float("TIKTOK_ADS_MAX_INCREASE_PCT", "20"),
        max_budget=_float_or_none("TIKTOK_ADS_MAX_BUDGET"),
        max_bid=_float_or_none("TIKTOK_ADS_MAX_BID"),
        audit_retention_days=_int("TIKTOK_ADS_AUDIT_RETENTION_DAYS", "30"),
        max_download_mb=_int("TIKTOK_ADS_MAX_DOWNLOAD_MB", "200"),
    )
