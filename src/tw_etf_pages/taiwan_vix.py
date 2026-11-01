"""臺指選擇權波動率指數 (TAIWAN VIX, 期交所) daily close history.

Official TAIFEX monthly daily-close files (new CBOE VIX formula), Big5 TSV:
  https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/YYYYMMnew.txt
  columns: 交易日期 | 時間 | 臺指選擇權波動率指數(13:45 收盤) | 收盤前1分鐘平均指數
The current month's file is updated each trading day (~16:00 Taipei).
Free download covers only the current month + previous 3 months, so history is
accumulated in data/vix/taiwan_vix.json. Never raises from update (caller wraps).
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import requests

from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

FILE_URL = "https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{ym}new.txt"
SOURCE_PAGE = "https://www.taifex.com.tw/cht/7/vixDaily3MNew"
UA = "Mozilla/5.0 (compatible; tw-etf-pages/1.0; +https://solymx.github.io/tw-etf-pages/)"
# 燈號門檻（經驗值，非官方）
HIGH_FEAR = 30.0
ELEVATED = 25.0
LOW_FEAR = 18.0


def vix_path(root: Path) -> Path:
    return root / "data" / "vix" / "taiwan_vix.json"


def parse_month_file(text: str) -> list[dict[str, Any]]:
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3 or not (parts[0].isdigit() and len(parts[0]) == 8):
            continue
        try:
            close = float(parts[2])
        except ValueError:
            continue
        avg = None
        if len(parts) >= 4:
            try:
                avg = float(parts[3])
            except ValueError:
                avg = None
        d = parts[0]
        rows.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "close": close, "close_1m_avg": avg})
    return rows


def _months_back(today: date, n: int) -> list[str]:
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def update_vix(root: Path, today: date | None = None) -> dict[str, Any] | None:
    today = today or date.today()
    path = vix_path(root)
    stored = read_json(path) if path.is_file() else {}
    by_date = {r["date"]: r for r in stored.get("rows", [])}
    # first run: backfill 4 months; afterwards current + previous month
    months = _months_back(today, 2 if by_date else 4)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    added = 0
    for ym in months:
        try:
            r = s.get(FILE_URL.format(ym=ym), timeout=30, allow_redirects=False)
            if r.status_code != 200:
                logger.info("TAIWAN VIX %s: HTTP %s (not published yet?)", ym, r.status_code)
                continue
            text = r.content.decode("big5", errors="replace")
            for row in parse_month_file(text):
                if by_date.get(row["date"]) != row:
                    by_date[row["date"]] = row
                    added += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("TAIWAN VIX %s failed: %s", ym, exc)
    if not by_date:
        return None
    rows = sorted(by_date.values(), key=lambda r: r["date"])
    data = {
        "name": "臺指選擇權波動率指數（TAIWAN VIX）",
        "publisher": "臺灣期貨交易所",
        "method": "依 CBOE VIX 編製公式，以臺指選擇權（TXO）近月、次近月價格計算之未來 30 日年化預期波動率",
        "source": SOURCE_PAGE,
        "updated_at": now_taipei_iso(),
        "rows": [{k: r[k] for k in ("date", "close", "close_1m_avg")} for r in rows],
    }
    if added or not path.is_file():
        write_json(path, data)
        logger.info("TAIWAN VIX: %d rows (+%d), latest %s %.2f", len(rows), added, rows[-1]["date"], rows[-1]["close"])
    return data


def level_of(v: float) -> str:
    if v >= HIGH_FEAR:
        return "high"
    if v >= ELEVATED:
        return "elevated"
    if v <= LOW_FEAR:
        return "low"
    return "normal"


LEVEL_LABEL = {"high": "高度恐慌", "elevated": "警戒", "normal": "正常", "low": "低恐慌／偏樂觀"}


def _svg(rows: list[dict[str, Any]], w: int = 760, h: int = 220) -> str:
    if len(rows) < 2:
        return ""
    vals = [r["close"] for r in rows]
    lo = min(min(vals), LOW_FEAR) - 2
    hi = max(max(vals), HIGH_FEAR) + 2
    pad_l, pad_r, pad_t, pad_b = 36, 10, 10, 22
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b

    def x(i: int) -> float:
        return pad_l + iw * i / (len(rows) - 1)

    def y(v: float) -> float:
        return pad_t + ih * (hi - v) / (hi - lo)

    parts = [f'<svg viewBox="0 0 {w} {h}" class="vix-svg" role="img" aria-label="TAIWAN VIX 走勢">']
    for thr, color, lab in ((HIGH_FEAR, "#dc2626", "30 高度恐慌"), (ELEVATED, "#f97316", "25 警戒"), (LOW_FEAR, "#2563eb", "18 低恐慌")):
        parts.append(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{y(thr):.1f}" y2="{y(thr):.1f}" stroke="{color}" stroke-dasharray="5 4" stroke-width="1"/>')
        parts.append(f'<text x="{w - pad_r - 2}" y="{y(thr) - 3:.1f}" text-anchor="end" font-size="11" fill="{color}">{lab}</text>')
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
    parts.append(f'<polyline points="{pts}" fill="none" stroke="#7c3aed" stroke-width="2"/>')
    for i, r in enumerate(rows):
        if i in (0, len(rows) - 1) or i % max(1, len(rows) // 6) == 0:
            parts.append(f'<text x="{x(i):.1f}" y="{h - 6}" text-anchor="middle" font-size="10" fill="#64748b">{r["date"][5:]}</text>')
    for v in (lo + 2, (lo + hi) / 2, hi - 2):
        parts.append(f'<text x="{pad_l - 4}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="10" fill="#64748b">{v:.0f}</text>')
    lx, ly = x(len(vals) - 1), y(vals[-1])
    parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" fill="#7c3aed"/>')
    parts.append("</svg>")
    return "".join(parts)


def build_vix_view(root: Path, recent: int = 10, full: int = 60) -> dict[str, Any] | None:
    path = vix_path(root)
    if not path.is_file():
        return None
    rows = read_json(path).get("rows") or []
    if not rows:
        return None
    prev = None
    for r in rows:
        r["change"] = round(r["close"] - prev["close"], 2) if prev else None
        r["change_pct"] = round((r["close"] / prev["close"] - 1) * 100, 1) if prev else None
        r["level"] = level_of(r["close"])
        r["level_label"] = LEVEL_LABEL[r["level"]]
        prev = r
    window = rows[-full:]
    vals = [r["close"] for r in window]
    latest = rows[-1]
    pct_rank = round(sum(1 for v in vals if v <= latest["close"]) / len(vals) * 100)
    return {
        "latest": latest,
        "recent": list(reversed(rows[-recent:])),
        "full": list(reversed(window)),
        "stats": {
            "days": len(window),
            "from": window[0]["date"],
            "max": max(vals),
            "min": min(vals),
            "avg": round(sum(vals) / len(vals), 2),
            "pct_rank": pct_rank,
        },
        "svg": _svg(window),
        "thresholds": {"high": HIGH_FEAR, "elevated": ELEVATED, "low": LOW_FEAR},
        "source_page": SOURCE_PAGE,
    }
