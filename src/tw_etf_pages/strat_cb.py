"""策略 9：可轉債發行公司警示。

Source: TPEx openapi bond_ISSBD5_data（可轉換公司債發行資料，只有最新一天）→ 每天快照
data/strategy/cb/YYYY-MM-DD.json，用快照差異算近一個月轉換比例。不回補歷史（避免倖存者偏差）。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .strategy_common import any_to_date, http_json, num, session, strategy_dir, today_tw
from .strategy_daily import load_series
from .strat_daily_compact import write_compact
from .utils import read_json

logger = logging.getLogger(__name__)

URL = "https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data"
SRC = "https://www.tpex.org.tw/zh-tw/bond/info/statistics-cb/issued.html"
WINDOW = 250          # 研究窗口（FinLab 1,441 檔：掛牌後 250 日平均落後 7.90%）
HEAVY_CONV = 20.0     # 一個月內轉換 ≥ 發行額 20%（研究窗口）
MKT_MULT = 1.5        # 近 20 個交易日新掛牌檔數 > 過去 12 個月月平均 × 1.5 → 偏空（經驗值）


def cb_dir(root: Path) -> Path:
    return strategy_dir(root) / "cb"


def parse_rows(js: list) -> dict[str, dict[str, Any]]:
    out = {}
    for r in js:
        code = str(r.get("BondCode", "")).strip()
        issuer = str(r.get("IssuerCode", "")).strip()
        if not code or "E" in code.upper() or str(r.get("ListingStatus")) == "5" or not issuer.isdigit() or len(issuer) != 4:
            continue
        ld = str(r.get("ListingDate", "")).strip()
        out[code] = {
            "issuer": issuer, "issuer_name": str(r.get("IssuerName", "")).strip(), "short": str(r.get("ShortName", "")).strip(),
            "issue_date": any_to_date(r["IssueDate"]).isoformat() if r.get("IssueDate") else None,
            "listing_date": any_to_date(ld).isoformat() if ld else None,
            "issue": num(r.get("IssueAmount")) or 0, "outstanding": num(r.get("OutstandingAmount")) or 0,
            "conv_price": num(r.get("Conversion/ExchangePriceAtIssuance")),
            "conv_start": str(r.get("Conversion/ExchangePeriodStartDate", "")).strip(),
            "put_date": str(r.get("PutOptionDate", "")).strip(), "put_price": num(r.get("PutOptionPrice")),
            "chg_date": str(r.get("OutstandingChangeDate", "")).strip(),
            "chg_desc": str(r.get("OutstandingChangeDescription", "")).strip(),
        }
    return out


def update_cb(root: Path, today: date | None = None) -> None:
    today = today or today_tw()
    try:
        js = http_json(session(), URL)
        rows = parse_rows(js)
        d = any_to_date(js[0]["Date"]).isoformat() if js else today.isoformat()
        if len(rows) > 100:
            write_compact(cb_dir(root) / f"{d}.json", {"date": d, "rows": rows})
    except Exception as exc:  # noqa: BLE001
        logger.warning("CB fetch failed: %s", exc)


def change_kind(desc: str) -> str:
    if any(w in desc for w in ("賣回", "買回", "贖回", "償還", "到期")):
        return "redeem"
    if "轉換" in desc:
        return "convert"
    return "unknown"


def trading_days_since(d: str, tdays: list[str]) -> int:
    """Trading days after d up to the latest stored day; before our history, weekdays approximate."""
    n = sum(1 for x in tdays if x > d)
    if tdays and d < tdays[0]:
        x = date.fromisoformat(d) + timedelta(days=1)
        end = date.fromisoformat(tdays[0])
        while x < end:
            n += x.weekday() < 5
            x += timedelta(days=1)
    return n


def build_cb_view(root: Path) -> dict[str, Any] | None:
    snaps = sorted(cb_dir(root).glob("*.json"))
    if not snaps:
        return None
    cur = read_json(snaps[-1])
    asof = cur["date"]
    month_ago = (date.fromisoformat(asof) - timedelta(days=31)).isoformat()
    base = None
    for p in snaps[:-1]:
        if p.stem >= month_ago:
            base = read_json(p)
            break
    series = load_series(root, "prices")
    tdays = [s["date"] for s in series]
    px = series[-1]["rows"] if series else {}
    sp = strategy_dir(root) / "sbl_meta" / "shares.json"
    shares = read_json(sp)["shares"] if sp.is_file() else {}
    items = []
    for code, r in cur["rows"].items():
        x = dict(r, code=code)
        ld = r["listing_date"]
        x["upcoming"] = bool(ld and ld > asof)
        x["days"] = None if (not ld or x["upcoming"]) else trading_days_since(ld, tdays)
        x["out_ratio"] = (r["outstanding"] / r["issue"] * 100) if r["issue"] else None
        close = px.get(r["issuer"], [None, None, None])[2]
        sh = shares.get(r["issuer"])
        x["mcap_pct"] = (r["issue"] / (sh * close) * 100) if sh and close else None
        x["conv_m"] = x["redeem_m"] = None
        if base and code in base["rows"]:
            diff = base["rows"][code]["outstanding"] - r["outstanding"]
            if diff > 0 and r["issue"]:
                kind = change_kind(r["chg_desc"])
                pct = diff / r["issue"] * 100
                if kind == "redeem":
                    x["redeem_m"] = pct
                else:
                    x["conv_m"] = pct
            elif r["issue"]:
                x["conv_m"] = 0.0
        if x["upcoming"]:
            x["kind"], x["label"] = "warn", "即將掛牌"
        elif r["outstanding"] <= 0 or x["days"] is None or x["days"] > WINDOW:
            x["kind"], x["label"] = "neutral", "中性"
        elif x["conv_m"] is not None and x["conv_m"] >= HEAVY_CONV:
            x["kind"], x["label"] = "bear", "偏空（加重）"
        else:
            x["kind"], x["label"] = "bear", "偏空"
        items.append(x)
    items.sort(key=lambda x: (x["upcoming"], -(x["days"] if x["days"] is not None else 99999)), reverse=True)
    # market: new listings in the last 20 trading days vs average monthly listings over the past 12 months
    recent_from = tdays[-20] if len(tdays) >= 20 else asof
    listed = [x for x in items if x["listing_date"] and not x["upcoming"]]
    n_recent = sum(1 for x in listed if x["listing_date"] >= recent_from)
    yr_from = (date.fromisoformat(asof) - timedelta(days=365)).isoformat()
    n_year = sum(1 for x in listed if yr_from <= x["listing_date"] < recent_from)
    avg = n_year / 11 if n_year else 0
    bear = avg > 0 and n_recent > MKT_MULT * avg
    verdict = "bear" if bear else "neutral"
    reason = (f"近 20 個交易日（{recent_from} 起）新掛牌 {n_recent} 檔可轉債，過去一年月平均約 {avg:.1f} 檔；"
              + (f"超過 {MKT_MULT} 倍（經驗值），可轉債供給偏多。" if bear else f"未超過 {MKT_MULT} 倍（經驗值）。")
              + f" 掛牌 250 個交易日內、仍有餘額的可轉債 {sum(1 for x in items if x['kind'] == 'bear')} 檔。")
    return {"items": items, "date": asof, "base_date": base["date"] if base else None, "n_snaps": len(snaps),
            "first_snap": snaps[0].stem, "verdict": verdict, "label": {"text": "偏空" if bear else "中性", "cls": verdict},
            "reason": reason, "n_bear": sum(1 for x in items if x["kind"] == "bear"),
            "n_heavy": sum(1 for x in items if x["label"] == "偏空（加重）"),
            "n_upcoming": sum(1 for x in items if x["upcoming"]), "n_recent": n_recent, "avg_month": avg, "src": SRC}
