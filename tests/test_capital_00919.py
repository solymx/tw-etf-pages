"""Minimal tests: config loads 00919; parse_capital_buyback on saved sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_capital_buyback


def test_config_loads_00919_capital():
    cfg = load_config(ROOT)
    etf = cfg.etf("00919")
    assert etf.name == "群益台灣精選高息"
    assert etf.issuer == "capital"
    assert etf.fund_code == "195"
    assert "capitalfund.com.tw" in etf.source_page
    assert "195" in etf.source_page


def test_parse_capital_00919_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "capital_00919_buyback.json"
    assert path.is_file(), "missing samples/capital_00919_buyback.json"
    snap = parse_capital_buyback(path, "00919", cfg.placeholder)
    assert snap["etf_ticker"] == "00919"
    assert snap["source"] == "capital"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] >= 20  # select high-div basket (~40 names)
    codes = {h["stock_code"] for h in snap["holdings"]}
    # high-dividend financials commonly dominate 00919
    assert "2881" in codes or "2882" in codes or "2891" in codes
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    assert any(h["weight_pct"] > 0.0 for h in snap["holdings"])
    top = max(snap["holdings"], key=lambda h: h["weight_pct"])
    assert top["shares"] > 0  # real qty from official buyback
    meta = snap.get("meta") or {}
    assert "capitalfund.com.tw" in str(meta.get("source_url") or meta.get("api_url") or "")


if __name__ == "__main__":
    test_config_loads_00919_capital()
    test_parse_capital_00919_sample()
    print("OK")
