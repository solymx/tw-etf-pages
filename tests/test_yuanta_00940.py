"""Minimal tests: config loads 00940; parse_yuanta on saved sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_yuanta_ratio


def test_config_loads_00940_yuanta():
    cfg = load_config(ROOT)
    etf = cfg.etf("00940")
    assert etf.name == "元大台灣價值高息"
    assert etf.issuer == "yuanta"
    assert etf.fund_code == "00940"
    assert "yuantaetfs.com" in etf.source_page
    assert "/00940/ratio" in etf.source_page


def test_parse_yuanta_00940_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "yuanta_00940_ratio.json"
    assert path.is_file(), "missing samples/yuanta_00940_ratio.json"
    snap = parse_yuanta_ratio(path, "00940", cfg.placeholder)
    assert snap["etf_ticker"] == "00940"
    assert snap["source"] == "yuanta"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] == 50
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert "2357" in codes  # 華碩 typically top weight in Value High Div
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    assert any(h["weight_pct"] > 0.0 for h in snap["holdings"])
    # Value high-div is more equal-weight — no mega TSMC tilt
    top = max(snap["holdings"], key=lambda h: h["weight_pct"])
    assert top["weight_pct"] < 15.0
    meta = snap.get("meta") or {}
    assert "yuantaetfs.com" in str(meta.get("source_url") or "")
    assert "價值高息" in str(meta.get("fundname") or "")


if __name__ == "__main__":
    test_config_loads_00940_yuanta()
    test_parse_yuanta_00940_sample()
    print("OK")
