"""策略 3：外資臺股期貨淨未平倉＋P/C 比（籌碼背景）。

Sources (TAIFEX, public):
  - 近 1 個月：openapi /v1/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate（CSV, UTF-8 BOM）
                openapi /v1/PutCallRatio（JSON）
  - 歷史：POST /cht/3/futContractsDateDown（commodityId=TXF, Big5 CSV）
          POST /cht/3/pcRatioDown（down_type=1，一次一個月，Big5 CSV）
Archive of record: data/strategy/futures/series.json (TAIFEX openapi 只留約 1 個月，所以每天自己存).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .strategy_common import (
    any_to_date, http, label, num, percentile_rank, session, strategy_dir, third_wednesday, today_tw,
)
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

OPEN_FUT = "https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate"
OPEN_PC = "https://openapi.taifex.com.tw/v1/PutCallRatio"
HIST_FUT = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
HIST_PC = "https://www.taifex.com.tw/cht/3/pcRatioDown"
SRC_FUT = "https://www.taifex.com.tw/cht/3/futContractsDate"
SRC_PC = "https://www.taifex.com.tw/cht/3/pcRatio"
BACKFILL_DAYS = 400


def series_path(root: Path) -> Path:
    return strategy_dir(root) / "futures" / "series.json"


def parse_fut_csv(text: str) -> dict[str, int]:
    """CSV rows → {iso date: 外資及陸資 臺股期貨 多空未平倉口數淨額}."""
    out: dict[str, int] = {}
    rd = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    head = next(rd, None)
    if not head:
        return out
    head = [h.strip() for h in head]
    try:
        i_d, i_p, i_w, i_n = head.index("日期"), head.index("商品名稱"), head.index("身份別"), head.index("多空未平倉口數淨額")
    except ValueError:
        raise RuntimeError(f"TAIFEX 期貨三大法人欄位格式變動: {head}")
    for r in rd:
        if len(r) <= i_n:
            continue
        if r[i_p].strip() == "臺股期貨" and r[i_w].strip().startswith("外資"):
            v = num(r[i_n])
            if v is not None:
                out[any_to_date(r[i_d]).isoformat()] = int(v)
    return out


def parse_fut_any(text: str) -> dict[str, int]:
    """openapi sometimes answers JSON instead of CSV (seen from GitHub Actions); accept both."""
    t = text.lstrip("\ufeff").lstrip()
    if not t.startswith("["):
        return parse_fut_csv(t)
    import json

    out: dict[str, int] = {}
    for r in json.loads(t):
        vals = {str(k): str(v).strip() for k, v in r.items()}
        date_v = vals.get("Date") or vals.get("日期")
        is_tx = any(v in ("臺股期貨", "TX", "TXF") for k, v in vals.items() if "ontract" in k or "商品" in k)
        is_fi = any(("外資" in v or v.lower().startswith("foreign")) for k, v in vals.items()
                    if "tem" in k or "dentit" in k or "身份" in k or "nvestor" in k)
        net_k = [k for k in vals if ("OpenInterest" in k or "未平倉" in k) and ("Net" in k or "淨額" in k)
                 and not any(x in k for x in ("Amount", "Value", "金額"))]
        if date_v and is_tx and is_fi and len(net_k) == 1:
            v = num(vals[net_k[0]])
            if v is not None:
                out[any_to_date(date_v).isoformat()] = int(v)
    return out


def parse_pc_csv(text: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    rd = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    head = next(rd, None)
    if not head or "日期" not in head[0]:
        return out
    for r in rd:
        if len(r) < 7 or not r[0].strip():
            continue
        vol, oi = num(r[3]), num(r[6])
        if vol is None or oi is None:
            continue
        out[any_to_date(r[0]).isoformat()] = {"pc_vol": vol, "pc_oi": oi}
    return out


def parse_pc_json(js: list) -> dict[str, dict[str, float]]:
    out = {}
    for r in js:
        vol, oi = num(r.get("PutCallVolumeRatio%")), num(r.get("PutCallOIRatio%"))
        if vol is None or oi is None:
            continue
        out[any_to_date(r["Date"]).isoformat()] = {"pc_vol": vol, "pc_oi": oi}
    return out


def update_futures(root: Path, today: date | None = None) -> int:
    today = today or today_tw()
    p = series_path(root)
    data = read_json(p) if p.is_file() else {"rows": []}
    rows = {r["date"]: r for r in data.get("rows", [])}
    sess = session()
    errors: list[str] = []
    fut: dict[str, int] = {}
    pc: dict[str, dict[str, float]] = {}
    # 1) history download: full backfill when short of data, otherwise the last ~5 weeks (most up to date source)
    oldest_needed = today - timedelta(days=BACKFILL_DAYS)
    have_fut = sorted(d for d, r in rows.items() if r.get("foreign_net") is not None)
    full = not have_fut or have_fut[0] > (oldest_needed + timedelta(days=10)).isoformat()
    fut_start = oldest_needed if full else today - timedelta(days=35)
    if True:
        try:
            r = http(sess, HIST_FUT, data={"queryStartDate": fut_start.strftime("%Y/%m/%d"),
                                            "queryEndDate": today.strftime("%Y/%m/%d"), "commodityId": "TXF"})
            fut.update(parse_fut_csv(r.content.decode("big5", errors="replace")))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"futContractsDateDown: {exc}")
    have_pc = sorted(d for d, r in rows.items() if r.get("pc_oi") is not None)
    start = oldest_needed if not have_pc or have_pc[0] > (oldest_needed + timedelta(days=10)).isoformat() else (
        date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1))
    if start:
        m = date(start.year, start.month, 1)
        while m <= today:
            nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
            end = min(nxt - timedelta(days=1), today)
            try:
                r = http(sess, HIST_PC, data={"down_type": "1", "queryStartDate": m.strftime("%Y/%m/%d"),
                                               "queryEndDate": end.strftime("%Y/%m/%d")})
                pc.update(parse_pc_csv(r.content.decode("big5", errors="replace")))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"pcRatioDown {m:%Y-%m}: {exc}")
            m = nxt
    # 2) latest month from openapi
    try:
        fut.update({k: v for k, v in parse_fut_any(http(sess, OPEN_FUT).content.decode("utf-8-sig", errors="replace")).items() if k not in fut})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"openapi futures: {exc}")
    try:
        pc.update({k: v for k, v in parse_pc_json(http(sess, OPEN_PC).json()).items() if k not in pc})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"openapi PutCallRatio: {exc}")
    before = len(rows)
    for d, v in fut.items():
        rows.setdefault(d, {"date": d})["foreign_net"] = v
    for d, v in pc.items():
        rows.setdefault(d, {"date": d}).update(v)
    out = sorted(rows.values(), key=lambda r: r["date"])
    write_json(p, {"source": [SRC_FUT, SRC_PC], "updated_at": now_taipei_iso(), "fetch_errors": errors, "rows": out})
    if errors:
        logger.warning("futures/PC fetch errors: %s", errors)
    return len(rows) - before


def settlement_flag(d: str, trading_days: list[str], window: int = 5) -> bool:
    """True if d is within ±window trading days of that month's (or adjacent month's) 3rd-Wednesday settlement."""
    dd = date.fromisoformat(d)
    for y, m in ((dd.year, dd.month), (dd.year - (dd.month == 1), (dd.month - 2) % 12 + 1),
                 (dd.year + (dd.month == 12), dd.month % 12 + 1)):
        s = third_wednesday(y, m).isoformat()
        # trading-day distance; days beyond our data fall back to weekdays
        days = sorted(set(trading_days))
        lo, hi = min(s, d), max(s, d)
        between = [x for x in days if lo < x <= hi]
        if hi > days[-1]:
            x = date.fromisoformat(days[-1]) + timedelta(days=1)
            while x.isoformat() <= hi:
                if x.weekday() < 5:
                    between.append(x.isoformat())
                x += timedelta(days=1)
        if len(between) <= window:
            return True
    return False


def compute(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add 20d avg / diff / 60d percentile / score to rows that have both series."""
    rows = [r for r in rows if r.get("foreign_net") is not None]
    out = []
    pcs = [r for r in rows]
    for i, r in enumerate(rows):
        x = dict(r)
        nets = [q["foreign_net"] for q in rows[max(0, i - 19): i + 1]]
        x["avg20"] = round(sum(nets) / len(nets), 1) if len(nets) == 20 else None
        x["diff20"] = round(r["foreign_net"] - x["avg20"], 1) if x["avg20"] is not None else None
        x["chg1"] = r["foreign_net"] - rows[i - 1]["foreign_net"] if i > 0 else None
        w60 = [q["foreign_net"] for q in rows[max(0, i - 59): i + 1]]
        x["pct60"] = percentile_rank(w60, r["foreign_net"]) if len(w60) == 60 else None
        pw = [q["pc_oi"] for q in pcs[max(0, i - 59): i + 1] if q.get("pc_oi") is not None]
        x["pc_pct60"] = percentile_rank(pw, r["pc_oi"]) if r.get("pc_oi") is not None and len(pw) >= 50 else None
        f_score = None
        if x["diff20"] is not None and x["chg1"] is not None:
            f_score = 1 if (x["diff20"] > 0 and x["chg1"] > 0) else -1 if (x["diff20"] < 0 and x["chg1"] < 0) else 0
        p_score = None
        if x["pc_pct60"] is not None:
            p_score = 1 if x["pc_pct60"] >= 70 else -1 if x["pc_pct60"] <= 30 else 0
        x["f_score"], x["p_score"] = f_score, p_score
        if f_score is None or p_score is None:
            x["score"], x["verdict"] = None, "na"
        else:
            x["score"] = f_score + p_score
            x["verdict"] = "bull" if x["score"] >= 2 else "bear" if x["score"] <= -2 else "neutral"
        x["extreme"] = x["pct60"] is not None and (x["pct60"] >= 90 or x["pct60"] <= 10)
        out.append(x)
    days = [r["date"] for r in out]
    for x in out:
        x["settle"] = settlement_flag(x["date"], days)
    return out


def _reason(x: dict[str, Any]) -> str:
    if x["verdict"] == "na":
        return "資料不足，暫不判讀。"
    f = {1: "外資淨未平倉高於 20 日均且比前一日增加（加多或回補空單）",
         -1: "外資淨未平倉低於 20 日均且比前一日減少（加空或減多）",
         0: "外資淨未平倉變化方向不一致"}[x["f_score"]]
    p = {1: f"P/C 未平倉比位於近 60 日 {x['pc_pct60']:.0f} 百分位（偏高，賣權賣方撐盤）",
         -1: f"P/C 未平倉比位於近 60 日 {x['pc_pct60']:.0f} 百分位（偏低）",
         0: f"P/C 未平倉比位於近 60 日 {x['pc_pct60']:.0f} 百分位（中間）"}[x["p_score"]]
    return f"{f}（{x['f_score']:+d}）；{p}（{x['p_score']:+d}）；合計 {x['score']:+d}。"


def _svg(rows: list[dict[str, Any]], taiex: dict[str, float], w: int = 760, h: int = 240) -> str:
    if len(rows) < 2:
        return ""
    pad_l, pad_r, pad_t, pad_b = 56, 56, 12, 22
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    nets = [r["foreign_net"] for r in rows]
    lo, hi = min(nets + [0]), max(nets + [0])
    span = (hi - lo) or 1
    tx = [taiex.get(r["date"]) for r in rows]
    tv = [v for v in tx if v]
    n = len(rows)

    def x(i: int) -> float:
        return pad_l + iw * i / (n - 1)

    def y(v: float) -> float:
        return pad_t + ih * (hi - v) / span

    bw = max(1.0, iw / n * 0.7)
    parts = [f'<svg viewBox="0 0 {w} {h}" class="vix-svg" role="img" aria-label="外資臺股期貨淨未平倉與加權指數">']
    parts.append(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#94a3b8" stroke-width="1"/>')
    for i, v in enumerate(nets):
        col = "#dc2626" if v >= 0 else "#16a34a"
        y0, y1 = sorted((y(0), y(v)))
        parts.append(f'<rect x="{x(i) - bw / 2:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{max(0.5, y1 - y0):.1f}" fill="{col}" opacity="0.55"/>')
    for v in (lo, (lo + hi) / 2, hi):
        parts.append(f'<text x="{pad_l - 4}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="10" fill="#64748b">{v / 1000:.0f}k</text>')
    if len(tv) >= 2:
        tlo, thi = min(tv), max(tv)
        ts = (thi - tlo) or 1

        def ty(v: float) -> float:
            return pad_t + ih * (thi - v) / ts

        pts = " ".join(f"{x(i):.1f},{ty(v):.1f}" for i, v in enumerate(tx) if v)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="#2563eb" stroke-width="1.8"/>')
        for v in (tlo, thi):
            parts.append(f'<text x="{w - pad_r + 4}" y="{ty(v) + 4:.1f}" font-size="10" fill="#2563eb">{v:,.0f}</text>')
    for i, r in enumerate(rows):
        if i in (0, n - 1) or i % max(1, n // 6) == 0:
            parts.append(f'<text x="{x(i):.1f}" y="{h - 6}" text-anchor="middle" font-size="10" fill="#64748b">{r["date"][2:]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_futures_view(root: Path, chart_days: int = 120) -> dict[str, Any] | None:
    p = series_path(root)
    if not p.is_file():
        return None
    data = read_json(p)
    rows = compute(data.get("rows") or [])
    if not rows:
        return None
    latest = rows[-1]
    taiex: dict[str, float] = {}
    kd = root / "data" / "taiex" / "kd.json"
    if kd.is_file():
        taiex = {r["date"]: r["close"] for r in read_json(kd).get("rows", [])}
    return {
        "latest": latest,
        "label": label(latest["verdict"]),
        "reason": _reason(latest),
        "recent": list(reversed(rows[-30:])),
        "svg": _svg(rows[-chart_days:], taiex),
        "coverage": {"from": rows[0]["date"], "to": latest["date"], "days": len(rows),
                     "pc_from": min((r["date"] for r in data["rows"] if r.get("pc_oi") is not None), default=None)},
        "fetch_errors": data.get("fetch_errors") or [],
        "updated_at": data.get("updated_at"),
        "src_fut": SRC_FUT,
        "src_pc": SRC_PC,
    }
