"""Download official Excel holdings (with WAF warmup / retries) + zdsetf fallback."""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from .config import AppConfig, EtfConfig
from .utils import today_taipei

logger = logging.getLogger(__name__)

UNI_WARMUP = "https://www.ezmoney.com.tw/"
UNI_EXCEL = "https://www.ezmoney.com.tw/ETF/Fund/AssetExcelNPOI?fundCode={fund_code}"
FH_EXCEL = "https://www.fhtrust.com.tw/api/assetsExcel/{fund_code}/{yyyymmdd}"
ZDSETF_SNAPSHOT = "https://zdsetf.com/api/etfs/{ticker}/snapshot"


class FetchError(RuntimeError):
    pass


def _session(cfg: AppConfig) -> requests.Session:
    s = requests.Session()
    ua = cfg.fetch.get(
        "user_agent",
        "tw-etf-pages/1.0 (public ETF holdings archive)",
    )
    s.headers.update(
        {
            "User-Agent": ua,
            "Accept": "*/*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        }
    )
    return s


def _retry_get(
    session: requests.Session,
    url: str,
    *,
    retries: int,
    backoff: float,
    timeout: float,
    **kwargs: Any,
) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout, **kwargs)
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("GET %s attempt %s/%s failed: %s", url, attempt, retries, exc)
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise FetchError(f"GET failed after {retries} tries: {url}: {last_exc}")


def fetch_uni_excel(cfg: AppConfig, etf: EtfConfig, dest: Path) -> Path:
    """Warm WAF cookie jar, then download Uni AssetExcelNPOI."""
    timeout = float(cfg.fetch.get("timeout_sec", 60))
    retries = int(cfg.fetch.get("retries", 3))
    backoff = float(cfg.fetch.get("retry_backoff_sec", 2))
    session = _session(cfg)

    logger.info("Uni WAF warmup for %s", etf.ticker)
    warm = _retry_get(session, UNI_WARMUP, retries=retries, backoff=backoff, timeout=timeout)
    if warm.status_code >= 400:
        logger.warning("warmup status %s (continuing)", warm.status_code)

    url = UNI_EXCEL.format(fund_code=etf.fund_code)
    logger.info("Downloading Uni Excel %s → %s", url, dest)
    resp = _retry_get(session, url, retries=retries, backoff=backoff, timeout=timeout)
    if resp.status_code != 200:
        raise FetchError(f"Uni Excel HTTP {resp.status_code} for {etf.ticker}: {url}")
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "html" in ctype and len(resp.content) < 5000:
        raise FetchError(f"Uni Excel looks like HTML challenge for {etf.ticker}")
    if len(resp.content) < 1000:
        raise FetchError(f"Uni Excel too small ({len(resp.content)} bytes) for {etf.ticker}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


def fetch_fh_excel(
    cfg: AppConfig,
    etf: EtfConfig,
    dest: Path,
    as_of: date | None = None,
    lookback_days: int = 7,
) -> Path:
    """Download FH Excel for as_of (default today), walking back if empty."""
    timeout = float(cfg.fetch.get("timeout_sec", 60))
    retries = int(cfg.fetch.get("retries", 3))
    backoff = float(cfg.fetch.get("retry_backoff_sec", 2))
    session = _session(cfg)

    start = as_of or today_taipei()
    errors: list[str] = []
    for delta in range(lookback_days + 1):
        d = start - timedelta(days=delta)
        ymd = d.strftime("%Y%m%d")
        url = FH_EXCEL.format(fund_code=etf.fund_code, yyyymmdd=ymd)
        logger.info("Trying FH Excel %s", url)
        resp = _retry_get(session, url, retries=retries, backoff=backoff, timeout=timeout)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        body = resp.content
        # empty / 查無資料 JSON
        if "json" in ctype or body[:1] == b"{":
            errors.append(f"{ymd}: no data yet ({body[:80]!r})")
            continue
        if resp.status_code != 200:
            errors.append(f"{ymd}: HTTP {resp.status_code}")
            continue
        if len(body) < 500:
            errors.append(f"{ymd}: too small ({len(body)})")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        return dest

    raise FetchError(
        f"FH Excel unavailable for {etf.ticker} in last {lookback_days} days: "
        + "; ".join(errors[-3:])
    )


def fetch_zdsetf_snapshot(cfg: AppConfig, ticker: str, dest: Path) -> Path:
    timeout = float(cfg.fetch.get("timeout_sec", 60))
    retries = int(cfg.fetch.get("retries", 3))
    backoff = float(cfg.fetch.get("retry_backoff_sec", 2))
    session = _session(cfg)
    url = ZDSETF_SNAPSHOT.format(ticker=ticker)
    logger.info("zdsetf snapshot %s", url)
    resp = _retry_get(session, url, retries=retries, backoff=backoff, timeout=timeout)
    if resp.status_code != 200:
        raise FetchError(f"zdsetf HTTP {resp.status_code}: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


def fetch_etf_holdings(
    cfg: AppConfig,
    etf: EtfConfig,
    *,
    allow_fallback: bool = True,
) -> tuple[Path, str]:
    """
    Fetch primary issuer Excel; on failure optionally fallback to zdsetf JSON.
    Returns (path, kind) where kind is 'uni_excel' | 'fh_excel' | 'zdsetf'.

    Capital Fund (群益投信) and Fubon (富邦投信) have no reliable public
    Excel/CSV download URL for automation; for issuer in {"capital", "fubon"}
    we archive via zdsetf.com snapshot, which mirrors the official portfolio
    page (source_url points at capitalfund.com.tw / websys.fsit.com.tw).
    """
    stamp = today_taipei().isoformat()
    raw_dir = cfg.raw_dir / etf.ticker

    # Primary path for capital / fubon: zdsetf mirror of official portfolio (no Excel API).
    if etf.issuer in ("capital", "fubon"):
        path = raw_dir / f"{etf.ticker}_{stamp}_zdsetf.json"
        fetch_zdsetf_snapshot(cfg, etf.ticker, path)
        return path, "zdsetf"

    try:
        if etf.issuer == "uni":
            path = raw_dir / f"{etf.ticker}_{stamp}_uni.xlsx"
            fetch_uni_excel(cfg, etf, path)
            return path, "uni_excel"
        if etf.issuer == "fh":
            path = raw_dir / f"{etf.ticker}_{stamp}_fh.xlsx"
            fetch_fh_excel(cfg, etf, path)
            return path, "fh_excel"
        raise FetchError(f"unknown issuer {etf.issuer}")
    except FetchError as exc:
        logger.error("Primary fetch failed for %s: %s", etf.ticker, exc)
        if not allow_fallback:
            raise
        path = raw_dir / f"{etf.ticker}_{stamp}_zdsetf.json"
        fetch_zdsetf_snapshot(cfg, etf.ticker, path)
        return path, "zdsetf"
