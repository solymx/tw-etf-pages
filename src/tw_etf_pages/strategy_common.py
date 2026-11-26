"""Shared helpers for the 4 strategy pages (月營收動能／高殖利率低波動／外資期貨＋P/C／借券賣出).

- Polite HTTP: per-host minimum spacing (TWSE rwd / MOPS ≥ 5 s) and retries.
- ROC ↔ AD date normalisation.
- Small statistics helpers and the 偏多／偏空／中性 label vocabulary.
"""

from __future__ import annotations

import logging
import math
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .utils import TZ_TAIPEI

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; tw-etf-pages/1.0; +https://solymx.github.io/tw-etf-pages/)"
DISCLAIMER = "不構成投資建議；判讀規則屬經驗法則，非研究保證。"
STOCK_CODE = re.compile(r"^[1-9]\d{3}$")  # 普通股 4 碼（排除 ETF 00xx、特別股 2881A、權證 6 碼）

# minimum seconds between requests to the same host
HOST_SPACING = {
    "www.twse.com.tw": 5.0,
    "mopsov.twse.com.tw": 5.0,
    "www.tpex.org.tw": 3.0,
    "www.taifex.com.tw": 3.0,
}
DEFAULT_SPACING = 1.0
_last_hit: dict[str, float] = {}


class NoData(Exception):
    """Source answered but has no data for that date (holiday / not yet published)."""


def strategy_dir(root: Path) -> Path:
    return root / "data" / "strategy"


def today_tw() -> date:
    return datetime.now(TZ_TAIPEI).date()


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*"})
    return s


def _wait(url: str) -> None:
    host = urlparse(url).netloc
    gap = HOST_SPACING.get(host, DEFAULT_SPACING)
    last = _last_hit.get(host)
    if last is not None:
        delta = time.monotonic() - last
        if delta < gap:
            time.sleep(gap - delta)
    _last_hit[host] = time.monotonic()


def http(sess: requests.Session, url: str, *, params: dict | None = None, data: dict | None = None,
         tries: int = 3, timeout: int = 90) -> requests.Response:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            _wait(url)
            if data is not None:
                r = sess.post(url, data=data, timeout=timeout)
            else:
                r = sess.get(url, params=params, timeout=timeout)
            if r.status_code in (301, 302, 307, 403, 429) or r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep((8, 25, 60)[min(attempt, 2)])
    raise RuntimeError(f"{url}: {last}")


def http_json(sess: requests.Session, url: str, **kw: Any) -> Any:
    return http(sess, url, **kw).json()


def num(v: Any) -> float | None:
    if v is None:
        return None
    t = re.sub(r"<[^>]+>", "", str(v)).replace(",", "").strip()
    if t in ("", "-", "--", "---", "N/A", "X"):
        return None
    try:
        f = float(t)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def roc_to_date(s: str) -> date:
    """'1151125' / '115/11/25' / '115年11月25日' → date."""
    t = str(s).strip()
    m = re.match(r"^(\d{2,3})[/年-]?(\d{1,2})[/月-]?(\d{1,2})日?$", t)
    if m and len(t) in (7, 6) and t.isdigit():
        return date(int(t[:-4]) + 1911, int(t[-4:-2]), int(t[-2:]))
    m = re.search(r"(\d{2,3})[/年](\d{1,2})[/月](\d{1,2})", t)
    if m:
        return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
    raise ValueError(f"not a ROC date: {s!r}")


def any_to_date(s: str) -> date:
    """Normalise ROC (1151125, 115/11/25) or AD (20261125, 2026/11/25, 2026-11-25) → date."""
    t = str(s).strip()
    if re.fullmatch(r"\d{8}", t):
        return date(int(t[:4]), int(t[4:6]), int(t[6:]))
    m = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", t)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return roc_to_date(t)


def roc_ym_to_iso(s: str) -> str:
    """'11510' → '2026-10'."""
    t = str(s).strip()
    return f"{int(t[:-2]) + 1911:04d}-{int(t[-2:]):02d}"


def weekdays_back(today: date, n_calendar: int):
    d = today
    for _ in range(n_calendar):
        if d.weekday() < 5:
            yield d
        d -= timedelta(days=1)


def percentile_rank(values: list[float], v: float) -> float:
    """Share (0–100) of values ≤ v."""
    if not values:
        return float("nan")
    return round(sum(1 for x in values if x <= v) / len(values) * 100, 1)


def median(vals: list[float]) -> float | None:
    s = sorted(vals)
    if not s:
        return None
    k = len(s) // 2
    return s[k] if len(s) % 2 else (s[k - 1] + s[k]) / 2


def stdev(vals: list[float]) -> float | None:
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - 1))


def third_wednesday(y: int, m: int) -> date:
    d = date(y, m, 1)
    first_wed = d + timedelta(days=(2 - d.weekday()) % 7)
    return first_wed + timedelta(days=14)


def label(kind: str) -> dict[str, str]:
    """kind: bull / bear / neutral → display label + css class."""
    return {
        "bull": {"text": "偏多", "cls": "bull"},
        "bear": {"text": "偏空", "cls": "bear"},
        "neutral": {"text": "中性", "cls": "neutral"},
        "na": {"text": "資料暫缺", "cls": "na"},
    }[kind]
