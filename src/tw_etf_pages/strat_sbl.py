"""策略 4：借券賣出餘額（空方壓力）。

Sources (public):
  - 借券賣出餘額／融券餘額：data/strategy/sbl（TWSE rwd TWT93U、TPEx www margin/sbl；strategy_daily 每日存檔）
  - 發行股數：TWSE openapi opendata/t187ap03_L（已發行普通股數）、TPEx openapi mopsfin_t187ap03_O（IssueShares）
  - 融資餘額（券資比用）：TWSE rwd MI_MARGN（指定日期）、TPEx openapi tpex_mainboard_margin_balance
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from .strategy_common import STOCK_CODE, any_to_date, http_json, label, num, session, strategy_dir, today_tw
from .strategy_daily import load_series
from .strat_daily_compact import write_compact
from .utils import now_taipei_iso, read_json

logger = logging.getLogger(__name__)

AP03_L = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
AP03_O = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
MI_MARGN = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TPEX_MARGIN = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"
SRC_L = "https://www.twse.com.tw/zh/trading/margin/twt93u.html"
SRC_O = "https://www.tpex.org.tw/zh-tw/mainboard/trading/margin-trading/sbl.html"
LOOKBACK = 20


def _dir(root: Path) -> Path:
    return strategy_dir(root) / "sbl_meta"


def update_shares(root: Path, today: date) -> None:
    p = _dir(root) / "shares.json"
    if p.is_file():
        old = read_json(p)
        if (today - date.fromisoformat(old["fetched_on"])).days < 7:
            return
    sess = session()
    shares: dict[str, int] = {}
    try:
        for r in http_json(sess, AP03_L):
            c = str(r.get("公司代號", "")).strip()
            v = num(r.get("已發行普通股數或TDR原股發行股數"))
            if STOCK_CODE.match(c) and v:
                shares[c] = int(v)
        for r in http_json(sess, AP03_O):
            c = str(r.get("SecuritiesCompanyCode", "")).strip()
            v = num(r.get("IssueShares"))
            if STOCK_CODE.match(c) and v:
                shares[c] = int(v)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sbl shares fetch failed: %s", exc)
        return
    if len(shares) > 1500:
        write_compact(p, {"fetched_on": today.isoformat(), "shares": shares})


def update_margin(root: Path, d: str) -> None:
    """融資／融券餘額（張）for the latest SBL date — only for 券資比 display."""
    p = _dir(root) / "margin.json"
    if p.is_file() and read_json(p).get("date") == d:
        return
    sess = session()
    rows: dict[str, list[float]] = {}
    try:
        js = http_json(sess, MI_MARGN, params={"date": d.replace("-", ""), "selectType": "ALL", "response": "json"})
        for t in js.get("tables") or []:
            f = t.get("fields") or []
            if f and f[0] == "代號" and len(f) > 12:
                for r in t["data"]:
                    c = str(r[0]).strip()
                    if STOCK_CODE.match(c):
                        rows[c] = [num(r[6]) or 0, num(r[12]) or 0]  # 融資今日餘額, 融券今日餘額
        js = http_json(sess, TPEX_MARGIN)
        if js and any_to_date(js[0]["Date"]).isoformat() == d:
            for r in js:
                c = str(r.get("SecuritiesCompanyCode", "")).strip()
                if STOCK_CODE.match(c):
                    rows[c] = [num(r.get("MarginPurchaseBalance")) or 0, num(r.get("ShortSaleBalance")) or 0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("sbl margin fetch failed: %s", exc)
    if rows:
        write_compact(p, {"date": d, "fetched_at": now_taipei_iso(), "rows": rows})


def update_sbl(root: Path, today: date | None = None) -> None:
    today = today or today_tw()
    update_shares(root, today)
    series = load_series(root, "sbl")
    if series:
        update_margin(root, series[-1]["date"])


def classify(ratio_pct_rank: float | None, g20: float | None) -> str:
    """ratio_pct_rank: 0–100 (100 = highest ratio)."""
    if ratio_pct_rank is None:
        return "neutral"
    if ratio_pct_rank >= 90 and g20 is not None and g20 > 0:
        return "bear"
    if ratio_pct_rank >= 80 and g20 is not None and g20 < -20:
        return "relief"
    return "neutral"


def compute(root: Path) -> dict[str, Any] | None:
    series = load_series(root, "sbl")
    if not series:
        return None
    sp = _dir(root) / "shares.json"
    shares = read_json(sp)["shares"] if sp.is_file() else {}
    mp = _dir(root) / "margin.json"
    margin = read_json(mp) if mp.is_file() else {"rows": {}, "date": None}
    cur = series[-1]
    base = series[-1 - LOOKBACK] if len(series) > LOOKBACK else None
    items = []
    for code, (name, mkt, bal, short) in cur["rows"].items():
        sh = shares.get(code)
        ratio = bal / sh * 100 if sh else None
        g20 = None
        if base and code in base["rows"] and base["rows"][code][2] > 0:
            g20 = (bal / base["rows"][code][2] - 1) * 100
        m = margin["rows"].get(code) if margin.get("date") == cur["date"] else None
        sr = (m[1] / m[0] * 100) if m and m[0] else None
        items.append({"code": code, "name": name, "market": mkt, "sbl": bal, "ratio": ratio, "g20": g20,
                      "short": short, "short_ratio": sr})
    ranked = sorted([x for x in items if x["ratio"] is not None], key=lambda x: x["ratio"])
    n = len(ranked)
    for i, x in enumerate(ranked):
        x["rank_pct"] = (i + 1) / n * 100
    for x in items:
        x.setdefault("rank_pct", None)
        x["kind"] = classify(x["rank_pct"], x["g20"])
        x["label"] = {"bear": "偏空（空方壓力高）", "relief": "空方減壓", "neutral": "中性"}[x["kind"]]
    items.sort(key=lambda x: (x["ratio"] is not None, x["ratio"] or 0), reverse=True)
    total = sum(x["sbl"] for x in items)
    total_base = sum(r[2] for r in base["rows"].values()) if base else None
    g_total = (total / total_base - 1) * 100 if total_base else None
    verdict = "na" if g_total is None else "bear" if g_total > 10 else "bull" if g_total < -10 else "neutral"
    reason = ("資料暫缺（借券歷史未滿 21 個交易日）。" if g_total is None else
              f"全市場借券賣出餘額 {total / 1e8:.2f} 億股，較 {LOOKBACK} 個交易日前（{base['date']}）"
              f"{'增加' if g_total >= 0 else '減少'} {abs(g_total):.1f}%"
              + ("，超過 +10%，空方壓力上升。" if verdict == "bear" else "，低於 −10%，空方在回補。" if verdict == "bull"
                 else "，在 ±10% 內。"))
    return {
        "date": cur["date"], "base_date": base["date"] if base else None, "days": len(series),
        "items": items, "total": total, "total_base": total_base, "g_total": g_total,
        "verdict": verdict, "label": label(verdict), "reason": reason,
        "n_bear": sum(1 for x in items if x["kind"] == "bear"),
        "n_relief": sum(1 for x in items if x["kind"] == "relief"),
        "margin_date": margin.get("date"), "src_l": SRC_L, "src_o": SRC_O,
    }


def build_sbl_view(root: Path) -> dict[str, Any] | None:
    return compute(root)
