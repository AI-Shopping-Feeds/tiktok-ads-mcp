"""CLI entrypoint exposed as the `tiktok-ads-mcp` console script.

Subcommands:

* `tiktok-ads-mcp run`       (default) — start the MCP server.
* `tiktok-ads-mcp auth`      — one-time advertiser authorisation; saves the access token.
* `tiktok-ads-mcp purge`     — delete the audit log and the stored token (optionally revoke it).
* `tiktok-ads-mcp describe`  — print the effective configuration (no secrets).
* `tiktok-ads-mcp version`   — print the package version.
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
import time
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import click

from . import __version__
from ._logging import configure_default, get_logger
from .auth import exchange_auth_code, redact, register_secret, revoke_token, save_token_file
from .config import (
    API_BASE,
    AUTHORIZE_URL,
    LOOPBACK_HOSTS,
    TRANSPORTS,
    app_home,
    audit_log_path,
    load_config,
    load_env,
    read_token_file,
    token_file_path,
)
from .server import build_server

logger = get_logger("cli")

DEFAULT_REDIRECT = "http://localhost:8765/callback"
_TIKTOK_AUTH_HOSTS = ("business-api.tiktok.com", "ads.tiktok.com")


@click.group(invoke_without_command=True)
@click.option(
    "--env",
    "env_file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to a .env file. Defaults to ./.env, then ~/.tiktok-ads-mcp/.env.",
)
@click.option(
    "--transport",
    type=click.Choice(TRANSPORTS),
    default=None,
    help="Override TIKTOK_ADS_TRANSPORT. 'sse' is deprecated; use 'streamable-http'.",
)
@click.option(
    "--host", default=None, help="Bind host for streamable-http / sse (default 127.0.0.1)."
)
@click.option(
    "--port", type=int, default=None, help="Bind port for streamable-http / sse (default 8000)."
)
@click.option(
    "--allow-remote",
    is_flag=True,
    help="Allow binding HTTP transports to a non-loopback address (same as "
    "TIKTOK_ADS_ALLOW_REMOTE=true). The server has no sign-in.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    env_file: Path | None,
    transport: str | None,
    host: str | None,
    port: int | None,
    allow_remote: bool,
) -> None:
    """TikTok Ads MCP server."""
    ctx.ensure_object(dict)
    ctx.obj["env_file"] = env_file
    ctx.obj["transport"] = transport
    ctx.obj["host"] = host
    ctx.obj["port"] = port
    ctx.obj["allow_remote"] = allow_remote
    if ctx.invoked_subcommand is None:
        ctx.invoke(run)


@cli.command()
@click.pass_context
def run(ctx: click.Context) -> None:
    """Start the MCP server (default subcommand)."""
    configure_default()
    config = load_config(env_file=ctx.obj.get("env_file"))
    if ctx.obj.get("transport"):
        config.transport = ctx.obj["transport"]
    if ctx.obj.get("host"):
        config.host = ctx.obj["host"]
    if ctx.obj.get("port"):
        config.port = ctx.obj["port"]
    if ctx.obj.get("allow_remote"):
        config.allow_remote = True

    if config.transport != "stdio" and config.host not in LOOPBACK_HOSTS:
        if not config.allow_remote:
            raise click.ClickException(
                f"Refusing to serve on {config.host}: the HTTP transport has no sign-in, so "
                "anyone who can reach it could use your TikTok Ads access. Bind to 127.0.0.1, "
                "or set TIKTOK_ADS_ALLOW_REMOTE=true (or --allow-remote) behind your own "
                "authenticating proxy."
            )
        logger.warning(
            "binding to %s: the server has no authentication, so anyone who can reach "
            "this address can use your TikTok Ads access",
            config.host,
        )

    mcp = build_server(config=config)

    if config.transport == "stdio":
        mcp.run("stdio")
    elif config.transport == "streamable-http":
        logger.info("serving streamable HTTP on http://%s:%d/mcp", config.host, config.port)
        mcp.run("streamable-http", host=config.host, port=config.port)
    elif config.transport == "sse":
        logger.warning(
            "the sse transport (HTTP+SSE) is deprecated by the MCP spec; "
            "use --transport streamable-http instead"
        )
        mcp.run("sse", host=config.host, port=config.port)
    else:
        raise click.ClickException(f"Unknown transport: {config.transport}")


# ---------------------------------------------------------------- auth helpers


def authorization_url(
    *, app_id: str, redirect_uri: str, state: str, base_url: str | None = None
) -> str:
    """The advertiser authorisation link, with our own `state`.

    base_url: the "Advertiser authorization URL" copied from My Apps, if given;
    its redirect_uri is kept and its state replaced.
    """
    if base_url:
        parsed = urlparse(base_url.strip())
        if parsed.scheme != "https" or parsed.hostname not in _TIKTOK_AUTH_HOSTS:
            raise click.ClickException(
                "--auth-url must be the Advertiser authorization URL from TikTok's My Apps page "
                "(https://business-api.tiktok.com/portal/auth?...)."
            )
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        params["state"] = state
        params.setdefault("app_id", app_id)
        params.setdefault("redirect_uri", redirect_uri)
        return urlunparse(parsed._replace(query=urlencode(params)))
    query = urlencode({"app_id": app_id, "state": state, "redirect_uri": redirect_uri})
    return f"{AUTHORIZE_URL}?{query}"


def redirect_from_url(url: str) -> str | None:
    values = parse_qs(urlparse(url).query).get("redirect_uri")
    return values[0] if values else None


def parse_redirect(value: str, expected_state: str) -> str:
    """Pull the auth_code out of a pasted redirect URL, or accept a bare code.

    A pasted URL must carry the same `state` this command generated.
    """
    value = value.strip()
    if "code=" not in value:
        if not value:
            raise click.ClickException("No code given.")
        if "://" in value or "?" in value or "&" in value:
            raise click.ClickException("That doesn't look like a redirect URL or a code.")
        return value
    query = parse_qs(urlparse(value).query or value.split("?", 1)[-1])
    if "error" in query:
        raise click.ClickException(f"TikTok returned an error: {query['error'][0]}")
    state = query.get("state", [None])[0]
    if state is None:
        raise click.ClickException(
            "The redirect URL has no state, so it can't be checked; start again."
        )
    if state != expected_state:
        raise click.ClickException("The state in the redirect doesn't match; start again.")
    code = query.get("auth_code", query.get("code", [""]))[0]
    if not code:
        raise click.ClickException("No auth_code in the redirect URL.")
    return code


def _wait_for_code(port: int, path: str, expected_state: str, timeout: float) -> str:
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path.rstrip("/") != path.rstrip("/"):
                self.send_response(404)
                self.end_headers()
                return
            code = query.get("auth_code", query.get("code", [""]))[0]
            if query.get("state", [""])[0] != expected_state:
                result["error"] = "state mismatch"
            elif "error" in query:
                result["error"] = query["error"][0]
            elif code:
                result["code"] = code
            else:
                result["error"] = "no auth_code in the redirect"
            ok = "code" in result
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            message = (
                "Authorised. You can close this window and return to the terminal."
                if ok
                else "Authorisation failed. Return to the terminal for details."
            )
            self.wfile.write(f"<html><body><p>{message}</p></body></html>".encode())

        def log_message(self, *args: Any, **kwargs: Any) -> None:  # never log the code
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    deadline = time.monotonic() + timeout
    try:
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "code" in result:
        return result["code"]
    if "error" in result:
        raise click.ClickException(f"Authorisation failed: {result['error']}")
    raise click.ClickException("Timed out waiting for the browser redirect.")


@cli.command()
@click.option(
    "--redirect-uri",
    default=None,
    help=f"Advertiser redirect URL registered on your developer app (default {DEFAULT_REDIRECT}).",
)
@click.option(
    "--auth-url",
    default=None,
    help="The Advertiser authorization URL copied from My Apps. Its redirect URL is used "
    "and its state replaced with a fresh one.",
)
@click.option(
    "--manual",
    is_flag=True,
    help="Don't start a local server: paste the address TikTok redirects you to.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Where to save the token (default TIKTOK_ADS_TOKEN_FILE or "
    "~/.tiktok-ads-mcp/secrets/tiktok-ads-token.json).",
)
@click.option(
    "--no-browser", is_flag=True, help="Print the authorisation URL instead of opening it."
)
@click.option(
    "--show-token",
    is_flag=True,
    help="Also print the access token once (e.g. to paste into a client config).",
)
@click.option("--timeout", type=float, default=300, help="Seconds to wait for the redirect.")
@click.pass_context
def auth(
    ctx: click.Context,
    redirect_uri: str | None,
    auth_url: str | None,
    manual: bool,
    output_path: Path | None,
    no_browser: bool,
    show_token: bool,
    timeout: float,
) -> None:
    """One-time advertiser authorisation: get a long-term access token for this server.

    Sign in with the TikTok For Business user that manages the ad accounts and
    approve the permissions. The redirect URL must be one of the advertiser
    redirect URLs on your developer app (My Apps -> your app).
    """
    configure_default()
    config = load_config(env_file=ctx.obj.get("env_file"), require_token=False)
    if not config.app_id or not config.app_secret:
        raise click.ClickException(
            "Set TIKTOK_ADS_APP_ID and TIKTOK_ADS_APP_SECRET first (My Apps -> your app -> "
            "Basic Information). See docs/setup-tiktok-ads-api.md."
        )
    register_secret(config.app_secret)
    redirect = (
        redirect_uri or (redirect_from_url(auth_url) if auth_url else None) or DEFAULT_REDIRECT
    )
    state = secrets.token_urlsafe(24)
    url = authorization_url(
        app_id=config.app_id, redirect_uri=redirect, state=state, base_url=auth_url
    )
    parsed_redirect = urlparse(redirect)
    local = parsed_redirect.hostname in LOOPBACK_HOSTS and parsed_redirect.scheme == "http"
    if not manual and not local:
        manual = True
        click.echo("The redirect URL isn't on this computer, so paste mode is used.")
    click.echo(f"Redirect URL (must be listed on your developer app): {redirect}")
    click.echo("Open this link, sign in with the TikTok For Business user that manages the ads,")
    click.echo("approve the permissions and enter the email verification code:")
    click.echo(url)

    if manual:
        if not no_browser:
            webbrowser.open(url)
        pasted = click.prompt(
            "Paste the full address you were redirected to (or just the auth_code)",
            hide_input=True,
        )
        code = parse_redirect(pasted, state)
    else:
        if not no_browser:
            threading.Timer(0.5, webbrowser.open, args=(url,)).start()
        port = parsed_redirect.port or 80
        click.echo(f"Waiting for the redirect on {redirect} ...")
        code = _wait_for_code(port, parsed_redirect.path or "/", state, timeout)

    register_secret(code)
    data = exchange_auth_code(
        app_id=config.app_id, secret=config.app_secret, auth_code=code, timeout=config.timeout
    )
    token = data["access_token"]
    advertiser_ids = [str(a) for a in data.get("advertiser_ids") or []]
    target = output_path or config.token_file or token_file_path()
    save_token_file(
        target,
        {
            "access_token": token,
            "advertiser_ids": advertiser_ids,
            "scope": data.get("scope"),
            "app_id": config.app_id,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )
    click.echo(f"Saved the access token to {target} (owner-only permissions).")
    if target.resolve() != token_file_path().resolve():
        click.echo(f"Set TIKTOK_ADS_TOKEN_FILE={target.resolve()} so the server finds it.")
    if advertiser_ids:
        click.echo(
            f"The token can manage {len(advertiser_ids)} ad account(s): {', '.join(advertiser_ids)}"
        )
        if len(advertiser_ids) > 1:
            click.echo("Set TIKTOK_ADS_ADVERTISER_ID to the one you use most.")
    click.echo(
        "The token doesn't expire; it stops working if the advertiser removes the "
        "authorisation. Next: run `tiktok-ads-mcp describe`, then add the server to your "
        "MCP client. Never paste the token into chat or commit it."
    )
    if show_token:
        click.echo(f"Access token: {token}")


@cli.command()
@click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
@click.option("--keep-token", is_flag=True, help="Delete only the audit log.")
@click.option(
    "--revoke",
    is_flag=True,
    help="Also revoke the stored access token at TikTok (needs the app ID and secret).",
)
@click.pass_context
def purge(ctx: click.Context, yes: bool, keep_token: bool, revoke: bool) -> None:
    """Delete locally stored TikTok data: the audit log and the access-token file."""
    load_env(ctx.obj.get("env_file"))
    audit = audit_log_path()
    token_path = token_file_path()
    targets = [audit, audit.with_suffix(audit.suffix + ".tmp")]
    if not keep_token:
        targets.append(token_path)
    existing = [p for p in targets if p.exists()]
    if revoke and keep_token:
        raise click.ClickException("--revoke and --keep-token don't go together.")
    if not existing and not revoke:
        click.echo("Nothing to delete.")
        return
    if existing:
        click.echo("Will delete:\n" + "\n".join(f"  {p}" for p in existing))
    if revoke:
        click.echo("Will revoke the stored access token at TikTok.")
    if not yes and not click.confirm("Go ahead?", default=False):
        click.echo("Cancelled.")
        return
    if revoke:
        config = load_config(env_file=ctx.obj.get("env_file"), require_token=False)
        token = str(read_token_file(token_path).get("access_token") or config.access_token or "")
        if not (config.app_id and config.app_secret and token):
            raise click.ClickException(
                "Revoking needs TIKTOK_ADS_APP_ID, TIKTOK_ADS_APP_SECRET and a stored token."
            )
        revoke_token(app_id=config.app_id, secret=config.app_secret, access_token=token)
        click.echo("Revoked the access token at TikTok.")
    for p in existing:
        p.unlink()
    click.echo(f"Deleted {len(existing)} file(s).")
    if not keep_token:
        click.echo(
            "If you also set TIKTOK_ADS_ACCESS_TOKEN in a client config, remove it there. To "
            "remove the app's access entirely, the advertiser can also remove it at "
            "https://ads.tiktok.com/ac/page/authorizations."
        )


@cli.command()
def version() -> None:
    """Print the tiktok-ads-mcp version."""
    click.echo(__version__)


@cli.command("describe")
@click.pass_context
def describe(ctx: click.Context) -> None:
    """Print effective config (ad account, paths, limits) and exit. No secrets."""
    configure_default()
    config = load_config(env_file=ctx.obj.get("env_file"), require_token=False)
    info = {
        "version": __version__,
        "api_base": API_BASE,
        "home": str(app_home()),
        "app_id": f"...{config.app_id[-4:]}" if config.app_id else None,
        "app_secret": "set" if config.app_secret else "missing",
        "access_token": "set" if config.access_token else "missing (run `tiktok-ads-mcp auth`)",
        "token_file": str(config.token_file) if config.token_file else None,
        "default_advertiser_id": config.advertiser_id,
        "default_bc_id": config.bc_id,
        "allowed_advertiser_ids": config.allowed_advertiser_ids or "all",
        "audit_log": str(config.audit_log),
        "audit_retention_days": config.audit_retention_days,
        "dry_run": config.dry_run,
        "read_only": config.read_only,
        "tool_groups": config.tool_groups or "all",
        "bulk_threshold": config.bulk_threshold,
        "max_increase_pct": config.max_increase_pct,
        "max_budget": config.max_budget,
        "max_bid": config.max_bid,
        "max_qps": config.max_qps,
        "max_download_mb": config.max_download_mb,
        "transport": config.transport,
        "host": config.host,
        "port": config.port,
        "allow_remote": config.allow_remote,
    }
    click.echo(json.dumps(info, indent=2, ensure_ascii=False))


def main() -> None:
    try:
        cli(obj={})
    except RuntimeError as e:
        # Surface config errors cleanly instead of a Python traceback.
        click.echo(f"Error: {redact(str(e))}", err=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
