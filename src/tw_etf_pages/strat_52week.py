"""策略 5：52 週新高動能。

Closes / 成交金額: data/strategy/prices（TWSE MI_INDEX ALLBUT0999、TPEx otc EW；strategy_daily 每日存檔）。
除權息還原：TWSE rwd exRight/TWT49U、TPEx www bulletin/exDailyQ；factor＝除權息參考價 ÷ 除權息前收盤價，
套用在除權息日之前的收盤價。減資／分割未還原（單日漲跌超過 11% 的股票標註）。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from .strategy_common import STOCK_CODE, any_to_date, http_json, label, num, session, strategy_dir, today_tw
from .strategy_daily import load_series
from .strat_daily_compact import write_compact
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

TWT49U = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
EXDAILYQ = "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ"
WINDOW = 250
MIN_TURNOVER = 20_000_000  # 經驗值
HIGH, LOW = 0.9, 0.7       # 經驗值
VOL_OK = 0.7               # 5 日均成交金額 ≥ 0.7 × 20 日均（經驗值）
MKT_BULL, MKT_BEAR = 40.0, 15.0  # 全市場比值 ≥0.9 家數占比（經驗值）
TREND_DAYS = 60
MIN_WINDOW = 200


def exright_dir(root: Path) -> Path:
    return strategy_dir(root) / "exright"


def parse_twt49u_factors(js: dict) -> dict[str, list]:
    out: dict[str, list] = {}
    if str(js.get("stat", "")).upper() != "OK":
        return out
    f = js["fields"]
    i_d, i_c, i_p, i_r = f.index("資料日期"), f.index("股票代號"), f.index("除權息前收盤價"), f.index("除權息參考價")
    for r in js["data"]:
        c = str(r[i_c]).strip()
        p, ref = num(r[i_p]), num(r[i_r])
        if STOCK_CODE.match(c) and p and ref and 0 < ref <= p:
            out.setdefault(c, []).append([any_to_date(r[i_d]).isoformat(), round(ref / p, 6)])
    return out


def parse_exdailyq_factors(js: dict) -> dict[str, list]:
    out: dict[str, list] = {}
    t = (js.get("tables") or [{}])[0]
    f = t.get("fields") or []
    if not f:
        return out
    i_d, i_c, i_p, i_r = f.index("除權息日期"), f.index("代號"), f.index("除權息前收盤價"), f.index("除權息參考價")
    for r in t.get("data", []):
        c = str(r[i_c]).strip()
        p, ref = num(r[i_p]), num(r[i_r])
        if STOCK_CODE.match(c) and p and ref and 0 < ref <= p:
            out.setdefault(c, []).append([any_to_date(r[i_d]).isoformat(), round(ref / p, 6)])
    return out


def update_exright(root: Path, today: date | None = None) -> None:
    """Cache per-year factors; past years once, current year refreshed every run (2 requests)."""
    today = today or today_tw()
    sess = session()
    for y in (today.year - 1, today.year):
        p = exright_dir(root) / f"{y}.json"
        if p.is_file() and y < today.year:
            continue
        try:
            tw = parse_twt49u_factors(http_json(sess, TWT49U, params={"startDate": f"{y}0101", "endDate": f"{y}1231", "response": "json"}))
            ot = parse_exdailyq_factors(http_json(sess, EXDAILYQ, params={"startDate": f"{y}/01/01", "endDate": f"{y}/12/31", "response": "json"}))
            if not tw or not ot:
                raise RuntimeError(f"empty ex-right list {y}: TWSE {len(tw)} TPEx {len(ot)}")
            write_compact(p, {"year": y, "fetched_at": now_taipei_iso(), "factors": {**ot, **tw}})
        except Exception as exc:  # noqa: BLE001
            logger.warning("ex-right %s failed: %s", y, exc)


def load_factors(root: Path) -> dict[str, list]:
    out: dict[str, list] = {}
    for p in sorted(exright_dir(root).glob("*.json")):
        for c, ev in read_json(p)["factors"].items():
            out.setdefault(c, []).extend(ev)
    return out


def adjusted(closes: list[tuple[str, float]], events: list) -> list[float]:
    """Back-adjust: every close dated before an ex-date is multiplied by that event's factor."""
    vals = []
    for d, c in closes:
        f = 1.0
        for ex, fac in events:
            if d < ex:
                f *= fac
        vals.append(c * f)
    return vals


def stock_ratio(series: list[dict[str, Any]], code: str, events: list, end: int | None = None) -> dict[str, Any] | None:
    sub = series[: end + 1] if end is not None else series
    sub = sub[-WINDOW:]
    closes = [(s["date"], s["rows"][code][2]) for s in sub if code in s["rows"]]
    if len(closes) < MIN_WINDOW or closes[-1][0] != sub[-1]["date"]:
        return None
    adj = adjusted(closes, events)
    hi = max(adj)
    jump = any(abs(b / a - 1) > 0.11 for a, b in zip(adj, adj[1:]) if a > 0)
    turns = [s["rows"][code][3] for s in sub[-20:] if code in s["rows"]]
    t5 = [s["rows"][code][3] for s in sub[-5:] if code in s["rows"]]
    t20 = sum(turns) / len(turns) if turns else 0
    return {"close": closes[-1][1], "high": hi, "ratio": closes[-1][1] / hi if hi else None,
            "new_high": closes[-1][1] >= hi - 1e-9, "turn20": t20, "turn5": (sum(t5) / len(t5)) if t5 else 0,
            "days": len(closes), "jump": jump, "name": series[-1]["rows"][code][0] if code in series[-1]["rows"] else "",
            "market": series[-1]["rows"][code][1] if code in series[-1]["rows"] else ""}


def classify(ratio: float, new_high: bool, vol_ok: bool) -> str:
    if (ratio >= HIGH or new_high) and vol_ok:
        return "bull"
    if ratio < LOW:
        return "bear"
    return "neutral"


def _market_share(series, factors, end: int) -> tuple[float | None, int]:
    hits = n = 0
    for code in series[end]["rows"]:
        if not STOCK_CODE.match(code):
            continue
        st = stock_ratio(series, code, factors.get(code, []), end)
        if not st or st["turn20"] < MIN_TURNOVER:
            continue
        n += 1
        hits += st["ratio"] >= HIGH
    return (round(hits / n * 100, 1) if n else None), n


def _svg(trend: list[dict[str, Any]], w: int = 760, h: int = 200) -> str:
    pts_v = [t for t in trend if t["share"] is not None]
    if len(pts_v) < 2:
        return ""
    pad_l, pad_r, pad_t, pad_b = 36, 10, 10, 22
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    hi = max(max(t["share"] for t in pts_v), MKT_BULL) + 5
    n = len(pts_v)

    def x(i): return pad_l + iw * i / (n - 1)
    def y(v): return pad_t + ih * (hi - v) / hi

    parts = [f'<svg viewBox="0 0 {w} {h}" class="vix-svg" role="img" aria-label="比值≥0.9 家數占比走勢">']
    for thr, col, lab in ((MKT_BULL, "#dc2626", f"{MKT_BULL:.0f}% 偏多線"), (MKT_BEAR, "#16a34a", f"{MKT_BEAR:.0f}% 偏空線")):
        parts.append(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{y(thr):.1f}" y2="{y(thr):.1f}" stroke="{col}" stroke-dasharray="5 4"/>')
        parts.append(f'<text x="{w - pad_r - 2}" y="{y(thr) - 3:.1f}" text-anchor="end" font-size="11" fill="{col}">{lab}（經驗值）</text>')
    parts.append('<polyline points="' + " ".join(f"{x(i):.1f},{y(t['share']):.1f}" for i, t in enumerate(pts_v))
                 + '" fill="none" stroke="#7c3aed" stroke-width="2"/>')
    for i, t in enumerate(pts_v):
        if i in (0, n - 1) or i % max(1, n // 6) == 0:
            parts.append(f'<text x="{x(i):.1f}" y="{h - 6}" text-anchor="middle" font-size="10" fill="#64748b">{t["date"][5:]}</text>')
    for v in (0, hi / 2, hi):
        parts.append(f'<text x="{pad_l - 4}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="10" fill="#64748b">{v:.0f}%</text>')
    parts.append("</svg>")
    return "".join(parts)


def compute(root: Path, today: date | None = None) -> dict[str, Any] | None:
    today = today or today_tw()
    series = load_series(root, "prices")
    if len(series) < MIN_WINDOW:
        return None
    factors = load_factors(root)
    rev = {}
    rp = strategy_dir(root) / "revenue" / "labels.json"
    if rp.is_file():
        rev = read_json(rp).get("labels", {})
    items = []
    for code in series[-1]["rows"]:
        if not STOCK_CODE.match(code):
            continue
        st = stock_ratio(series, code, factors.get(code, []))
        if not st or st["turn20"] < MIN_TURNOVER or st["ratio"] is None:
            continue
        vol_ok = st["turn20"] > 0 and st["turn5"] >= VOL_OK * st["turn20"]
        kind = classify(st["ratio"], st["new_high"], vol_ok)
        items.append({"code": code, **st, "vol_ok": vol_ok, "kind": kind,
                      "label": {"bull": "偏多", "bear": "偏空", "neutral": "中性"}[kind]
                      + ("（新高）" if st["new_high"] and kind == "bull" else ""),
                      "rev": rev.get(code)})
    ranked = sorted(items, key=lambda x: x["ratio"])
    for i, x in enumerate(ranked):
        x["pct"] = round((i + 1) / len(ranked) * 100, 1)
        x["top20"] = x["pct"] > 80
    items.sort(key=lambda x: x["ratio"], reverse=True)
    n = len(items)
    hits = sum(1 for x in items if x["ratio"] >= HIGH)
    share = round(hits / n * 100, 1) if n else None
    verdict = "na" if share is None else "bull" if share > MKT_BULL else "bear" if share < MKT_BEAR else "neutral"
    # trend: archive daily share; backfill recent days from cached closes (window ≥ 200 days)
    tp = strategy_dir(root) / "52week" / "trend.json"
    trend = {t["date"]: t for t in (read_json(tp).get("rows", []) if tp.is_file() else [])}
    for end in range(len(series) - 1, max(-1, len(series) - 1 - TREND_DAYS), -1):
        d = series[end]["date"]
        if d in trend and end != len(series) - 1:
            continue
        if end + 1 < MIN_WINDOW:
            break
        s, cnt = (share, n) if end == len(series) - 1 else _market_share(series, factors, end)
        trend[d] = {"date": d, "share": s, "n": cnt}
    trend_rows = sorted(trend.values(), key=lambda t: t["date"])
    write_json(tp, {"updated_at": now_taipei_iso(), "rows": trend_rows})
    reason = ("資料暫缺。" if share is None else
              f"成交值合格的 {n} 檔中，{hits} 檔（{share:.1f}%）收盤價在還原後 52 週高點的 9 成以上；"
              + (f"高於 {MKT_BULL:.0f}%（經驗值），多數股票貼近高點。" if verdict == "bull"
                 else f"低於 {MKT_BEAR:.0f}%（經驗值），貼近高點的股票很少。" if verdict == "bear"
                 else f"介於 {MKT_BEAR:.0f}%～{MKT_BULL:.0f}%（經驗值）。"))
    return {
        "date": series[-1]["date"], "items": items, "n": n, "hits": hits, "share": share,
        "verdict": verdict, "label": label(verdict), "reason": reason,
        "n_bull": sum(1 for x in items if x["kind"] == "bull"), "n_bear": sum(1 for x in items if x["kind"] == "bear"),
        "n_new_high": sum(1 for x in items if x["new_high"]),
        "january": today.month == 1, "svg": _svg(trend_rows[-TREND_DAYS:]), "trend": list(reversed(trend_rows[-20:])),
        "price_from": series[0]["date"], "price_days": len(series),
        "factor_years": sorted(p.stem for p in exright_dir(root).glob("*.json")),
    }


def build_52week_view(root: Path) -> dict[str, Any] | None:
    return compute(root)
