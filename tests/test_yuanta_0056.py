"""Minimal tests: config loads 0056; parse_yuanta on saved sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_yuanta_ratio


def test_config_loads_0056_yuanta():
    cfg = load_config(ROOT)
    etf = cfg.etf("0056")
    assert etf.name == "元大台灣高股息"
    assert etf.issuer == "yuanta"
    assert etf.fund_code == "0056"
    assert "yuantaetfs.com" in etf.source_page
    assert "/0056/ratio" in etf.source_page


def test_parse_yuanta_0056_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "yuanta_0056_ratio.json"
    assert path.is_file(), "missing samples/yuanta_0056_ratio.json"
    snap = parse_yuanta_ratio(path, "0056", cfg.placeholder)
    assert snap["etf_ticker"] == "0056"
    assert snap["source"] == "yuanta"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] == 50
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert "1303" in codes  # 南亞 typically top weight in High Dividend
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    assert any(h["weight_pct"] > 0.0 for h in snap["holdings"])
    # High Dividend is more equal-weight than Taiwan 50 — no mega TSMC tilt
    top = max(snap["holdings"], key=lambda h: h["weight_pct"])
    assert top["weight_pct"] < 15.0
    meta = snap.get("meta") or {}
    assert "yuantaetfs.com" in str(meta.get("source_url") or "")
    assert "高股息" in str(meta.get("fundname") or "")


if __name__ == "__main__":
    test_config_loads_0056_yuanta()
    test_parse_yuanta_0056_sample()
    print("OK")
