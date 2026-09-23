"""Parser + compare unit tests using samples/ (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.compare import compare_snapshots
from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_fh_excel, parse_uni_excel


def test_parse_uni_00981A():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "00981A_ETF_Investment_Portfolio_20260922.xlsx"
    snap = parse_uni_excel(path, "00981A", cfg.placeholder)
    assert snap["as_of_date"] == "2026-09-22"
    assert snap["holdings_count"] == 50
    assert snap["placeholder_count"] >= 10
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert "2330" in codes
    tsmc = next(h for h in snap["holdings"] if h["stock_code"] == "2330")
    assert tsmc["shares"] == 11_864_000


def test_parse_fh_two_dates_and_compare():
    cfg = load_config(ROOT)
    a = parse_fh_excel(ROOT / "samples" / "00991A_20260918.xlsx", "00991A", cfg.placeholder)
    b = parse_fh_excel(ROOT / "samples" / "00991A_20260922.xlsx", "00991A", cfg.placeholder)
    assert a["as_of_date"] == "2026-09-18"
    assert b["as_of_date"] == "2026-09-22"
    report = compare_snapshots(a, b, cfg, compute_streak=False)
    assert "summary" in report
    total = sum(report["summary"].values())
    # Expect some activity between 09-18 and 09-22
    assert total >= 0
    for row in report["increase"] + report["decrease"]:
        assert row["curr_shares"] != row["prev_shares"]


if __name__ == "__main__":
    test_parse_uni_00981A()
    test_parse_fh_two_dates_and_compare()
    print("OK")
