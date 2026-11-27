"""策略 16：買臺指賣權當保險（買方避險，不是賣方燈號）。"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from .strategy_common import strategy_dir
from .strat_options import MULT, expiry_of, opt_dir, pick_contracts
from .utils import read_json

logger = logging.getLogger(__name__)

# 價外 5%、10% 為經驗值／示例
OTM = (0, 5, 10)
# 流動性偏低（自算）：該檔成交量 < 100 口
LOW_VOL = 100


def _spot(root: Path, d: str) -> tuple[float | None, str | None]:
    ohlc = strategy_dir(root) / "taiex" / "ohlc.json"
    if not ohlc.is_file():
        return None, None
    rows = [r for r in (read_json(ohlc).get("rows") or []) if r["date"] <= d]
    return (rows[-1]["close"], rows[-1]["date"]) if rows else (None, None)


def pick_puts(rows: list[list], spot: float) -> list[dict[str, Any]]:
    """ATM / ~5% OTM / ~10% OTM puts among strikes that have volume (or OI as fallback)."""
    puts = [r for r in rows if r[1] == "P" and ((r[5] or 0) > 0 or (r[4] or 0) > 0)]
    live = [r for r in puts if (r[5] or 0) > 0] or puts
    if not live or not spot:
        return []
    by_k = {r[0]: r for r in live}
    out = []
    for pct in OTM:
        target = spot * (1 - pct / 100)
        k = min(by_k, key=lambda s: (abs(s - target), -s))  # closer, then higher strike
        r = by_k[k]
        prem = r[3] if r[3] is not None else r[2]  # settlement preferred, else close
        out.append({"pct": pct, "label": "價平" if pct == 0 else f"約價外 {pct}%",
                    "target": target, "strike": k, "otm": (k / spot - 1) * 100,
                    "close": r[2], "settle": r[3], "prem": prem,
                    "twd": prem * MULT if prem is not None else None,
                    "oi": r[4], "vol": r[5],
                    "low_liq": (r[5] or 0) < LOW_VOL})
    return out


def spread(buy: dict, sell: dict) -> dict[str, Any] | None:
    """買高履約、賣低履約；淨權利金與最大保護＝履約差 − 淨權利金。"""
    if buy["prem"] is None or sell["prem"] is None:
        return None
    if buy["strike"] <= sell["strike"]:
        return None
    net = buy["prem"] - sell["prem"]
    width = buy["strike"] - sell["strike"]
    return {"buy": buy, "sell": sell, "net": net, "net_twd": net * MULT,
            "width": width, "cap": width - net, "cap_twd": (width - net) * MULT}


def position_read(ratio: float | None) -> dict[str, str]:
    """ratio = 買入口數 / 理論口數."""
    if ratio is None or ratio == 0:
        return {"text": "無保護", "cls": "na"}
    if 0.8 <= ratio <= 1.2:
        return {"text": "中性偏防守", "cls": "neutral"}
    if ratio > 1.2:
        return {"text": "偏空", "cls": "bear"}
    return {"text": "保護不足", "cls": "warn"}


def build_put_view(root: Path) -> dict[str, Any] | None:
    from .taiwan_vix import vix_path
    od = opt_dir(root)
    status = read_json(od / "status.json") if (od / "status.json").is_file() else {}
    snaps = sorted(od.glob("????-??-??.json")) if od.is_dir() else []
    view: dict[str, Any] = {"status": status, "snap_date": None, "date": None, "blocks": [],
                            "label": position_read(0), "stale": not status.get("ok"),
                            "vix": None, "spot": None, "mult": MULT}
    if snaps:
        snap = read_json(snaps[-1])
        d = snap["date"]
        view["snap_date"] = view["date"] = d
        spot, spot_d = _spot(root, d)
        view["spot"], view["spot_date"] = spot, spot_d
        view["notional"] = spot * MULT if spot else None
        picks = pick_contracts(d, snap["contracts"])
        for kind, name in (("weekly", "最近週選"), ("monthly", "最近月選")):
            code = picks.get(kind)
            if not code or spot is None:
                continue
            exp = expiry_of(code)[0]
            puts = pick_puts(snap["contracts"][code], spot)
            if not puts:
                continue
            # 示例價差：買價平或 5% 賣權、賣更價外一檔
            spr = None
            if len(puts) >= 2:
                spr = spread(puts[0], puts[1])
                if spr is None and len(puts) > 2:
                    spr = spread(puts[1], puts[2])
            # 有成交量？
            has_vol = any((p["vol"] or 0) > 0 for p in puts)
            view["blocks"].append({"name": name, "code": code, "expiry": exp.isoformat(),
                                   "days": (exp - date.fromisoformat(d)).days,
                                   "puts": puts, "spread": spr, "has_vol": has_vol})
    vp = vix_path(root)
    if vp.is_file():
        rows = read_json(vp).get("rows") or []
        if rows:
            view["vix"] = rows[-1]
    # prefer a series that has volume, weekly first
    chosen = next((b for b in view["blocks"] if b["has_vol"]), view["blocks"][0] if view["blocks"] else None)
    view["chosen"] = chosen
    bits = ["本頁是買方避險（買賣權當保險），和「賣方風險燈號」不同；未輸入部位＝無保護。"]
    if view["spot"]:
        bits.append(f"指數 {view['spot_date']} 收盤 {view['spot']:,.2f}，一口名目 {view['notional']:,.0f} 元（×50）。")
    if chosen and chosen["puts"] and chosen["puts"][0]["prem"] is not None:
        p0 = chosen["puts"][0]
        bits.append(f"{chosen['name']} {chosen['code']} 價平賣權權利金 {p0['prem']} 點（約 {p0['twd']:,.0f} 元／口，示例）。")
    if view.get("vix"):
        bits.append(f"臺指 VIX {view['vix']['close']:.2f}（{view['vix']['date']}）：權利金會隨隱含波動變貴或變便宜，這裡不把 VIX 當買賣訊號。")
    if view["stale"] and view["snap_date"]:
        bits.append(f"期交所本次抓取失敗，沿用 {view['snap_date']} 快照。")
    view["reason"] = "".join(s if s.endswith("。") else s + "。" for s in bits)
    return view
