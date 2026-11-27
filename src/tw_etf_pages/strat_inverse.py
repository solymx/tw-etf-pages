"""策略 15：00632R 反向 ETF 耗損說明（風險說明，不做自動買賣燈號）。"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from .strategy_common import any_to_date, http, http_json, num, session, strategy_dir, today_tw
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

DAYALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
STOCK_DAY = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
# 公開說明書／產品頁原文（元大投信 00632R 基本資訊頁）
PROSPECTUS = (
    "本基金為策略交易型產品且投資具有反向操作風險，故本基金不適合長期持有，"
    "僅符合臺灣證券交易所訂適格條件之投資人始得交易。"
)
# 七併一，約 2024-12-11 恢復交易（規格）
MERGE_RESUME = "2024-12-11"
MERGE_RATIO = 7


def etf_path(root: Path, code: str) -> Path:
    return strategy_dir(root) / "etf" / f"{code}.json"


def parse_stock_day(js: dict[str, Any], code: str) -> list[dict[str, Any]]:
    if js.get("stat") != "OK":
        return []
    out = []
    for row in js.get("data") or []:
        try:
            d = any_to_date(row[0]).isoformat()
            close, vol = num(row[6]), num(row[1])
            if close is None:
                continue
            out.append({"date": d, "close": close, "volume": vol, "code": code})
        except (ValueError, IndexError):
            continue
    return out


def parse_day_all(rows: list[dict[str, Any]], codes: set[str]) -> list[dict[str, Any]]:
    out = []
    for r in rows or []:
        c = str(r.get("Code") or r.get("證券代號") or "")
        if c not in codes:
            continue
        try:
            d = any_to_date(r["Date"]).isoformat()
        except (KeyError, ValueError):
            continue
        close, vol = num(r.get("ClosingPrice") or r.get("收盤價")), num(r.get("TradeVolume") or r.get("成交股數"))
        if close is None:
            continue
        out.append({"date": d, "close": close, "volume": vol, "code": c})
    return out


def merge_series(path: Path, rows: list[dict[str, Any]], src: str) -> int:
    store = read_json(path) if path.is_file() else {"rows": []}
    by = {r["date"]: r for r in store.get("rows") or []}
    n = 0
    for r in rows:
        new = {"date": r["date"], "close": r["close"], "volume": r.get("volume"), "src": src}
        if by.get(r["date"]) != new:
            by[r["date"]] = new
            n += 1
    if n or not path.is_file():
        write_json(path, {"code": rows[0]["code"] if rows else path.stem,
                          "source": [DAYALL, STOCK_DAY], "updated_at": now_taipei_iso(),
                          "rows": sorted(by.values(), key=lambda r: r["date"])})
    return n


def _from_prices(root: Path, code: str) -> list[dict[str, Any]]:
    pdir = strategy_dir(root) / "prices"
    if not pdir.is_dir():
        return []
    out = []
    for f in sorted(pdir.glob("????-??-??.json")):
        d = read_json(f)
        row = (d.get("rows") or {}).get(code)
        if row:
            out.append({"date": d["date"], "close": row[2], "volume": None, "code": code})
    return out



def _fill_etf_months(root: Path, code: str, limit: int = 12) -> int:
    """Newest-first official STOCK_DAY fill; stop at first 307 so the daily job is not stalled."""
    import time
    import requests
    path = etf_path(root, code)
    have = {r["date"][:7] for r in ((read_json(path).get("rows") or []) if path.is_file() else [])}
    today = today_tw()
    y, m = today.year, today.month
    missing = []
    for _ in range(18):
        key = f"{y:04d}-{m:02d}"
        if key not in have:
            missing.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        if len(missing) >= limit:
            break
    if not missing:
        return 0
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (compatible; tw-etf-pages/1.0)"
    added = 0
    for i, d in enumerate(missing):
        if i:
            time.sleep(15)
        try:
            r = sess.get(STOCK_DAY, params={"response": "json", "date": d.strftime("%Y%m01"), "stockNo": code},
                         timeout=(10, 25), allow_redirects=False)
            if r.status_code != 200 or not r.text.lstrip().startswith("{"):
                logger.warning("inverse: STOCK_DAY %s %s blocked HTTP %s, stop fill", code, d, r.status_code)
                break
            added += merge_series(path, parse_stock_day(r.json(), code), "twse")
        except Exception as exc:  # noqa: BLE001
            logger.warning("inverse: STOCK_DAY %s %s failed: %s", code, d, exc)
            break
    return added


def update_inverse(root: Path) -> None:
    sess = session()
    codes = {"00632R", "0050"}
    got: list[dict[str, Any]] = []
    try:
        got = parse_day_all(http_json(sess, DAYALL, tries=2, timeout=90) or [], codes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("inverse: STOCK_DAY_ALL failed: %s", exc)
    # merge existing 0050 prices first
    merge_series(etf_path(root, "0050"), _from_prices(root, "0050") + [r for r in got if r["code"] == "0050"], "twse")
    merge_series(etf_path(root, "00632R"), [r for r in got if r["code"] == "00632R"], "twse")
    # if 00632R still missing today, try current-month STOCK_DAY (caller should respect TWSE spacing)
    rpath = etf_path(root, "00632R")
    have = {r["date"] for r in (read_json(rpath).get("rows") or [])} if rpath.is_file() else set()
    today = today_tw().isoformat()
    if today not in have:
        try:
            js = http(sess, STOCK_DAY, params={"response": "json", "date": today_tw().strftime("%Y%m01"),
                                               "stockNo": "00632R"}, timeout=30).json()
            merge_series(rpath, parse_stock_day(js, "00632R"), "twse")
        except Exception as exc:  # noqa: BLE001
            logger.warning("inverse: STOCK_DAY 00632R failed: %s", exc)
    if len((read_json(rpath).get("rows") or []) if rpath.is_file() else []) < 80:
        _fill_etf_months(root, "00632R", 14)
    logger.info("inverse: 00632R %s rows, 0050 %s rows",
                len((read_json(rpath).get("rows") or []) if rpath.is_file() else []),
                len((read_json(etf_path(root, "0050")).get("rows") or []) if etf_path(root, "0050").is_file() else []))


def _ret(rows: list[dict], n: int) -> float | None:
    if len(rows) < n + 1:
        return None
    a, b = rows[-(n + 1)]["close"], rows[-1]["close"]
    return b / a - 1 if a else None


def adj_close(r: dict[str, Any]) -> float:
    """Pre-merger closes ×7 so the long-term chart is continuous (七併一)."""
    if r["date"] < MERGE_RESUME:
        return r["close"] * MERGE_RATIO
    return r["close"]


def decay_gap(inv: list[dict], bench: list[dict], n: int) -> float | None:
    """近 N 日 00632R 報酬 −（−1 × 同期台灣 50／0050 報酬）（自算）. Overlapping dates."""
    bi = {r["date"]: r["close"] for r in bench}
    pts = [r for r in inv if r["date"] in bi]
    if len(pts) < n + 1:
        return None
    a, b = pts[-(n + 1)], pts[-1]
    if not a["close"] or not bi[a["date"]]:
        return None
    r_inv = b["close"] / a["close"] - 1
    r_b = bi[b["date"]] / bi[a["date"]] - 1
    return r_inv - (-1 * r_b)


def _svg(inv: list[dict[str, Any]], bench: list[dict[str, Any]] | None = None) -> str:
    """Normalized (100 at first adj close) long-term path."""
    if len(inv) < 2:
        return ""
    w, h, pad = 760, 200, 28
    xs = [{"date": r["date"], "v": adj_close(r)} for r in inv]
    base = xs[0]["v"]
    vals = [x["v"] / base * 100 for x in xs]
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1
    def X(i): return pad + i * (w - 2 * pad) / (len(xs) - 1)
    def Y(v): return pad + (hi - v) / span * (h - 2 * pad)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
    parts = [f'<svg viewBox="0 0 {w} {h + 20}" class="kd-svg" role="img" aria-label="00632R 還原走勢">',
             f'<polyline fill="none" stroke="#2563eb" stroke-width="1.8" points="{pts}"/>']
    # merger marker
    for i, x in enumerate(xs):
        if x["date"] >= MERGE_RESUME:
            parts.append(f'<line x1="{X(i):.1f}" y1="{pad}" x2="{X(i):.1f}" y2="{h - pad}" '
                         f'stroke="#94a3b8" stroke-dasharray="4 3"/>'
                         f'<text x="{X(i) + 4:.1f}" y="{pad + 10}" font-size="11" fill="#64748b">七併一 {MERGE_RESUME}</text>')
            break
    for i in (0, len(xs) // 2, len(xs) - 1):
        anchor = "start" if i == 0 else ("end" if i == len(xs) - 1 else "middle")
        parts.append(f'<text x="{X(i):.1f}" y="{h + 14}" font-size="11" fill="#64748b" text-anchor="{anchor}">{xs[i]["date"][2:]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_inverse_view(root: Path) -> dict[str, Any] | None:
    rp, bp = etf_path(root, "00632R"), etf_path(root, "0050")
    inv = (read_json(rp).get("rows") or []) if rp.is_file() else []
    bench = (read_json(bp).get("rows") or []) if bp.is_file() else []
    if not inv:
        return None
    last = inv[-1]
    b_last = bench[-1] if bench else None
    # align for returns
    table = []
    for n, lab in ((1, "1 日"), (5, "5 日"), (20, "20 日")):
        table.append({"n": n, "lab": lab, "inv": _ret(inv, n), "bench": _ret(bench, n) if bench else None,
                      "gap": decay_gap(inv, bench, n) if bench else None})
    gap20 = next((t["gap"] for t in table if t["n"] == 20), None)
    reason = (
        f"00632R {last['date']} 收盤 {last['close']:.2f}。"
        + (f"近 20 日報酬 {table[2]['inv']*100:+.2f}%，0050 {table[2]['bench']*100:+.2f}%，"
           f"衰減缺口（自算）{gap20*100:+.2f}%。" if table[2]["inv"] is not None and table[2]["bench"] is not None and gap20 is not None
           else "對照報酬資料不足。")
        + "本頁是風險說明，不做自動買賣燈號；公開說明書載明不適合長期持有。"
    )
    pre, post = sum(1 for r in inv if r["date"] < MERGE_RESUME), sum(1 for r in inv if r["date"] >= MERGE_RESUME)
    return {
        "date": last["date"], "close": last["close"], "volume": last.get("volume"),
        "bench_date": b_last["date"] if b_last else None, "bench_close": b_last["close"] if b_last else None,
        "table": table, "prospectus": PROSPECTUS, "merge": MERGE_RESUME, "merge_ratio": MERGE_RATIO,
        "n": len(inv), "first": inv[0]["date"], "pre_n": pre, "post_n": post,
        "svg": _svg(inv), "label": {"text": "僅供風險說明", "cls": "na"}, "reason": reason,
        "gap5": next((t["gap"] for t in table if t["n"] == 5), None),
        "gap20": gap20,
    }
