"""Minimal tests: config loads 00881; parse_cathay on saved sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_cathay_weights


def test_config_loads_00881_cathay():
    cfg = load_config(ROOT)
    etf = cfg.etf("00881")
    assert etf.name == "國泰台灣科技龍頭"
    assert etf.issuer == "cathay"
    assert etf.fund_code == "CR"
    assert "cathaysite.com.tw" in etf.source_page
    assert "ECR" in etf.source_page


def test_parse_cathay_00881_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "cathay_00881_weights.json"
    assert path.is_file(), "missing samples/cathay_00881_weights.json"
    snap = parse_cathay_weights(path, "00881", cfg.placeholder)
    assert snap["etf_ticker"] == "00881"
    assert snap["source"] == "cathay"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] >= 20
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert "2330" in codes
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    assert any(h["weight_pct"] > 0.0 for h in snap["holdings"])
    tsmc = next(h for h in snap["holdings"] if h["stock_code"] == "2330")
    assert tsmc["weight_pct"] > 30.0
    assert tsmc["shares"] > 0  # synthetic from weight
    meta = snap.get("meta") or {}
    assert "cathaysite.com.tw" in str(meta.get("source_url") or "")


if __name__ == "__main__":
    test_config_loads_00881_cathay()
    test_parse_cathay_00881_sample()
    print("OK")
