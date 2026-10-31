"""每週千張大戶籌碼 (TDCC 集保戶股權分散表) for every stock held by tracked ETFs.

Definition (single, consistent): 持股分級 15 = 持有 1,000,001 股以上（≥1,000 張）。
For each stock we store that level's 人數 / 股數 / 占集保庫存數比例%, plus 總人數 (level 17).
Week-over-week change compares the latest TDCC data date with the previous one.

Sources (official TDCC):
  - 開放資料 1-5（最新一週全市場）: https://opendata.tdcc.com.tw/getOD.ashx?id=1-5
  - 集保戶股權分散表查詢（歷史週，逐檔）: https://www.tdcc.com.tw/portal/zh/smWeb/qryStock
Weekly files: data/chips/weeks/YYYYMMDD.json ; view: data/chips/latest.json. Never raises
from update_chips (caller wraps), and the site skips the section when no data.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from pathlib import Path
from typing import Any

import requests

from .compare import list_snapshot_dates, load_snapshot
from .config import AppConfig
from .utils import now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

OPEN_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
QRY_URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
UA = "Mozilla/5.0 (compatible; tw-etf-pages/1.0; +https://solymx.github.io/tw-etf-pages/)"
BIG_LEVEL = 15
TOTAL_LEVEL = 17
STOCK_RE = re.compile(r"^\d{4,6}[A-Z]?$")
# 「明顯」門檻：千張大戶持股比例週變化 ≥ 0.5 個百分點
NOTABLE_PP = 0.5
MAX_BACKFILL_PER_RUN = 400


def chips_dir(root: Path) -> Path:
    return root / "data" / "chips"


def week_path(root: Path, d: str) -> Path:
    return chips_dir(root) / "weeks" / f"{d}.json"


def tracked_stocks(cfg: AppConfig) -> dict[str, dict[str, Any]]:
    """Deduped Taiwan stocks across every tracked ETF's latest snapshot."""
    out: dict[str, dict[str, Any]] = {}
    for etf in cfg.etfs:
        dates = list_snapshot_dates(cfg.snapshots_dir, etf.ticker)
        if not dates:
            continue
        snap = load_snapshot(cfg.snapshots_dir, etf.ticker, dates[-1])
        for h in snap.get("holdings", []):
            code = str(h.get("stock_code", "")).strip()
            if h.get("is_placeholder") or not STOCK_RE.match(code):
                continue
            e = out.setdefault(code, {"name": h.get("stock_name", ""), "etfs": []})
            e["etfs"].append({"ticker": etf.ticker, "weight_pct": h.get("weight_pct")})
    return out


def _num(s: str) -> float:
    return float(str(s).replace(",", "").strip() or 0)


def fetch_open_latest(session: requests.Session) -> tuple[str, dict[str, dict[str, Any]]]:
    r = session.get(OPEN_URL, timeout=120)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    rows: dict[str, dict[str, Any]] = {}
    data_date = ""
    for rec in csv.reader(io.StringIO(text)):
        if len(rec) < 6 or not rec[0].strip().isdigit():
            continue
        data_date = rec[0].strip()
        code = rec[1].strip()
        lvl = int(rec[2])
        if lvl not in (BIG_LEVEL, TOTAL_LEVEL):
            continue
        e = rows.setdefault(code, {})
        if lvl == BIG_LEVEL:
            e.update(big_holders=int(_num(rec[3])), big_shares=int(_num(rec[4])), big_pct=_num(rec[5]))
        else:
            e.update(total_holders=int(_num(rec[3])), total_shares=int(_num(rec[4])))
    if not data_date:
        raise RuntimeError("TDCC open data empty")
    return data_date, rows


class TdccQuery:
    """Per-stock historical query on TDCC portal (needs session token)."""

    def __init__(self, session: requests.Session):
        self.s = session
        self.token = ""
        self.fir = ""
        self.dates: list[str] = []

    def refresh(self) -> None:
        r = self.s.get(QRY_URL, timeout=30)
        r.raise_for_status()
        t = r.text
        m = re.search(r'name="SYNCHRONIZER_TOKEN" value="([^"]+)"', t)
        if not m:
            raise RuntimeError("TDCC token not found")
        self.token = m.group(1)
        f = re.search(r'name="firDate" value="(\d{8})"', t)
        self.fir = f.group(1) if f else ""
        self.dates = re.findall(r'<option value="(\d{8})"', t)

    def query(self, code: str, d: str) -> dict[str, Any] | None:
        last: Exception | None = None
        for attempt in range(3):
            try:
                if not self.token:
                    self.refresh()
                r = self.s.post(
                    QRY_URL,
                    data={
                        "SYNCHRONIZER_TOKEN": self.token,
                        "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
                        "method": "submit",
                        "firDate": self.fir,
                        "scaDate": d,
                        "sqlMethod": "StockNo",
                        "stockNo": code,
                        "stockName": "",
                    },
                    headers={"Referer": QRY_URL},
                    timeout=30,
                )
                r.raise_for_status()
                t = r.text
                # token rotates per response
                m = re.search(r'name="SYNCHRONIZER_TOKEN" value="([^"]+)"', t)
                self.token = m.group(1) if m else ""
                if "查無此資料" in t:
                    return None
                dm = re.search(r"資料日期：(\d{2,3})年(\d{1,2})月(\d{1,2})日", t)
                if not dm:
                    raise RuntimeError("no data date in response")
                got = f"{int(dm.group(1)) + 1911:04d}{int(dm.group(2)):02d}{int(dm.group(3)):02d}"
                if got != d:
                    raise RuntimeError(f"date mismatch {got} != {d}")
                plain = re.sub(r"<[^>]+>", " ", t)
                plain = re.sub(r"\s+", " ", plain)
                b = re.search(r" 15 1,000,001以上 ([\d,]+) ([\d,]+) ([\d.]+) ", plain)
                tot = re.search(r" 1[67] 合 ?計 ([\d,]+) ([\d,]+) ", plain)
                if not b or not tot:
                    return None
                return {
                    "big_holders": int(_num(b.group(1))),
                    "big_shares": int(_num(b.group(2))),
                    "big_pct": _num(b.group(3)),
                    "total_holders": int(_num(tot.group(1))),
                    "total_shares": int(_num(tot.group(2))),
                }
            except Exception as exc:  # noqa: BLE001
                last = exc
                self.token = ""
                time.sleep(2 + attempt * 3)
        logger.warning("TDCC query %s %s failed: %s", code, d, last)
        return None


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def _save_week(root: Path, d: str, source: str, stocks: dict[str, Any]) -> None:
    p = week_path(root, d)
    old = read_json(p) if p.is_file() else {"stocks": {}}
    merged = dict(old.get("stocks", {}))
    merged.update(stocks)
    write_json(
        p,
        {
            "data_date": d,
            "definition": "TDCC 集保戶股權分散表 持股分級15（1,000,001股以上＝千張大戶）",
            "source": source,
            "updated_at": now_taipei_iso(),
            "stocks": dict(sorted(merged.items())),
        },
    )


def update_chips(cfg: AppConfig) -> None:
    root = cfg.root
    stocks = tracked_stocks(cfg)
    if not stocks:
        return
    s = _session()
    latest, rows = fetch_open_latest(s)
    _save_week(root, latest, OPEN_URL, {c: rows[c] for c in stocks if c in rows})

    q = TdccQuery(s)
    q.refresh()
    prev_dates = [d for d in q.dates if d < latest]
    if not prev_dates:
        logger.warning("no previous TDCC week available")
    else:
        prev = prev_dates[0]
        p = week_path(root, prev)
        have = set(read_json(p).get("stocks", {})) if p.is_file() else set()
        missing = [c for c in stocks if c not in have][:MAX_BACKFILL_PER_RUN]
        got: dict[str, Any] = {}
        for i, c in enumerate(missing):
            v = q.query(c, prev)
            if v:
                got[c] = v
            time.sleep(0.4)
            if (i + 1) % 50 == 0:
                logger.info("TDCC backfill %s: %d/%d", prev, i + 1, len(missing))
        if got or not p.is_file():
            _save_week(root, prev, QRY_URL, got)
    build_latest(cfg, stocks)


def _weeks(root: Path) -> list[str]:
    d = chips_dir(root) / "weeks"
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def build_latest(cfg: AppConfig, stocks: dict[str, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    root = cfg.root
    stocks = stocks or tracked_stocks(cfg)
    weeks = _weeks(root)
    if len(weeks) < 1:
        return None
    cur_d = weeks[-1]
    prev_d = weeks[-2] if len(weeks) >= 2 else None
    cur = read_json(week_path(root, cur_d)).get("stocks", {})
    prv = read_json(week_path(root, prev_d)).get("stocks", {}) if prev_d else {}
    out_rows = []
    for code, meta in stocks.items():
        c, p = cur.get(code), prv.get(code)
        row: dict[str, Any] = {
            "code": code,
            "name": meta["name"],
            "etfs": [e["ticker"] for e in meta["etfs"]],
            "etf_count": len(meta["etfs"]),
            "cur": c,
            "prev": p,
        }
        if c and p:
            row["d_pct"] = round(c["big_pct"] - p["big_pct"], 2)
            row["d_holders"] = c["big_holders"] - p["big_holders"]
            row["d_lots"] = round((c["big_shares"] - p["big_shares"]) / 1000)
            row["d_total_holders"] = c["total_holders"] - p["total_holders"]
        out_rows.append(row)
    has = [r for r in out_rows if "d_pct" in r]
    inc = sorted([r for r in has if r["d_pct"] >= NOTABLE_PP], key=lambda r: (-r["d_pct"], -r["etf_count"]))
    dec = sorted([r for r in has if r["d_pct"] <= -NOTABLE_PP], key=lambda r: (r["d_pct"], -r["etf_count"]))
    n_up = sum(1 for r in has if r["d_pct"] > 0)
    n_dn = sum(1 for r in has if r["d_pct"] < 0)
    if not has:
        tilt = "無資料"
    elif n_up >= 1.3 * max(n_dn, 1) and n_up > n_dn:
        tilt = "偏增"
    elif n_dn >= 1.3 * max(n_up, 1) and n_dn > n_up:
        tilt = "偏減"
    elif n_dn > n_up:
        tilt = "混雜（略偏減）"
    elif n_up > n_dn:
        tilt = "混雜（略偏增）"
    else:
        tilt = "混雜"
    # 權重加權（以 ETF 檔數）平均變化
    w = sum(r["etf_count"] for r in has) or 1
    avg = round(sum(r["d_pct"] * r["etf_count"] for r in has) / w, 3) if has else None
    view = {
        "data_date": cur_d,
        "prev_date": prev_d,
        "generated_at": now_taipei_iso(),
        "definition": "持股 1,000 張以上（TDCC 持股分級 15：1,000,001 股以上）",
        "notable_pp": NOTABLE_PP,
        "sources": {"open_data": OPEN_URL, "history_query": QRY_URL},
        "summary": {
            "stocks": len(out_rows),
            "with_data": len(has),
            "missing": len(out_rows) - len(has),
            "up": n_up,
            "down": n_dn,
            "flat": len(has) - n_up - n_dn,
            "notable_up": len(inc),
            "notable_down": len(dec),
            "tilt": tilt,
            "avg_d_pct_etf_weighted": avg,
        },
        "increase": [r["code"] for r in inc],
        "decrease": [r["code"] for r in dec],
        "rows": sorted(out_rows, key=lambda r: (-(r.get("d_pct") if r.get("d_pct") is not None else -999), r["code"])),
    }
    write_json(chips_dir(root) / "latest.json", view)
    return view


def build_chips_view(root: Path) -> dict[str, Any] | None:
    p = chips_dir(root) / "latest.json"
    if not p.is_file():
        return None
    v = read_json(p)
    by = {r["code"]: r for r in v["rows"]}
    v["inc_rows"] = [by[c] for c in v["increase"] if c in by]
    v["dec_rows"] = [by[c] for c in v["decrease"] if c in by]

    def fmt(d: str | None) -> str:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}" if d else "—"

    v["data_date_fmt"] = fmt(v["data_date"])
    v["prev_date_fmt"] = fmt(v.get("prev_date"))
    return v
