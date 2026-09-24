"""Minimal tests: config loads 00918; parse_uobam on saved sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_uobam_pcf


def test_config_loads_00918_uobam():
    cfg = load_config(ROOT)
    etf = cfg.etf("00918")
    assert etf.name == "大華優利高填息30"
    assert etf.issuer == "uobam"
    assert etf.fund_code == "88329556"
    assert "uobam.com.tw" in etf.source_page
    assert "88329556" in etf.source_page


def test_parse_uobam_00918_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "uobam_00918_pcf.json"
    assert path.is_file(), "missing samples/uobam_00918_pcf.json"
    snap = parse_uobam_pcf(path, "00918", cfg.placeholder)
    assert snap["etf_ticker"] == "00918"
    assert snap["source"] == "uobam"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] == 30  # index is 30 names
    codes = {h["stock_code"] for h in snap["holdings"]}
    # high-fill / high-dividend basket — financials commonly present
    assert "2887" in codes or "2884" in codes or "2603" in codes
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    assert any(h["weight_pct"] > 0.0 for h in snap["holdings"])
    top = max(snap["holdings"], key=lambda h: h["weight_pct"])
    assert top["shares"] > 0  # real qty from PCF
    meta = snap.get("meta") or {}
    assert "uobam.com.tw" in str(meta.get("source_url") or meta.get("api_url") or "")


if __name__ == "__main__":
    test_config_loads_00918_uobam()
    test_parse_uobam_00918_sample()
    print("OK")
