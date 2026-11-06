"""CLI: transports and the remote-binding guard, auth helpers, purge and describe."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import click
import pytest
from click.testing import CliRunner

from tiktok_ads_mcp import cli

from .conftest import APP_ID, APP_SECRET


class _FakeServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, transport: str, **kwargs: Any) -> None:
        self.calls.append((transport, kwargs))


@pytest.fixture
def base_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> Path:
    monkeypatch.setenv("TIKTOK_ADS_APP_ID", APP_ID)
    monkeypatch.setenv("TIKTOK_ADS_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("TIKTOK_ADS_ACCESS_TOKEN", "cli-access-token-value")
    return _isolated_home


@pytest.fixture
def fake_run(base_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    server = _FakeServer()
    monkeypatch.setattr(cli, "build_server", lambda config: server)
    warnings: list[str] = []
    monkeypatch.setattr(cli.logger, "warning", lambda msg, *args: warnings.append(msg % args))

    def invoke(*args: str, exit_code: int = 0):
        env_file = str(tmp_path / "missing.env")
        result = CliRunner().invoke(cli.cli, ["--env", env_file, *args, "run"], obj={})
        assert result.exit_code == exit_code, result.output
        return server.calls, warnings, result.output

    return invoke


def test_stdio_is_the_default(fake_run) -> None:
    calls, warnings, _ = fake_run()
    assert calls == [("stdio", {})]
    assert warnings == []


def test_streamable_http_gets_host_and_port(fake_run) -> None:
    calls, _, _ = fake_run("--transport", "streamable-http", "--port", "9123")
    assert calls == [("streamable-http", {"host": "127.0.0.1", "port": 9123})]


def test_non_loopback_host_is_refused(fake_run) -> None:
    calls, _, output = fake_run("--transport", "streamable-http", "--host", "0.0.0.0", exit_code=1)
    assert calls == []
    assert "Refusing to serve on 0.0.0.0" in output


def test_non_loopback_allowed_with_flag_warns(fake_run) -> None:
    calls, warnings, _ = fake_run(
        "--transport", "streamable-http", "--host", "0.0.0.0", "--allow-remote"
    )
    assert calls == [("streamable-http", {"host": "0.0.0.0", "port": 8000})]
    assert any("no authentication" in w for w in warnings)


def test_non_loopback_allowed_with_env(fake_run, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIKTOK_ADS_ALLOW_REMOTE", "true")
    calls, _, _ = fake_run("--transport", "streamable-http", "--host", "0.0.0.0")
    assert calls and calls[0][0] == "streamable-http"


def test_authorization_url() -> None:
    url = cli.authorization_url(
        app_id="123", redirect_uri="http://localhost:8765/callback", state="st"
    )
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://business-api.tiktok.com/portal/auth"
    )
    q = parse_qs(parsed.query)
    assert q == {
        "app_id": ["123"],
        "state": ["st"],
        "redirect_uri": ["http://localhost:8765/callback"],
    }


def test_authorization_url_from_my_apps_link_replaces_state() -> None:
    url = cli.authorization_url(
        app_id="123",
        redirect_uri="ignored",
        state="fresh",
        base_url="https://business-api.tiktok.com/portal/auth?app_id=123&state=your_custom_params&redirect_uri=https%3A%2F%2Fexample.com%2Fcb",
    )
    q = parse_qs(urlparse(url).query)
    assert q["state"] == ["fresh"]
    assert q["redirect_uri"] == ["https://example.com/cb"]
    with pytest.raises(click.ClickException):
        cli.authorization_url(
            app_id="1", redirect_uri="r", state="s", base_url="https://evil.example/auth"
        )


def test_parse_redirect() -> None:
    url = "https://example.com/cb?state=st&code=AAA&auth_code=BBB"
    assert cli.parse_redirect(url, "st") == "BBB"
    assert cli.parse_redirect("https://example.com/cb?state=st&code=AAA", "st") == "AAA"
    assert cli.parse_redirect("  BARECODE  ", "st") == "BARECODE"
    with pytest.raises(click.ClickException, match="doesn't match"):
        cli.parse_redirect("https://example.com/cb?state=other&auth_code=X", "st")
    with pytest.raises(click.ClickException, match="no state"):
        cli.parse_redirect("https://example.com/cb?auth_code=X", "st")
    with pytest.raises(click.ClickException, match="error"):
        cli.parse_redirect("https://example.com/cb?error=denied&state=st&code=", "st")
    with pytest.raises(click.ClickException):
        cli.parse_redirect("https://example.com/cb?foo=bar", "st")


def test_auth_manual_flow_saves_token_without_printing_it(
    base_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.secrets, "token_urlsafe", lambda n: "fixedstate")
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: True)
    seen: dict[str, Any] = {}

    def fake_exchange(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {
            "access_token": "brand-new-token-value",
            "advertiser_ids": ["111", "222"],
            "scope": [4],
        }

    monkeypatch.setattr(cli, "exchange_auth_code", fake_exchange)
    result = CliRunner().invoke(
        cli.cli,
        [
            "--env",
            str(tmp_path / "missing.env"),
            "auth",
            "--redirect-uri",
            "https://example.com/cb",
            "--no-browser",
        ],
        input="https://example.com/cb?state=fixedstate&auth_code=THECODE&code=THECODE\n",
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert "paste mode" in result.output
    assert seen["auth_code"] == "THECODE"
    assert seen["app_id"] == APP_ID
    token_file = base_env / "secrets" / "tiktok-ads-token.json"
    saved = json.loads(token_file.read_text())
    assert saved["access_token"] == "brand-new-token-value"
    assert saved["advertiser_ids"] == ["111", "222"]
    assert "brand-new-token-value" not in result.output
    assert APP_SECRET not in result.output
    assert "111, 222" in result.output
    if sys.platform != "win32":
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_auth_rejects_mismatched_state(
    base_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.secrets, "token_urlsafe", lambda n: "fixedstate")
    called: list[Any] = []
    monkeypatch.setattr(cli, "exchange_auth_code", lambda **kw: called.append(kw))
    result = CliRunner().invoke(
        cli.cli,
        ["--env", str(tmp_path / "missing.env"), "auth", "--manual", "--no-browser"],
        input="http://localhost:8765/callback?state=evil&auth_code=X\n",
        obj={},
    )
    assert result.exit_code != 0
    assert called == []


def test_auth_needs_app_credentials(base_env: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TIKTOK_ADS_APP_SECRET")
    result = CliRunner().invoke(
        cli.cli, ["--env", str(tmp_path / "missing.env"), "auth", "--manual"], obj={}
    )
    assert result.exit_code != 0
    assert "TIKTOK_ADS_APP_SECRET" in result.output


def test_purge_deletes_audit_and_token(base_env: Path, tmp_path: Path) -> None:
    audit = base_env / "logs" / "audit.jsonl"
    token = base_env / "secrets" / "tiktok-ads-token.json"
    audit.parent.mkdir(parents=True)
    token.parent.mkdir(parents=True)
    audit.write_text("{}\n")
    token.write_text("{}")
    result = CliRunner().invoke(
        cli.cli, ["--env", str(tmp_path / "missing.env"), "purge", "--yes"], obj={}
    )
    assert result.exit_code == 0, result.output
    assert not audit.exists()
    assert not token.exists()


def test_purge_keep_token(base_env: Path, tmp_path: Path) -> None:
    token = base_env / "secrets" / "tiktok-ads-token.json"
    token.parent.mkdir(parents=True)
    token.write_text("{}")
    result = CliRunner().invoke(
        cli.cli, ["--env", str(tmp_path / "missing.env"), "purge", "--yes", "--keep-token"], obj={}
    )
    assert result.exit_code == 0
    assert "Nothing to delete" in result.output
    assert token.exists()


def test_purge_revoke_calls_tiktok(
    base_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = base_env / "secrets" / "tiktok-ads-token.json"
    token.parent.mkdir(parents=True)
    token.write_text(json.dumps({"access_token": "stored-token-123456"}))
    revoked: list[dict[str, Any]] = []
    monkeypatch.setattr(cli, "revoke_token", lambda **kw: revoked.append(kw))
    result = CliRunner().invoke(
        cli.cli, ["--env", str(tmp_path / "missing.env"), "purge", "--yes", "--revoke"], obj={}
    )
    assert result.exit_code == 0, result.output
    assert revoked == [
        {"app_id": APP_ID, "secret": APP_SECRET, "access_token": "stored-token-123456"}
    ]
    assert not token.exists()


def test_describe_hides_secrets(base_env: Path, tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli.cli, ["--env", str(tmp_path / "missing.env"), "describe"], obj={}
    )
    assert result.exit_code == 0, result.output
    assert APP_SECRET not in result.output
    assert "cli-access-token-value" not in result.output
    info = json.loads(result.output)
    assert info["access_token"] == "set"
    assert info["home"] == str(base_env)


def test_main_reports_config_errors_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["tiktok-ads-mcp", "run"])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 2
    assert "tiktok-ads-mcp auth" in capsys.readouterr().err
