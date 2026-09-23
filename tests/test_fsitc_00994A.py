"""Minimal tests: config loads 00994A; parse_zdsetf on saved fsitc sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_zdsetf_snapshot


def test_config_loads_00994A_fsitc():
    cfg = load_config(ROOT)
    etf = cfg.etf("00994A")
    assert etf.name == "主動第一金台股優"
    assert etf.issuer == "fsitc"
    assert etf.fund_code == "182"
    assert "fsitc.com.tw" in etf.source_page
    assert "ID=182" in etf.source_page


def test_parse_zdsetf_00994A_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "zdsetf_00994A_snapshot.json"
    assert path.is_file(), "missing samples/zdsetf_00994A_snapshot.json"
    snap = parse_zdsetf_snapshot(path, "00994A", cfg.placeholder)
    assert snap["etf_ticker"] == "00994A"
    assert snap["source"] == "zdsetf"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] >= 1
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert codes
    # weight_pct arrives as string; parser must normalize to float (do not invent)
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    # This sample has non-null weights (unlike 00400A/00401A/00987A all-null cases)
    assert any(h["weight_pct"] > 0.0 for h in snap["holdings"])
    meta = snap.get("meta") or {}
    assert "fsitc.com.tw" in str(meta.get("source_url") or "")
    assert "ID=182" in str(meta.get("source_url") or "")


def test_parse_zdsetf_aliases_still_work_for_prior_fsitc():
    """Adding 00994A must not break 00408A sample parse."""
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "zdsetf_00408A_snapshot.json"
    snap = parse_zdsetf_snapshot(path, "00408A", cfg.placeholder)
    assert snap["etf_ticker"] == "00408A"
    assert snap["holdings_count"] >= 1
    assert "fsitc.com.tw" in str((snap.get("meta") or {}).get("source_url") or "")


if __name__ == "__main__":
    test_config_loads_00994A_fsitc()
    test_parse_zdsetf_00994A_sample()
    test_parse_zdsetf_aliases_still_work_for_prior_fsitc()
    print("OK")
