"""Audit log: redaction, permissions, retention and purge."""

from __future__ import annotations

import stat
import sys
import time
from pathlib import Path

import pytest

from tiktok_ads_mcp.audit import DAY, AuditLog
from tiktok_ads_mcp.auth import register_secret

from .conftest import audit_entries


def test_record_redacts_secrets(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "logs" / "audit.jsonl")
    register_secret("super-secret-token-value")
    log.record(
        op="x",
        resource="/a/",
        method="POST",
        url="https://business-api.tiktok.com/open_api/v1.3/a/?secret=abc123",
        request_body={"access_token": "t", "note": "has super-secret-token-value inside"},
    )
    [entry] = audit_entries(log.path)
    assert entry["request_body"]["access_token"] == "***"
    assert "super-secret-token-value" not in entry["request_body"]["note"]
    assert "abc123" not in entry["url"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_files_are_owner_only(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "logs" / "audit.jsonl")
    log.record(op="x", resource="/a/", method="POST", url="u")
    assert stat.S_IMODE(log.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(log.path.parent.stat().st_mode) == 0o700


def test_find_and_tail(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    ids = [log.record(op=f"op{i}", resource="/a/", method="POST", url="u") for i in range(3)]
    assert log.find(ids[1])["op"] == "op1"
    assert log.find("missing") is None
    assert [e["op"] for e in log.tail(2)] == ["op1", "op2"]
    assert log.tail(0) == []


def test_prune_drops_old_entries(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", retention_days=30)
    log.record(op="old", resource="/a/", method="POST", url="u")
    log.record(op="new", resource="/a/", method="POST", url="u")
    assert log.prune(now=time.time()) == 0
    future = time.time() + 31 * DAY
    lines = log.path.read_text().splitlines()
    # Make the first entry old relative to `future`, the second recent.
    import json

    entries = [json.loads(line) for line in lines]
    entries[1]["ts"] = future
    log.path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    assert log.prune(now=future) == 1
    assert [e["op"] for e in log.entries()] == ["new"]


def test_retention_zero_keeps_everything(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", retention_days=0)
    log.record(op="x", resource="/a/", method="POST", url="u")
    assert log.prune(now=time.time() + 1000 * DAY) == 0


def test_purge(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    assert log.purge() is False
    log.record(op="x", resource="/a/", method="POST", url="u")
    assert log.purge() is True
    assert not log.path.exists()
