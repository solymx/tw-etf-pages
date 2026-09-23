"""Minimal tests: config loads 00408A; parse_zdsetf on saved fsitc sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_zdsetf_snapshot


def test_config_loads_00408A_fsitc():
    cfg = load_config(ROOT)
    etf = cfg.etf("00408A")
    assert etf.name == "主動第一金優股息"
    assert etf.issuer == "fsitc"
    assert etf.fund_code == "183"
    assert "fsitc.com.tw" in etf.source_page
    assert "ID=183" in etf.source_page


def test_parse_zdsetf_00408A_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "zdsetf_00408A_snapshot.json"
    assert path.is_file(), "missing samples/zdsetf_00408A_snapshot.json"
    snap = parse_zdsetf_snapshot(path, "00408A", cfg.placeholder)
    assert snap["etf_ticker"] == "00408A"
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


def test_parse_zdsetf_aliases_still_work_for_prior_issuers():
    """Alias hardening must not break prior zdsetf-primary issuer samples."""
    cfg = load_config(ROOT)
    for ticker, needle in (
        ("00992A", "capitalfund.com.tw"),
        ("00405A", "fsit.com.tw"),
        ("00406A", "ctbcinvestments.com"),
        ("00980A", "nomurafunds.com.tw"),
        ("00984A", "allianzgi.com.tw"),
        ("00400A", "cathaysite.com.tw"),
        ("00401A", "am.jpmorgan.com"),
        ("00987A", "tsit.com.tw"),
    ):
        path = ROOT / "samples" / f"zdsetf_{ticker}_snapshot.json"
        snap = parse_zdsetf_snapshot(path, ticker, cfg.placeholder)
        assert snap["etf_ticker"] == ticker
        assert snap["holdings_count"] >= 1
        assert needle in str((snap.get("meta") or {}).get("source_url") or "")


if __name__ == "__main__":
    test_config_loads_00408A_fsitc()
    test_parse_zdsetf_00408A_sample()
    test_parse_zdsetf_aliases_still_work_for_prior_issuers()
    print("OK")
