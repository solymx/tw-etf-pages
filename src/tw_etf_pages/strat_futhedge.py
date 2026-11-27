"""策略 14：小台／微台 Beta 避險口數（避險工具，不是買賣訊號）。

近月 MTX／TMF 結算價、保證金：期交所 OpenAPI（當日），每天存快照與序列。
Beta：60／250 日 OLS，Rs＝加權指數報酬、Rf＝近月 MTX 結算價報酬；序列不足時顯示資料累積中，試算器可自填 beta。
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .strategy_common import any_to_date, http_json, num, session, strategy_dir, third_wednesday, today_tw
from .strat_daily_compact import write_compact
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

FUT_URL = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
MARGIN_URL = "https://openapi.taifex.com.tw/v1/IndexFuturesAndOptionsMargining"
SETTLE_URL = "https://openapi.taifex.com.tw/v1/FinalSettlementPriceIndexFutures"
# 官方乘數
MULT = {"MTX": 50, "TMF": 10}
# 偏避險：空單約理論口數 80–120%（經驗值）
HEDGE_LO, HEDGE_HI = 0.80, 1.20
# beta 不穩定（自算）：兩窗相差 ≥ 0.20，或相對差距 ≥ 25%
BETA_ABS, BETA_REL = 0.20, 0.25


def hedge_dir(root: Path) -> Path:
    return strategy_dir(root) / "futhedge"


def is_monthly(code: str) -> bool:
    t = (code or "").strip()
    return bool(t) and "/" not in t and "W" not in t and "F" not in t and t.isdigit() and len(t) == 6


def parse_fut(rows: list[dict[str, Any]]) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """Regular-session MTX/TMF monthly (no spreads) → (date, {(contract, month): fields})."""
    out: dict[str, dict[str, Any]] = {}
    d = None
    for r in rows or []:
        c = r.get("Contract")
        if c not in MULT or r.get("TradingSession") != "一般":
            continue
        month = (r.get("ContractMonth(Week)") or r.get("ContractMonth") or "").strip()
        if not is_monthly(month):
            continue
        d = d or any_to_date(r["Date"]).isoformat()
        out[f"{c}:{month}"] = {
            "contract": c, "month": month,
            "settle": num(r.get("SettlementPrice")), "last": num(r.get("Last")),
            "volume": num(r.get("Volume")), "oi": num(r.get("OpenInterest")),
        }
    return d, out


def parse_margins(rows: list[dict[str, Any]]) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """Map 小型臺指 → MTX, 微型臺指期貨 → TMF (official names)."""
    key = {"小型臺指": "MTX", "微型臺指期貨": "TMF"}
    out: dict[str, dict[str, Any]] = {}
    d = None
    for r in rows or []:
        c = key.get((r.get("Contract") or "").strip())
        if not c:
            continue
        d = d or any_to_date(r["Date"]).isoformat()
        out[c] = {"initial": num(r.get("InitialMargin")), "maint": num(r.get("MaintenanceMargin")),
                  "clearing": num(r.get("ClearingMargin")), "name": r.get("Contract")}
    return d, out


def front_month(d: str, items: dict[str, dict[str, Any]], contract: str) -> dict[str, Any] | None:
    day = date.fromisoformat(d)
    best = None
    for v in items.values():
        if v["contract"] != contract:
            continue
        y, m = int(v["month"][:4]), int(v["month"][4:6])
        exp = third_wednesday(y, m)
        if exp <= day:
            continue
        if best is None or exp < best[0]:
            best = (exp, v)
    return {**best[1], "expiry": best[0].isoformat()} if best else None


def adjust_expiry(exp: date, closed: set[str]) -> tuple[date, bool]:
    d, adj = exp, False
    while d.isoformat() in closed or d.weekday() >= 5:
        d -= timedelta(days=1)
        adj = True
    return d, adj


def ols_beta(rs: list[float], rf: list[float]) -> float | None:
    n = len(rs)
    if n < 20 or n != len(rf):
        return None
    ms, mf = sum(rs) / n, sum(rf) / n
    var = sum((x - mf) ** 2 for x in rf)
    if var <= 0:
        return None
    cov = sum((a - ms) * (b - mf) for a, b in zip(rs, rf))
    return cov / var


def beta_unstable(b60: float | None, b250: float | None) -> bool:
    if b60 is None or b250 is None:
        return False
    if abs(b60 - b250) >= BETA_ABS:
        return True
    scale = max(abs(b250), 0.1)
    return abs(b60 - b250) / scale >= BETA_REL


def contracts_needed(beta: float, value: float, settle: float, mult: int) -> dict[str, float] | None:
    notion = settle * mult
    if notion <= 0:
        return None
    n = beta * value / notion
    n_int = int(math.floor(n + 0.5))  # 四捨五入（.5 進位）
    residual = beta * value - n_int * notion
    return {"n": n, "n_int": n_int, "residual": residual, "notional": notion}


def position_read(ratio: float | None) -> dict[str, str]:
    """ratio = 空單口數 / 理論口數. None or 0 → 未避險."""
    if ratio is None or ratio == 0:
        return {"text": "中性／未避險", "cls": "neutral"}
    if HEDGE_LO <= ratio <= HEDGE_HI:
        return {"text": "偏避險", "cls": "neutral"}
    if ratio > HEDGE_HI:
        return {"text": "偏空（淨空）", "cls": "bear"}
    return {"text": "偏多（避險不足）", "cls": "bull"}


def _closed(root: Path) -> set[str]:
    p = strategy_dir(root) / "closed_days.json"
    return set((read_json(p).get("closed") or []) if p.is_file() else [])


def _taiex_map(root: Path) -> dict[str, float]:
    p = strategy_dir(root) / "taiex" / "ohlc.json"
    if not p.is_file():
        p2 = root / "data" / "taiex" / "kd.json"
        rows = read_json(p2).get("rows") or [] if p2.is_file() else []
    else:
        rows = read_json(p).get("rows") or []
    return {r["date"]: r["close"] for r in rows}


def update_futhedge(root: Path) -> dict[str, Any]:
    od = hedge_dir(root)
    status: dict[str, Any] = {"checked_at": now_taipei_iso(), "ok": False, "error": None}
    sess = session()
    try:
        raw = http_json(sess, FUT_URL, tries=2, timeout=120)
        if not isinstance(raw, list):
            raise RuntimeError(f"unexpected payload {type(raw).__name__}")
        d, items = parse_fut(raw)
        if not d or not items:
            raise RuntimeError(f"no MTX/TMF monthly rows (got {len(raw)} rows)")
        md, margins = parse_margins(http_json(sess, MARGIN_URL, tries=2, timeout=60) or [])
        snap = {"date": d, "source": FUT_URL, "fetched_at": now_taipei_iso(),
                "items": items, "margins": margins, "margin_date": md}
        write_compact(od / f"{d}.json", snap)
        # append series for beta
        series_p = od / "series.json"
        series = read_json(series_p) if series_p.is_file() else {"rows": []}
        by = {r["date"]: r for r in series.get("rows") or []}
        tmap = _taiex_map(root)
        front = {c: front_month(d, items, c) for c in ("MTX", "TMF")}
        row = {"date": d, "taiex": tmap.get(d),
               "mtx": (front["MTX"] or {}).get("settle"), "tmf": (front["TMF"] or {}).get("settle"),
               "mtx_month": (front["MTX"] or {}).get("month"), "tmf_month": (front["TMF"] or {}).get("month")}
        if by.get(d) != row:
            by[d] = row
            write_json(series_p, {"source": FUT_URL, "updated_at": now_taipei_iso(),
                                  "rows": sorted(by.values(), key=lambda r: r["date"])})
        status.update(ok=True, date=d, n=len(items), margin_ok=bool(margins))
        logger.info("futhedge: TAIFEX openapi OK, %s, %d monthly rows", d, len(items))
    except Exception as exc:  # noqa: BLE001
        status["error"] = str(exc)[:300]
        logger.warning("futhedge: DailyMarketReportFut failed: %s", exc)
    try:
        st = read_json(od / "final_settlement.json") if (od / "final_settlement.json").is_file() else {"rows": []}
        bys = {(r["month"], r.get("date")): r for r in st["rows"]}
        for r in http_json(sess, SETTLE_URL, tries=2, timeout=60) or []:
            if "TX" in str(r.get("Contract") or "") or "MTX" in str(r.get("Contract") or ""):
                rec = {"month": r.get("ContractDeliveryMonth"),
                       "date": any_to_date(r["TheFinalSettlementDay"]).isoformat(),
                       "price": num(r.get("TheFinalSettlementPrice"))}
                bys[(rec["month"], rec["date"])] = rec
        write_json(od / "final_settlement.json", {"source": SETTLE_URL, "rows": list(bys.values())})
    except Exception as exc:  # noqa: BLE001
        logger.warning("futhedge: FinalSettlementPriceIndexFutures failed: %s", exc)
    write_json(od / "status.json", status)
    return status


def _betas(series: list[dict[str, Any]]) -> dict[str, Any]:
    """OLS of TAIEX returns on MTX settlement returns, 60 and 250 windows."""
    pts = [r for r in series if r.get("taiex") and r.get("mtx")]
    rets_s, rets_f = [], []
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        if a["taiex"] and a["mtx"] and a["taiex"] > 0 and a["mtx"] > 0:
            rets_s.append(b["taiex"] / a["taiex"] - 1)
            rets_f.append(b["mtx"] / a["mtx"] - 1)
    out = {"n": len(rets_s), "b60": None, "b250": None, "unstable": False}
    if len(rets_s) >= 60:
        out["b60"] = ols_beta(rets_s[-60:], rets_f[-60:])
    if len(rets_s) >= 250:
        out["b250"] = ols_beta(rets_s[-250:], rets_f[-250:])
    out["unstable"] = beta_unstable(out["b60"], out["b250"])
    return out


def build_futhedge_view(root: Path) -> dict[str, Any] | None:
    od = hedge_dir(root)
    status = read_json(od / "status.json") if (od / "status.json").is_file() else {}
    snaps = sorted(od.glob("????-??-??.json")) if od.is_dir() else []
    tmap = _taiex_map(root)
    taiex_date = max(tmap) if tmap else None
    view: dict[str, Any] = {"status": status, "snap_date": None, "date": taiex_date,
                            "taiex": tmap.get(taiex_date) if taiex_date else None,
                            "stale": not status.get("ok"), "contracts": [], "beta": {"n": 0},
                            "label": position_read(0), "closed_note": None}
    if snaps:
        snap = read_json(snaps[-1])
        d = snap["date"]
        view["snap_date"] = d
        view["date"] = d  # 以期貨資料日為準
        view["taiex"] = tmap.get(d)
        view["taiex_latest_date"] = taiex_date
        view["taiex_latest"] = tmap.get(taiex_date) if taiex_date else None
        closed = _closed(root)
        for c, name in (("MTX", "小型臺指期貨（小台）"), ("TMF", "微型臺指期貨（微台）")):
            f = front_month(d, snap["items"], c)
            if not f or f.get("settle") is None:
                continue
            y, m = int(f["month"][:4]), int(f["month"][4:6])
            raw_exp = date.fromisoformat(f["expiry"])
            exp, adj = adjust_expiry(raw_exp, closed)
            mg = (snap.get("margins") or {}).get(c) or {}
            notion = f["settle"] * MULT[c]
            view["contracts"].append({
                "id": c, "name": name, "month": f["month"], "settle": f["settle"],
                "volume": f.get("volume"), "oi": f.get("oi"), "notional": notion,
                "mult": MULT[c], "expiry": exp.isoformat(), "expiry_raw": raw_exp.isoformat(),
                "expiry_adj": adj, "days": (exp - date.fromisoformat(d)).days,
                "initial": mg.get("initial"), "maint": mg.get("maint"),
                "margin_date": snap.get("margin_date"), "margin_name": mg.get("name"),
            })
        view["closed_note"] = "到期日若碰上本站休市日表中的日期，會往前調整到前一個營業日；休市日表可能不完整，以期交所公告為準。"
        series = (read_json(od / "series.json").get("rows") if (od / "series.json").is_file() else []) or []
        view["beta"] = _betas(series)
        view["n_snaps"] = len(snaps)
    b = view["beta"]
    bits = []
    if view["contracts"]:
        mtx = next((c for c in view["contracts"] if c["id"] == "MTX"), view["contracts"][0])
        bits.append(f"近月 {mtx['id']} {mtx['month']} 結算價 {mtx['settle']:,.0f}（一口名目約 {mtx['notional']:,.0f} 元）")
        if mtx.get("initial"):
            bits.append(f"原始／維持保證金 {mtx['initial']:,.0f}／{mtx['maint']:,.0f} 元")
    if b.get("b60") is not None:
        bits.append(f"60 日 beta {b['b60']:.2f}" + (f"、250 日 {b['b250']:.2f}" if b.get("b250") is not None else "（250 日資料累積中）"))
        if b["unstable"]:
            bits.append("兩窗差較大，標示 beta 不穩定（自算）")
    else:
        bits.append(f"beta 序列目前 {b.get('n', 0)} 個報酬日，60／250 日窗資料累積中")
    bits.append("本頁是避險工具，未輸入部位時視為空單 0（中性／未避險）。")
    if view["stale"] and view["snap_date"]:
        bits.append(f"期交所本次抓取失敗，沿用 {view['snap_date']} 快照。")
    view["reason"] = "；".join(bits)
    view["label"] = position_read(0)
    return view
