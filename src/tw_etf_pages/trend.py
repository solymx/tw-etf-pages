"""Build per-stock share time series (~20 trading days) for ETF trend charts."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from .compare import list_snapshot_dates, load_snapshot
from .config import PlaceholderPolicy

logger = logging.getLogger(__name__)

DEFAULT_MAX_DAYS = 20
TOP_INTERMITTENT = 8
TOP_ACTIVITY = 12


def _deltas(shares: list[int | None]) -> list[int | None]:
    """Day-over-day share deltas; None when either side missing."""
    out: list[int | None] = [None]
    for i in range(1, len(shares)):
        a, b = shares[i - 1], shares[i]
        if a is None or b is None:
            out.append(None)
        else:
            out.append(int(b) - int(a))
    return out


def _intermittent_buy_stats(deltas: list[int | None]) -> dict[str, Any]:
    """
    Detect intermittent buy (buy-gap-buy) patterns on consecutive archived days.

    A "buy" day is delta > 0. A "gap" is one or more non-buy days (flat/sell/missing)
    between two buy days. Score = number of such buy→gap→buy completions.
    """
    signs: list[str] = []
    for d in deltas[1:]:  # skip leading None placeholder
        if d is None:
            signs.append("?")
        elif d > 0:
            signs.append("↑")
        elif d < 0:
            signs.append("↓")
        else:
            signs.append("·")

    buy_days = sum(1 for s in signs if s == "↑")
    sell_days = sum(1 for s in signs if s == "↓")
    score = 0
    i = 0
    while i < len(signs):
        if signs[i] != "↑":
            i += 1
            continue
        j = i + 1
        saw_gap = False
        while j < len(signs) and signs[j] != "↑":
            if signs[j] in ("·", "↓", "?"):
                saw_gap = True
            j += 1
        if saw_gap and j < len(signs) and signs[j] == "↑":
            score += 1
            i = j  # continue from the second buy (may start another pair)
            continue
        i += 1

    label = ""
    if score >= 2:
        label = f"反覆間歇加碼×{score}"
    elif score == 1:
        label = "間歇加碼"
    elif buy_days >= 2 and "·" not in signs and "↓" not in signs and "?" not in signs:
        label = f"連續加碼{buy_days}日"
    elif buy_days >= 1:
        label = f"加碼{buy_days}日"

    return {
        "buy_days": buy_days,
        "sell_days": sell_days,
        "intermittent_buy_score": score,
        "intermittent_label": label,
        "pattern": "".join(signs) if signs else "",
    }


def build_holdings_trend(
    snapshots_dir,
    ticker: str,
    policy: PlaceholderPolicy,
    *,
    max_days: int = DEFAULT_MAX_DAYS,
) -> dict[str, Any]:
    """
    Build share-series for all non-placeholder stocks across the last N archived dates.

    Works with sparse history (1–2 days): charts still render; intermittent highlights
    need ≥3 dates. Grows automatically as Actions archives daily snapshots.
    """
    all_dates = list_snapshot_dates(snapshots_dir, ticker)
    dates = all_dates[-max_days:] if all_dates else []
    date_strs = [d.isoformat() for d in dates]

    # stock_code → {name, shares[], weights[]}
    series: dict[str, dict[str, Any]] = {}

    for d in dates:
        snap = load_snapshot(snapshots_dir, ticker, d)
        present: set[str] = set()
        for h in snap.get("holdings", []):
            if policy.exclude_from_changes and h.get("is_placeholder"):
                continue
            code = h["stock_code"]
            present.add(code)
            entry = series.setdefault(
                code,
                {
                    "stock_code": code,
                    "stock_name": h.get("stock_name") or "",
                    "shares": [None] * len(dates),
                    "weights": [None] * len(dates),
                },
            )
            if h.get("stock_name") and not entry["stock_name"]:
                entry["stock_name"] = h["stock_name"]
            idx = date_strs.index(d.isoformat())
            entry["shares"][idx] = int(h["shares"])
            w = h.get("weight_pct")
            entry["weights"][idx] = float(w) if w is not None else None
        # stocks that exited: leave None for that day (already default)

    stocks: list[dict[str, Any]] = []
    for code, entry in series.items():
        shares = entry["shares"]
        deltas = _deltas(shares)
        stats = _intermittent_buy_stats(deltas)
        # net change from first non-null to last non-null
        first = next((s for s in shares if s is not None), None)
        last = next((s for s in reversed(shares) if s is not None), None)
        net = (int(last) - int(first)) if first is not None and last is not None else 0
        activity = abs(net) + sum(abs(d) for d in deltas if d is not None)
        stocks.append(
            {
                **entry,
                **stats,
                "latest_shares": last,
                "net_delta": net,
                "activity": activity,
                "deltas": deltas,
            }
        )

    # Sort helpers
    by_intermittent = sorted(
        stocks,
        key=lambda s: (
            -s["intermittent_buy_score"],
            -s["buy_days"],
            -s["activity"],
            s["stock_code"],
        ),
    )
    by_activity = sorted(stocks, key=lambda s: (-s["activity"], s["stock_code"]))

    top_intermittent = [
        s["stock_code"]
        for s in by_intermittent
        if s["intermittent_buy_score"] > 0 or s["buy_days"] > 0
    ][:TOP_INTERMITTENT]

    # Default chart picks: prefer intermittent, else top activity movers
    default_codes = top_intermittent[:5]
    if len(default_codes) < 3:
        for s in by_activity:
            if s["stock_code"] not in default_codes and s["activity"] > 0:
                default_codes.append(s["stock_code"])
            if len(default_codes) >= 5:
                break
    if not default_codes and stocks:
        # flat holdings — show top weight by latest shares
        by_latest = sorted(
            stocks,
            key=lambda s: (-(s["latest_shares"] or 0), s["stock_code"]),
        )
        default_codes = [s["stock_code"] for s in by_latest[:5]]

    # Slim payload for HTML embed (drop weights/deltas from full list to keep size down?
    # Keep shares + key stats; weights optional for tooltip)
    slim_stocks = []
    for s in stocks:
        slim_stocks.append(
            {
                "stock_code": s["stock_code"],
                "stock_name": s["stock_name"],
                "shares": s["shares"],
                "buy_days": s["buy_days"],
                "sell_days": s["sell_days"],
                "intermittent_buy_score": s["intermittent_buy_score"],
                "intermittent_label": s["intermittent_label"],
                "pattern": s["pattern"],
                "latest_shares": s["latest_shares"],
                "net_delta": s["net_delta"],
                "activity": s["activity"],
            }
        )

    tip_rows = [
        {
            "stock_code": s["stock_code"],
            "stock_name": s["stock_name"],
            "intermittent_label": s["intermittent_label"],
            "pattern": s["pattern"],
            "buy_days": s["buy_days"],
            "sell_days": s["sell_days"],
            "intermittent_buy_score": s["intermittent_buy_score"],
            "net_delta": s["net_delta"],
            "latest_shares": s["latest_shares"],
        }
        for s in by_intermittent
        if s["intermittent_buy_score"] > 0 or s["buy_days"] >= 2
    ][:TOP_INTERMITTENT]

    return {
        "etf_ticker": ticker,
        "dates": date_strs,
        "day_count": len(date_strs),
        "max_days": max_days,
        "total_archived": len(all_dates),
        "stocks": slim_stocks,
        "top_intermittent": tip_rows,
        "default_codes": default_codes,
        "enough_for_intermittent": len(date_strs) >= 3,
        "enough_for_chart": len(date_strs) >= 2,
    }
