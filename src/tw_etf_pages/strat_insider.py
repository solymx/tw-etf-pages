"""策略 7：內部人持股轉讓事前申報。

Sources: TWSE openapi opendata/t187ap12_L、TPEx openapi mopsfin_t187ap12_O（只給最新一天）
→ 每次執行存檔到 data/strategy/insider/records.json（以 代號＋姓名＋申報日＋股數 去重）。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import Any

from .strategy_common import STOCK_CODE, any_to_date, http_json, num, session, strategy_dir, today_tw
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

OPEN_L = "https://openapi.twse.com.tw/v1/opendata/t187ap12_L"
OPEN_O = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap12_O"
SRC = "https://mops.twse.com.tw/mops/#/web/t56sb12_q1"
HIGH, LOW = 10.0, 3.0   # 經驗值
MKT_DAYS = 20


def records_path(root: Path) -> Path:
    return strategy_dir(root) / "insider" / "records.json"


def parse_rows(js: list, market: str) -> list[dict[str, Any]]:
    out = []
    for r in js:
        code = str(r.get("公司代號") or r.get("SecuritiesCompanyCode") or "").strip()
        if not STOCK_CODE.match(code):
            continue
        d = any_to_date(str(r.get("出表日期") or r.get("Date"))).isoformat()
        ident = str(r.get("申報人身分") or r.get("申請人身分") or "").strip()
        method = str(r.get("預定轉讓方式及股數-轉讓方式") or "").strip()
        own = (num(r.get("目前持有股數-自有持股")) or 0) + (num(r.get("目前持有股數-保留運用決定權信託股數")) or 0)
        sh = (num(r.get("預定轉讓總股數-自有持股")) or 0) + (num(r.get("預定轉讓總股數-保留運用決定權信託股數")) or 0)
        name = str(r.get("姓名", "")).strip()
        key = hashlib.sha1(f"{code}|{name}|{d}|{sh}|{method}".encode()).hexdigest()[:12]
        out.append({"key": key, "date": d, "code": code, "company": str(r.get("公司名稱") or r.get("CompanyName") or "").strip(),
                    "market": market, "identity": ident, "person": name, "method": method, "shares": int(sh),
                    "holding": int(own), "ratio": round(sh / own * 100, 2) if own else None,
                    "receiver": str(r.get("受讓人", "")).strip(), "period": str(r.get("有效轉讓期間", "")).strip()})
    return out


def update_insider(root: Path) -> int:
    p = records_path(root)
    data = read_json(p) if p.is_file() else {"started": today_tw().isoformat(), "records": [], "days": []}
    have = {r["key"] for r in data["records"]}
    sess = session()
    added = 0
    dates = set(data.get("days", []))
    for url, mkt in ((OPEN_L, "上市"), (OPEN_O, "上櫃")):
        try:
            js = http_json(sess, url)
            for rec in parse_rows(js, mkt):
                dates.add(rec["date"])
                if rec["key"] not in have:
                    data["records"].append(rec)
                    have.add(rec["key"])
                    added += 1
            for r in js[:1]:
                dates.add(any_to_date(str(r.get("出表日期") or r.get("Date"))).isoformat())
        except Exception as exc:  # noqa: BLE001
            logger.warning("insider %s failed: %s", mkt, exc)
    data["records"].sort(key=lambda r: (r["date"], r["code"]), reverse=True)
    data["days"] = sorted(dates)
    data["updated_at"] = now_taipei_iso()
    write_json(p, data)
    return added


def classify(rec: dict[str, Any]) -> str:
    gift = "贈與" in rec["method"]
    ratio = rec.get("ratio")
    if gift or ratio is None or ratio < LOW:
        return "neutral"
    insider = "董事" in rec["identity"] or "大股東" in rec["identity"] or "10%" in rec["identity"]
    if insider and ratio >= HIGH:
        return "bear"
    return "watch"


LABEL = {"bear": "偏空", "watch": "留意", "neutral": "中性"}


def build_insider_view(root: Path) -> dict[str, Any] | None:
    p = records_path(root)
    if not p.is_file():
        return None
    data = read_json(p)
    items = []
    for r in data["records"]:
        x = dict(r)
        x["kind"] = classify(r)
        x["label"] = LABEL[x["kind"]]
        items.append(x)
    days = data.get("days", [])
    last = days[-1] if days else None
    bear_by_day = {d: 0 for d in days}
    for x in items:
        if x["kind"] == "bear" and x["date"] in bear_by_day:
            bear_by_day[x["date"]] += 1
    today_n = bear_by_day.get(last, 0) if last else 0
    prior = [bear_by_day[d] for d in days[:-1]][-MKT_DAYS:]
    if len(prior) < MKT_DAYS:
        verdict, lab = "na", {"text": "資料累積中", "cls": "na"}
        reason = (f"{last or '—'} 申報 {sum(1 for x in items if x['date'] == last)} 筆，其中偏空 {today_n} 筆；"
                  f"本站從 {data.get('started')} 起累積，滿 {MKT_DAYS} 個申報日後才和平均比較。")
    else:
        avg = sum(prior) / len(prior)
        bear = today_n >= 3 and today_n > 2 * avg
        verdict = "bear" if bear else "neutral"
        lab = {"text": "偏空" if bear else "中性", "cls": verdict}
        reason = f"{last} 偏空申報 {today_n} 筆，近 {MKT_DAYS} 日平均 {avg:.1f} 筆" + (
            "，超過 2 倍且 ≥ 3 筆（經驗值）。" if bear else "，未明顯增加。")
    return {"items": items, "date": last, "verdict": verdict, "label": lab, "reason": reason,
            "n_today": sum(1 for x in items if x["date"] == last), "n_bear_today": today_n,
            "started": data.get("started"), "n_days": len(days), "src": SRC}
