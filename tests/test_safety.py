"""Confirm-word guards."""

from __future__ import annotations

from tiktok_ads_mcp import safety
from tiktok_ads_mcp.config import Config


def test_no_guard_for_small_safe_change(config: Config) -> None:
    d = safety.assess(config, count=1)
    assert d.required is None
    assert safety.refusal(config, d, "") is None


def test_delete_needs_delete(config: Config) -> None:
    d = safety.assess(config, count=2, destructive=safety.DELETE)
    assert d.required == "DELETE"
    refused = safety.refusal(config, d, "APPLY", preview={"ids": ["1"]})
    assert refused and refused["refused"] is True
    assert refused["would_send"] == {"ids": ["1"]}
    assert safety.refusal(config, d, "DELETE") is None


def test_bulk_needs_apply(config: Config) -> None:
    d = safety.assess(config, count=config.bulk_threshold + 1)
    assert d.required == "APPLY"
    assert "TIKTOK_ADS_BULK_THRESHOLD" in d.reasons[0]


def test_enabling_needs_apply(config: Config) -> None:
    d = safety.assess(config, count=1, enabling=True)
    assert d.required == "APPLY"
    assert "spending" in d.reasons[0]


def test_increase_above_limit_needs_apply(config: Config) -> None:
    within = safety.assess(config, count=1, changes=[safety.MoneyChange("1", "budget", 100, 120)])
    assert within.required is None  # exactly 20%
    over = safety.assess(config, count=1, changes=[safety.MoneyChange("1", "budget", 100, 121)])
    assert over.required == "APPLY"
    assert over.changes[0]["change_pct"] == 21.0
    from_zero = safety.assess(config, count=1, changes=[safety.MoneyChange("1", "bid", 0, 1)])
    assert from_zero.required == "APPLY"
    decrease = safety.assess(config, count=1, changes=[safety.MoneyChange("1", "bid", 2, 1)])
    assert decrease.required is None


def test_unknown_current_value_needs_apply(config: Config) -> None:
    d = safety.assess(config, count=1, changes=[safety.MoneyChange("1", "budget", None, 50)])
    assert d.required == "APPLY"
    assert "unknown" in d.reasons[0]


def test_caps_apply_to_creates(config: Config) -> None:
    config.max_budget = 100
    config.max_bid = 2
    d = safety.assess(
        config,
        count=1,
        changes=safety.new_values(
            [{"budget": 150, "bid_price": 1}], [("budget", ("budget",)), ("bid", ("bid_price",))]
        ),
        creating=True,
    )
    assert d.required == "APPLY"
    assert any("cap" in r for r in d.reasons)
    ok = safety.assess(
        config,
        count=1,
        changes=safety.new_values([{"budget": 50}], [("budget", ("budget",))]),
        creating=True,
    )
    assert ok.required is None


def test_money_changes_pairs_with_current(config: Config) -> None:
    changes = safety.money_changes(
        [{"adgroup_id": "1", "bid_price": 2}, {"adgroup_id": "2", "bid_price": 1}],
        [{"adgroup_id": "1", "bid_price": 1}],
        id_field="adgroup_id",
        fields=[("bid", ("bid_price",))],
    )
    assert [(c.entity_id, c.old, c.new) for c in changes] == [("1", 1.0, 2.0), ("2", None, 1.0)]


def test_dry_run_never_blocks(config: Config) -> None:
    config.dry_run = True
    d = safety.assess(config, count=1, destructive=safety.DELETE)
    assert safety.refusal(config, d, "") is None
    assert safety.annotate({"a": 1}, d)["safety"]["required_confirm"] == "DELETE"
