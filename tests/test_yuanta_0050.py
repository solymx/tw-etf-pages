"""Minimal tests: config loads 0050; parse_yuanta on saved sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_yuanta_ratio


def test_config_loads_0050_yuanta():
    cfg = load_config(ROOT)
    etf = cfg.etf("0050")
    assert etf.name == "元大台灣卓越50"
    assert etf.issuer == "yuanta"
    assert etf.fund_code == "0050"
    assert "yuantaetfs.com" in etf.source_page
    assert "/0050/ratio" in etf.source_page


def test_parse_yuanta_0050_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "yuanta_0050_ratio.json"
    assert path.is_file(), "missing samples/yuanta_0050_ratio.json"
    snap = parse_yuanta_ratio(path, "0050", cfg.placeholder)
    assert snap["etf_ticker"] == "0050"
    assert snap["source"] == "yuanta"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] == 50
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert "2330" in codes
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    assert any(h["weight_pct"] > 0.0 for h in snap["holdings"])
    # TSMC should dominate Taiwan 50
    tsmc = next(h for h in snap["holdings"] if h["stock_code"] == "2330")
    assert tsmc["weight_pct"] > 30.0
    meta = snap.get("meta") or {}
    assert "yuantaetfs.com" in str(meta.get("source_url") or "")


if __name__ == "__main__":
    test_config_loads_0050_yuanta()
    test_parse_yuanta_0050_sample()
    print("OK")
