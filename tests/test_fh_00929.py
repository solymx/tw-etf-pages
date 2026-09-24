"""Minimal tests: config loads 00929; parse_fh_excel on saved sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_fh_excel


def test_config_loads_00929_fh():
    cfg = load_config(ROOT)
    etf = cfg.etf("00929")
    assert etf.name == "復華台灣科技優息"
    assert etf.issuer == "fh"
    assert etf.fund_code == "ETF21"
    assert "fhtrust.com.tw" in etf.source_page
    assert "ETF21" in etf.source_page


def test_parse_fh_00929_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "00929_20260924.xlsx"
    assert path.is_file(), "missing samples/00929_20260924.xlsx"
    snap = parse_fh_excel(path, "00929", cfg.placeholder)
    assert snap["etf_ticker"] == "00929"
    assert snap["source"] == "fh_excel"
    assert snap["as_of_date"] == "2026-09-24"
    assert snap["holdings_count"] == 50  # tech high-div basket equities
    codes = {h["stock_code"] for h in snap["holdings"]}
    # futures block must be excluded
    assert not any(c.startswith("WTX") for c in codes)
    assert "2357" in codes or "3034" in codes or "2317" in codes
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    assert any(h["weight_pct"] > 0.0 for h in snap["holdings"])
    top = max(snap["holdings"], key=lambda h: h["weight_pct"])
    assert top["shares"] > 0
    meta = snap.get("meta") or {}
    assert meta.get("nav_total_raw") or meta.get("units_raw") or meta.get("nav_pu_raw")


if __name__ == "__main__":
    test_config_loads_00929_fh()
    test_parse_fh_00929_sample()
    print("OK")
