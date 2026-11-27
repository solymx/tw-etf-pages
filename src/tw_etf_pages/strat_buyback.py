"""策略 6：庫藏股買回（董事會決議買回公告）。

Sources: TWSE openapi opendata/t187ap04_L（上市重大訊息，「主旨 」欄名尾端有空白）、
TPEx openapi mopsfin_t187ap04_O（上櫃重大訊息）。兩者都只給最近一天 → 每次執行存檔到
data/strategy/buyback/records.json（以 代號＋發言日期＋主旨 去重）。MOPS 歷史查詢會被 307 擋，所以從上線日起累積。
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from pathlib import Path
from typing import Any

from .strategy_common import STOCK_CODE, any_to_date, http_json, session, strategy_dir, today_tw
from .strategy_daily import load_series
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

OPEN_L = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
OPEN_O = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O"
SRC = "https://mops.twse.com.tw/mops/#/web/t35sc09"
FOLLOWUPS = ("執行完畢", "未執行完畢", "註銷", "轉讓", "金額達", "變更", "更正", "調整", "延長", "停止")
MIN_RATIO = 2.0       # 經驗值
MIN_MONTHS = 12       # 月數不足就顯示「資料累積中」
SIGMA = 1.5


def records_path(root: Path) -> Path:
    return strategy_dir(root) / "buyback" / "records.json"


def _field(text: str, pat: str) -> str | None:
    m = re.search(pat + r"\s*[:：]\s*([^\r\n]+)", text)
    return m.group(1).strip() if m else None


def parse_desc(desc: str) -> dict[str, Any]:
    t = desc.replace("\r\n", "\n")
    purpose = _field(t, r"買回股份目的") or ""
    pr = _field(t, r"買回區間價格\(元\)") or ""
    m = re.search(r"([\d,.]+)\s*[~～至\-]\s*([\d,.]+)", pr)
    lo = float(m.group(1).replace(",", "")) if m else None
    hi = float(m.group(2).replace(",", "")) if m else None
    rt = _field(t, r"已發行股份總數之比率\(%\)") or ""
    m2 = re.search(r"[\d.]+", rt)
    ratio = float(m2.group(0)) if m2 else None
    period = _field(t, r"預定買回之期間") or ""
    pm = re.findall(r"(\d{2,3}/\d{1,2}/\d{1,2})", period)
    p_from = any_to_date(pm[0]).isoformat() if pm else None
    p_to = any_to_date(pm[1]).isoformat() if len(pm) > 1 else None
    tags = []
    if "註銷" in purpose:
        tags.append("註銷")
    if "員工" in purpose:
        tags.append("轉讓員工")
    if "維護" in purpose or "股東權益" in purpose:
        tags.append("維護股東權益")
    if "轉換" in purpose or "認股權" in purpose:
        tags.append("轉換／認股")
    return {"purpose": purpose, "tags": tags, "lo": lo, "hi": hi, "ratio": ratio, "from": p_from, "to": p_to}


def is_new_buyback(clause: str, subject: str, desc: str) -> bool:
    if "第35款" not in clause.replace(" ", "") or "買回" not in subject:
        return False
    if any(w in subject for w in FOLLOWUPS):
        return False
    return "買回股份目的" in desc


def parse_rows(js: list, market: str) -> list[dict[str, Any]]:
    out = []
    for r in js:
        code = str(r.get("公司代號") or r.get("SecuritiesCompanyCode") or "").strip()
        subject = str(r.get("主旨 ") or r.get("主旨") or "").replace("\r\n", "").strip()
        clause = str(r.get("符合條款", ""))
        desc = str(r.get("說明", ""))
        if not STOCK_CODE.match(code) or not is_new_buyback(clause, subject, desc):
            continue
        d = any_to_date(str(r.get("發言日期"))).isoformat()
        key = hashlib.sha1(f"{code}|{d}|{subject}".encode()).hexdigest()[:12]
        out.append({"key": key, "date": d, "code": code, "name": str(r.get("公司名稱") or r.get("CompanyName") or "").strip(),
                    "market": market, "subject": subject, **parse_desc(desc)})
    return out


def update_buyback(root: Path) -> int:
    p = records_path(root)
    data = read_json(p) if p.is_file() else {"started": today_tw().isoformat(), "records": [], "fetch_log": []}
    have = {r["key"] for r in data["records"]}
    sess = session()
    added = 0
    for url, mkt in ((OPEN_L, "上市"), (OPEN_O, "上櫃")):
        try:
            for rec in parse_rows(http_json(sess, url), mkt):
                if rec["key"] not in have:
                    data["records"].append(rec)
                    have.add(rec["key"])
                    added += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("buyback %s failed: %s", mkt, exc)
    data["records"].sort(key=lambda r: (r["date"], r["code"]), reverse=True)
    data["updated_at"] = now_taipei_iso()
    write_json(p, data)
    return added


def classify(rec: dict[str, Any], pos: float | None) -> str:
    good = "註銷" in rec["tags"] or "維護股東權益" in rec["tags"]
    if good and rec.get("ratio") is not None and rec["ratio"] >= MIN_RATIO and pos is not None and pos < 0.5:
        return "bull"
    return "neutral"


def build_buyback_view(root: Path) -> dict[str, Any] | None:
    p = records_path(root)
    if not p.is_file():
        return None
    data = read_json(p)
    series = load_series(root, "prices")
    latest = series[-1]["rows"] if series else {}
    items = []
    for r in data["records"]:
        x = dict(r)
        c = latest.get(r["code"], [None, None, None])[2]
        x["close"] = c
        x["pos"] = ((c - r["lo"]) / (r["hi"] - r["lo"])) if c and r["lo"] is not None and r["hi"] and r["hi"] > r["lo"] else None
        x["kind"] = classify(r, x["pos"])
        x["label"] = "偏多" if x["kind"] == "bull" else "中性"
        items.append(x)
    today = today_tw()
    started = data.get("started", today.isoformat())
    ym = today.strftime("%Y-%m")
    by_month: dict[str, int] = {}
    for r in data["records"]:
        by_month[r["date"][:7]] = by_month.get(r["date"][:7], 0) + 1
    this_month = by_month.get(ym, 0)
    full_months = sorted(m for m in by_month if m > started[:7] and m < ym)
    if len(full_months) < MIN_MONTHS:
        verdict, lab = "na", {"text": "資料累積中", "cls": "na"}
        reason = f"本站從 {started} 開始累積（官方歷史查詢無法自動下載），本月至今 {this_month} 件董事會決議買回；滿 {MIN_MONTHS} 個月後才判讀。"
        thr = None
    else:
        vals = [by_month[m] for m in full_months]
        mean = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) if len(vals) > 1 else 0
        thr = mean + SIGMA * sd
        if this_month > thr:
            verdict, lab = "bull", {"text": "偏多（抄底區）", "cls": "bull"}
        else:
            verdict, lab = "neutral", {"text": "中性", "cls": "neutral"}
        reason = f"本月至今 {this_month} 件，歷史月平均 {mean:.1f} 件、門檻（平均＋{SIGMA}σ）{thr:.1f} 件。"
    return {"items": items, "this_month": this_month, "ym": ym, "by_month": sorted(by_month.items(), reverse=True),
            "verdict": verdict, "label": lab, "reason": reason, "started": started, "threshold": thr,
            "n_bull": sum(1 for x in items if x["kind"] == "bull"),
            "date": data["records"][0]["date"] if data["records"] else None,
            "price_date": series[-1]["date"] if series else None, "updated_at": data.get("updated_at"), "src": SRC}
