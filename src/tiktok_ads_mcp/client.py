from __future__ import annotations

import csv
import io
import json
import random
import threading
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from . import __version__
from ._logging import get_logger
from .audit import AuditLog
from .auth import Auth, redact, register_secret
from .config import API_HOST, Config

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
RETRYABLE_HTTP = {429, 500, 502, 503, 504}
# TikTok answers HTTP 200 with a `code` in the body. These codes mean the
# request was throttled before it was processed, so even writes can be retried.
THROTTLE_CODES = {40016, 40100, 40133}
# Server-side failures; only reads are retried (a write may have gone through).
SERVER_CODES = {50000, 50002, 51305, 60001}
PARTIAL_SUCCESS = 20001
TOKEN_CODES = {40102, 40104, 40105, 40106}
MAX_ATTEMPTS = 5
MAX_BACKOFF = 60.0
# Report files come from TikTok's own hosts; nothing else is fetched.
DOWNLOAD_HOST_SUFFIXES = (".tiktok.com",)
_CHUNK = 64 * 1024

logger = get_logger("client")

_HINTS = {
    40001: "The access token lacks permission for this; check the app's scopes and that the "
    "advertiser granted them.",
    40100: "TikTok throttled the developer app (QPS/QPM/QPD limit). A per-minute block lasts "
    "about 5 minutes; a daily block lasts until 00:00 UTC.",
    40133: "TikTok throttled this ad account. Wait a little and try again.",
    40102: "The access token is invalid. Run `tiktok-ads-mcp auth` again.",
    40104: "No access token was sent. Run `tiktok-ads-mcp auth`.",
    40105: "The access token is invalid or was revoked. Run `tiktok-ads-mcp auth` again.",
    40106: "This token can't access that advertiser. Check advertiser_id with "
    "tiktok_ads_list_advertisers.",
    40118: "The app or ad account isn't on TikTok's allowlist for this feature; ask your TikTok "
    "representative.",
}


class TikTokAdsAPIError(Exception):
    def __init__(
        self,
        code: int,
        message: str,
        *,
        request_id: str | None = None,
        http_status: int | None = None,
        body: Any = None,
    ):
        self.code = code
        self.api_message = redact(str(message))
        self.request_id = request_id
        self.http_status = http_status
        self.body = redact(body)
        text = f"TikTok API error {code}: {self.api_message}"
        if request_id:
            text += f" (request_id {request_id})"
        hint = _HINTS.get(code)
        if hint:
            text += f". {hint}"
        super().__init__(text)


class _RateLimiter:
    """Spaces requests at least 1/max_qps seconds apart (all threads together)."""

    def __init__(self, max_qps: float):
        self.interval = 1.0 / max_qps if max_qps > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


def encode_params(params: dict[str, Any] | None) -> dict[str, str]:
    """Encode GET parameters the way TikTok expects: lists and objects as JSON."""
    out: dict[str, str] = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        elif isinstance(value, list | tuple | dict):
            out[key] = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        else:
            out[key] = str(value)
    return out


class TikTokAdsClient:
    """Thin HTTP wrapper over the TikTok Marketing API (v1.3).

    Sends the Access-Token header, spaces requests to stay under the app's rate
    limit, retries throttled and failed requests with backoff, unwraps TikTok's
    {code, message, data} envelope, paginates, and sends every write through
    dry-run and the audit log. It only talks to business-api.tiktok.com and,
    for report files, TikTok-owned hosts.
    """

    def __init__(self, config: Config, auth: Auth, audit: AuditLog):
        self.config = config
        self.auth = auth
        self.audit = audit
        # Whatever Auth is used, its token and the app secret never reach logs or errors.
        register_secret(config.app_secret)
        register_secret(auth.access_token())
        self._limiter = _RateLimiter(config.max_qps)
        self._http = httpx.Client(
            timeout=config.timeout,
            headers={"User-Agent": f"tiktok-ads-mcp/{__version__}"},
            follow_redirects=False,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> TikTokAdsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def base_url(self) -> str:
        return self.config.api_base

    # ------------------------------------------------------------- scoping

    def resolve_advertiser(self, advertiser_id: str | int | None) -> str:
        aid = (
            str(advertiser_id).strip()
            if advertiser_id not in (None, "")
            else self.config.advertiser_id
        )
        if not aid:
            raise ValueError(
                "No advertiser_id. Pass advertiser_id (see tiktok_ads_list_advertisers) or set "
                "TIKTOK_ADS_ADVERTISER_ID."
            )
        if not aid.isdigit():
            raise ValueError(f"advertiser_id must be numeric, got '{aid}'.")
        allowed = self.config.allowed_advertiser_ids
        if allowed and aid not in allowed:
            raise PermissionError(
                f"advertiser_id {aid} is not in TIKTOK_ADS_ALLOWED_ADVERTISER_IDS, so this "
                "server won't touch it."
            )
        return aid

    def resolve_bc(self, bc_id: str | int | None) -> str:
        bid = str(bc_id).strip() if bc_id not in (None, "") else self.config.bc_id
        if not bid:
            raise ValueError(
                "No bc_id. Pass bc_id (see tiktok_ads_list_business_centers) or set "
                "TIKTOK_ADS_BC_ID."
            )
        if not bid.isdigit():
            raise ValueError(f"bc_id must be numeric, got '{bid}'.")
        return bid

    # ------------------------------------------------------------- requests

    @staticmethod
    def check_path(path: str) -> str:
        if not path.startswith("/") or "://" in path or ".." in path or "\\" in path:
            raise ValueError(
                "path must be relative to https://business-api.tiktok.com/open_api/v1.3, "
                "e.g. '/campaign/get/'."
            )
        if "?" in path or "#" in path:
            raise ValueError("Pass query parameters in `query`, not in the path.")
        return path

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        op: str | None = None,
        before: Any | None = None,
        read_only: bool = False,
    ) -> Any:
        """Perform one API request and return TikTok's `data` object.

        path: relative to /open_api/v1.3, starting with '/', e.g. '/campaign/get/'.
        read_only: set True for POST endpoints that don't change anything
            (estimates, searches, report tasks). They then bypass dry-run and
            are not written to the audit log.
        """
        method = method.upper()
        self.check_path(path)
        url = f"{self.base_url}{path}"
        is_write = method in WRITE_METHODS and not read_only
        advertiser = None
        for source in (json_body, params):
            if isinstance(source, dict) and source.get("advertiser_id"):
                advertiser = str(source["advertiser_id"])
                break
        if advertiser and self.config.allowed_advertiser_ids:
            self.resolve_advertiser(advertiser)

        if is_write and self.config.dry_run:
            audit_id = self.audit.record(
                op=op or f"{method} {path}",
                resource=path,
                method=method,
                url=url,
                advertiser_id=advertiser,
                request_body=json_body,
                dry_run=True,
                before=before,
            )
            logger.info("dry-run %s %s (audit=%s)", method, path, audit_id)
            return {
                "_dry_run": True,
                "method": method,
                "url": url,
                "advertiser_id": advertiser,
                "body": json_body,
                "audit_id": audit_id,
            }

        def record_error(status: int | None, payload: Any, error: str) -> None:
            if is_write:
                self.audit.record(
                    op=op or f"{method} {path}",
                    resource=path,
                    method=method,
                    url=url,
                    advertiser_id=advertiser,
                    request_body=json_body,
                    response_status=status,
                    response_body=payload,
                    before=before,
                    error=error,
                )

        last_exc: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            last_attempt = attempt == MAX_ATTEMPTS - 1
            self._limiter.wait()
            try:
                resp = self._http.request(
                    method,
                    url,
                    params=encode_params(params) if params else None,
                    content=None if json_body is None else json.dumps(json_body),
                    headers=self._headers(json_body is not None),
                )
            except httpx.RequestError as e:
                last_exc = e
                logger.warning(
                    "transport error attempt=%d %s %s: %s",
                    attempt + 1,
                    method,
                    path,
                    redact(str(e)),
                )
                if is_write or last_attempt:
                    # The write may have reached TikTok; don't send it twice.
                    record_error(None, None, f"transport error: {e}")
                    raise
                self._sleep_backoff(attempt)
                continue

            # 429 means TikTok refused the request, so even writes are retried; other
            # 5xx answers are retried only for reads (a write may have gone through).
            retry_http = resp.status_code == 429 or (
                resp.status_code in RETRYABLE_HTTP and not is_write
            )
            if retry_http and not last_attempt:
                logger.warning(
                    "retryable status=%d attempt=%d %s %s",
                    resp.status_code,
                    attempt + 1,
                    method,
                    path,
                )
                self._sleep_backoff(attempt, resp)
                continue

            payload: Any = self._safe_json(resp)
            if resp.status_code != 200 or not isinstance(payload, dict) or "code" not in payload:
                record_error(resp.status_code, payload, f"HTTP {resp.status_code}")
                raise TikTokAdsAPIError(
                    resp.status_code if resp.status_code != 200 else -1,
                    f"unexpected HTTP {resp.status_code} response",
                    http_status=resp.status_code,
                    body=payload,
                )

            code = payload.get("code")
            request_id = payload.get("request_id")
            if code in THROTTLE_CODES and not last_attempt:
                logger.warning(
                    "throttled code=%s attempt=%d %s %s", code, attempt + 1, method, path
                )
                self._sleep_backoff(attempt + 1)
                continue
            if code in SERVER_CODES and not is_write and not last_attempt:
                logger.warning("server error code=%s attempt=%d %s", code, attempt + 1, path)
                self._sleep_backoff(attempt)
                continue
            if code not in (0, PARTIAL_SUCCESS):
                record_error(resp.status_code, payload, f"code {code}")
                logger.error("api error %s %s %s: %s", code, method, path, redact(payload))
                raise TikTokAdsAPIError(
                    int(code) if isinstance(code, int) else -1,
                    str(payload.get("message") or ""),
                    request_id=request_id,
                    http_status=resp.status_code,
                    body=payload,
                )

            data = payload.get("data")
            result: Any = data if data is not None else {}
            if code == PARTIAL_SUCCESS:
                extra = {"partial_success": True, "message": payload.get("message")}
                result = (
                    {**result, **extra} if isinstance(result, dict) else {"data": result, **extra}
                )

            if is_write:
                audit_id = self.audit.record(
                    op=op or f"{method} {path}",
                    resource=path,
                    method=method,
                    url=url,
                    advertiser_id=advertiser,
                    request_body=json_body,
                    response_status=resp.status_code,
                    response_body=payload,
                    before=before,
                )
                logger.info("write %s %s -> code %s (audit=%s)", method, path, code, audit_id)
                meta = {"audit_id": audit_id, "tiktok_request_id": request_id}
                result = (
                    {**result, **meta} if isinstance(result, dict) else {"result": result, **meta}
                )
            else:
                logger.debug("read  %s %s -> code %s", method, path, code)
            return result

        raise TikTokAdsAPIError(-1, f"gave up after {MAX_ATTEMPTS} attempts: {last_exc or ''}")

    def _headers(self, has_body: bool) -> dict[str, str]:
        headers = {"Access-Token": self.auth.access_token(), "Accept": "application/json"}
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def paginate(
        self,
        path: str,
        params: dict[str, Any],
        *,
        max_results: int = 200,
        max_page_size: int = 1000,
        items_key: str = "list",
    ) -> tuple[list[Any], bool, dict[str, Any]]:
        """Follow page/page_size on GET list endpoints. Returns (items, truncated, page_info)."""
        items: list[Any] = []
        page = 1
        page_info: dict[str, Any] = {}
        size = max(1, min(self.config.page_size, max_page_size, max(1, max_results)))
        while True:
            data = self.request("GET", path, params={**params, "page": page, "page_size": size})
            batch = (data or {}).get(items_key) or [] if isinstance(data, dict) else []
            page_info = (data or {}).get("page_info") or {} if isinstance(data, dict) else {}
            items.extend(batch)
            total_page = page_info.get("total_page")
            done = not batch or (isinstance(total_page, int) and page >= total_page)
            if len(items) >= max_results:
                more = not done or len(items) > max_results
                return items[:max_results], more, page_info
            if done:
                return items, False, page_info
            page += 1

    def snapshot(self, fn: Any, *args: Any, **kwargs: Any) -> Any | None:
        """Run a read for a `before` snapshot; returns None instead of raising."""
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            logger.warning("before-snapshot failed: %s", redact(str(e)))
            return None

    # ------------------------------------------------------------- downloads

    def _read_capped(self, resp: httpx.Response) -> bytes:
        cap = self.config.max_download_mb * 1024 * 1024
        declared = resp.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > cap:
            raise ValueError(
                f"The report is larger than TIKTOK_ADS_MAX_DOWNLOAD_MB ({self.config.max_download_mb} "
                "MB). Narrow the date range, dimensions or filters."
            )
        buf = bytearray()
        for chunk in resp.iter_bytes(_CHUNK):
            buf.extend(chunk)
            if len(buf) > cap:
                raise ValueError(
                    f"The report is larger than TIKTOK_ADS_MAX_DOWNLOAD_MB "
                    f"({self.config.max_download_mb} MB). Narrow the date range, dimensions or "
                    "filters."
                )
        return bytes(buf)

    def download_report_task(self, advertiser_id: str, task_id: str) -> list[dict[str, Any]]:
        """Download a finished async report task and return its rows, in memory only.

        TikTok answers with the CSV itself or with JSON holding a short-lived
        download_url on a TikTok host. Both are size-capped and parsed in memory.
        """
        params = encode_params({"advertiser_id": advertiser_id, "task_id": task_id})
        url = f"{self.base_url}/report/task/download/"
        raw = b""
        content_type = ""
        for attempt in range(MAX_ATTEMPTS):
            self._limiter.wait()
            try:
                with self._http.stream(
                    "GET", url, params=params, headers=self._headers(False)
                ) as resp:
                    if resp.status_code in RETRYABLE_HTTP and attempt < MAX_ATTEMPTS - 1:
                        self._sleep_backoff(attempt, resp)
                        continue
                    if resp.status_code != 200:
                        raise TikTokAdsAPIError(
                            resp.status_code, "report download failed", http_status=resp.status_code
                        )
                    content_type = resp.headers.get("Content-Type", "")
                    raw = self._read_capped(resp)
                    break
            except httpx.RequestError:
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                self._sleep_backoff(attempt)
        if "json" in content_type or raw[:1] == b"{":
            payload = json.loads(raw.decode("utf-8") or "{}")
            if payload.get("code") not in (0, None):
                raise TikTokAdsAPIError(
                    int(payload.get("code") or -1),
                    str(payload.get("message") or ""),
                    request_id=payload.get("request_id"),
                    body=payload,
                )
            link = (payload.get("data") or {}).get("download_url")
            if not link:
                raise TikTokAdsAPIError(-1, "the download response had no file or download_url")
            raw = self._fetch_file(link)
        return parse_csv(raw)

    def _fetch_file(self, link: str) -> bytes:
        parsed = urlparse(link)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not (
            host.endswith(DOWNLOAD_HOST_SUFFIXES) or link.startswith(API_HOST)
        ):
            raise ValueError(f"Refusing to download a report from a non-TikTok host: {host!r}")
        for attempt in range(MAX_ATTEMPTS):
            try:
                with httpx.stream(
                    "GET", link, timeout=max(self.config.timeout, 120.0), follow_redirects=False
                ) as resp:
                    if resp.status_code in RETRYABLE_HTTP and attempt < MAX_ATTEMPTS - 1:
                        self._sleep_backoff(attempt, resp)
                        continue
                    if resp.status_code != 200:
                        raise TikTokAdsAPIError(
                            resp.status_code,
                            "report file download failed",
                            http_status=resp.status_code,
                        )
                    return self._read_capped(resp)
            except httpx.RequestError:
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                self._sleep_backoff(attempt)
        raise TikTokAdsAPIError(-1, "report file download failed")

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _safe_json(resp: httpx.Response) -> Any:
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"_raw": resp.text[:2000]}

    @staticmethod
    def _sleep_backoff(attempt: int, resp: httpx.Response | None = None) -> None:
        retry_after = 0.0
        if resp is not None and "Retry-After" in resp.headers:
            try:
                retry_after = float(resp.headers["Retry-After"])
            except ValueError:
                retry_after = 0.0
        base = min(max(retry_after, min(2**attempt, 30)), MAX_BACKOFF)
        time.sleep(base + random.uniform(0, 0.5))


def parse_csv(raw: bytes) -> list[dict[str, Any]]:
    """Parse a TikTok report CSV (UTF-8, optional BOM) into a list of row dicts."""
    text = raw.decode("utf-8-sig", errors="replace")
    if not text.strip():
        return []
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]
