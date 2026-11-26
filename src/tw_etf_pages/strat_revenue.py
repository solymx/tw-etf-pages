"""策略 1：月營收年增率動能（上市櫃，排除金融業）。

Sources (public):
  - 最新月：TWSE openapi t187ap05_L（上市）、TPEx openapi mopsfin_t187ap05_O（上櫃；只有最新月）
  - 歷史月：mopsov.twse.com.tw/nas/t21/{sii,otc}/t21sc03_{民國年}_{月}_{0,1}.html（Big5；_0 國內、_1 外國/KY）
Snapshots: data/strategy/revenue/months/YYYY-MM.json  {code: [name, market, industry, revenue, yoy, mom, cum_yoy]}
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from .strategy_common import (
    STOCK_CODE, http, http_json, label, median, num, roc_ym_to_iso, session, strategy_dir, today_tw,
)
from .strat_daily_compact import write_compact
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

OPEN_L = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
OPEN_O = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
MOPS_HIST = "https://mopsov.twse.com.tw/nas/t21/{mkt}/t21sc03_{roc}_{m}_{k}.html"
SRC = "https://mopsov.twse.com.tw/mops/web/t21sc04_ifrs"
HIST_MONTHS = 13
STRONG = 20.0


def months_dir(root: Path) -> Path:
    return strategy_dir(root) / "revenue" / "months"


def is_financial(industry: str) -> bool:
    return "金融" in (industry or "")


def parse_openapi(js: list, market: str) -> tuple[str | None, dict[str, list]]:
    out: dict[str, list] = {}
    ym: str | None = None
    for r in js:
        code = str(r.get("公司代號", "")).strip()
        if not STOCK_CODE.match(code):
            continue
        rev = num(r.get("營業收入-當月營收"))
        if rev is None:
            continue
        ym_r = roc_ym_to_iso(r["資料年月"])
        ym = max(ym or ym_r, ym_r)
        out[code] = [str(r.get("公司名稱", "")).strip(), market, str(r.get("產業別", "")).strip(), rev,
                     num(r.get("營業收入-去年同月增減(%)")), num(r.get("營業收入-上月比較增減(%)")),
                     num(r.get("累計營業收入-前期比較增減(%)")), ym_r]
    return ym, out


_ROW = re.compile(
    r"<td align=center>\s*(\d{4})\s*</td>\s*<td align=left>([^<]*)</td>"
    r"((?:\s*<[tT][dD][^>]*>[^<]*</[tT][dD]>){9})", re.S)
_CELL = re.compile(r"<[tT][dD][^>]*>([^<]*)</[tT][dD]>")
_IND = re.compile(r"產業別[：:]\s*([^<\s]+)")


def parse_mops_html(text: str, market: str) -> dict[str, list]:
    inds = [(m.start(), m.group(1).strip()) for m in _IND.finditer(text)]
    out: dict[str, list] = {}
    for m in _ROW.finditer(text):
        ind = ""
        for pos, name in inds:
            if pos < m.start():
                ind = name
            else:
                break
        cells = [num(c) for c in _CELL.findall(m.group(3))]
        rev, _prev, _ly, mom, yoy, _cum, _cumly, cum_yoy = cells[0], cells[1], cells[2], cells[3], cells[4], cells[5], cells[6], cells[7]
        if rev is None:
            continue
        out[m.group(1)] = [html.unescape(m.group(2)).strip(), market, ind, rev, yoy, mom, cum_yoy]
    return out


def _prev_months(ym: str, n: int) -> list[str]:
    y, m = int(ym[:4]), int(ym[5:])
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}-{m:02d}")
    return out


def update_revenue(root: Path, today: date | None = None) -> str | None:
    """Snapshot the latest month from openapi; backfill missing history months from MOPS. Returns latest ym."""
    sess = session()
    md = months_dir(root)
    md.mkdir(parents=True, exist_ok=True)
    latest: dict[str, list] = {}
    yms: list[str] = []
    for url, mkt in ((OPEN_L, "上市"), (OPEN_O, "上櫃")):
        try:
            ym, rows = parse_openapi(http_json(sess, url), mkt)
            if ym:
                yms.append(ym)
                latest.update({k: v[:7] for k, v in rows.items() if v[7] == ym})
        except Exception as exc:  # noqa: BLE001
            logger.warning("revenue openapi %s failed: %s", mkt, exc)
    ym = max(yms) if yms else None
    if ym and latest:
        p = md / f"{ym}.json"
        old = read_json(p).get("rows", {}) if p.is_file() else {}
        # the official list fills in during the month (11th–18th); keep any history rows, overlay openapi
        write_compact(p, {"ym": ym, "source": "openapi", "updated_at": now_taipei_iso(), "rows": {**old, **latest}})
    anchor = ym or max((q.stem for q in md.glob("*.json")), default=None)
    if not anchor:
        return None
    for hm in _prev_months(anchor, HIST_MONTHS):
        p = md / f"{hm}.json"
        if p.is_file():
            continue
        roc, mo = int(hm[:4]) - 1911, int(hm[5:])
        rows: dict[str, list] = {}
        ok = True
        for mkt, mname in (("sii", "上市"), ("otc", "上櫃")):
            for k in (0, 1):
                try:
                    r = http(sess, MOPS_HIST.format(mkt=mkt, roc=roc, m=mo, k=k))
                    rows.update(parse_mops_html(r.content.decode("big5", errors="replace"), mname))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("revenue MOPS %s %s_%d failed: %s", hm, mkt, k, exc)
                    ok = ok and k == 1  # foreign page is optional
        if ok and len(rows) > 500:
            write_compact(p, {"ym": hm, "source": "mopsov", "updated_at": now_taipei_iso(), "rows": rows})
            logger.info("revenue %s: %d companies", hm, len(rows))
    return ym


def _load_months(root: Path) -> dict[str, dict[str, list]]:
    return {p.stem: read_json(p)["rows"] for p in sorted(months_dir(root).glob("*.json"))}


def classify(yoy: float | None, cum: float | None, mom: float | None, high12: bool) -> tuple[str, str]:
    if yoy is not None and cum is not None and mom is not None and yoy >= STRONG and cum >= STRONG and mom > 0:
        return ("bull", "偏多（強）" if high12 else "偏多")
    if yoy is not None and cum is not None and yoy < 0 and cum < 0:
        return ("bear", "偏空")
    return ("neutral", "中性")


def compute(months: dict[str, dict[str, list]]) -> dict[str, Any] | None:
    if not months:
        return None
    ym = max(months)
    cur = months[ym]
    prev_keys = _prev_months(ym, HIST_MONTHS)
    items = []
    for code, r in cur.items():
        name, mkt, ind, rev, yoy, mom, cum = r[:7]
        if is_financial(ind):
            continue
        hist = [months[k][code][3] for k in prev_keys[:11] if k in months and code in months[k]]
        high12 = len(hist) == 11 and rev >= max(hist)
        streak = 0
        for k in [ym] + prev_keys:
            row = months.get(k, {}).get(code)
            if row and row[4] is not None and row[4] > STRONG:
                streak += 1
            else:
                break
        kind, text = classify(yoy, cum, mom, high12)
        items.append({"code": code, "name": name, "market": mkt, "industry": ind, "revenue": rev,
                      "yoy": yoy, "cum_yoy": cum, "mom": mom, "high12": high12, "high12_known": len(hist) == 11,
                      "streak": streak, "kind": kind, "label": text,
                      "screen": kind == "bull"})
    items.sort(key=lambda x: (x["yoy"] is not None, x["yoy"] or 0), reverse=True)
    with_yoy = [x for x in items if x["yoy"] is not None]
    pos = sum(1 for x in with_yoy if x["yoy"] > 0)
    share = round(pos / len(with_yoy) * 100, 1) if with_yoy else None
    med = median([x["yoy"] for x in with_yoy if x["market"] == "上市"])
    verdict = "na" if share is None else "bull" if share > 60 else "bear" if share < 40 else "neutral"
    reason = ("資料暫缺。" if share is None else
              f"{ym} 有 {pos}/{len(with_yoy)} 家（{share:.1f}%）單月營收年增 > 0，"
              f"{'高於 60%' if verdict == 'bull' else '低於 40%' if verdict == 'bear' else '介於 40%～60%'}；上市年增率中位數 {med:.1f}%。")
    return {
        "ym": ym, "items": items, "screened": [x for x in items if x["screen"]],
        "share_pos": share, "n_pos": pos, "n_total": len(with_yoy), "median_listed": med,
        "verdict": verdict, "label": label(verdict), "reason": reason,
        "n_bull": sum(1 for x in items if x["kind"] == "bull"),
        "n_bear": sum(1 for x in items if x["kind"] == "bear"),
        "n_high12": sum(1 for x in items if x["high12"]),
        "months_stored": sorted(months), "source": SRC,
    }


def build_revenue_view(root: Path) -> dict[str, Any] | None:
    v = compute(_load_months(root))
    if v:
        write_json(strategy_dir(root) / "revenue" / "latest_summary.json",
                   {k: v[k] for k in ("ym", "share_pos", "n_pos", "n_total", "median_listed", "verdict", "reason")})
    return v
