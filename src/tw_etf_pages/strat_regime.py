"""策略 12：震盪盤判定器（＋定期定額狀態提示）。

加權指數日 OHLC：data/strategy/taiex/ohlc.json。
  - 一次性回補：證交所 rwd MI_5MINS_HIST（每月一次，≥15 秒間隔）；缺口才用 Yahoo ^TWII（非官方，逐列標 src）。
  - 每日累積：沿用 data/taiex/kd.json（taiex_kd 已抓證交所 rwd）＋ openapi indicesReport/MI_5MINS_HIST（當月）。
指標全部由日 OHLC 自算；判讀門檻為經驗值。只描述目前狀態、預告波動，不預測方向。
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .strategy_common import any_to_date, http_json, label, num, session, strategy_dir, today_tw
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

RWD_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
OPENAPI_URL = "https://openapi.twse.com.tw/v1/indicesReport/MI_5MINS_HIST"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII"

# 判讀門檻（經驗值）
ADX_TREND, ADX_RANGE = 25.0, 20.0
ER_TREND, ER_RANGE, ER_DIR = 0.35, 0.25, 0.40
WIDTH_LOW, WIDTH_HIGH, WIDTH_SQUEEZE = 30.0, 80.0, 20.0
RANGE_LOW, RANGE_HIGH = 7.0, 14.0
CHOP_TREND, CHOP_RANGE = 38.2, 61.8
TANGLE = 3.0
POS_LOW, POS_HIGH = 0.2, 0.8
WIDTH_PCT_WIN = 120
# 盤整結束（自算）：回看窗
END_BREAK_WIN = 5      # 近 5 個交易日內收盤突破前 20 日高／低
END_ADX_WIN = 10       # 近 10 個交易日內 ADX 曾 < 20，今天 ≥ 25
END_WIDTH_WIN = 10     # 近 10 個交易日內帶寬百分位曾 ≤ 20%，今天比該低點高 ≥ 10 個百分點且比昨天高
END_WIDTH_RISE = 10.0
BAND_DAYS = 60
MARGIN_LOW = 150.0     # 沿用本站融資維持率「警戒」線


def ohlc_path(root: Path) -> Path:
    return strategy_dir(root) / "taiex" / "ohlc.json"


# ---------------------------------------------------------------- parsing

def parse_rwd(js: dict[str, Any]) -> list[dict[str, Any]]:
    if js.get("stat") != "OK":
        return []
    out = []
    for row in js.get("data") or []:
        try:
            o, h, l, c = (num(x) for x in row[1:5])
            if None in (o, h, l, c):
                continue
            out.append({"date": any_to_date(row[0]).isoformat(), "open": o, "high": h, "low": l, "close": c})
        except (ValueError, IndexError):
            continue
    return out


def parse_openapi(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows or []:
        try:
            o, h, l, c = (num(r.get(k)) for k in ("OpeningIndex", "HighestIndex", "LowestIndex", "ClosingIndex"))
            if None in (o, h, l, c):
                continue
            out.append({"date": any_to_date(r["Date"]).isoformat(), "open": o, "high": h, "low": l, "close": c})
        except (KeyError, ValueError):
            continue
    return out


def parse_yahoo(js: dict[str, Any], today: date) -> list[dict[str, Any]]:
    """Daily bars; drops today's bar (could be intraday, never use as close)."""
    try:
        res = js["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        return []
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        d = datetime.fromtimestamp(ts, timezone(timedelta(hours=8))).date()
        if d >= today:
            continue
        vals = [q.get(k, [None])[i] for k in ("open", "high", "low", "close")]
        if any(v is None for v in vals):
            continue
        out.append({"date": d.isoformat(), "open": round(vals[0], 2), "high": round(vals[1], 2),
                    "low": round(vals[2], 2), "close": round(vals[3], 2), "src": "yahoo"})
    return out


# ---------------------------------------------------------------- store

def merge_rows(by: dict[str, dict], rows: list[dict], src: str) -> int:
    n = 0
    for r in rows:
        old = by.get(r["date"])
        if old and old.get("src") != "yahoo" and src == "yahoo":
            continue  # never replace official data with Yahoo
        new = {**{k: r[k] for k in ("date", "open", "high", "low", "close")}, "src": src}
        if old != new:
            by[r["date"]] = new
            n += 1
    return n


def update_regime(root: Path, today: date | None = None) -> dict[str, Any]:
    today = today or today_tw()
    path = ohlc_path(root)
    store = read_json(path) if path.is_file() else {}
    by = {r["date"]: r for r in store.get("rows", [])}
    errors: list[str] = []
    added = 0
    kd = root / "data" / "taiex" / "kd.json"
    if kd.is_file():
        added += merge_rows(by, read_json(kd).get("rows") or [], "twse")
    try:
        sess = session()
        added += merge_rows(by, parse_openapi(http_json(sess, OPENAPI_URL, tries=2, timeout=60)), "twse")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"openapi MI_5MINS_HIST: {exc}")
        logger.warning("regime: openapi failed: %s", exc)
    rows = sorted(by.values(), key=lambda r: r["date"])
    data = {"source": [RWD_URL, OPENAPI_URL], "updated_at": now_taipei_iso(),
            "fetch_errors": errors, "rows": rows}
    if added or not path.is_file():
        write_json(path, data)
    logger.info("regime: %d OHLC rows (+%d), latest %s", len(rows), added, rows[-1]["date"] if rows else None)
    return data


# ---------------------------------------------------------------- indicators

def _sd(xs: list[float], ddof: int = 0) -> float:
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - ddof))


def _pct_rank(win: list[float], v: float) -> float:
    """Share (0–100) of window values ≤ v (window includes today)."""
    return sum(1 for x in win if x <= v) / len(win) * 100


def indicators(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n = len(rows)
    H = [r["high"] for r in rows]
    L = [r["low"] for r in rows]
    C = [r["close"] for r in rows]
    tr = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, n)]
    pdm = [0.0] + [(H[i] - H[i - 1]) if (H[i] - H[i - 1]) > (L[i - 1] - L[i]) and (H[i] - H[i - 1]) > 0 else 0.0
                   for i in range(1, n)]
    mdm = [0.0] + [(L[i - 1] - L[i]) if (L[i - 1] - L[i]) > (H[i] - H[i - 1]) and (L[i - 1] - L[i]) > 0 else 0.0
                   for i in range(1, n)]
    out = [dict(date=r["date"], close=r["close"], high=r["high"], low=r["low"], src=r.get("src", "twse"))
           for r in rows]
    # Wilder ADX(14)
    P = 14
    s_tr = s_p = s_m = None
    dxs: list[float] = []
    adx = None
    for i in range(1, n):
        if i < P:
            continue
        if i == P:
            s_tr, s_p, s_m = sum(tr[1:P + 1]), sum(pdm[1:P + 1]), sum(mdm[1:P + 1])
        else:
            s_tr = s_tr - s_tr / P + tr[i]
            s_p = s_p - s_p / P + pdm[i]
            s_m = s_m - s_m / P + mdm[i]
        pdi = 100 * s_p / s_tr if s_tr else 0.0
        mdi = 100 * s_m / s_tr if s_tr else 0.0
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0.0
        dxs.append(dx)
        if len(dxs) == P:
            adx = sum(dxs) / P
        elif len(dxs) > P:
            adx = (adx * (P - 1) + dx) / P
        out[i].update(pdi=pdi, mdi=mdi, adx=adx)
    for i in range(n):
        o = out[i]
        if i >= 19:
            w = C[i - 19:i + 1]
            ma = sum(w) / 20
            o["width"] = 4 * _sd(w) / ma
            h20, l20 = max(H[i - 19:i + 1]), min(L[i - 19:i + 1])
            o["range20"] = (h20 - l20) / l20 * 100
            o["pos"] = (C[i] - l20) / (h20 - l20) if h20 > l20 else None
            o["h20"], o["l20"] = h20, l20
            rets = [C[j] / C[j - 1] - 1 for j in range(i - 19, i + 1) if j >= 1]
            if len(rets) == 20:
                o["vol20"] = _sd(rets, 1) * math.sqrt(252) * 100
        if i >= 20:
            o["brk_up"] = C[i] > max(H[i - 20:i])
            o["brk_dn"] = C[i] < min(L[i - 20:i])
        if i >= 14:
            hh, ll = max(H[i - 13:i + 1]), min(L[i - 13:i + 1])
            s = sum(tr[i - 13:i + 1])
            o["chop"] = 100 * math.log10(s / (hh - ll)) / math.log10(14) if hh > ll else None
        for k in (10, 20):
            if i >= k:
                path = sum(abs(C[j] - C[j - 1]) for j in range(i - k + 1, i + 1))
                o[f"er{k}"] = abs(C[i] - C[i - k]) / path if path else 0.0
                o[f"net{k}"] = C[i] - C[i - k]
        if i >= 59:
            mas = [sum(C[i - k + 1:i + 1]) / k for k in (5, 10, 20, 60)]
            o["tangle"] = (max(mas) - min(mas)) / C[i] * 100
            o["ma"] = mas
    widths = [o.get("width") for o in out]
    for i in range(n):
        if i >= 19 + WIDTH_PCT_WIN - 1:
            win = widths[i - WIDTH_PCT_WIN + 1:i + 1]
            out[i]["width_pct"] = _pct_rank(win, widths[i])
    for o in out:
        o["regime"], o["direction"] = classify(o)
    return out


def classify(o: dict[str, Any]) -> tuple[str | None, str | None]:
    need = ("adx", "pdi", "mdi", "er20", "width_pct", "range20")
    if any(o.get(k) is None for k in need):
        return None, None
    di = "偏多" if o["pdi"] > o["mdi"] else "偏空"
    if o["adx"] >= ADX_TREND and o["er20"] >= ER_TREND:
        return "趨勢盤", di
    if (o["adx"] < ADX_RANGE and o["er20"] < ER_RANGE and o["width_pct"] <= WIDTH_LOW
            and o["range20"] <= RANGE_LOW):
        return "低波動盤整", "中性"
    if (o["width_pct"] >= WIDTH_HIGH or o["range20"] >= RANGE_HIGH) and o["er20"] < ER_TREND:
        return "高波動動盪", di
    return "過渡", "中性"


def range_end_signal(ind: list[dict[str, Any]], i: int) -> dict[str, Any]:
    o = ind[i]
    brk = [x for x in ind[max(0, i - END_BREAK_WIN + 1):i + 1] if x.get("brk_up") or x.get("brk_dn")]
    a_hit = bool(brk)
    a_txt = (f"{brk[-1]['date']} 收盤{'突破前 20 日高點' if brk[-1].get('brk_up') else '跌破前 20 日低點'}"
             if brk else f"近 {END_BREAK_WIN} 個交易日沒有收盤突破／跌破前 20 日高低點")
    prev_adx = [x.get("adx") for x in ind[max(0, i - END_ADX_WIN):i] if x.get("adx") is not None]
    b_hit = bool(o.get("adx") is not None and o["adx"] >= ADX_TREND and prev_adx and min(prev_adx) < ADX_RANGE)
    b_txt = (f"近 {END_ADX_WIN} 日 ADX 最低 {min(prev_adx):.1f}，今天 {o['adx']:.1f}" if prev_adx and o.get("adx")
             is not None else "資料暫缺")
    pw = [x.get("width_pct") for x in ind[max(0, i - END_WIDTH_WIN):i] if x.get("width_pct") is not None]
    wp, wy = o.get("width_pct"), ind[i - 1].get("width_pct") if i else None
    c_hit = bool(pw and wp is not None and wy is not None and min(pw) <= WIDTH_SQUEEZE
                 and wp >= min(pw) + END_WIDTH_RISE and wp > wy)
    c_txt = (f"近 {END_WIDTH_WIN} 日帶寬百分位最低 {min(pw):.0f}%，今天 {wp:.0f}%" if pw and wp is not None
             else "資料暫缺")
    n = sum((a_hit, b_hit, c_hit))
    return {"items": [("收盤突破 20 日高／低", a_hit, a_txt), ("ADX 由 <20 升到 ≥25", b_hit, b_txt),
                      ("帶寬百分位從 ≤20% 翻升", c_hit, c_txt)], "n": n, "ended": n >= 2}


# ---------------------------------------------------------------- reads

def reads(o: dict[str, Any], chop_pct: float | None) -> list[dict[str, Any]]:
    def r(name, val, extra, kind, text, rule):
        return {"name": name, "val": val, "extra": extra, "kind": kind, "read": text, "rule": rule}
    out = []
    adx, pdi, mdi = o["adx"], o["pdi"], o["mdi"]
    if adx >= ADX_TREND:
        k, t = ("bull", "偏多（趨勢成形、+DI 在上）") if pdi > mdi else ("bear", "偏空（趨勢成形、−DI 在上）")
    elif adx < ADX_RANGE:
        k, t = "neutral", "盤整（沒有趨勢）"
    else:
        k, t = "neutral", "過渡"
    out.append(r("ADX(14)", f"{adx:.1f}", f"+DI {pdi:.1f}／−DI {mdi:.1f}", k, t,
                 "≥25 且 +DI>−DI 偏多；≥25 且 −DI>+DI 偏空；<20 盤整；20–25 過渡（經驗值）"))
    er = o["er20"]
    if er >= ER_DIR:
        k, t = ("bull", "偏多（走得很直、往上）") if o["net20"] > 0 else ("bear", "偏空（走得很直、往下）")
    elif er <= ER_RANGE:
        k, t = "neutral", "來回盤（走了很多路但沒前進）"
    else:
        k, t = "neutral", "中性"
    out.append(r("效率比 ER20", f"{er:.2f}", f"ER10 {o['er10']:.2f}", k, t,
                 "≥0.40 依淨漲跌方向判偏多／偏空；≤0.25 來回盤（經驗值）"))
    ch = o.get("chop")
    if ch is not None:
        t = "趨勢" if ch <= CHOP_TREND else ("盤整" if ch >= CHOP_RANGE else "中性")
        out.append(r("CHOP(14)", f"{ch:.1f}", f"本站歷史百分位 {chop_pct:.0f}%" if chop_pct is not None else "",
                     "neutral", t, "≤38.2 趨勢；≥61.8 盤整（經驗值）；台股 6 年 p90 只有 56.4，所以很少到盤整線，請一併看百分位"))
    wp = o["width_pct"]
    t = "壓縮（波動很小，常是變盤前）" if wp <= WIDTH_SQUEEZE else ("高波動" if wp >= WIDTH_HIGH else "中性")
    out.append(r("布林帶寬 (20,2)", f"{o['width'] * 100:.2f}%", f"近 120 日百分位 {wp:.1f}%",
                 "warn" if wp >= WIDTH_HIGH else "neutral", t, "百分位 ≤20% 壓縮；≥80% 高波動（經驗值）"))
    out.append(r("20 日區間幅度", f"{o['range20']:.1f}%", f"高 {o['h20']:,.0f}／低 {o['l20']:,.0f}", "neutral",
                 "窄（≤7%）" if o["range20"] <= RANGE_LOW else ("寬（≥14%）" if o["range20"] >= RANGE_HIGH else "中等"),
                 "≤7% 是低波動盤整條件之一；≥14% 是高波動條件之一（經驗值）"))
    tg = o.get("tangle")
    if tg is not None:
        out.append(r("均線糾結 (5/10/20/60)", f"{tg:.1f}%", "", "neutral",
                     "糾結（均線擠在一起）" if tg <= TANGLE else "發散", "≤3% 糾結（經驗值）"))
    pos = o.get("pos")
    if pos is not None:
        meaningful = o["regime"] == "低波動盤整"
        t = "下緣" if pos <= POS_LOW else ("上緣" if pos >= POS_HIGH else "中段")
        out.append(r("區間位置", f"{pos:.2f}", "只有在「低波動盤整」才有意義" if not meaningful else "目前是低波動盤整，可參考",
                     "neutral", t if meaningful else f"{t}（非盤整，不判讀）", "≤0.2 下緣；≥0.8 上緣（經驗值）"))
    if o.get("vol20") is not None:
        out.append(r("20 日年化波動", f"{o['vol20']:.1f}%", "", "neutral", "僅顯示", "日報酬標準差 × √252"))
    return out


REGIME_KIND = {("趨勢盤", "偏多"): "bull", ("趨勢盤", "偏空"): "bear", ("高波動動盪", "偏空"): "bear",
               ("高波動動盪", "偏多"): "warn", ("低波動盤整", "中性"): "neutral", ("過渡", "中性"): "neutral"}
REGIME_COLOR = {"趨勢盤偏多": "#dc2626", "趨勢盤偏空": "#16a34a", "高波動動盪偏空": "#86efac",
                "高波動動盪偏多": "#fca5a5", "低波動盤整中性": "#94a3b8", "過渡中性": "#e2e8f0"}


def regime_label(regime: str, direction: str) -> dict[str, str]:
    kind = REGIME_KIND.get((regime, direction), "neutral")
    text = regime if direction == "中性" else f"{regime}・{direction}"
    return {"text": text, "cls": kind}


def dca_advice(regime: str, direction: str, margin: float | None) -> dict[str, Any]:
    if (regime, direction) in (("趨勢盤", "偏多"),) or regime == "低波動盤整":
        kind, text, lb = "bull", "照常扣款", "中性偏多"
    elif (regime, direction) in (("高波動動盪", "偏空"), ("趨勢盤", "偏空")):
        kind, text, lb = "bear", "照常扣款，但不加碼、不借錢加碼", "偏空"
    elif regime == "高波動動盪":
        kind, text, lb = "neutral", "照常扣款，不追高加碼", "中性"
    else:
        kind, text, lb = "neutral", "照常扣款", "中性"
    low = margin is not None and margin < MARGIN_LOW
    if low:
        text += "；先降槓桿"
    return {"text": text, "label": {"text": f"{text}（{lb}）", "cls": kind}, "margin": margin, "margin_low": low}


def _load_margin(root: Path) -> tuple[float | None, str | None]:
    p = root / "data" / "margin" / "ratio.json"
    if not p.is_file():
        return None, None
    rows = read_json(p).get("rows") or []
    return (rows[-1]["ratio"], rows[-1]["date"]) if rows else (None, None)


def _load_vix(root: Path) -> list[dict[str, Any]]:
    p = root / "data" / "vix" / "taiwan_vix.json"
    return (read_json(p).get("rows") or []) if p.is_file() else []


def _band_svg(days: list[dict[str, Any]]) -> str:
    w, h = 760, 46
    n = len(days)
    if not n:
        return ""
    bw = w / n
    parts = [f'<svg viewBox="0 0 {w} {h + 18}" class="kd-svg" role="img" aria-label="近 {n} 日盤型色帶">']
    for i, d in enumerate(days):
        key = f"{d['regime']}{d['direction']}"
        parts.append(f'<rect x="{i * bw:.1f}" y="0" width="{bw + 0.5:.1f}" height="{h}" fill="{REGIME_COLOR.get(key, "#f3f4f6")}">'
                     f'<title>{d["date"]} {d["regime"]}・{d["direction"]}</title></rect>')
    for i in (0, n // 2, n - 1):
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        parts.append(f'<text x="{(i + 0.5) * bw:.1f}" y="{h + 14}" font-size="11" fill="#64748b" text-anchor="{anchor}">{days[i]["date"][2:]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_regime_view(root: Path) -> dict[str, Any] | None:
    path = ohlc_path(root)
    if not path.is_file():
        return None
    store = read_json(path)
    rows = store.get("rows") or []
    if len(rows) < 200:
        return None
    ind = indicators(rows)
    i = len(ind) - 1
    o = ind[i]
    if o["regime"] is None:
        return None
    chops = [x["chop"] for x in ind if x.get("chop") is not None]
    chop_pct = _pct_rank(chops, o["chop"]) if o.get("chop") is not None else None
    chops_sorted = sorted(chops)
    chop_p90 = chops_sorted[int(0.9 * (len(chops_sorted) - 1))] if chops_sorted else None
    kd = {}
    kdp = root / "data" / "taiex" / "kd.json"
    if kdp.is_file():
        kd = {r["date"]: r for r in read_json(kdp).get("rows") or []}
    k = kd.get(o["date"])
    vix = _load_vix(root)
    v_last = vix[-1] if vix else None
    margin, margin_date = _load_margin(root)
    lb = regime_label(o["regime"], o["direction"])
    end = range_end_signal(ind, i)
    dca = dca_advice(o["regime"], o["direction"], margin)
    band = [x for x in ind if x["regime"]][-BAND_DAYS:]
    counts: dict[str, int] = {}
    for x in band:
        counts[x["regime"]] = counts.get(x["regime"], 0) + 1
    reason = {
        "高波動動盪": f"布林帶寬在近 120 日的 {o['width_pct']:.0f}% 百分位、20 日區間 {o['range20']:.1f}%，波動很大；"
                  f"但效率比 ER20 只有 {o['er20']:.2f}，漲跌來回、不是單向趨勢。{'−DI 在上，方向偏空' if o['direction'] == '偏空' else '+DI 在上，方向偏多'}。",
        "趨勢盤": f"ADX {o['adx']:.1f}（≥25）且 ER20 {o['er20']:.2f}（≥0.35），走勢有方向；"
               f"{'+DI 在上，偏多' if o['direction'] == '偏多' else '−DI 在上，偏空'}。",
        "低波動盤整": f"ADX {o['adx']:.1f}（<20）、ER20 {o['er20']:.2f}、帶寬百分位 {o['width_pct']:.0f}%、20 日區間 {o['range20']:.1f}%，大盤在窄區間來回。",
        "過渡": f"ADX {o['adx']:.1f}、ER20 {o['er20']:.2f}、帶寬百分位 {o['width_pct']:.0f}%，不符合任何一種典型盤型的條件，視為過渡。",
    }[o["regime"]]
    yahoo_n = sum(1 for r in rows if r.get("src") == "yahoo")
    return {
        "date": o["date"], "close": o["close"], "regime": o["regime"], "direction": o["direction"],
        "label": lb, "reason": reason, "ind": o, "reads": reads(o, chop_pct), "chop_pct": chop_pct,
        "chop_p90": chop_p90, "kd": k, "vix": v_last, "end": end, "dca": dca,
        "margin": margin, "margin_date": margin_date, "band_svg": _band_svg(band), "band_counts": counts,
        "band": list(reversed(band)), "n_rows": len(rows), "first": rows[0]["date"], "yahoo_n": yahoo_n,
        "colors": REGIME_COLOR, "fetch_errors": store.get("fetch_errors") or [],
        "dca_reason": f"盤型「{lb['text']}」→ {dca['text']}。" + (
            f"上市融資維持率 {margin:.1f}%（{margin_date}）低於 150% 警戒線，有融資的人先降槓桿。" if dca["margin_low"]
            else (f"上市融資維持率 {margin:.1f}%（{margin_date}），未低於 150%。" if margin is not None else "融資維持率資料暫缺。")),
    }


def regime_series(root: Path) -> list[dict[str, Any]]:
    path = ohlc_path(root)
    if not path.is_file():
        return []
    return indicators(read_json(path).get("rows") or [])


def backfill_regime(root: Path, start: date = date(2020, 1, 1), use_yahoo: bool = True) -> int:
    """One-time slow backfill (run by hand, not in the daily job): TWSE rwd month by month, ≥15 s apart,
    wait 3 min when blocked; months still missing afterwards are filled from Yahoo ^TWII (src="yahoo")."""
    import time

    import requests

    path = ohlc_path(root)
    store = read_json(path) if path.is_file() else {}
    by = {r["date"]: r for r in store.get("rows", [])}
    have = {d[:7] for d in by}
    today = today_tw()
    y, m = start.year, start.month
    missing = []
    while (y, m) <= (today.year, today.month):
        if f"{y:04d}-{m:02d}" not in have:
            missing.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (compatible; tw-etf-pages/1.0)"
    failed = []
    for y, m in missing:
        for attempt in range(4):
            try:
                r = sess.get(RWD_URL, params={"date": f"{y}{m:02d}01", "response": "json"}, timeout=(10, 20),
                             allow_redirects=False)
                if r.status_code == 200 and r.text.lstrip().startswith("{"):
                    merge_rows(by, parse_rwd(r.json()), "twse")
                    break
                raise RuntimeError(f"HTTP {r.status_code}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("backfill %d-%02d: %s; waiting 3 min", y, m, exc)
                time.sleep(180)
        else:
            failed.append((y, m))
        time.sleep(15)
    if failed and use_yahoo:
        js = requests.get(YAHOO_URL, params={"range": "6y", "interval": "1d"}, timeout=30,
                          headers={"User-Agent": "Mozilla/5.0"}).json()
        want = {f"{y:04d}-{m:02d}" for y, m in failed}
        merge_rows(by, [r for r in parse_yahoo(js, today) if r["date"][:7] in want], "yahoo")
    rows = sorted(by.values(), key=lambda r: r["date"])
    write_json(path, {"source": [RWD_URL, OPENAPI_URL], "updated_at": now_taipei_iso(), "fetch_errors": [],
                      "rows": rows})
    return len(rows)
