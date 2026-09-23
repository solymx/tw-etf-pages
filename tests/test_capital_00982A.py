"""Minimal tests: config loads 00982A; parse_zdsetf on saved capital sample."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.config import load_config
from tw_etf_pages.parse import parse_zdsetf_snapshot


def test_config_loads_00982A_capital():
    cfg = load_config(ROOT)
    etf = cfg.etf("00982A")
    assert etf.name == "主動群益台灣強棒"
    assert etf.issuer == "capital"
    assert etf.fund_code == "399"
    assert "capitalfund.com.tw" in etf.source_page
    assert "399" in etf.source_page


def test_parse_zdsetf_00982A_sample():
    cfg = load_config(ROOT)
    path = ROOT / "samples" / "zdsetf_00982A_snapshot.json"
    assert path.is_file(), "missing samples/zdsetf_00982A_snapshot.json"
    snap = parse_zdsetf_snapshot(path, "00982A", cfg.placeholder)
    assert snap["etf_ticker"] == "00982A"
    assert snap["source"] == "zdsetf"
    assert snap["as_of_date"]  # non-empty ISO date
    assert snap["holdings_count"] >= 1
    codes = {h["stock_code"] for h in snap["holdings"]}
    assert codes  # at least one holding code
    meta = snap.get("meta") or {}
    assert "capitalfund.com.tw" in str(meta.get("source_url") or "")


if __name__ == "__main__":
    test_config_loads_00982A_capital()
    test_parse_zdsetf_00982A_sample()
    print("OK")
