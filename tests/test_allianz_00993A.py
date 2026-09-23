"""Minimal tests: config loads 00993A; parse_zdsetf on saved allianz sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_zdsetf_snapshot


def test_config_loads_00993A_allianz():
    cfg = load_config(ROOT)
    etf = cfg.etf("00993A")
    assert etf.name == "主動安聯台灣"
    assert etf.issuer == "allianz"
    assert etf.fund_code == "E0002"
    assert "allianzgi.com.tw" in etf.source_page
    assert "E0002" in etf.source_page


def test_parse_zdsetf_00993A_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "zdsetf_00993A_snapshot.json"
    assert path.is_file(), "missing samples/zdsetf_00993A_snapshot.json"
    snap = parse_zdsetf_snapshot(path, "00993A", cfg.placeholder)
    assert snap["etf_ticker"] == "00993A"
    assert snap["source"] == "zdsetf"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] >= 1
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert codes
    # weight_pct may arrive as string; parser must normalize
    assert all(isinstance(h["weight_pct"], float) for h in snap["holdings"])
    meta = snap.get("meta") or {}
    assert "allianzgi.com.tw" in str(meta.get("source_url") or "")


def test_parse_zdsetf_aliases_still_work_for_prior_allianz():
    """Adding 00993A must not break 00984A sample parse."""
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "zdsetf_00984A_snapshot.json"
    snap = parse_zdsetf_snapshot(path, "00984A", cfg.placeholder)
    assert snap["etf_ticker"] == "00984A"
    assert snap["holdings_count"] >= 1
    assert "allianzgi.com.tw" in str((snap.get("meta") or {}).get("source_url") or "")


if __name__ == "__main__":
    test_config_loads_00993A_allianz()
    test_parse_zdsetf_00993A_sample()
    test_parse_zdsetf_aliases_still_work_for_prior_allianz()
    print("OK")
