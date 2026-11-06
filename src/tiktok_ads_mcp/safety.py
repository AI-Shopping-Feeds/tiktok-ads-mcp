"""Confirmation guards for writes that change live ads or spend money.

A write tool asks `assess()` what its change needs, then `refusal()` whether to
stop. A guarded write is refused (with a summary of what it would do) unless the
caller passes the required `confirm` word:

* deletes need confirm='DELETE' (TikTok deletes can't be undone);
* writes touching more than TIKTOK_ADS_BULK_THRESHOLD entities, bid or budget
  increases above TIKTOK_ADS_MAX_INCREASE_PCT, increases whose current value
  couldn't be read, values over TIKTOK_ADS_MAX_BUDGET / TIKTOK_ADS_MAX_BID,
  enabling delivery (status ENABLE, or creating something enabled) and raw
  writes need confirm='APPLY'.

In dry-run mode nothing is sent, so guards don't block; the result says which
confirm a real run would need.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .config import Config

APPLY = "APPLY"
DELETE = "DELETE"


@dataclass
class MoneyChange:
    """A bid or budget value a write sets: `old` is None if it couldn't be read."""

    entity_id: str
    kind: str  # "bid" or "budget"
    old: float | None
    new: float


@dataclass
class Decision:
    required: str | None = None
    reasons: list[str] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "required_confirm": self.required,
            "reasons": self.reasons,
            "money_changes": self.changes[:50],
        }


def _num(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def dig(obj: Any, path: Sequence[str]) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def money_changes(
    items: Iterable[dict[str, Any]],
    current: Iterable[dict[str, Any]] | None,
    *,
    id_field: str,
    fields: Sequence[tuple[str, Sequence[str]]],
    current_id_field: str | None = None,
) -> list[MoneyChange]:
    """Pair each update's bid/budget fields with the entity's current values.

    fields: (kind, path) pairs, e.g. ("budget", ("budget",)). The current value
    is read from the same path on the matching entity in `current`.
    """
    cid = current_id_field or id_field
    by_id = {str(c.get(cid)): c for c in (current or []) if isinstance(c, dict)}
    out: list[MoneyChange] = []
    for item in items:
        eid = str(item.get(id_field))
        for kind, path in fields:
            new = _num(dig(item, path))
            if new is None:
                continue
            old = _num(dig(by_id[eid], path)) if eid in by_id else None
            out.append(MoneyChange(eid, kind, old, new))
    return out


def new_values(
    items: Iterable[dict[str, Any]], fields: Sequence[tuple[str, Sequence[str]]]
) -> list[MoneyChange]:
    """Bid/budget values set by creates (no previous value to compare)."""
    out: list[MoneyChange] = []
    for i, item in enumerate(items):
        for kind, path in fields:
            new = _num(dig(item, path))
            if new is not None:
                out.append(MoneyChange(f"new[{i}]", kind, None, new))
    return out


def assess(
    config: Config,
    *,
    count: int,
    destructive: str | None = None,
    changes: Sequence[MoneyChange] = (),
    creating: bool = False,
    enabling: bool = False,
) -> Decision:
    """Work out which confirm word, if any, a write needs."""
    d = Decision()
    if destructive:
        d.required = destructive
        d.reasons.append(f"{destructive.lower()} of {count} item(s) can't be undone")
    if count > config.bulk_threshold:
        d.reasons.append(
            f"{count} items is more than TIKTOK_ADS_BULK_THRESHOLD ({config.bulk_threshold})"
        )
    if enabling:
        d.reasons.append("this turns delivery on, so ads can start spending")
    limit = config.max_increase_pct
    for c in changes:
        info: dict[str, Any] = {"id": c.entity_id, "kind": c.kind, "old": c.old, "new": c.new}
        if c.old is not None and c.old > 0:
            info["change_pct"] = round((c.new - c.old) / c.old * 100, 1)
        d.changes.append(info)
        cap = config.max_budget if c.kind == "budget" else config.max_bid
        if cap is not None and c.new > cap:
            d.reasons.append(f"{c.kind} {c.new} for {c.entity_id} is above the cap of {cap}")
        if creating:
            continue
        if c.old is None:
            d.reasons.append(
                f"current {c.kind} for {c.entity_id} is unknown, so the change is unchecked"
            )
        elif c.old <= 0 < c.new or (c.old > 0 and (c.new - c.old) / c.old * 100 > limit):
            d.reasons.append(
                f"{c.kind} for {c.entity_id} rises from {c.old} to {c.new} "
                f"(more than TIKTOK_ADS_MAX_INCREASE_PCT={limit:g}%)"
            )
    if d.reasons and d.required is None:
        d.required = APPLY
    return d


def refusal(
    config: Config, decision: Decision, confirm: str, *, preview: Any = None
) -> dict | None:
    """Return a refusal payload if the write must not go ahead, else None."""
    if decision.required is None or config.dry_run or confirm == decision.required:
        return None
    out: dict[str, Any] = {
        "refused": True,
        "error": (
            f"Not sent. Show the user what will change, and once they agree call again "
            f"with confirm='{decision.required}' (case-sensitive)."
        ),
        **decision.as_dict(),
    }
    if preview is not None:
        out["would_send"] = preview
    return out


def annotate(result: Any, decision: Decision) -> Any:
    """Attach the guard summary to a result (useful in dry-run)."""
    if decision.required is None:
        return result
    if isinstance(result, dict):
        return {**result, "safety": decision.as_dict()}
    return {"result": result, "safety": decision.as_dict()}
