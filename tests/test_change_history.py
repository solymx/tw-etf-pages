"""Change history loading + date list (offline, uses archived data/)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tw_etf_pages.compare import list_snapshot_dates, save_change_report, compare_snapshots, load_snapshot
from tw_etf_pages.config import load_config
from tw_etf_pages.render import (
    build_change_history,
    ensure_change_reports,
    list_change_dates,
)


def test_list_change_dates_00981A():
    cfg = load_config(ROOT)
    dates = list_change_dates(cfg.changes_dir, "00981A")
    assert dates, "00981A should have at least one change report"
    # ascending
    assert dates == sorted(dates)


def test_ensure_backfills_missing_from_snapshots():
    cfg = load_config(ROOT)
    # 00991A has many snapshots; ensure fills gaps
    snap_dates = list_snapshot_dates(cfg.snapshots_dir, "00991A")
    assert len(snap_dates) >= 2
    written = ensure_change_reports(cfg, "00991A")
    # May be 0 if already backfilled in a prior run
    assert written >= 0
    change_dates = list_change_dates(cfg.changes_dir, "00991A")
    # Every snapshot except the first should have a change report
    expected = snap_dates[1:]
    assert change_dates == expected


def test_build_change_history_newest_first():
    cfg = load_config(ROOT)
    ensure_change_reports(cfg, "00981A")
    history = build_change_history(cfg, "00981A")
    assert history, "00981A history should not be empty"
    dates = [h["as_of_date"] for h in history]
    assert dates == sorted(dates, reverse=True)
    latest = history[0]
    assert "as_of_date" in latest
    assert "prev_as_of_date" in latest
    assert "summary" in latest
    assert "rows" in latest
    assert isinstance(latest["rows"], list)
    assert latest["changed_count"] == sum(1 for r in latest["rows"] if r["changed"])
    # Still show selector payload with 1–2 dates
    assert len(history) >= 1


def test_build_change_history_00991A_many_dates():
    cfg = load_config(ROOT)
    ensure_change_reports(cfg, "00991A")
    history = build_change_history(cfg, "00991A")
    assert len(history) >= 2
    assert len(history) <= 10  # UI date menu capped at 10 days
    for h in history:
        assert h["as_of_date"]
        assert "first_buy" in h
        assert "increase" in h
        assert "decrease" in h
        assert "full_exit" in h


def test_build_change_history_respects_max_days():
    cfg = load_config(ROOT)
    ensure_change_reports(cfg, "00991A")
    capped = build_change_history(cfg, "00991A", max_days=3)
    assert len(capped) <= 3
    all_dates = list_change_dates(cfg.changes_dir, "00991A")
    if len(all_dates) >= 3:
        assert [h["as_of_date"] for h in capped] == [
            d.isoformat() for d in reversed(all_dates[-3:])
        ]


if __name__ == "__main__":
    test_list_change_dates_00981A()
    test_ensure_backfills_missing_from_snapshots()
    test_build_change_history_newest_first()
    test_build_change_history_00991A_many_dates()
    test_build_change_history_respects_max_days()
    print("OK")
