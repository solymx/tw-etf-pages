"""ETF futures positions (統一 ezmoney): enrichment + day-over-day view.

Futures live in snapshot["futures"] (never in "holdings"), so the stock
change pipeline is untouched. Snapshots archived before this feature have no
"futures" key; deltas only start once two consecutive snapshots carry it.
"""

from __future__ import annotations

import html as _html
import json
import logging
import re
from pathlib import Path
from typing import Any

from .utils import read_json

logger = logging.getLogger(__name__)

UNI_INFO = "https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode={fund_code}"
POSITION_LABEL = {"B": "多單", "S": "空單"}


def parse_uni_data_asset(page_html: str) -> list[dict[str, Any]]:
    """Extract futures details from ezmoney Info page `#DataAsset` JSON."""
    m = re.search(r'id="DataAsset"\s+data-content="([^"]*)"', page_html)
    if not m:
        return []
    try:
        data = json.loads(_html.unescape(m.group(1)))
    except ValueError:
        return []
    out: list[dict[str, Any]] = []
    for a in data or []:
        if a.get("AssetCode") != "GD":
            continue
        for d in a.get("Details") or []:
            out.append(
                {
                    "code": str(d.get("DetailCode") or "").strip(),
                    "month": str(d.get("MTH") or "").strip(),
                    "position": str(d.get("Position") or "").strip().upper(),
                    "contracts": d.get("Share"),
                    "notional": d.get("Amount"),
                    "currency": d.get("MoneyType"),
                    "tran_date": (d.get("TranDate") or "")[:10],
                }
            )
    return out


def enrich_uni_futures(snapshot: dict[str, Any], session: Any, fund_code: str, timeout: float = 30) -> None:
    """Best effort: fill 多/空 + notional per contract from the Info page."""
    if not snapshot.get("futures"):
        return
    try:
        resp = session.get(UNI_INFO.format(fund_code=fund_code), timeout=timeout)
        details = parse_uni_data_asset(resp.text) if resp.status_code == 200 else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("uni futures enrichment failed for %s: %s", fund_code, exc)
        return
    for f in snapshot["futures"]:
        for d in details:
            if d["code"] == f["code"] and d["month"] == f["month"] and d["tran_date"] == snapshot["as_of_date"]:
                if d["position"] in POSITION_LABEL:
                    f["position"] = d["position"]
                    f["position_source"] = "ezmoney_page"
                if d.get("notional") is not None:
                    f["notional"] = float(d["notional"])
                    f["currency"] = d.get("currency") or "NTD"
                break


def _agg(futures: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for f in futures or []:
        key = (f.get("code", ""), f.get("position", "B"))
        a = out.setdefault(
            key, {"code": key[0], "name": f.get("name", ""), "position": key[1], "contracts": 0, "weight_pct": 0.0, "months": []}
        )
        a["contracts"] += int(f.get("contracts") or 0)
        a["weight_pct"] = round(a["weight_pct"] + float(f.get("weight_pct") or 0), 4)
        if f.get("month") and f["month"] not in a["months"]:
            a["months"].append(f["month"])
    return out


def _status(prev: dict | None, curr: dict | None) -> tuple[str, str]:
    if prev is None and curr is not None:
        return "new", "新建倉"
    if curr is None and prev is not None:
        return "closed", "平倉"
    d = curr["contracts"] - prev["contracts"]
    if d > 0:
        return "up", "加碼"
    if d < 0:
        return "down", "減碼"
    if curr["months"] != prev["months"]:
        return "roll", "轉倉"
    return "flat", "持平"


def build_futures_view(snapshots_dir: Path, ticker: str, history: int = 10) -> dict[str, Any] | None:
    d = snapshots_dir / ticker
    if not d.is_dir():
        return None
    snaps = []
    for p in sorted(d.glob("*.json")):
        s = read_json(p)
        if "futures" in s:
            snaps.append(s)
    if not snaps:
        return None
    curr = snaps[-1]
    prev = snaps[-2] if len(snaps) >= 2 else None
    ca = _agg(curr["futures"])
    pa = _agg(prev["futures"]) if prev else {}
    rows = []
    for key in sorted(set(ca) | set(pa)):
        c, p = ca.get(key), pa.get(key)
        base = c or p
        row = {
            "code": base["code"],
            "name": base["name"],
            "position": base["position"],
            "position_label": POSITION_LABEL.get(base["position"], base["position"]),
            "contracts": c["contracts"] if c else 0,
            "weight_pct": c["weight_pct"] if c else 0.0,
            "months": "／".join(c["months"]) if c else "—",
            "prev_contracts": p["contracts"] if p else None,
            "prev_weight_pct": p["weight_pct"] if p else None,
            "prev_months": "／".join(p["months"]) if p else None,
        }
        if prev is not None:
            row["delta_contracts"] = row["contracts"] - (row["prev_contracts"] or 0)
            row["delta_weight"] = round(row["weight_pct"] - (row["prev_weight_pct"] or 0), 4)
            row["status"], row["status_label"] = _status(p, c)
        else:
            row["delta_contracts"] = None
            row["delta_weight"] = None
            row["status"], row["status_label"] = "base", "基準日"
        rows.append(row)
    # notional (TWD) for each current contract, if enriched
    notional = sum(float(f.get("notional") or 0) for f in curr["futures"]) or (
        (curr.get("assets") or {}).get("futures_notional", {}).get("amount")
    )
    assets = curr.get("assets") or {}
    hist = []
    for s in snaps[-history:][::-1]:
        a = _agg(s["futures"])
        hist.append(
            {
                "date": s["as_of_date"],
                "items": [
                    {"code": v["code"], "position_label": POSITION_LABEL.get(v["position"], v["position"]),
                     "contracts": v["contracts"], "weight_pct": v["weight_pct"], "months": "／".join(v["months"])}
                    for v in a.values()
                ],
                "weight_total": round(sum(v["weight_pct"] for v in a.values()), 4),
            }
        )
    return {
        "as_of_date": curr["as_of_date"],
        "prev_as_of_date": prev["as_of_date"] if prev else None,
        "rows": rows,
        "has_position": bool(ca),
        "notional": notional,
        "weight_total": round(sum(v["weight_pct"] for v in ca.values()), 4),
        "margin": assets.get("futures_margin"),
        "cash": assets.get("cash"),
        "stocks": assets.get("stocks"),
        "history": hist,
        "tracked_since": snaps[0]["as_of_date"],
    }
