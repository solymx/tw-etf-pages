"""策略 8：注意股（公布注意交易資訊）。

Sources: TWSE rwd announcement/notice（querytype=1，日期區間）、TPEx www bulletin/attention（日期區間）。
每次執行抓近 14 天並合併存檔到 data/strategy/attention/notices.json（首次回補約 1 個月）。只留 4 碼普通股。
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .strategy_common import STOCK_CODE, any_to_date, http_json, num, session, strategy_dir, today_tw
from .strategy_daily import load_series
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

TWSE_URL = "https://www.twse.com.tw/rwd/zh/announcement/notice"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/attention"
SRC_L = "https://www.twse.com.tw/zh/announcement/notice.html"
SRC_O = "https://www.tpex.org.tw/zh-tw/announce/market/attention.html"
BACKFILL_DAYS = 35
DAILY_DAYS = 14
CHASE_DAYS = 5          # 漲幅型：公告後 1–5 天避免追高（經驗值）
NEAR_DISPOSAL = 3       # 近 10 個交易日被注意 ≥ 3 次（經驗值）
HOT_SHARE = 50.0        # 當日注意股中漲幅型占比 ≥ 50% → 偏空（過熱）（經驗值）
CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def notices_path(root: Path) -> Path:
    return strategy_dir(root) / "attention" / "notices.json"


def cn_num(s: str) -> int | None:
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + CN.get(s[1:], 0)
    if "十" in s:
        a, _, b = s.partition("十")
        return CN.get(a, 0) * 10 + (CN.get(b, 0) if b else 0)
    return CN.get(s)


def parse_info(text: str) -> tuple[str, str]:
    t = re.sub(r"<[^>]+>", "", text)
    m = re.findall(r"第([一二三四五六七八九十\d]+)款", t)
    clause = "、".join(f"第{cn_num(x) or x}款" for x in dict.fromkeys(m)) if m else "—"
    if "漲幅" in t:
        direction = "漲幅"
    elif "跌幅" in t:
        direction = "跌幅"
    else:
        direction = "其他"
    return clause, direction


def _rec(code, name, market, d, info, close) -> dict[str, Any]:
    clause, direction = parse_info(info)
    key = hashlib.sha1(f"{code}|{d}|{clause}|{direction}".encode()).hexdigest()[:12]
    return {"key": key, "date": d, "code": code, "name": name.strip(), "market": market, "clause": clause,
            "direction": direction, "close_at": close, "info": re.sub(r"<[^>]+>", "", info).strip()[:200]}


def parse_twse(js: dict) -> list[dict[str, Any]]:
    if str(js.get("stat", "")).upper() != "OK":
        return []
    f = js["fields"]
    ic, iname, iinfo, idt, iclose = (f.index("證券代號"), f.index("證券名稱"), f.index("注意交易資訊"),
                                      f.index("日期"), f.index("收盤價"))
    out = []
    for r in js.get("data", []):
        code = str(r[ic]).strip()
        if STOCK_CODE.match(code):
            out.append(_rec(code, str(r[iname]), "上市", any_to_date(str(r[idt]).replace(".", "/")).isoformat(),
                            str(r[iinfo]), num(r[iclose])))
    return out


def parse_tpex(js: dict) -> list[dict[str, Any]]:
    t = (js.get("tables") or [{}])[0]
    f = t.get("fields") or []
    if not f:
        return []
    ic, iname, iinfo, idt, iclose = (f.index("證券代號"), f.index("證券名稱"), f.index("注意交易資訊"),
                                      f.index("公告日期"), f.index("收盤價"))
    out = []
    for r in t.get("data", []):
        code = str(r[ic]).strip()
        if STOCK_CODE.match(code):
            out.append(_rec(code, str(r[iname]), "上櫃", any_to_date(str(r[idt])).isoformat(), str(r[iinfo]), num(r[iclose])))
    return out


def update_attention(root: Path, today: date | None = None) -> int:
    today = today or today_tw()
    p = notices_path(root)
    data = read_json(p) if p.is_file() else {"records": []}
    start = today - timedelta(days=DAILY_DAYS if data["records"] else BACKFILL_DAYS)
    have = {r["key"] for r in data["records"]}
    sess = session()
    added = 0
    errors = []
    try:
        recs = parse_twse(http_json(sess, TWSE_URL, params={"startDate": start.strftime("%Y%m%d"), "endDate": today.strftime("%Y%m%d"),
                                                             "stockNo": "", "querytype": "1", "selectType": "", "response": "json"}))
        recs += parse_tpex(http_json(sess, TPEX_URL, params={"startDate": start.strftime("%Y/%m/%d"), "endDate": today.strftime("%Y/%m/%d"),
                                                              "response": "json"}))
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        recs = []
    for r in recs:
        if r["key"] not in have:
            data["records"].append(r)
            have.add(r["key"])
            added += 1
    cutoff = (today - timedelta(days=120)).isoformat()
    data["records"] = sorted([r for r in data["records"] if r["date"] >= cutoff], key=lambda r: (r["date"], r["code"]), reverse=True)
    data["updated_at"] = now_taipei_iso()
    data["fetch_errors"] = errors
    if errors:
        logger.warning("attention fetch errors: %s", errors)
    write_json(p, data)
    return added


def classify(direction: str, day_after: int | None) -> tuple[str, str]:
    if direction == "漲幅":
        if day_after is None or day_after <= CHASE_DAYS:
            return "bear", "偏空（風險）"
        return "neutral", "中性（已過 5 天）"
    if direction == "跌幅":
        if day_after is None or day_after < CHASE_DAYS + 1:
            return "neutral", "中性觀察（第 6 天後再看）"
        return "neutral", "中性（可重新觀察）"
    return "neutral", "中性"


def build_attention_view(root: Path) -> dict[str, Any] | None:
    p = notices_path(root)
    if not p.is_file():
        return None
    data = read_json(p)
    recs = data["records"]
    if not recs:
        return None
    series = load_series(root, "prices")
    tdays = [s["date"] for s in series]
    latest_px = series[-1]["rows"] if series else {}
    last_notice = max(r["date"] for r in recs)
    ref_days = sorted(set(tdays) | {r["date"] for r in recs})

    def day_after(d: str) -> int | None:
        if d not in ref_days:
            return None
        return len([x for x in ref_days if d < x <= ref_days[-1]])

    window = ref_days[-10:]
    counts: dict[str, int] = {}
    for r in recs:
        if r["date"] in window:
            counts[r["code"]] = counts.get(r["code"], 0) + 1
    latest_by_code: dict[str, dict] = {}
    for r in recs:  # newest first
        if r["date"] in window and r["code"] not in latest_by_code:
            latest_by_code[r["code"]] = r
    items = []
    for code, r in latest_by_code.items():
        x = dict(r)
        x["day_after"] = day_after(r["date"])
        x["count10"] = counts.get(code, 0)
        x["near_disposal"] = x["count10"] >= NEAR_DISPOSAL
        x["close"] = latest_px.get(code, [None, None, None])[2] or r.get("close_at")
        x["kind"], x["label"] = classify(r["direction"], x["day_after"])
        items.append(x)
    items.sort(key=lambda x: (x["date"], x["count10"]), reverse=True)
    today_recs = {r["code"]: r for r in recs if r["date"] == last_notice}
    n_today = len(today_recs)
    n_up = sum(1 for r in today_recs.values() if r["direction"] == "漲幅")
    n_down = sum(1 for r in today_recs.values() if r["direction"] == "跌幅")
    share = round(n_up / n_today * 100, 1) if n_today else None
    verdict = "na" if share is None else "bear" if share >= HOT_SHARE else "neutral"
    lab = {"na": {"text": "資料暫缺", "cls": "na"}, "bear": {"text": "偏空（過熱）", "cls": "bear"},
           "neutral": {"text": "中性", "cls": "neutral"}}[verdict]
    reason = ("資料暫缺。" if share is None else
              f"{last_notice} 共 {n_today} 檔普通股被列注意股，漲幅型 {n_up} 檔（{share:.1f}%）、跌幅型 {n_down} 檔；"
              + (f"漲幅型占比 ≥ {HOT_SHARE:.0f}%（經驗值），短線偏過熱。" if verdict == "bear" else f"漲幅型占比低於 {HOT_SHARE:.0f}%（經驗值）。"))
    dates = sorted({r["date"] for r in recs})
    return {"items": items, "date": last_notice, "n_today": n_today, "n_up": n_up, "n_down": n_down, "share_up": share,
            "verdict": verdict, "label": lab, "reason": reason, "from": dates[0], "n_days": len(dates),
            "n_near": sum(1 for x in items if x["near_disposal"]), "window_from": window[0] if window else None,
            "fetch_errors": data.get("fetch_errors") or [], "src_l": SRC_L, "src_o": SRC_O}
