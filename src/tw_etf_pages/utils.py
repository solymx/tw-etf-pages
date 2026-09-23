"""Shared helpers: numbers, dates, JSON I/O."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TZ_TAIPEI = ZoneInfo("Asia/Taipei")

_COMMA_NUM = re.compile(r"[,\s]")


def parse_int(value: Any) -> int:
    """Parse shares / counts that may include commas or be numeric."""
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError(f"unexpected bool: {value}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    s = str(value).strip()
    if not s or s == "-":
        return 0
    s = _COMMA_NUM.sub("", s)
    s = s.replace("NTD", "").strip()
    return int(round(float(s)))


def parse_weight_pct(value: Any) -> float:
    """Parse weight like '10.05%' or 10.05 into float percent points."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("%", "")
    if not s:
        return 0.0
    return float(s)


def parse_roc_date(text: str) -> date:
    """Parse ROC date '115/09/22' → Gregorian date."""
    m = re.search(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", text)
    if not m:
        raise ValueError(f"cannot parse ROC date from: {text!r}")
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return date(y + 1911, mo, d)


def parse_iso_or_slash_date(text: str) -> date:
    """Parse 'YYYY/MM/DD' or 'YYYY-MM-DD' (optionally prefixed)."""
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if not m:
        raise ValueError(f"cannot parse date from: {text!r}")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def today_taipei() -> date:
    return datetime.now(TZ_TAIPEI).date()


def now_taipei_iso() -> str:
    return datetime.now(TZ_TAIPEI).isoformat(timespec="seconds")


def normalize_stock_code(code: Any) -> str:
    return str(code).strip().upper()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
