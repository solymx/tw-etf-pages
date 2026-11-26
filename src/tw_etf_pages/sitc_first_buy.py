"""投信「第一次買超」追蹤：今天投信買超、且前 10 個交易日都沒有買超的個股。

Sources (official, public):
  - TWSE 上市：fund/T86（三大法人買賣超日報，selectType=ALLBUT0999）＋ afterTrading/MI_INDEX（收盤價）
  - TPEx 上櫃：insti/dailyTrade（三大法人買賣明細）＋ afterTrading/otc（收盤價）
Per-day files data/sitc/daily/YYYY-MM-DD.json store only stocks with non-zero 投信 net
(4-digit stock codes; ETFs / warrants / preferred shares excluded).
Output data/sitc/first_buy.json holds the last ~20 daily lists. Never raises into the pipeline.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from datetime import datetime

from .utils import TZ_TAIPEI, now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_INSTI_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
TPEX_CLOSE_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
SOURCE_TWSE = "https://www.twse.com.tw/zh/trading/foreign/t86.html"
SOURCE_TPEX = "https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html"
UA = "Mozilla/5.0 (compatible; tw-etf-pages/1.0; +https://solymx.github.io/tw-etf-pages/)"

LOOKBACK = 10          # 前 N 個交易日都沒有買超
HISTORY_DAYS = 20      # 保留最近 N 天的每日名單
KEEP_DAYS = HISTORY_DAYS + LOOKBACK + 2
SPACING = 2.5          # seconds between requests
BIG_LOTS = 100          # 「較有意義的買超」門檻（僅用於統計顯示，名單不過濾）
STOCK_CODE = re.compile(r"^[1-9]\d{3}$")


class NoData(Exception):
    """Official source answered but has no data (holiday / not yet published)."""


def sitc_dir(root: Path) -> Path:
    return root / "data" / "sitc"


def _num(s: Any) -> float | None:
    t = str(s).replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _int(s: Any) -> int:
    v = _num(s)
    return int(v) if v is not None else 0


def _get(session: requests.Session, url: str, params: dict, want_date: str) -> dict:
    last: Exception | None = None
    for attempt in range(4):
        try:
            time.sleep(SPACING)
            r = session.get(url, params=params, timeout=90)
            r.raise_for_status()
            js = r.json()
            stat = str(js.get("stat", ""))
            if stat.lower() != "ok":
                raise NoData(stat)
            if str(js.get("date", "")) != want_date:
                raise NoData(f"date mismatch: {js.get('date')}")
            return js
        except NoData:
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep((10, 30, 60, 60)[attempt])  # WAF throttle (307 HTML) clears after a pause
    raise RuntimeError(f"{url} {want_date}: {last}")


def parse_t86(js: dict) -> dict[str, dict[str, Any]]:
    fields = js["fields"]
    i_net = fields.index("投信買賣超股數")
    out: dict[str, dict[str, Any]] = {}
    for r in js["data"]:
        code = str(r[0]).strip()
        if not STOCK_CODE.match(code):
            continue
        net = _int(r[i_net])
        if net:
            out[code] = {"n": str(r[1]).strip(), "m": "上市", "net": net}
    return out


def parse_twse_closes(js: dict) -> dict[str, tuple[float, float]]:
    for t in js.get("tables") or []:
        if (t.get("fields") or [""])[0] == "證券代號":
            out: dict[str, tuple[float, float]] = {}
            for r in t["data"]:
                c = _num(r[8])
                if not c:
                    continue
                sign = str(r[9])
                diff = _num(r[10]) or 0.0
                chg = diff if "+" in sign else -diff if "-" in sign else 0.0
                out[str(r[0]).strip()] = (c, chg)
            return out
    raise NoData("MI_INDEX 無每日收盤行情")


def parse_tpex_insti(js: dict) -> dict[str, dict[str, Any]]:
    t = js["tables"][0]
    # groups of (買進, 賣出, 買賣超): 外資(不含自營) 外資自營 外資合計 投信 自營(自行) 自營(避險) 自營合計 → 投信 = cols 11..13
    if len(t["fields"]) < 14 or t["fields"][13] != "買賣超股數":
        raise RuntimeError("TPEx 三大法人欄位格式變動")
    out: dict[str, dict[str, Any]] = {}
    for r in t["data"]:
        code = str(r[0]).strip()
        if not STOCK_CODE.match(code):
            continue
        net = _int(r[13])
        if net:
            out[code] = {"n": str(r[1]).strip(), "m": "上櫃", "net": net}
    if not t["data"]:
        raise NoData("TPEx 無資料")
    return out


def parse_tpex_closes(js: dict) -> dict[str, tuple[float, float]]:
    t = js["tables"][0]
    out: dict[str, tuple[float, float]] = {}
    for r in t["data"]:
        c = _num(r[2])
        if not c:
            continue
        out[str(r[0]).strip()] = (c, _num(r[3]) or 0.0)
    return out


def fetch_day(session: requests.Session, d: date) -> dict[str, Any]:
    """One trading day. Raises NoData if TWSE has no report (holiday / not yet out)."""
    ds = d.strftime("%Y%m%d")
    t86 = _get(session, T86_URL, {"date": ds, "selectType": "ALLBUT0999", "response": "json"}, ds)
    listed = parse_t86(t86)
    mi = _get(session, MI_INDEX_URL, {"date": ds, "type": "ALLBUT0999", "response": "json"}, ds)
    listed_close = parse_twse_closes(mi)
    sl = d.strftime("%Y/%m/%d")
    ti = _get(session, TPEX_INSTI_URL, {"type": "Daily", "sect": "EW", "date": sl, "id": "", "response": "json"}, ds)
    otc = parse_tpex_insti(ti)
    tc = _get(session, TPEX_CLOSE_URL, {"date": sl, "type": "EW", "response": "json"}, ds)
    otc_close = parse_tpex_closes(tc)
    rows: dict[str, dict[str, Any]] = {}
    for code, row in {**listed, **otc}.items():
        px = (listed_close if row["m"] == "上市" else otc_close).get(code)
        row = dict(row)
        if px:
            row["c"], row["chg"] = px[0], round(px[1], 4)
        rows[code] = row
    return {
        "date": d.isoformat(),
        "fetched_at": now_taipei_iso(),
        "rows": rows,
    }


def _weekdays_back(today: date, limit_days: int = 80):
    d = today
    for _ in range(limit_days):
        if d.weekday() < 5:
            yield d
        d -= timedelta(days=1)


def load_days(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in sorted((sitc_dir(root) / "daily").glob("*.json")):
        out[p.stem] = read_json(p)
    return out


def update_sitc(root: Path, today: date | None = None, target_days: int = KEEP_DAYS) -> int:
    """Fetch missing trading days (newest first, until target_days stored). Returns days added."""
    today = today or datetime.now(TZ_TAIPEI).date()
    base = sitc_dir(root)
    (base / "daily").mkdir(parents=True, exist_ok=True)
    idx_path = base / "index.json"
    idx = read_json(idx_path) if idx_path.is_file() else {}
    closed = set(idx.get("closed", []))
    have = {p.stem for p in (base / "daily").glob("*.json")}
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})
    count = 0
    added = 0
    for d in _weekdays_back(today):
        if count >= target_days:
            break
        iso = d.isoformat()
        if iso in have:
            count += 1
            continue
        if iso in closed:
            continue
        try:
            day = fetch_day(session, d)
        except NoData as exc:
            if d < today:
                closed.add(iso)  # past weekday with no report = market holiday
                logger.info("SITC %s: 休市/無資料 (%s)", iso, exc)
            else:
                logger.info("SITC %s: 尚未公布 (%s)", iso, exc)
            continue
        except Exception as exc:  # noqa: BLE001 — retry on next run
            logger.warning("SITC %s failed: %s", iso, exc)
            continue
        write_json(base / "daily" / f"{iso}.json", day)
        have.add(iso)
        count += 1
        added += 1
        logger.info("SITC %s: %d stocks with 投信 net", iso, len(day["rows"]))
    write_json(idx_path, {"closed": sorted(closed), "updated_at": now_taipei_iso()})
    # prune old daily files
    stored = sorted(have)
    for old in stored[:-KEEP_DAYS]:
        try:
            (base / "daily" / f"{old}.json").unlink()
        except OSError:
            pass
    compute_lists(root)
    return added


def first_buy_for(days: list[dict[str, Any]], i: int, lookback: int = LOOKBACK) -> list[dict[str, Any]]:
    """Stocks with 投信 買超 on days[i] and no 買超 on each of the previous `lookback` days."""
    prior = days[i - lookback : i]
    items: list[dict[str, Any]] = []
    for code, r in days[i]["rows"].items():
        if r["net"] <= 0:
            continue
        if any(p["rows"].get(code, {}).get("net", 0) > 0 for p in prior):
            continue
        c = r.get("c")
        chg = r.get("chg")
        pct = None
        if c is not None and chg is not None and (c - chg) > 0:
            pct = round(chg / (c - chg) * 100, 2)
        items.append(
            {
                "code": code,
                "name": r["n"],
                "market": r["m"],
                "net_shares": r["net"],
                "net_lots": round(r["net"] / 1000, 3),
                "close": c,
                "chg_pct": pct,
                "amount": round(r["net"] * c) if c else None,
            }
        )
    items.sort(key=lambda x: (x["amount"] is not None, x["amount"] or 0, x["net_shares"]), reverse=True)
    return items


def window_is_contiguous(dates: list[str], i: int, closed: set[str], lookback: int = LOOKBACK) -> bool:
    """True if the `lookback` trading days before dates[i] are exactly dates[i-lookback:i] (no missing day)."""
    if i < lookback:
        return False
    expected: list[str] = []
    d = date.fromisoformat(dates[i]) - timedelta(days=1)
    while len(expected) < lookback and (date.fromisoformat(dates[i]) - d).days < 40:
        if d.weekday() < 5 and d.isoformat() not in closed:
            expected.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(expected)) == dates[i - lookback : i]


def compute_lists(root: Path) -> dict[str, Any] | None:
    days_by = load_days(root)
    idx_path = sitc_dir(root) / "index.json"
    closed = set(read_json(idx_path).get("closed", [])) if idx_path.is_file() else set()
    dates = sorted(days_by)
    days = [days_by[k] for k in dates]
    out_days: list[dict[str, Any]] = []
    for i in range(len(days) - 1, LOOKBACK - 1, -1):
        if len(out_days) >= HISTORY_DAYS:
            break
        if not window_is_contiguous(dates, i, closed):
            logger.warning("SITC %s: 前 %d 個交易日資料有缺口，略過該日名單", dates[i], LOOKBACK)
            continue
        out_days.append(
            {
                "date": dates[i],
                "prev_from": dates[i - LOOKBACK],
                "prev_to": dates[i - 1],
                "items": first_buy_for(days, i),
            }
        )
    if not out_days:
        return None
    payload = {
        "generated_at": now_taipei_iso(),
        "lookback": LOOKBACK,
        "latest_stored_date": dates[-1],
        "days": out_days,
    }
    write_json(sitc_dir(root) / "first_buy.json", payload)
    return payload


def _etf_holders(cfg: Any) -> dict[str, list[str]]:
    from .compare import list_snapshot_dates, load_snapshot

    m: dict[str, list[str]] = {}
    for e in cfg.etfs:
        try:
            ds = list_snapshot_dates(cfg.snapshots_dir, e.ticker)
            if not ds:
                continue
            snap = load_snapshot(cfg.snapshots_dir, e.ticker, ds[-1])
            for h in snap.get("holdings", []):
                if h.get("is_placeholder"):
                    continue
                m.setdefault(str(h.get("stock_code")), []).append(e.ticker)
        except Exception:  # noqa: BLE001
            logger.exception("sitc: holders for %s failed", e.ticker)
    return m


def build_sitc_view(cfg: Any) -> dict[str, Any] | None:
    p = sitc_dir(cfg.root) / "first_buy.json"
    if not p.is_file():
        return None
    data = read_json(p)
    days = data.get("days") or []
    if not days:
        return None
    holders = _etf_holders(cfg)
    for day in days:
        for it in day["items"]:
            it["etfs"] = holders.get(it["code"], [])
        day["listed"] = sum(1 for x in day["items"] if x["market"] == "上市")
        day["otc"] = sum(1 for x in day["items"] if x["market"] == "上櫃")
        day["total"] = len(day["items"])
        day["big"] = sum(1 for x in day["items"] if x["net_lots"] >= BIG_LOTS)
        day["in_etf"] = sum(1 for x in day["items"] if x["etfs"])
        day["total_amount"] = sum(x["amount"] or 0 for x in day["items"])
    return {
        "latest": days[0],
        "history": days,
        "lookback": data.get("lookback", LOOKBACK),
        "generated_at": data.get("generated_at"),
        "source_twse": SOURCE_TWSE,
        "source_tpex": SOURCE_TPEX,
    }
