"""Holdings trend / intermittent-buy unit tests (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.trend import _intermittent_buy_stats, _deltas, build_holdings_trend


def test_intermittent_buy_gap_buy():
    # deltas[0] is always None (no prev); then ↑ · ↑
    shares = [1000, 2000, 2000, 3000]
    deltas = _deltas(shares)
    stats = _intermittent_buy_stats(deltas)
    assert stats["pattern"] == "↑·↑"
    assert stats["intermittent_buy_score"] == 1
    assert stats["buy_days"] == 2
    assert "間歇" in stats["intermittent_label"]


def test_consecutive_buys_not_intermittent():
    shares = [1000, 2000, 3000, 4000]
    stats = _intermittent_buy_stats(_deltas(shares))
    assert stats["pattern"] == "↑↑↑"
    assert stats["intermittent_buy_score"] == 0
    assert stats["buy_days"] == 3


def test_build_trend_from_archived_snapshots():
    cfg = load_config(ROOT)
    # 00991A should have FH backfill (~20 days) if present; else at least 2
    trend = build_holdings_trend(cfg.snapshots_dir, "00991A", cfg.placeholder)
    assert trend["etf_ticker"] == "00991A"
    assert trend["day_count"] >= 2
    assert trend["enough_for_chart"] is True
    assert len(trend["dates"]) == trend["day_count"]
    assert trend["stocks"]
    for s in trend["stocks"]:
        assert len(s["shares"]) == trend["day_count"]


def test_build_trend_sparse_00981A():
    cfg = load_config(ROOT)
    trend = build_holdings_trend(cfg.snapshots_dir, "00981A", cfg.placeholder)
    assert trend["day_count"] >= 1
    # With only 2 days, intermittent highlight may be empty — still valid payload
    assert "default_codes" in trend
    assert "top_intermittent" in trend


if __name__ == "__main__":
    test_intermittent_buy_gap_buy()
    test_consecutive_buys_not_intermittent()
    test_build_trend_from_archived_snapshots()
    test_build_trend_sparse_00981A()
    print("OK")
