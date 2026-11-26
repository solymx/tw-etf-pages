"""策略 2：高殖利率＋低波動（防守型名單）。

Sources (public):
  - 殖利率／本益比：TWSE openapi exchangeReport/BWIBBU_d（DividendYield, PEratio, PBratio）、
                   TPEx openapi tpex_mainboard_peratio_analysis（YieldRatio, PriceEarningRatio）
  - 配息年度：TWSE rwd exRight/TWT49U、TPEx www bulletin/exDailyQ（除權息結果，每年一次請求並快取）
  - 處置股：TWSE openapi announcement/punish、TPEx openapi tpex_disposal_information
  - 日收盤／成交值：data/strategy/prices（strategy_daily）
近四季 EPS 以「收盤價 ÷ 本益比」推得（交易所本益比即以近四季 EPS 計算；本益比空白代表 EPS ≤ 0）。
"""

from __future__ import annotations

import logging
import math
from datetime import date
from pathlib import Path
from typing import Any

from .strategy_common import (
    STOCK_CODE, any_to_date, http_json, num, session, stdev, strategy_dir, today_tw,
)
from .strategy_daily import BENCH, load_series
from .strat_daily_compact import write_compact
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

BWIBBU = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d"
TPEX_PE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
TWT49U = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
EXDAILYQ = "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ"
PUNISH_L = "https://openapi.twse.com.tw/v1/announcement/punish"
PUNISH_O = "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information"
SRC_L = "https://www.twse.com.tw/zh/trading/historical/bwibbu-day.html"
SRC_O = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/pe-ratio.html"

MIN_TURNOVER = 30_000_000
N_PICK = 30
VOL_DAYS = 250
MIN_DIV_YEARS = 5
DIV_YEARS_BACK = 7
MAX_DAILY_MOVE = 0.11  # |r| > 11% exceeds the 10% price limit → corporate action, drop from σ


def div_dir(root: Path) -> Path:
    return strategy_dir(root) / "dividend"


def parse_twt49u(js: dict) -> set[str]:
    if str(js.get("stat", "")).upper() != "OK":
        return set()
    f = js["fields"]
    ic, ik = f.index("股票代號"), f.index("權/息")
    return {str(r[ic]).strip() for r in js["data"] if "息" in str(r[ik]) and STOCK_CODE.match(str(r[ic]).strip())}


def parse_exdailyq(js: dict) -> set[str]:
    t = (js.get("tables") or [{}])[0]
    f = t.get("fields") or []
    if not f:
        return set()
    ic, ik = f.index("代號"), f.index("息值")
    return {str(r[ic]).strip() for r in t.get("data", []) if (num(r[ik]) or 0) > 0 and STOCK_CODE.match(str(r[ic]).strip())}


def update_div_years(root: Path, today: date) -> None:
    sess = session()
    d = div_dir(root)
    for y in range(today.year - DIV_YEARS_BACK + 1, today.year + 1):
        p = d / f"exdiv_{y}.json"
        if p.is_file():
            old = read_json(p)
            fresh = y < today.year or old.get("fetched_on") == today.isoformat() or (
                today - date.fromisoformat(old["fetched_on"])).days < 7
            if fresh and old.get("complete"):
                continue
        try:
            tw = parse_twt49u(http_json(sess, TWT49U, params={"startDate": f"{y}0101", "endDate": f"{y}1231", "response": "json"}))
            ot = parse_exdailyq(http_json(sess, EXDAILYQ, params={"startDate": f"{y}/01/01", "endDate": f"{y}/12/31", "response": "json"}))
            if not tw or not ot:
                raise RuntimeError(f"empty ex-dividend list {y}: TWSE {len(tw)} TPEx {len(ot)}")
            write_json(p, {"year": y, "fetched_on": today.isoformat(), "complete": True,
                           "codes": sorted(tw | ot)})
        except Exception as exc:  # noqa: BLE001
            logger.warning("ex-dividend %s failed: %s", y, exc)


def div_streaks(root: Path, today: date) -> tuple[dict[str, int], bool]:
    years = {}
    for y in range(today.year - DIV_YEARS_BACK + 1, today.year + 1):
        p = div_dir(root) / f"exdiv_{y}.json"
        if p.is_file():
            years[y] = set(read_json(p)["codes"])
    complete = all(y in years for y in range(today.year - DIV_YEARS_BACK + 1, today.year))
    codes = set().union(*years.values()) if years else set()
    out = {}
    for c in codes:
        n = 0
        # 今年若已除息就算今年；否則從去年起算
        start = today.year if c in years.get(today.year, set()) else today.year - 1
        for y in range(start, start - DIV_YEARS_BACK, -1):
            if c in years.get(y, set()):
                n += 1
            else:
                break
        out[c] = n
    return out, complete


def fetch_fundamentals(root: Path) -> dict[str, Any]:
    sess = session()
    rows: dict[str, dict[str, Any]] = {}
    dates = {}
    errors = []
    try:
        js = http_json(sess, BWIBBU)
        for r in js:
            c = str(r.get("Code", "")).strip()
            if STOCK_CODE.match(c):
                rows[c] = {"name": r.get("Name", "").strip(), "market": "上市", "yield": num(r.get("DividendYield")),
                           "pe": num(r.get("PEratio")), "pb": num(r.get("PBratio"))}
                dates["上市"] = any_to_date(r["Date"]).isoformat()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"BWIBBU_d: {exc}")
    try:
        js = http_json(sess, TPEX_PE)
        for r in js:
            c = str(r.get("SecuritiesCompanyCode", "")).strip()
            if STOCK_CODE.match(c):
                rows[c] = {"name": r.get("CompanyName", "").strip(), "market": "上櫃", "yield": num(r.get("YieldRatio")),
                           "pe": num(r.get("PriceEarningRatio")), "pb": num(r.get("PriceBookRatio"))}
                dates["上櫃"] = any_to_date(r["Date"]).isoformat()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"tpex_mainboard_peratio_analysis: {exc}")
    punished = set()
    for url, key in ((PUNISH_L, "Code"), (PUNISH_O, "SecuritiesCompanyCode")):
        try:
            punished |= {str(r.get(key, "")).strip() for r in http_json(sess, url)}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"punish: {exc}")
    out = {"dates": dates, "rows": rows, "punished": sorted(punished), "errors": errors, "fetched_at": now_taipei_iso()}
    if rows:
        write_compact(div_dir(root) / "fundamentals.json", out)
    return out


def rebalance_key(d: date) -> str:
    if d.month >= 12:
        return f"{d.year}-12"
    if d.month >= 6:
        return f"{d.year}-06"
    return f"{d.year - 1}-12"


def _price_stats(series: list[dict[str, Any]], code: str) -> dict[str, Any]:
    closes = [(s["date"], s["rows"][code][2]) for s in series if code in s["rows"]]
    turn = [s["rows"][code][3] for s in series[-20:] if code in s["rows"]]
    rets = []
    for (_, a), (_, b) in zip(closes, closes[1:]):
        if a > 0:
            r = b / a - 1
            if abs(r) <= MAX_DAILY_MOVE:
                rets.append(r)
    rets = rets[-VOL_DAYS:]
    sd = stdev(rets)
    c = [x for _, x in closes]
    return {
        "close": c[-1] if c else None,
        "n_days": len(c),
        "turnover20": (sum(turn) / len(turn)) if turn else None,
        "vol": round(sd * math.sqrt(250) * 100, 2) if sd is not None and len(rets) >= 40 else None,
        "ma60": (sum(c[-60:]) / 60) if len(c) >= 60 else None,
        "chg60": (c[-1] / c[-61] - 1) * 100 if len(c) >= 61 else None,
        "chg20": (c[-1] / c[-21] - 1) * 100 if len(c) >= 21 else None,
    }


def compute(root: Path, today: date | None = None) -> dict[str, Any] | None:
    today = today or today_tw()
    fp = div_dir(root) / "fundamentals.json"
    if not fp.is_file():
        return None
    fund = read_json(fp)
    series = load_series(root, "prices")
    if len(series) < 21:
        return None
    streaks, div_complete = div_streaks(root, today)
    punished = set(fund.get("punished", []))
    latest = series[-1]["rows"]
    pool = []
    for code, f in fund["rows"].items():
        if code not in latest or code in punished:
            continue
        st = _price_stats(series, code)
        if st["turnover20"] is None or st["turnover20"] < MIN_TURNOVER or not f.get("yield"):
            continue
        eps = round(st["close"] / f["pe"], 2) if f.get("pe") and st["close"] else None
        pool.append({"code": code, "name": f["name"], "market": f["market"], "yield": f["yield"],
                     "pe": f.get("pe"), "eps4q": eps, "eps_pos": eps is not None and eps > 0,
                     "div_years": streaks.get(code, 0), **st})
    pool.sort(key=lambda x: x["yield"], reverse=True)
    top = pool[: max(1, len(pool) // 3)]
    qual = [x for x in top if x["div_years"] >= MIN_DIV_YEARS and x["eps_pos"] and x["vol"] is not None]
    qual.sort(key=lambda x: x["vol"])
    picks = {x["code"] for x in qual[:N_PICK]}
    n_days = len(series)
    provisional = n_days < VOL_DAYS + 1
    # frozen list per rebalance period (Jun/Dec); keep recomputing while price history is still short
    key = rebalance_key(today)
    lp = div_dir(root) / "list.json"
    saved = read_json(lp) if lp.is_file() else None
    if saved and saved.get("period") == key and not saved.get("provisional") and not provisional:
        picks = set(saved["codes"])
    else:
        write_json(lp, {"period": key, "formed_on": series[-1]["date"], "provisional": provisional,
                        "price_days": n_days, "codes": sorted(picks)})
        saved = read_json(lp)
    for x in top:
        x["picked"] = x["code"] in picks
        x["steady"] = x["picked"] and x["yield"] > 5 and x["ma60"] is not None and x["close"] > x["ma60"]
        x["trap"] = (x["chg60"] is not None and x["chg60"] < -15) or not x["eps_pos"]
        x["trap_why"] = "；".join(
            ([f"近 60 日跌 {-x['chg60']:.1f}%"] if x["chg60"] is not None and x["chg60"] < -15 else [])
            + (["近四季 EPS ≤ 0（本益比空白）"] if not x["eps_pos"] else []))
    picked_rows = [x for x in top if x["picked"]]
    # basket 20d return vs 0050
    rets = [x["chg20"] for x in picked_rows if x["chg20"] is not None]
    basket = sum(rets) / len(rets) if rets else None
    bench = _price_stats(series, BENCH)["chg20"] if BENCH in latest else None
    mood = None
    if basket is not None and bench is not None:
        mood = "defensive" if basket > bench else "offensive"
    reason = ("資料暫缺。" if mood is None else
              f"入選 {len(rets)} 檔等權近 20 日報酬 {basket:+.2f}%，0050 {bench:+.2f}%；"
              + ("防守股跑贏大盤，市場偏保守、資金避險。" if mood == "defensive" else "防守股跑輸大盤，市場偏追高、風險偏好高。"))
    return {
        "date": series[-1]["date"], "fund_dates": fund.get("dates", {}),
        "pool_n": len(pool), "top_n": len(top), "qual_n": len(qual),
        "picked": sorted(picked_rows, key=lambda x: x["vol"] if x["vol"] is not None else 999),
        "top": top, "n_steady": sum(1 for x in top if x["steady"]), "n_trap": sum(1 for x in top if x["trap"]),
        "basket20": basket, "bench20": bench, "mood": mood,
        "mood_label": {"defensive": {"text": "防守氣氛（偏保守）", "cls": "neutral"},
                       "offensive": {"text": "攻擊氣氛（追高）", "cls": "neutral"},
                       None: {"text": "資料暫缺", "cls": "na"}}[mood],
        "reason": reason, "price_days": n_days, "provisional": provisional, "div_complete": div_complete,
        "period": saved.get("period"), "formed_on": saved.get("formed_on"),
        "errors": fund.get("errors", []), "src_l": SRC_L, "src_o": SRC_O,
    }


def update_divlowvol(root: Path, today: date | None = None) -> None:
    today = today or today_tw()
    update_div_years(root, today)
    fetch_fundamentals(root)


def build_divlowvol_view(root: Path) -> dict[str, Any] | None:
    return compute(root)
