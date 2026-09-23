"""Compare consecutive snapshots → change categories + streaks."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Literal

from .config import AppConfig, PlaceholderPolicy
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

ChangeType = Literal["first_buy", "increase", "decrease", "full_exit"]


def _index_holdings(
    snapshot: dict[str, Any],
    policy: PlaceholderPolicy,
    *,
    for_changes: bool,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for h in snapshot.get("holdings", []):
        code = h["stock_code"]
        if for_changes and policy.exclude_from_changes and h.get("is_placeholder"):
            continue
        out[code] = h
    return out


def list_snapshot_dates(snapshots_dir: Path, ticker: str) -> list[date]:
    d = snapshots_dir / ticker
    if not d.is_dir():
        return []
    dates: list[date] = []
    for p in d.glob("*.json"):
        try:
            dates.append(date.fromisoformat(p.stem))
        except ValueError:
            continue
    return sorted(dates)


def load_snapshot(snapshots_dir: Path, ticker: str, as_of: date) -> dict[str, Any]:
    path = snapshots_dir / ticker / f"{as_of.isoformat()}.json"
    return read_json(path)


def previous_snapshot_date(
    snapshots_dir: Path, ticker: str, as_of: date
) -> date | None:
    dates = [d for d in list_snapshot_dates(snapshots_dir, ticker) if d < as_of]
    return dates[-1] if dates else None


def compute_streaks(
    snapshots_dir: Path,
    ticker: str,
    as_of: date,
    stock_code: str,
    direction: Literal["increase", "decrease"],
    policy: PlaceholderPolicy,
    max_lookback: int = 60,
) -> int:
    """
    Count consecutive calendar-archived days ending at as_of where shares moved
    in `direction` vs the immediately previous archived snapshot.
    """
    dates = [d for d in list_snapshot_dates(snapshots_dir, ticker) if d <= as_of]
    if len(dates) < 2:
        return 1
    dates = dates[-(max_lookback + 1) :]
    streak = 0
    # walk newest pairs backward
    for i in range(len(dates) - 1, 0, -1):
        curr_d, prev_d = dates[i], dates[i - 1]
        curr = _index_holdings(load_snapshot(snapshots_dir, ticker, curr_d), policy, for_changes=True)
        prev = _index_holdings(load_snapshot(snapshots_dir, ticker, prev_d), policy, for_changes=True)
        if stock_code not in curr or stock_code not in prev:
            break
        c_shares = int(curr[stock_code]["shares"])
        p_shares = int(prev[stock_code]["shares"])
        if direction == "increase" and c_shares > p_shares:
            streak += 1
        elif direction == "decrease" and c_shares < p_shares:
            streak += 1
        else:
            break
    return max(streak, 1)


def compare_snapshots(
    prev: dict[str, Any],
    curr: dict[str, Any],
    cfg: AppConfig,
    *,
    snapshots_dir: Path | None = None,
    compute_streak: bool = True,
) -> dict[str, Any]:
    """Diff prev vs curr by stock_code using shares."""
    policy = cfg.placeholder
    ticker = curr["etf_ticker"]
    as_of = date.fromisoformat(curr["as_of_date"])
    prev_map = _index_holdings(prev, policy, for_changes=True)
    curr_map = _index_holdings(curr, policy, for_changes=True)

    first_buy: list[dict[str, Any]] = []
    increase: list[dict[str, Any]] = []
    decrease: list[dict[str, Any]] = []
    full_exit: list[dict[str, Any]] = []

    snap_dir = snapshots_dir or cfg.snapshots_dir

    for code, h in curr_map.items():
        if code not in prev_map:
            first_buy.append(
                {
                    "stock_code": code,
                    "stock_name": h["stock_name"],
                    "prev_shares": 0,
                    "curr_shares": h["shares"],
                    "shares_delta": h["shares"],
                    "prev_weight_pct": None,
                    "curr_weight_pct": h.get("weight_pct"),
                    "streak_days": 1,
                }
            )
            continue
        p = prev_map[code]
        delta = int(h["shares"]) - int(p["shares"])
        if delta > 0:
            streak = (
                compute_streaks(snap_dir, ticker, as_of, code, "increase", policy)
                if compute_streak
                else 1
            )
            increase.append(
                {
                    "stock_code": code,
                    "stock_name": h["stock_name"],
                    "prev_shares": p["shares"],
                    "curr_shares": h["shares"],
                    "shares_delta": delta,
                    "prev_weight_pct": p.get("weight_pct"),
                    "curr_weight_pct": h.get("weight_pct"),
                    "streak_days": streak,
                }
            )
        elif delta < 0:
            streak = (
                compute_streaks(snap_dir, ticker, as_of, code, "decrease", policy)
                if compute_streak
                else 1
            )
            decrease.append(
                {
                    "stock_code": code,
                    "stock_name": h["stock_name"],
                    "prev_shares": p["shares"],
                    "curr_shares": h["shares"],
                    "shares_delta": delta,
                    "prev_weight_pct": p.get("weight_pct"),
                    "curr_weight_pct": h.get("weight_pct"),
                    "streak_days": streak,
                }
            )

    for code, h in prev_map.items():
        if code not in curr_map:
            full_exit.append(
                {
                    "stock_code": code,
                    "stock_name": h["stock_name"],
                    "prev_shares": h["shares"],
                    "curr_shares": 0,
                    "shares_delta": -int(h["shares"]),
                    "prev_weight_pct": h.get("weight_pct"),
                    "curr_weight_pct": None,
                    "streak_days": 1,
                }
            )

    def _sort_key(row: dict[str, Any]) -> tuple:
        return (-abs(int(row["shares_delta"])), row["stock_code"])

    first_buy.sort(key=_sort_key)
    increase.sort(key=_sort_key)
    decrease.sort(key=_sort_key)
    full_exit.sort(key=_sort_key)

    return {
        "etf_ticker": ticker,
        "as_of_date": curr["as_of_date"],
        "prev_as_of_date": prev["as_of_date"],
        "compared_at": now_taipei_iso(),
        "source": curr.get("source"),
        "placeholder_policy": {
            "max_shares": policy.max_shares,
            "max_weight_pct": policy.max_weight_pct,
            "exclude_from_changes": policy.exclude_from_changes,
        },
        "summary": {
            "first_buy": len(first_buy),
            "increase": len(increase),
            "decrease": len(decrease),
            "full_exit": len(full_exit),
        },
        "first_buy": first_buy,
        "increase": increase,
        "decrease": decrease,
        "full_exit": full_exit,
    }


def save_change_report(cfg: AppConfig, report: dict[str, Any]) -> Path:
    ticker = report["etf_ticker"]
    as_of = report["as_of_date"]
    path = cfg.changes_dir / ticker / f"{as_of}.json"
    write_json(path, report)
    return path


def save_snapshot(cfg: AppConfig, snapshot: dict[str, Any]) -> Path:
    ticker = snapshot["etf_ticker"]
    as_of = snapshot["as_of_date"]
    path = cfg.snapshots_dir / ticker / f"{as_of}.json"
    write_json(path, snapshot)
    return path
