"""策略 17：大盤均線濾網（發行量加權股價報酬指數）。官方／政府資料 only，不用第三方行情。"""

from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

from .strategy_common import any_to_date, http_json, num, session, strategy_dir, today_tw
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

OPENAPI = "https://openapi.twse.com.tw/v1/indicesReport/MFI94U"
# Official TWSE monthly JSON (government open-data sibling). rwd / open_data paths hit 307; this one works.
HIST = "https://www.twse.com.tw/indicesReport/MFI94U"
TWSE_GAP, TWSE_BLOCK = 15, 180
# FinLab 原參數，研究值
MA, BUF = 120, 0.02
# 只當說明、不改用的組
SHOW_MA = (60, 120, 240)
SHOW_BUF = (0.0, 0.02, 0.04)


def tri_path(root: Path) -> Path:
    return strategy_dir(root) / "tri" / "mfi94u.json"


def parse_openapi(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows or []:
        v = num(r.get("TAIEXTotalReturnIndex"))
        if v is None:
            continue
        try:
            out.append({"date": any_to_date(r["Date"]).isoformat(), "close": v, "src": "openapi"})
        except (KeyError, ValueError):
            continue
    return out


def parse_month(js: dict[str, Any]) -> list[dict[str, Any]]:
    if js.get("stat") != "OK":
        return []
    out = []
    for row in js.get("data") or []:
        try:
            v = num(row[1])
            if v is None:
                continue
            out.append({"date": any_to_date(row[0]).isoformat(), "close": v, "src": "twse"})
        except (ValueError, IndexError):
            continue
    return out


def merge(by: dict[str, dict], rows: list[dict]) -> int:
    n = 0
    for r in rows:
        new = {"date": r["date"], "close": r["close"], "src": r.get("src", "twse")}
        if by.get(r["date"]) != new:
            by[r["date"]] = new
            n += 1
    return n



def _fill_recent_months(by: dict[str, dict], errors: list[str], limit: int = 12) -> int:
    today = today_tw()
    y, m = today.year, today.month
    want = []
    for _ in range(18):
        want.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    have = {d[:7] for d in by}
    missing = [d for d in want if f"{d:%Y-%m}" not in have][:limit]
    if not missing:
        return 0
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (compatible; tw-etf-pages/1.0)"
    added = 0
    for i, d in enumerate(missing):
        if i:
            time.sleep(TWSE_GAP)
        try:
            r = sess.get(HIST, params={"response": "json", "date": d.strftime("%Y%m01")},
                         timeout=(10, 25), allow_redirects=False)
            if r.status_code != 200 or not r.text.lstrip().startswith("{"):
                errors.append(f"MFI94U {d:%Y-%m} HTTP {r.status_code}（官方月檔被擋，本次停止回補）")
                logger.warning("trend-filter: official monthly MFI94U blocked at %s (%s)", d, r.status_code)
                break
            added += merge(by, parse_month(r.json()))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"MFI94U {d:%Y-%m}: {exc}")
            break
    return added


def update_trend(root: Path) -> dict[str, Any]:
    path = tri_path(root)
    store = read_json(path) if path.is_file() else {}
    by = {r["date"]: r for r in store.get("rows") or []}
    errors: list[str] = []
    n = 0
    try:
        n += merge(by, parse_openapi(http_json(session(), OPENAPI, tries=2, timeout=60) or []))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"openapi MFI94U: {exc}")
        logger.warning("trend-filter: openapi MFI94U failed: %s", exc)
    # Official monthly JSON (same family as data.gov.tw 11871). rwd/open_data often 307.
    # Fill missing months newest-first; stop at the first 307 so the daily job is not stalled.
    if len(by) < 260:
        n += _fill_recent_months(by, errors, limit=12)
    rows = sorted(by.values(), key=lambda r: r["date"])
    data = {"source": [OPENAPI, HIST], "updated_at": now_taipei_iso(),
            "fetch_errors": errors, "rows": rows}
    if n or not path.is_file():
        write_json(path, data)
    logger.info("trend-filter: %d TRI rows (+%d), latest %s", len(rows), n, rows[-1]["date"] if rows else None)
    return data


def backfill_tri(root: Path, start: date = date(2023, 11, 1), cache: Path | None = None) -> int:
    """One-time official monthly backfill, ≥15s apart; 3 min on 307. Optional pre-fetched cache dir."""
    path = tri_path(root)
    store = read_json(path) if path.is_file() else {}
    by = {r["date"]: r for r in store.get("rows") or []}
    if cache and cache.is_dir():
        for f in sorted(cache.glob("*.json")):
            merge(by, parse_month(read_json(f)))
    today = today_tw()
    have = {d[:7] for d in by}
    y, m = start.year, start.month
    missing = []
    while (y, m) <= (today.year, today.month):
        if f"{y:04d}-{m:02d}" not in have:
            missing.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    if missing:
        sess = requests.Session()
        sess.headers["User-Agent"] = "Mozilla/5.0 (compatible; tw-etf-pages/1.0)"
        for i, d in enumerate(missing):
            if i:
                time.sleep(TWSE_GAP)
            for _ in range(4):
                try:
                    r = sess.get(HIST, params={"response": "json", "date": d.strftime("%Y%m01")},
                                 timeout=(10, 25), allow_redirects=False)
                    if r.status_code == 200 and r.text.lstrip().startswith("{"):
                        merge(by, parse_month(r.json()))
                        break
                    logger.warning("TRI %s HTTP %s, wait 3 min", d, r.status_code)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("TRI %s: %s", d, exc)
                time.sleep(TWSE_BLOCK)
    rows = sorted(by.values(), key=lambda r: r["date"])
    write_json(path, {"source": [OPENAPI, HIST], "updated_at": now_taipei_iso(),
                      "fetch_errors": [], "rows": rows})
    return len(rows)


def ma(vals: list[float], n: int) -> float | None:
    return sum(vals[-n:]) / n if len(vals) >= n else None


def signal(close: float, ma120: float | None, prev: str | None) -> str | None:
    if ma120 is None:
        return None
    if close > ma120:
        return "in"
    if close < ma120 * (1 - BUF):
        return "hedge"
    return prev  # 介於之間維持前一天狀態


def series_states(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    closes = [r["close"] for r in rows]
    out = []
    prev = None
    for i, r in enumerate(rows):
        win = closes[: i + 1]
        o = {**r}
        for n in SHOW_MA:
            o[f"ma{n}"] = ma(win, n)
        o["dist"] = (r["close"] / o["ma120"] - 1) * 100 if o["ma120"] else None
        o["buf2"] = o["ma120"] * (1 - BUF) if o["ma120"] else None
        sig = signal(r["close"], o["ma120"], prev)
        o["signal"] = sig  # 當日收盤判斷
        o["exec"] = prev   # 下一交易日執行＝前一日訊號
        prev = sig
        out.append(o)
    return out


def _label(sig: str | None) -> dict[str, str]:
    if sig == "in":
        return {"text": "偏多／在場", "cls": "bull"}
    if sig == "hedge":
        return {"text": "偏防守（減碼／啟動避險）", "cls": "bear"}
    if sig is None:
        return {"text": "資料暫缺", "cls": "na"}
    return {"text": "中性（沿用前一天）", "cls": "neutral"}


def _streak(states: list[dict], key: str) -> tuple[int, str | None]:
    if not states or not states[-1].get(key):
        return 0, None
    cur = states[-1][key]
    n = 0
    for s in reversed(states):
        if s.get(key) == cur:
            n += 1
        else:
            break
    return n, cur


def _svg(states: list[dict[str, Any]], n: int = 240) -> str:
    days = [s for s in states if s.get("ma120") is not None][-n:]
    if len(days) < 2:
        return ""
    w, h, pad = 760, 200, 28
    ys = [s["close"] for s in days] + [s["ma120"] for s in days] + [s["buf2"] for s in days if s.get("buf2")]
    lo, hi = min(ys), max(ys)
    span = hi - lo or 1
    def X(i): return pad + i * (w - 2 * pad) / (len(days) - 1)
    def Y(v): return pad + (hi - v) / span * (h - 2 * pad)
    def line(key, color, dash=""):
        pts = " ".join(f"{X(i):.1f},{Y(s[key]):.1f}" for i, s in enumerate(days) if s.get(key))
        d = f' stroke-dasharray="{dash}"' if dash else ""
        return f'<polyline fill="none" stroke="{color}" stroke-width="1.6"{d} points="{pts}"/>'
    parts = [f'<svg viewBox="0 0 {w} {h + 20}" class="kd-svg" role="img" aria-label="報酬指數與 120MA">',
             line("close", "#1e293b"), line("ma120", "#dc2626"), line("buf2", "#16a34a", "4 3")]
    if days[0].get("ma60"):
        parts.append(line("ma60", "#94a3b8", "2 2"))
    if days[0].get("ma240") or days[-1].get("ma240"):
        parts.append(line("ma240", "#7c3aed", "6 3"))
    for i in (0, len(days) // 2, len(days) - 1):
        anchor = "start" if i == 0 else ("end" if i == len(days) - 1 else "middle")
        parts.append(f'<text x="{X(i):.1f}" y="{h + 14}" font-size="11" fill="#64748b" text-anchor="{anchor}">{days[i]["date"][2:]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_trend_view(root: Path) -> dict[str, Any] | None:
    path = tri_path(root)
    if not path.is_file():
        return None
    store = read_json(path)
    rows = store.get("rows") or []
    if len(rows) < 5:
        return None
    states = series_states(rows)
    o = states[-1]
    prev = states[-2] if len(states) > 1 else {}
    n_in, _ = _streak([s for s in states if s.get("exec")], "exec")
    # streak of today's signal (will be executed tomorrow)
    n_sig, _ = _streak(states, "signal")
    lab = _label(o["signal"])  # 今日收盤判斷、下一交易日執行
    enough120 = o["ma120"] is not None
    enough240 = o["ma240"] is not None
    if o["signal"] == "hedge":
        why = f"報酬指數收盤 {o['close']:,.2f} 低於 120MA×0.98（{o['buf2']:,.2f}），距 120MA {o['dist']:+.2f}%。訊號為減碼／啟動避險（下一交易日執行，研究值）。"
    elif o["signal"] == "in":
        why = f"報酬指數收盤 {o['close']:,.2f} 高於 120MA（{o['ma120']:,.2f}），距均線 {o['dist']:+.2f}%。訊號為在場（下一交易日執行，研究值）。"
    elif o["signal"] is None:
        why = f"報酬指數收盤 {o['close']:,.2f}，但 120 日均線資料不足（目前 {len(rows)} 個交易日），無法判讀。"
    else:
        why = (f"報酬指數收盤 {o['close']:,.2f} 介於 120MA（{o['ma120']:,.2f}）與 2% 緩衝線（{o['buf2']:,.2f}）之間，"
               f"維持前一天狀態（目前沿用「{_label(o['signal'])['text']}」）。")
    return {
        "date": o["date"], "close": o["close"], "ind": o, "prev": prev, "label": lab, "reason": why,
        "n": len(rows), "first": rows[0]["date"], "enough120": enough120, "enough240": enough240,
        "streak_exec": n_in, "streak_sig": n_sig, "svg": _svg(states),
        "exec_label": _label(o["exec"]), "sig_label": lab,
        "note_240": None if enough240 else "官方報酬指數歷史不足 240 個交易日，240 日均線顯示資料暫缺；沒有改用第三方行情。",
        "fetch_errors": store.get("fetch_errors") or [],
    }
