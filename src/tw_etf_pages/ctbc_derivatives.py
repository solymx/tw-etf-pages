"""中信投信 (CTBC) ETF 衍生性商品部位：選擇權（掩護性買權）＋期貨。

Source: the official CTBC ETF page「投資組合」tab
(https://www.ctbcinvestments.com/etfprod/<ticker>/pcf), which loads its table
from the site's own data service (anonymous session token, same as any
visitor's browser). We only persist what that table discloses:
商品代碼 / 買賣權 / 商品名稱 / 口數 / 契約年月 / 權重(%). Strike price is NOT
disclosed there, so it is never stored or guessed.

Stored separately under data/derivatives/<ticker>/<official date>.json so the
stock snapshot / change pipeline is untouched.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from .utils import now_taipei_iso, read_json, today_taipei, write_json

logger = logging.getLogger(__name__)

API = "https://www.ctbcinvestments.com.tw/API/"
PAGE = "https://www.ctbcinvestments.com/etfprod/{ticker}/pcf"
COVERED_CALL_CAP_PCT = 25.0  # 公開說明書：未沖銷賣出買權總名目價值 ≤ 淨資產 25%（上限，非實際）
BACKFILL_DAYS = 14
RIGHT_LABEL = {"C": "買權", "P": "賣權"}


def deriv_dir(root: Path, ticker: str) -> Path:
    return root / "data" / "derivatives" / ticker


def _num(s: Any) -> float | None:
    if s in (None, ""):
        return None
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


class CtbcClient:
    def __init__(self, timeout: float = 30) -> None:
        self.s = requests.Session()
        self.s.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (tw-etf-pages; +https://solymx.github.io/tw-etf-pages/)",
                "Origin": "https://www.ctbcinvestments.com",
                "Referer": "https://www.ctbcinvestments.com/",
            }
        )
        self.timeout = timeout
        self.token = ""

    def _post(self, ep: str, body: dict[str, Any]) -> Any:
        payload = {"token": self.token, **body}
        r = self.s.post(API + ep, params={"token": self.token}, json=payload, timeout=self.timeout)
        r.raise_for_status()
        j = r.json()
        if j.get("ResultCode") != 0:
            raise RuntimeError(f"CTBC {ep}: {j.get('ResultCode')} {j.get('ResultMsg')}")
        return j.get("Data")

    def auth(self) -> None:
        self.token = ""
        self.token = self._post("home/AuthToken", {})["token"]

    def fid_map(self) -> dict[str, str]:
        return {x["ETF_ID"]: x["FID"] for x in self._post("etf/ETFCNOList", {})["List"]}

    def holding_weight(self, fid: str, d: date) -> dict[str, Any]:
        return self._post("etf/ETFHoldingWeight", {"FID": fid, "StartDate": d.isoformat()})


def normalize(ticker: str, data: dict[str, Any]) -> dict[str, Any] | None:
    fa = (data.get("FundAssets") or [{}])[0]
    raw_date = fa.get("資料日期")
    if not raw_date:
        return None
    as_of = raw_date.replace("/", "-")
    groups = {g.get("Code"): g for g in data.get("FundAssetsDetail") or []}
    options = []
    for x in (groups.get("OPTION") or {}).get("Data") or []:
        qty = _num(x.get("qty_")) or 0.0
        right = (x.get("ename_") or "").strip().upper()
        options.append(
            {
                "code": (x.get("code_") or "").strip(),
                "name": (x.get("name_") or "").strip(),
                "right": right,  # C=買權 P=賣權
                "side": "sell" if qty < 0 else "buy",
                "contracts": int(abs(qty)),
                "month": (x.get("ym_") or "").strip(),
                "weight_pct": _num(x.get("weights_")),  # official, signed (negative = sold)
                "amount_raw": x.get("amount_"),  # API field not shown on the official page; kept raw, not interpreted
            }
        )
    futures = []
    for x in (groups.get("FUTURE") or {}).get("Data") or []:
        qty = _num(x.get("qty_")) or 0.0
        futures.append(
            {
                "code": (x.get("code_") or "").strip(),
                "name": (x.get("name_") or "").strip(),
                "side": "short" if qty < 0 else "long",
                "contracts": int(abs(qty)),
                "month": (x.get("ym_") or "").strip(),
                "weight_pct": _num(x.get("weights_")),
            }
        )
    other = {}
    for code in ("MARGIN", "CASH"):
        for x in (groups.get(code) or {}).get("Data") or []:
            other[x.get("invtp_") or code] = {"name": x.get("name_"), "amount": _num(x.get("amount_")), "weight_pct": _num(x.get("weights_"))}
    return {
        "etf_ticker": ticker,
        "as_of_date": as_of,
        "source": "ctbc_official_holding_weight",
        "source_page": PAGE.format(ticker=ticker),
        "fetched_at": now_taipei_iso(),
        "nav_total_raw": fa.get("基金淨資產"),
        "option_sum_pct": (groups.get("OPTION") or {}).get("Sum"),
        "future_sum_pct": (groups.get("FUTURE") or {}).get("Sum"),
        "stock_sum_pct": (groups.get("STOCK") or {}).get("Sum"),
        "options": options,
        "futures": futures,
        "other_assets": other,
    }


def update_ctbc_derivatives(
    root: Path,
    tickers: list[str],
    today: date | None = None,
    client: CtbcClient | None = None,
    pause: float = 2.0,
) -> dict[str, int]:
    today = today or today_taipei()
    client = client or CtbcClient()
    client.auth()
    fids = client.fid_map()
    written: dict[str, int] = {}
    for t in tickers:
        fid = fids.get(t)
        if not fid:
            logger.warning("CTBC: no FID for %s", t)
            continue
        d_dir = deriv_dir(root, t)
        have = sorted(p.stem for p in d_dir.glob("*.json")) if d_dir.is_dir() else []
        start = date.fromisoformat(have[-1]) + timedelta(days=1) if have else today - timedelta(days=BACKFILL_DAYS)
        n = 0
        d = start
        seen: set[str] = set(have)
        while d <= today:
            if d.weekday() < 5:
                time.sleep(pause)  # be gentle: one request per pause
                try:
                    snap = normalize(t, client.holding_weight(fid, d))
                except Exception as exc:  # noqa: BLE001
                    # Stop here so the next run resumes from this date (no silent gaps).
                    logger.warning("CTBC %s %s: %s — stop, resume next run", t, d, exc)
                    break
                if snap and snap["as_of_date"] == d.isoformat() and snap["as_of_date"] not in seen:
                    write_json(d_dir / f"{snap['as_of_date']}.json", snap)
                    seen.add(snap["as_of_date"])
                    n += 1
            d += timedelta(days=1)
        written[t] = n
        logger.info("CTBC derivatives %s: +%d day(s)", t, n)
    return written


def _key(o: dict[str, Any]) -> tuple:
    return (o["code"], o.get("right", ""), o["side"], o["month"])


def _status(p: dict | None, c: dict | None) -> tuple[str, str]:
    if p is None:
        return "new", "新建倉"
    if c is None:
        return "closed", "已無部位（到期／回補）"
    d = c["contracts"] - p["contracts"]
    if d > 0:
        return "up", "增加口數"
    if d < 0:
        return "down", "減少口數"
    return "flat", "口數持平"


def _rows(curr: list[dict], prev: list[dict] | None) -> list[dict[str, Any]]:
    ci = {_key(o): o for o in curr}
    pi = {_key(o): o for o in prev or []}
    out = []
    keys = list(ci) + [k for k in pi if k not in ci]
    for k in keys:
        c, p = ci.get(k), pi.get(k)
        b = c or p
        row = {
            **{f: b.get(f) for f in ("code", "name", "right", "side", "month")},
            "right_label": RIGHT_LABEL.get(b.get("right", ""), b.get("right", "")),
            "contracts": c["contracts"] if c else 0,
            "weight_pct": c.get("weight_pct") if c else None,
            "prev_contracts": p["contracts"] if p else None,
            "prev_weight_pct": p.get("weight_pct") if p else None,
        }
        if prev is None:
            row.update(delta_contracts=None, delta_weight=None, status="base", status_label="基準日")
        else:
            row["delta_contracts"] = row["contracts"] - (row["prev_contracts"] or 0)
            row["delta_weight"] = (
                round((row["weight_pct"] or 0) - (row["prev_weight_pct"] or 0), 2) if (c or p) else None
            )
            row["status"], row["status_label"] = _status(p, c)
        out.append(row)
    return out


def build_ctbc_derivatives_view(root: Path, ticker: str, history: int = 10) -> dict[str, Any] | None:
    d = deriv_dir(root, ticker)
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    if not files:
        return None
    snaps = [read_json(p) for p in files]
    if not any(s.get("options") or s.get("futures") for s in snaps):
        return None
    curr = snaps[-1]
    prev = snaps[-2] if len(snaps) >= 2 else None
    sold_calls = [o for o in curr["options"] if o["side"] == "sell" and o["right"] == "C"]
    hist = []
    for s in snaps[-history:][::-1]:
        hist.append(
            {
                "date": s["as_of_date"],
                "options": "；".join(
                    f"{'賣出' if o['side']=='sell' else '買進'}{RIGHT_LABEL.get(o['right'], o['right'])} {o['code']} {o['contracts']:,} 口（{o['month']}，{o['weight_pct']}%）"
                    for o in s["options"]
                ) or "無",
                "option_sum_pct": s.get("option_sum_pct"),
                "futures": "；".join(
                    f"{f['code']} {'多' if f['side']=='long' else '空'} {f['contracts']:,} 口（{f['weight_pct']}%）" for f in s["futures"]
                ) or "無",
            }
        )
    return {
        "as_of_date": curr["as_of_date"],
        "prev_as_of_date": prev["as_of_date"] if prev else None,
        "source_page": curr.get("source_page"),
        "option_rows": _rows(curr["options"], prev["options"] if prev else None),
        "future_rows": _rows(curr["futures"], prev["futures"] if prev else None),
        "option_sum_pct": curr.get("option_sum_pct"),
        "future_sum_pct": curr.get("future_sum_pct"),
        "stock_sum_pct": curr.get("stock_sum_pct"),
        "sold_call_contracts": sum(o["contracts"] for o in sold_calls),
        "has_covered_call": bool(sold_calls),
        "cap_pct": COVERED_CALL_CAP_PCT,
        "history": hist,
        "tracked_since": snaps[0]["as_of_date"],
        "days": len(snaps),
    }
