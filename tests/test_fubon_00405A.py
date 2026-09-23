"""Minimal tests: config loads 00405A; parse_zdsetf on saved fubon sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_zdsetf_snapshot


def test_config_loads_00405A_fubon():
    cfg = load_config(ROOT)
    etf = cfg.etf("00405A")
    assert etf.name == "主動富邦台灣龍耀"
    assert etf.issuer == "fubon"
    assert etf.fund_code == "00405A"
    assert "fsit.com.tw" in etf.source_page or "FubonETF" in etf.source_page
    assert "00405A" in etf.source_page


def test_parse_zdsetf_00405A_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "zdsetf_00405A_snapshot.json"
    assert path.is_file(), "missing samples/zdsetf_00405A_snapshot.json"
    snap = parse_zdsetf_snapshot(path, "00405A", cfg.placeholder)
    assert snap["etf_ticker"] == "00405A"
    assert snap["source"] == "zdsetf"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] >= 1
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert codes
    meta = snap.get("meta") or {}
    assert "fsit.com.tw" in str(meta.get("source_url") or "")


def test_parse_zdsetf_00992A_still_works():
    """Alias hardening must not break capital/00992A sample."""
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "zdsetf_00992A_snapshot.json"
    snap = parse_zdsetf_snapshot(path, "00992A", cfg.placeholder)
    assert snap["etf_ticker"] == "00992A"
    assert snap["holdings_count"] >= 1
    assert "capitalfund.com.tw" in str((snap.get("meta") or {}).get("source_url") or "")


if __name__ == "__main__":
    test_config_loads_00405A_fubon()
    test_parse_zdsetf_00405A_sample()
    test_parse_zdsetf_00992A_still_works()
    print("OK")
