"""策略 13：賣方風險燈號（臺指選擇權 TXO）。

期交所 OpenAPI 只給「最近一個交易日」→ 每日存快照 data/strategy/options/{date}.json（只存最近 2 個週選＋2 個月選）。
燈號依「震盪盤判定器」盤型＋臺指 VIX 是否穩定（經驗值／自算）。抓不到時沿用最後一份快照並標示日期。
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .strategy_common import any_to_date, http_json, num, session, strategy_dir, today_tw
from .strat_daily_compact import write_compact
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

OPT_URL = "https://openapi.taifex.com.tw/v1/DailyMarketReportOpt"
SETTLE_URL = "https://openapi.taifex.com.tw/v1/FinalSettlementPriceIndexOptions"
MULT = 50
OTM = (5, 10)
# VIX 穩定（自算）：低於 25 警戒線、不高於近 20 日平均的 1.1 倍、5 日內上升不超過 2 點
VIX_CAP, VIX_AVG_MULT, VIX_RISE5 = 25.0, 1.10, 2.0


def opt_dir(root: Path) -> Path:
    return strategy_dir(root) / "options"


def expiry_of(code: str) -> tuple[date, str] | None:
    """'202612W1' → (1st Wed, 'weekly'); '202611F4' → (4th Fri, 'weekly'); '202612' → (3rd Wed, 'monthly')."""
    m = re.fullmatch(r"(\d{4})(\d{2})(?:([WF])(\d))?", code.strip())
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    kind, nth = m.group(3) or "W", int(m.group(4) or 3)
    wd = 2 if kind == "W" else 4
    d = date(y, mo, 1)
    first = d + timedelta(days=(wd - d.weekday()) % 7)
    exp = first + timedelta(days=7 * (nth - 1))
    if exp.month != mo:
        return None
    return exp, ("weekly" if m.group(3) else "monthly")


def parse_opt(rows: list[dict[str, Any]]) -> tuple[str | None, dict[str, list[list]]]:
    """TXO regular-session rows → (date, {contract: [[strike, 'C'/'P', close, settle, oi, vol], ...]})."""
    out: dict[str, list[list]] = {}
    d = None
    for r in rows or []:
        if r.get("Contract") != "TXO" or r.get("TradingSession") != "一般":
            continue
        cp = {"買權": "C", "賣權": "P"}.get(r.get("CallPut"))
        k = num(r.get("StrikePrice"))
        if cp is None or k is None:
            continue
        d = d or any_to_date(r["Date"]).isoformat()
        out.setdefault(r["ContractMonth(Week)"].strip(), []).append(
            [k, cp, num(r.get("Close")), num(r.get("SettlementPrice")), num(r.get("OpenInterest")), num(r.get("Volume"))])
    return d, out


def pick_contracts(d: str, contracts: dict[str, list]) -> dict[str, str]:
    day = date.fromisoformat(d)
    best: dict[str, tuple[date, str]] = {}
    for code in contracts:
        e = expiry_of(code)
        if not e or e[0] <= day:
            continue
        if e[1] not in best or e[0] < best[e[1]][0]:
            best[e[1]] = (e[0], code)
    return {k: v[1] for k, v in best.items()}


def _keep(d: str, contracts: dict[str, list]) -> dict[str, list]:
    day = date.fromisoformat(d)
    live = sorted(((expiry_of(c), c) for c in contracts if expiry_of(c) and expiry_of(c)[0] > day))
    keep = [c for _, c in [x for x in live if x[0][1] == "weekly"][:2] + [x for x in live if x[0][1] == "monthly"][:2]]
    # drop dead strikes (no OI, no volume) to keep daily snapshots small
    return {c: [r for r in contracts[c] if (r[4] or 0) > 0 or (r[5] or 0) > 0] for c in keep}


def update_options(root: Path) -> dict[str, Any]:
    od = opt_dir(root)
    status: dict[str, Any] = {"checked_at": now_taipei_iso(), "ok": False, "error": None}
    sess = session()
    try:
        raw = http_json(sess, OPT_URL, tries=2, timeout=120)
        if not isinstance(raw, list):
            raise RuntimeError(f"unexpected payload {type(raw).__name__}")
        d, contracts = parse_opt(raw)
        if not d or not contracts:
            raise RuntimeError(f"no TXO rows (got {len(raw)} rows)")
        write_compact(od / f"{d}.json", {"date": d, "source": OPT_URL, "fetched_at": now_taipei_iso(),
                                       "contracts": _keep(d, contracts)})
        status.update(ok=True, date=d, n_contracts=len(contracts))
        logger.info("options: TAIFEX openapi OK, %s, %d TXO contracts", d, len(contracts))
    except Exception as exc:  # noqa: BLE001 — e.g. HTML/blocked from CI runners
        status["error"] = str(exc)[:300]
        logger.warning("options: TAIFEX openapi DailyMarketReportOpt failed: %s", exc)
    try:
        st = read_json(od / "final_settlement.json") if (od / "final_settlement.json").is_file() else {"rows": []}
        by = {(r["contract"], r["month"]): r for r in st["rows"]}
        for r in http_json(sess, SETTLE_URL, tries=2, timeout=60) or []:
            if r.get("Contract") == "TXO":
                by[("TXO", r["ContractDeliveryMonth"])] = {
                    "contract": "TXO", "month": r["ContractDeliveryMonth"],
                    "date": any_to_date(r["TheFinalSettlementDay"]).isoformat(),
                    "price": num(r.get("TheFinalSettlementPrice"))}
        write_json(od / "final_settlement.json", {"source": SETTLE_URL,
                                                  "rows": sorted(by.values(), key=lambda r: r["date"])})
        status["settle_ok"] = True
    except Exception as exc:  # noqa: BLE001
        status["settle_error"] = str(exc)[:300]
        logger.warning("options: TAIFEX openapi FinalSettlementPriceIndexOptions failed: %s", exc)
    write_json(od / "status.json", status)
    return status


def strike_table(rows: list[list], spot: float) -> list[dict[str, Any]]:
    out = []
    for cp, sign in (("P", -1), ("C", 1)):
        side = {r[0]: r for r in rows if r[1] == cp}
        if not side:
            continue
        for pct in OTM:
            target = spot * (1 + sign * pct / 100)
            k = min(side, key=lambda s: (abs(s - target), -sign * s))
            r = side[k]
            out.append({"cp": "賣權 Put" if cp == "P" else "買權 Call", "pct": pct, "target": target, "strike": k,
                        "otm": (k / spot - 1) * 100, "close": r[2], "settle": r[3],
                        "twd": r[3] * MULT if r[3] is not None else None, "oi": r[4], "vol": r[5]})
    return out


def vix_stable(vix: list[dict[str, Any]]) -> tuple[bool | None, str]:
    if len(vix) < 21:
        return None, "VIX 資料不足"
    last = vix[-1]["close"]
    avg20 = sum(r["close"] for r in vix[-20:]) / 20
    rise5 = last - vix[-6]["close"]
    ok = last < VIX_CAP and last <= avg20 * VIX_AVG_MULT and rise5 <= VIX_RISE5
    return ok, (f"VIX {last:.2f}（{vix[-1]['date']}），近 20 日平均 {avg20:.2f}，5 日變化 {rise5:+.2f}；"
                f"{'穩定' if ok else '不穩定'}（穩定＝<25、≤20 日均 ×1.1、5 日升幅 ≤2 點，自算）")


def light(regime: str | None, stable: bool | None) -> dict[str, Any]:
    if regime == "低波動盤整" and stable:
        return {"color": "green", "text": "綠（中性）", "cls": "neutral",
                "advice": "盤整且 VIX 穩定，才可以考慮「有限風險價差」（買了保護的賣方價差），不是裸賣。"}
    if regime == "低波動盤整":
        return {"color": "yellow", "text": "黃（觀望）", "cls": "warn",
                "advice": "雖然是低波動盤整，但 VIX 不穩定，先觀望。"}
    if regime == "高波動動盪":
        return {"color": "red", "text": "紅（偏空，不碰賣方）", "cls": "bear",
                "advice": "高波動動盪：單日大漲大跌常見，賣方最容易被一根長 K 打爆，不碰賣方。"}
    if regime == "趨勢盤":
        return {"color": "red", "text": "紅（不碰賣方）", "cls": "bear",
                "advice": "趨勢盤：行情可能一路走，賣方逆勢那一邊虧損會持續擴大，不碰賣方。"}
    if regime == "過渡":
        return {"color": "yellow", "text": "黃（觀望）", "cls": "warn", "advice": "過渡盤型，訊號不明確，先觀望。"}
    return {"color": "gray", "text": "資料暫缺", "cls": "na", "advice": "盤型資料暫缺。"}


def build_options_view(root: Path) -> dict[str, Any] | None:
    from .strat_regime import build_regime_view, _load_vix
    od = opt_dir(root)
    status = read_json(od / "status.json") if (od / "status.json").is_file() else {}
    snaps = sorted(p for p in od.glob("????-??-??.json")) if od.is_dir() else []
    rg = build_regime_view(root)
    vix = _load_vix(root)
    stable, vtxt = vix_stable(vix)
    lt = light(rg["regime"] if rg else None, stable)
    regime_txt = rg["label"]["text"] if rg else "資料暫缺"
    view: dict[str, Any] = {"light": lt, "label": {"text": lt["text"], "cls": lt["cls"]}, "regime": regime_txt,
                            "vix_txt": vtxt, "vix_stable": stable, "status": status, "snap_date": None,
                            "blocks": [], "n_snaps": len(snaps), "date": None}
    if snaps:
        snap = read_json(snaps[-1])
        d = snap["date"]
        view["snap_date"] = view["date"] = d
        spot, spot_date = None, None
        ohlc = strategy_dir(root) / "taiex" / "ohlc.json"
        if ohlc.is_file():
            rows = read_json(ohlc).get("rows") or []
            same = [r for r in rows if r["date"] <= d]
            if same:
                spot, spot_date = same[-1]["close"], same[-1]["date"]
        view["spot"], view["spot_date"] = spot, spot_date
        picks = pick_contracts(d, snap["contracts"])
        for kind, name in (("weekly", "最近週選"), ("monthly", "最近月選")):
            code = picks.get(kind)
            if not code or spot is None:
                continue
            exp = expiry_of(code)[0]
            view["blocks"].append({"name": name, "code": code, "expiry": exp.isoformat(),
                                   "days": (exp - date.fromisoformat(d)).days,
                                   "rows": strike_table(snap["contracts"][code], spot)})
    stale = bool(view["snap_date"]) and not status.get("ok")
    view["stale"] = stale
    view["reason"] = (f"盤型「{regime_txt}」；{vtxt.split('；')[0]}，{'穩定' if stable else '不穩定' if stable is not None else '資料不足'} → {lt['text']}。"
                      + (f"期交所資料暫停更新，沿用 {view['snap_date']} 快照。" if stale else ""))
    return view
