"""Render the 4 strategy pages + build the 「今日多空總覽」 data for index.html. Never raises."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .strategy_common import label

logger = logging.getLogger(__name__)


def update_strategies(root: Path) -> None:
    """Fetch step for the daily pipeline; each part is isolated."""
    steps = []
    from .strategy_daily import update_daily
    from .strat_revenue import update_revenue
    from .strat_divlowvol import update_divlowvol
    from .strat_futures import update_futures
    from .strat_sbl import update_sbl

    steps = [("daily prices/SBL", lambda: update_daily(root)), ("revenue", lambda: update_revenue(root)),
             ("dividend low-vol", lambda: update_divlowvol(root)), ("futures/PC", lambda: update_futures(root)),
             ("SBL meta", lambda: update_sbl(root))]
    for name, fn in steps:
        try:
            fn()
        except Exception:  # noqa: BLE001
            logger.exception("Strategy update failed: %s", name)


def render_strategies(env: Any, site: Path, root: Path, generated_at: str) -> dict[str, Any]:
    from .strat_revenue import build_revenue_view
    from .strat_divlowvol import build_divlowvol_view
    from .strat_futures import build_futures_view
    from .strat_sbl import build_sbl_view

    views: dict[str, Any] = {}
    pages = (("rv", build_revenue_view, "strat_revenue.html", "revenue.html"),
             ("dv", build_divlowvol_view, "strat_divlowvol.html", "dividend-lowvol.html"),
             ("fv", build_futures_view, "strat_futures.html", "futures-pc.html"),
             ("sb", build_sbl_view, "strat_sbl.html", "sbl.html"))
    for key, build, tpl, out in pages:
        try:
            v = build(root)
            views[key] = v
            if v:
                (site / out).write_text(env.get_template(tpl).render(
                    **{key: v}, generated_at=generated_at, assets_prefix="assets"), encoding="utf-8")
                logger.info("Wrote %s", site / out)
        except Exception:  # noqa: BLE001
            logger.exception("Strategy page %s failed", out)
            views[key] = None
    na = label("na")
    rv, fv, sb, dv = views.get("rv"), views.get("fv"), views.get("sb"), views.get("dv")
    cards = [
        {"title": "① 月營收大盤溫度計", "href": "revenue.html",
         "label": rv["label"] if rv else na, "reason": rv["reason"] if rv else "資料暫缺。",
         "date": f"{rv['ym']}（月）" if rv else None, "flag": None},
        {"title": "③ 外資期貨＋P/C 合計分數", "href": "futures-pc.html",
         "label": fv["label"] if fv else na, "reason": fv["reason"] if fv else "資料暫缺。",
         "date": fv["latest"]["date"] if fv else None,
         "flag": ("結算週：訊號可能失真" if fv and fv["latest"]["settle"] else None)},
        {"title": "④ 借券賣出（大盤）", "href": "sbl.html",
         "label": sb["label"] if sb else na, "reason": sb["reason"] if sb else "資料暫缺。",
         "date": sb["date"] if sb else None, "flag": None},
    ]
    return {"cards": cards, "dv": dv}
