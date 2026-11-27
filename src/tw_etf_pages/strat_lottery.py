"""策略 11：樂透股警示（近 21 日最大單日漲幅，MAX effect）。

Closes: data/strategy/prices（TWSE MI_INDEX ALLBUT0999、TPEx otc EW）。
日報酬＝今日收盤 ÷ 參考價 − 1，參考價＝前一日收盤 × 除權息因子（除權息日當天，因子＝除權息參考價 ÷ 除權息前收盤價），
等同以「漲跌價差 ÷ 參考價」計算。|報酬| > 10.5% 視為減資恢復交易／無漲跌幅限制日而排除；新上市前 5 個交易日排除。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .strategy_common import STOCK_CODE, label, strategy_dir
from .strategy_daily import load_series
from .strat_52week import load_factors
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

LOOK = 21
MIN_TURNOVER = 20_000_000   # 經驗值
LIMIT_UP = 0.095            # 單日 ≥ 9.5% 視為接近漲停
MAX_VALID = 0.105           # 超過漲跌幅限制 → 排除
MKT_HOT = 22.4              # FinLab 2014–2026 長期平均（經驗值）
NEW_LISTING_SKIP = 5
TREND_DAYS = 240


def daily_returns(series: list[dict[str, Any]], factors: dict[str, list]) -> list[dict[str, float]]:
    """rets[i][code] for day i (vs day i-1); None-excluded values are dropped."""
    fac_by = {c: {d: f for d, f in ev} for c, ev in factors.items()}
    first_seen: dict[str, int] = {}
    out: list[dict[str, float]] = [{}]
    for i in range(len(series)):
        for c in series[i]["rows"]:
            first_seen.setdefault(c, i)
    for i in range(1, len(series)):
        cur, prev, d = series[i]["rows"], series[i - 1]["rows"], series[i]["date"]
        day = {}
        for c, row in cur.items():
            if not STOCK_CODE.match(c) or c not in prev:
                continue
            if first_seen[c] > 0 and i - first_seen[c] < NEW_LISTING_SKIP:
                continue
            ref = prev[c][2] * fac_by.get(c, {}).get(d, 1.0)
            if ref <= 0:
                continue
            r = row[2] / ref - 1
            if abs(r) <= MAX_VALID:
                day[c] = r
        out.append(day)
    return out


def market_share(rets: list[dict[str, float]], end: int) -> tuple[float | None, int]:
    win = rets[end - LOOK + 1: end + 1]
    if len(win) < LOOK:
        return None, 0
    codes = set(win[-1])
    n = hits = 0
    for c in codes:
        vals = [d[c] for d in win if c in d]
        if len(vals) < LOOK - 2:
            continue
        n += 1
        hits += max(vals) >= LIMIT_UP
    return (round(hits / n * 100, 1) if n else None), n


def _svg(trend: list[dict[str, Any]], w: int = 760, h: int = 200) -> str:
    pts = [t for t in trend if t["share"] is not None]
    if len(pts) < 2:
        return ""
    pad_l, pad_r, pad_t, pad_b = 36, 10, 10, 22
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    hi = max(max(t["share"] for t in pts), MKT_HOT) + 5
    n = len(pts)

    def x(i): return pad_l + iw * i / (n - 1)
    def y(v): return pad_t + ih * (hi - v) / hi

    parts = [f'<svg viewBox="0 0 {w} {h}" class="vix-svg" role="img" aria-label="近 21 日曾漲停股票占比">',
             f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{y(MKT_HOT):.1f}" y2="{y(MKT_HOT):.1f}" stroke="#dc2626" stroke-dasharray="5 4"/>',
             f'<text x="{w - pad_r - 2}" y="{y(MKT_HOT) - 3:.1f}" text-anchor="end" font-size="11" fill="#dc2626">22.4% 長期平均（經驗值）</text>',
             '<polyline points="' + " ".join(f"{x(i):.1f},{y(t['share']):.1f}" for i, t in enumerate(pts)) + '" fill="none" stroke="#7c3aed" stroke-width="2"/>']
    for i, t in enumerate(pts):
        if i in (0, n - 1) or i % max(1, n // 6) == 0:
            parts.append(f'<text x="{x(i):.1f}" y="{h - 6}" text-anchor="middle" font-size="10" fill="#64748b">{t["date"][2:]}</text>')
    for v in (0, hi / 2, hi):
        parts.append(f'<text x="{pad_l - 4}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="10" fill="#64748b">{v:.0f}%</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_lottery_view(root: Path) -> dict[str, Any] | None:
    series = load_series(root, "prices")
    if len(series) < LOOK + 2:
        return None
    rets = daily_returns(series, load_factors(root))
    last = len(series) - 1
    win = rets[last - LOOK + 1:]
    latest = series[-1]["rows"]
    items = []
    for c, row in latest.items():
        if not STOCK_CODE.match(c):
            continue
        vals = [d[c] for d in win if c in d]
        if len(vals) < LOOK - 2:
            continue
        turns = [s["rows"][c][3] for s in series[-20:] if c in s["rows"]]
        t20 = sum(turns) / len(turns) if turns else 0
        if t20 < MIN_TURNOVER:
            continue
        mx = max(vals)
        items.append({"code": c, "name": row[0], "market": row[1], "max": mx * 100, "turn20": t20,
                      "limit_days": sum(1 for v in vals if v >= LIMIT_UP), "close": row[2]})
    import bisect

    vals_sorted = sorted(x["max"] for x in items)
    for x in items:  # tie-aware: share of stocks with max ≤ this stock's max
        x["pct"] = round(bisect.bisect_right(vals_sorted, x["max"] + 1e-9) / len(vals_sorted) * 100, 1)
        if x["pct"] > 80:
            x["kind"], x["label"] = "bear", "偏空（個股風險高）"
        elif x["pct"] <= 20:
            x["kind"], x["label"] = "relief", "相對防守"
        else:
            x["kind"], x["label"] = "neutral", "中性"
    items.sort(key=lambda x: x["max"], reverse=True)
    # market share trend (all common stocks with enough data, no liquidity filter)
    tp = strategy_dir(root) / "lottery" / "trend.json"
    trend = {t["date"]: t for t in (read_json(tp).get("rows", []) if tp.is_file() else [])}
    for end in range(last, max(LOOK - 1, last - TREND_DAYS), -1):
        d = series[end]["date"]
        if d in trend and end != last:
            continue
        s, n = market_share(rets, end)
        trend[d] = {"date": d, "share": s, "n": n}
    rows = sorted(trend.values(), key=lambda t: t["date"])
    write_json(tp, {"updated_at": now_taipei_iso(), "rows": rows})
    share, n_all = trend[series[-1]["date"]]["share"], trend[series[-1]["date"]]["n"]
    hot = share is not None and share > MKT_HOT
    verdict = "na" if share is None else "bear" if hot else "neutral"
    lab = {"na": label("na"), "bear": {"text": "投機過熱", "cls": "bear"}, "neutral": label("neutral")}[verdict]
    reason = ("資料暫缺。" if share is None else
              f"近 21 個交易日曾單日上漲 ≥ 9.5% 的股票占 {share:.1f}%（{n_all} 檔普通股）"
              + (f"，高於長期平均 22.4%（經驗值），投機氣氛偏熱。" if hot else "，未高於長期平均 22.4%（經驗值）。"))
    return {"items": items, "date": series[-1]["date"], "from": series[last - LOOK + 1]["date"], "share": share, "n_all": n_all,
            "verdict": verdict, "label": lab, "reason": reason, "svg": _svg(rows[-TREND_DAYS:]),
            "trend_from": rows[0]["date"] if rows else None, "n_trend": len(rows),
            "n_bear": sum(1 for x in items if x["kind"] == "bear"), "n_relief": sum(1 for x in items if x["kind"] == "relief")}
