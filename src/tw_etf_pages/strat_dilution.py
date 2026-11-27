"""策略 10：現金增資與股本稀釋。

(a) 即將除權的現金增資：TWSE openapi exchangeReport/TWT48U_ALL（SubscriptionRatio 有值才是現增）、
    TPEx openapi tpex_exright_prepost（SubscriptionRatioToNewSharesIssued）。每天存預告快照。
(b) 12 個月淨發行：ln(今日股數 ÷ 12 個月前股數)，股數取 t187ap03_L／mopsfin_t187ap03_O；
    每月存一份股數快照，滿 12 個月前顯示「資料累積中」。
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .strategy_common import STOCK_CODE, any_to_date, http_json, num, session, strategy_dir, today_tw
from .strategy_daily import load_series
from .strat_daily_compact import write_compact
from .utils import read_json

logger = logging.getLogger(__name__)

TWT48U = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
TPEX_PRE = "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost"
AP03_L = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
AP03_O = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
HIGH_DIL = 10.0     # 認股比率 ≥ 10% →「高稀釋」（經驗值）
MKT_HIGH = 5        # 未來 20 個交易日內除權的「高稀釋」現增 ≥ 5 檔 → 偏空（經驗值）


def dil_dir(root: Path) -> Path:
    return strategy_dir(root) / "dilution"


def parse_twt48u(js: list) -> list[dict[str, Any]]:
    out = []
    for r in js:
        code = str(r.get("Code", "")).strip()
        ratio = num(r.get("SubscriptionRatio"))
        if STOCK_CODE.match(code) and ratio and ratio > 0:
            out.append({"code": code, "name": str(r.get("Name", "")).strip(), "market": "上市",
                        "ex_date": any_to_date(str(r["Date"])).isoformat(), "ratio": round(ratio * 100, 3),
                        "price": num(r.get("SubscriptionPricePerShare")),
                        "price_note": "" if num(r.get("SubscriptionPricePerShare")) else str(r.get("SubscriptionPricePerShare", "")).strip()})
    return out


def parse_tpex_pre(js: list) -> list[dict[str, Any]]:
    out = []
    for r in js:
        code = str(r.get("SecuritiesCompanyCode", "")).strip()
        ratio = num(r.get("SubscriptionRatioToNewSharesIssued"))
        if STOCK_CODE.match(code) and ratio and ratio > 0:
            p = num(r.get("SubscriptionPricePerShare"))
            out.append({"code": code, "name": str(r.get("CompanyName", "")).strip(), "market": "上櫃",
                        "ex_date": any_to_date(str(r["ExRrightsExDividendDate"])).isoformat(), "ratio": round(ratio * 100, 3),
                        "price": p if p else None,
                        "price_note": "" if p else ("尚未公告" if str(r.get("SubscriptionPricePerShare", "")).startswith("註") else str(r.get("SubscriptionPricePerShare", "")))})
    return out


def update_dilution(root: Path, today: date | None = None) -> None:
    today = today or today_tw()
    sess = session()
    try:
        rows = parse_twt48u(http_json(sess, TWT48U)) + parse_tpex_pre(http_json(sess, TPEX_PRE))
        write_compact(dil_dir(root) / "forecast" / f"{today.isoformat()}.json", {"date": today.isoformat(), "rows": rows})
    except Exception as exc:  # noqa: BLE001
        logger.warning("dilution forecast failed: %s", exc)
    sp = dil_dir(root) / "shares" / f"{today:%Y-%m}.json"
    if not sp.is_file():
        try:
            shares: dict[str, int] = {}
            for r in http_json(sess, AP03_L):
                c, v = str(r.get("公司代號", "")).strip(), num(r.get("已發行普通股數或TDR原股發行股數"))
                if STOCK_CODE.match(c) and v:
                    shares[c] = int(v)
            for r in http_json(sess, AP03_O):
                c, v = str(r.get("SecuritiesCompanyCode", "")).strip(), num(r.get("IssueShares"))
                if STOCK_CODE.match(c) and v:
                    shares[c] = int(v)
            if len(shares) > 1500:
                write_compact(sp, {"date": today.isoformat(), "shares": shares})
        except Exception as exc:  # noqa: BLE001
            logger.warning("dilution shares snapshot failed: %s", exc)


def _tdays_until(d: str, today: str, closed: set[str]) -> int:
    n, x, end = 0, date.fromisoformat(today) + timedelta(days=1), date.fromisoformat(d)
    while x <= end:
        if x.weekday() < 5 and x.isoformat() not in closed:
            n += 1
        x += timedelta(days=1)
    return n


def issuance(root: Path) -> tuple[dict[str, float], str | None, str | None]:
    snaps = sorted((dil_dir(root) / "shares").glob("*.json"))
    if len(snaps) < 13:
        return {}, (snaps[0].stem if snaps else None), None
    old, new = read_json(snaps[-13]), read_json(snaps[-1])
    out = {c: math.log(v / old["shares"][c]) for c, v in new["shares"].items() if old["shares"].get(c)}
    return out, old["date"], new["date"]


def build_dilution_view(root: Path) -> dict[str, Any] | None:
    fs = sorted((dil_dir(root) / "forecast").glob("*.json"))
    if not fs:
        return None
    cur = read_json(fs[-1])
    prev = read_json(fs[-2]) if len(fs) > 1 else None
    prev_keys = {(r["code"], r["ex_date"]) for r in prev["rows"]} if prev else None
    series = load_series(root, "prices")
    px = series[-1]["rows"] if series else {}
    cp = strategy_dir(root) / "closed_days.json"
    closed = set(read_json(cp).get("closed", [])) if cp.is_file() else set()
    today = cur["date"]
    iss, iss_from, iss_to = issuance(root)
    ranked = sorted(iss.values())
    pct_of = {c: (sorted(ranked).index(v) + 1) / len(ranked) * 100 for c, v in iss.items()} if ranked else {}
    items = []
    for r in cur["rows"]:
        if r["ex_date"] < today:
            continue
        x = dict(r)
        x["close"] = px.get(r["code"], [None, None, None])[2]
        x["discount"] = (1 - r["price"] / x["close"]) * 100 if r.get("price") and x["close"] else None
        x["tdays"] = _tdays_until(r["ex_date"], today, closed)
        x["event"] = prev_keys is not None and (r["code"], r["ex_date"]) not in prev_keys
        x["iss_pct"] = pct_of.get(r["code"])
        x["kind"] = "bear"
        x["label"] = "偏空（高稀釋）" if r["ratio"] >= HIGH_DIL else "偏空"
        items.append(x)
    items.sort(key=lambda x: x["ex_date"])
    # (b) quintiles of 12-month issuance (when available)
    iss_items = []
    if iss:
        names = {c: v[0] for c, v in px.items()}
        for c, v in iss.items():
            p = pct_of[c]
            kind, lab = ("bear", "偏空（發行最多 20%）") if p > 80 else ("bull", "弱偏多（僅相對）") if p <= 20 else ("neutral", "中性")
            iss_items.append({"code": c, "name": names.get(c, ""), "iss": v * 100, "pct": p, "kind": kind, "label": lab})
        iss_items.sort(key=lambda x: x["iss"], reverse=True)
    n_high20 = sum(1 for x in items if x["ratio"] >= HIGH_DIL and x["tdays"] <= 20)
    bear = n_high20 >= MKT_HIGH
    verdict = "bear" if bear else "neutral"
    reason = (f"預告除權的現金增資 {len(items)} 檔，其中未來 20 個交易日內除權、認股比率 ≥ 10% 的 {n_high20} 檔；"
              + (f"≥ {MKT_HIGH} 檔（經驗值），籌資賣壓偏多。" if bear else f"少於 {MKT_HIGH} 檔（經驗值）。"))
    return {"items": items, "date": today, "verdict": verdict, "label": {"text": "偏空" if bear else "中性", "cls": verdict},
            "reason": reason, "n_high": sum(1 for x in items if x["ratio"] >= HIGH_DIL), "n_high20": n_high20,
            "iss_items": iss_items, "iss_from": iss_from, "iss_to": iss_to,
            "n_share_snaps": len(list((dil_dir(root) / "shares").glob("*.json"))), "first_forecast": fs[0].stem,
            "price_date": series[-1]["date"] if series else None}
