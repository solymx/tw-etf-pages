"""CLI: python -m tw_etf_pages [dry-run|run|render]."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tw_etf_pages",
        description="台灣主動式 ETF 每日持股異動報告",
    )
    parser.add_argument(
        "command",
        choices=["dry-run", "run", "render"],
        help="dry-run: 使用 samples/ 離線產生；run: 線上下載；render: 僅重繪 HTML",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="專案根目錄（預設為套件上層）",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="主來源失敗時不改用 zdsetf",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    # Ensure src on path when run without pip install
    root_guess = Path(__file__).resolve().parents[2]
    src = root_guess / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from tw_etf_pages.config import load_config
    from tw_etf_pages.pipeline import dry_run, run_live
    from tw_etf_pages.render import render_site

    cfg = load_config(args.root)
    if args.command == "dry-run":
        site = dry_run(cfg)
        print(f"Dry-run OK → {site}")
        return 0
    if args.command == "run":
        site = run_live(cfg, allow_fallback=not args.no_fallback)
        print(f"Run OK → {site}")
        return 0
    if args.command == "render":
        site = render_site(cfg)
        print(f"Render OK → {site}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
