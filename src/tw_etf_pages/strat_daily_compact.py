"""Compact JSON writer (no indentation) for large strategy archives."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_compact(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
