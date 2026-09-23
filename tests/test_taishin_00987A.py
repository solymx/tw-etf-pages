"""Minimal tests: config loads 00987A; parse_zdsetf on saved taishin sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_zdsetf_snapshot


def test_config_loads_00987A_taishin():
    cfg = load_config(ROOT)
    etf = cfg.etf("00987A")
    assert etf.name == "主動台新優勢成長"
    assert etf.issuer == "taishin"
    assert etf.fund_code == "00987A"
    assert "tsit.com.tw" in etf.source_page
    assert "00987A" in etf.source_page


def test_parse_zdsetf_00987A_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "zdsetf_00987A_snapshot.json"
    assert path.is_file(), "missing samples/zdsetf_00987A_snapshot.json"
    snap = parse_zdsetf_snapshot(path, "00987A", cfg.placeholder)
    assert snap["etf_ticker"] == "00987A"
    assert snap["source"] == "zdsetf"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] >= 1
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert codes
    # weight_pct may arrive as string or null; parser must normalize to float
    # (00987A sample has all-null weights → 0.0; do not invent non-zero weights)
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    assert all(h["weight_pct"] == 0.0 for h in snap["holdings"])
    meta = snap.get("meta") or {}
    assert "tsit.com.tw" in str(meta.get("source_url") or "")


def test_parse_zdsetf_aliases_still_work_for_prior_issuers():
    """Alias hardening must not break capital / fubon / ctbc / nomura / allianz / cathay / jpm samples."""
    cfg = load_config(ROOT)
    for ticker, needle in (
        ("00992A", "capitalfund.com.tw"),
        ("00405A", "fsit.com.tw"),
        ("00406A", "ctbcinvestments.com"),
        ("00980A", "nomurafunds.com.tw"),
        ("00984A", "allianzgi.com.tw"),
        ("00400A", "cathaysite.com.tw"),
        ("00401A", "am.jpmorgan.com"),
    ):
        path = ROOT / "samples" / f"zdsetf_{ticker}_snapshot.json"
        snap = parse_zdsetf_snapshot(path, ticker, cfg.placeholder)
        assert snap["etf_ticker"] == ticker
        assert snap["holdings_count"] >= 1
        assert needle in str((snap.get("meta") or {}).get("source_url") or "")


if __name__ == "__main__":
    test_config_loads_00987A_taishin()
    test_parse_zdsetf_00987A_sample()
    test_parse_zdsetf_aliases_still_work_for_prior_issuers()
    print("OK")
