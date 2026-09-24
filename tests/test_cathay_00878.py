"""Minimal tests: config loads 00878; parse_cathay on saved sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_cathay_weights


def test_config_loads_00878_cathay():
    cfg = load_config(ROOT)
    etf = cfg.etf("00878")
    assert etf.name == "國泰永續高股息"
    assert etf.issuer == "cathay"
    assert etf.fund_code == "CN"
    assert "cathaysite.com.tw" in etf.source_page
    assert "ECS" in etf.source_page


def test_parse_cathay_00878_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "cathay_00878_weights.json"
    assert path.is_file(), "missing samples/cathay_00878_weights.json"
    snap = parse_cathay_weights(path, "00878", cfg.placeholder)
    assert snap["etf_ticker"] == "00878"
    assert snap["source"] == "cathay"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] >= 20
    codes = {h["stock_code"] for h in snap["holdings"]}
    # 00878 is a high-dividend / ESG basket; financials commonly present
    assert "2891" in codes or "2882" in codes
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    assert any(h["weight_pct"] > 0.0 for h in snap["holdings"])
    top = max(snap["holdings"], key=lambda h: h["weight_pct"])
    assert top["shares"] > 0  # synthetic from weight
    meta = snap.get("meta") or {}
    assert "cathaysite.com.tw" in str(meta.get("source_url") or "")


if __name__ == "__main__":
    test_config_loads_00878_cathay()
    test_parse_cathay_00878_sample()
    print("OK")
