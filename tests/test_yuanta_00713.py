"""Minimal tests: config loads 00713; parse_yuanta on saved sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_yuanta_ratio


def test_config_loads_00713_yuanta():
    cfg = load_config(ROOT)
    etf = cfg.etf("00713")
    assert etf.name == "元大台灣高息低波"
    assert etf.issuer == "yuanta"
    assert etf.fund_code == "00713"
    assert "yuantaetfs.com" in etf.source_page
    assert "/00713/ratio" in etf.source_page


def test_parse_yuanta_00713_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "yuanta_00713_ratio.json"
    assert path.is_file(), "missing samples/yuanta_00713_ratio.json"
    snap = parse_yuanta_ratio(path, "00713", cfg.placeholder)
    assert snap["etf_ticker"] == "00713"
    assert snap["source"] == "yuanta"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] == 50
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert "3045" in codes  # 台灣大 typically top weight in High Div Low Vol
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    assert any(h["weight_pct"] > 0.0 for h in snap["holdings"])
    # High Div Low Vol is more equal-weight — no mega TSMC tilt
    top = max(snap["holdings"], key=lambda h: h["weight_pct"])
    assert top["weight_pct"] < 15.0
    meta = snap.get("meta") or {}
    assert "yuantaetfs.com" in str(meta.get("source_url") or "")
    assert "高股息低波" in str(meta.get("fundname") or "") or "高息低波" in str(
        meta.get("fundname") or ""
    )


if __name__ == "__main__":
    test_config_loads_00713_yuanta()
    test_parse_yuanta_00713_sample()
    print("OK")
