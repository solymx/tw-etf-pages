"""Render static HTML site from snapshots + change reports."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .compare import list_snapshot_dates, load_snapshot
from .config import AppConfig
from .utils import now_taipei_iso, read_json

logger = logging.getLogger(__name__)

TEMPLATES = Path(__file__).parent / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def latest_change_report(cfg: AppConfig, ticker: str) -> dict[str, Any] | None:
    d = cfg.changes_dir / ticker
    if not d.is_dir():
        return None
    files = sorted(d.glob("*.json"))
    if not files:
        return None
    return read_json(files[-1])


def latest_snapshot(cfg: AppConfig, ticker: str) -> dict[str, Any] | None:
    dates = list_snapshot_dates(cfg.snapshots_dir, ticker)
    if not dates:
        return None
    return load_snapshot(cfg.snapshots_dir, ticker, dates[-1])


def render_site(cfg: AppConfig) -> Path:
    env = _env()
    site = cfg.site_dir
    site.mkdir(parents=True, exist_ok=True)
    generated_at = now_taipei_iso()

    index_rows: list[dict[str, Any]] = []
    all_etfs_meta = [{"ticker": e.ticker, "name": e.name} for e in cfg.etfs]

    for etf in cfg.etfs:
        snap = latest_snapshot(cfg, etf.ticker)
        report = latest_change_report(cfg, etf.ticker)
        summary = {"first_buy": 0, "increase": 0, "decrease": 0, "full_exit": 0}
        if report:
            summary = report.get("summary", summary)
        index_rows.append(
            {
                "ticker": etf.ticker,
                "name": etf.name,
                "as_of_date": (report or snap or {}).get("as_of_date"),
                "prev_as_of_date": (report or {}).get("prev_as_of_date"),
                "source": (report or snap or {}).get("source"),
                "summary": summary,
            }
        )

        html = env.get_template("etf.html").render(
            ticker=etf.ticker,
            name=etf.name,
            as_of_date=(report or snap or {}).get("as_of_date"),
            prev_as_of_date=(report or {}).get("prev_as_of_date"),
            source=(report or snap or {}).get("source"),
            source_page=etf.source_page,
            report=report,
            snapshot=snap,
            all_etfs=all_etfs_meta,
            generated_at=generated_at,
            ph_max_shares=cfg.placeholder.max_shares,
            ph_max_weight=cfg.placeholder.max_weight_pct,
        )
        (site / f"{etf.ticker}.html").write_text(html, encoding="utf-8")
        logger.info("Wrote %s", site / f"{etf.ticker}.html")

    index_html = env.get_template("index.html").render(
        etfs=index_rows,
        generated_at=generated_at,
    )
    (site / "index.html").write_text(index_html, encoding="utf-8")

    # GitHub Pages: avoid Jekyll processing
    (site / ".nojekyll").write_text("", encoding="utf-8")
    logger.info("Wrote %s", site / "index.html")
    return site
