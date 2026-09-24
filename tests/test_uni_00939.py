"""Minimal tests: config loads 00939; parse_uni_excel on saved sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_uni_excel


def test_config_loads_00939_uni():
    cfg = load_config(ROOT)
    etf = cfg.etf("00939")
    assert etf.name == "統一台灣高息動能"
    assert etf.issuer == "uni"
    assert etf.fund_code == "46YTW"
    assert "ezmoney.com.tw" in etf.source_page
    assert "46YTW" in etf.source_page


def test_parse_uni_00939_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "00939_20260924.xlsx"
    assert path.is_file(), "missing samples/00939_20260924.xlsx"
    snap = parse_uni_excel(path, "00939", cfg.placeholder)
    assert snap["etf_ticker"] == "00939"
    assert snap["source"] == "uni_excel"
    assert snap["as_of_date"] == "2026-09-24"
    assert snap["holdings_count"] == 40  # 特選臺灣高息動能指數 ~40 equities
    codes = {h["stock_code"] for h in snap["holdings"]}
    # futures block (TX) must be excluded — only equities after 股票代號
    assert "TX" not in codes
    assert "2881" in codes or "2882" in codes or "2357" in codes
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    assert any(h["weight_pct"] > 0.0 for h in snap["holdings"])
    top = max(snap["holdings"], key=lambda h: h["weight_pct"])
    assert top["shares"] > 0
    meta = snap.get("meta") or {}
    assert meta.get("nav_total_raw") or meta.get("units_raw") or meta.get("nav_pu_raw")


if __name__ == "__main__":
    test_config_loads_00939_uni()
    test_parse_uni_00939_sample()
    print("OK")
