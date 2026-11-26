"""Daily archives shared by strategy 2 (收盤/成交值) and strategy 4 (借券賣出/融券餘額).

Per trading day:
  data/strategy/prices/YYYY-MM-DD.json  {"date", "rows": {code: [name, market, close, turnover_yuan]}}
      上市 TWSE rwd MI_INDEX (ALLBUT0999) / 上櫃 TPEx afterTrading/otc
  data/strategy/sbl/YYYY-MM-DD.json     {"date", "rows": {code: [name, market, sbl_balance_shares, short_balance_shares]}}
      上市 TWSE rwd TWT93U / 上櫃 TPEx www margin/sbl（同版面：index 6 融券今日餘額、index 12 借券賣出當日餘額）
Only 4-digit common-stock codes (+ 0050 as benchmark) are kept. Backfill walks newest → oldest,
remembers holidays in index.json, and never raises into the pipeline.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from .strategy_common import STOCK_CODE, NoData, http_json, num, session, strategy_dir, today_tw, weekdays_back
from .utils import now_taipei_iso, read_json

logger = logging.getLogger(__name__)

MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_CLOSE_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
TWT93U_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U"
TPEX_SBL_URL = "https://www.tpex.org.tw/www/zh-tw/margin/sbl"

PRICE_DAYS = 262
SBL_DAYS = 30
BENCH = "0050"


def _keep(code: str) -> bool:
    return bool(STOCK_CODE.match(code)) or code == BENCH


def write_compact(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def parse_mi_index(js: dict, want: str) -> dict[str, list]:
    if str(js.get("stat", "")).upper() != "OK" or str(js.get("date")) != want:
        raise NoData(f"MI_INDEX {js.get('stat')} {js.get('date')}")
    for t in js.get("tables") or []:
        f = t.get("fields") or []
        if f and f[0] == "證券代號" and "收盤價" in f:
            ic, it = f.index("收盤價"), f.index("成交金額")
            out = {}
            for r in t["data"]:
                code = str(r[0]).strip()
                c = num(r[ic])
                if _keep(code) and c:
                    out[code] = [str(r[1]).strip(), "上市", c, num(r[it]) or 0.0]
            if out:
                return out
    raise NoData("MI_INDEX 無每日收盤行情")


def parse_tpex_otc(js: dict, want: str) -> dict[str, list]:
    if str(js.get("date")) != want or not js.get("tables") or not js["tables"][0].get("data"):
        raise NoData(f"TPEx otc no data {js.get('date')}")
    t = js["tables"][0]
    f = [x.strip() for x in t["fields"]]
    ic, it = f.index("收盤"), f.index("成交金額(元)")
    out = {}
    for r in t["data"]:
        code = str(r[0]).strip()
        c = num(r[ic])
        if _keep(code) and c:
            out[code] = [str(r[1]).strip(), "上櫃", c, num(r[it]) or 0.0]
    return out


def _sbl_rows(fields: list, data: list, market: str) -> dict[str, list]:
    # Two columns are both named 前日餘額/當日餘額 — use positions (verified 2026-11-25):
    # [0]代號 [1]名稱 [2..7]融券(前日,賣出,買進,現券,今日餘額,限額) [8..13]借券賣出(前日,賣出,還券,調整,當日餘額,次日限額)
    if len(fields) < 14 or "餘額" not in fields[6] or "餘額" not in fields[12]:
        raise RuntimeError(f"{market} 借券欄位格式變動: {fields}")
    out = {}
    for r in data:
        code = str(r[0]).strip()
        if not STOCK_CODE.match(code):
            continue
        out[code] = [str(r[1]).strip(), market, int(num(r[12]) or 0), int(num(r[6]) or 0)]
    return out


def parse_twt93u(js: dict, want: str) -> dict[str, list]:
    if str(js.get("stat", "")).upper() != "OK" or str(js.get("date")) != want or not js.get("data"):
        raise NoData(f"TWT93U {js.get('stat')} {js.get('date')}")
    return _sbl_rows(js["fields"], js["data"], "上市")


def parse_tpex_sbl(js: dict, want: str) -> dict[str, list]:
    if str(js.get("date")) != want or not js.get("tables") or not js["tables"][0].get("data"):
        raise NoData(f"TPEx sbl no data {js.get('date')}")
    t = js["tables"][0]
    return _sbl_rows(t["fields"], t["data"], "上櫃")


def fetch_prices(sess, d: date) -> dict[str, Any]:
    ds, sl = d.strftime("%Y%m%d"), d.strftime("%Y/%m/%d")
    tw = parse_mi_index(http_json(sess, MI_INDEX_URL, params={"date": ds, "type": "ALLBUT0999", "response": "json"}), ds)
    ot = parse_tpex_otc(http_json(sess, TPEX_CLOSE_URL, params={"date": sl, "type": "EW", "response": "json"}), ds)
    return {"date": d.isoformat(), "fetched_at": now_taipei_iso(), "rows": {**ot, **tw}}


def fetch_sbl(sess, d: date) -> dict[str, Any]:
    ds, sl = d.strftime("%Y%m%d"), d.strftime("%Y/%m/%d")
    tw = parse_twt93u(http_json(sess, TWT93U_URL, params={"date": ds, "response": "json"}), ds)
    ot = parse_tpex_sbl(http_json(sess, TPEX_SBL_URL, params={"date": sl, "response": "json"}), ds)
    return {"date": d.isoformat(), "fetched_at": now_taipei_iso(), "rows": {**ot, **tw}}


def _update_series(root: Path, kind: str, fetch, target: int, today: date, max_new: int | None) -> int:
    base = strategy_dir(root) / kind
    base.mkdir(parents=True, exist_ok=True)
    idx_path = strategy_dir(root) / "closed_days.json"
    closed = set(read_json(idx_path).get("closed", [])) if idx_path.is_file() else set()
    have = {p.stem for p in base.glob("*.json")}
    sess = session()
    count = added = 0
    for d in weekdays_back(today, int(target * 1.6) + 30):
        if count >= target or (max_new is not None and added >= max_new):
            break
        iso = d.isoformat()
        if iso in have:
            count += 1
            continue
        if iso in closed:
            continue
        try:
            day = fetch(sess, d)
        except NoData as exc:
            if d < today and (today - d).days > 1:
                closed.add(iso)
                logger.info("strategy %s %s: 休市/無資料 (%s)", kind, iso, exc)
            else:
                logger.info("strategy %s %s: 尚未公布 (%s)", kind, iso, exc)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("strategy %s %s failed: %s", kind, iso, exc)
            continue
        write_compact(base / f"{iso}.json", day)
        have.add(iso)
        count += 1
        added += 1
        logger.info("strategy %s %s: %d rows", kind, iso, len(day["rows"]))
        from .utils import write_json
        write_json(idx_path, {"closed": sorted(closed), "updated_at": now_taipei_iso()})
    from .utils import write_json
    write_json(idx_path, {"closed": sorted(closed), "updated_at": now_taipei_iso()})
    for old in sorted(have)[:-target]:
        try:
            (base / f"{old}.json").unlink()
        except OSError:
            pass
    return added


def update_daily(root: Path, today: date | None = None, max_new_prices: int | None = 15) -> None:
    """Daily path: fetch any missing recent days. max_new caps backfill per run (keeps CI short)."""
    today = today or today_tw()
    _update_series(root, "sbl", fetch_sbl, SBL_DAYS, today, None)
    _update_series(root, "prices", fetch_prices, PRICE_DAYS, today, max_new_prices)


def load_series(root: Path, kind: str) -> list[dict[str, Any]]:
    base = strategy_dir(root) / kind
    return [read_json(p) for p in sorted(base.glob("*.json"))]
