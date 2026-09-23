"""Minimal tests: config loads 00985A; parse_zdsetf on saved nomura sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_zdsetf_snapshot


def test_config_loads_00985A_nomura():
    cfg = load_config(ROOT)
    etf = cfg.etf("00985A")
    assert etf.name == "主動野村台灣50"
    assert etf.issuer == "nomura"
    assert etf.fund_code == "00985A"
    assert "nomurafunds.com.tw" in etf.source_page
    assert "00985A" in etf.source_page


def test_parse_zdsetf_00985A_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "zdsetf_00985A_snapshot.json"
    assert path.is_file(), "missing samples/zdsetf_00985A_snapshot.json"
    snap = parse_zdsetf_snapshot(path, "00985A", cfg.placeholder)
    assert snap["etf_ticker"] == "00985A"
    assert snap["source"] == "zdsetf"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] >= 1
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert codes
    # weight_pct may arrive as string; parser must normalize
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    meta = snap.get("meta") or {}
    assert "nomurafunds.com.tw" in str(meta.get("source_url") or "")


def test_parse_zdsetf_aliases_still_work_for_prior_nomura():
    """Adding 00985A must not break 00980A sample parse."""
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "zdsetf_00980A_snapshot.json"
    snap = parse_zdsetf_snapshot(path, "00980A", cfg.placeholder)
    assert snap["etf_ticker"] == "00980A"
    assert snap["holdings_count"] >= 1
    assert "nomurafunds.com.tw" in str((snap.get("meta") or {}).get("source_url") or "")


if __name__ == "__main__":
    test_config_loads_00985A_nomura()
    test_parse_zdsetf_00985A_sample()
    test_parse_zdsetf_aliases_still_work_for_prior_nomura()
    print("OK")
