"""今日台灣財經新聞清單：只存標題、原文連結與發布時間，不複製內文。

公開 RSS／API（各自獨立重試，單一來源失敗不影響整頁）：
  - 工商時報 ctee.com.tw 官方 RSS（證券／產業／金融／科技）
  - 經濟日報 money.udn.com 官方 RSS（股市／市場／產業等）
  - Google 新聞 RSS（「台股」搜尋＋商業主題，連結點進去即可開原文）
  - 鉅亨網公開 API（只取 title / newsId / publishAt）
  - 中央社產經 Feedburner RSS
  - MoneyDJ 即時新聞官方 RSS（個人／非營利網站使用）
  - 自由時報財經官方 RSS
富途牛牛沒有可穩定使用的官方公開 RSS／API，不列入抓取。
輸出 data/news/latest.json；永不讓例外穿過 pipeline。
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import requests

from .utils import TZ_TAIPEI, now_taipei_iso, read_json, write_json

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; tw-etf-pages/1.0; +https://solymx.github.io/tw-etf-pages/)"
ACCEPT_RSS = "application/rss+xml, application/xml, text/xml, application/json;q=0.9, */*;q=0.8"
SPACING = 0.6
RETRIES = 4
TIMEOUT = 30
PRIOR_EVENING_HOUR = 17
MORNING_HOUR = 8
MIN_TODAY_ITEMS = 8
SIMILARITY = 0.88
GOOGLE_PRIORITY = 9

CNYES_URL = "https://news.cnyes.com/news/id/{news_id}"
CNYES_API = "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?page=1&limit=30"

# kind: rss | json
FEEDS: list[dict[str, str]] = [
    {"id": "ctee_stock", "name": "工商時報", "kind": "rss",
     "url": "https://www.ctee.com.tw/rss_web/livenews/stock"},
    {"id": "ctee_industry", "name": "工商時報", "kind": "rss",
     "url": "https://www.ctee.com.tw/rss_web/livenews/industry"},
    {"id": "ctee_finance", "name": "工商時報", "kind": "rss",
     "url": "https://www.ctee.com.tw/rss_web/livenews/finance"},
    {"id": "ctee_tech", "name": "工商時報", "kind": "rss",
     "url": "https://www.ctee.com.tw/rss_web/livenews/tech"},
    {"id": "udn_stock", "name": "經濟日報", "kind": "rss",
     "url": "https://money.udn.com/rssfeed/news/1001/5591?ch=money"},
    {"id": "udn_market", "name": "經濟日報", "kind": "rss",
     "url": "https://money.udn.com/rssfeed/news/1001/5590?ch=money"},
    {"id": "udn_5592", "name": "經濟日報", "kind": "rss",
     "url": "https://money.udn.com/rssfeed/news/1001/5592?ch=money"},
    {"id": "udn_industry", "name": "經濟日報", "kind": "rss",
     "url": "https://money.udn.com/rssfeed/news/1001/5588?ch=money"},
    {"id": "gnews_taigu", "name": "Google 新聞", "kind": "rss",
     "url": "https://news.google.com/rss/search?q=%E5%8F%B0%E8%82%A1&hl=zh-TW&gl=TW&ceid=TW:zh-TW"},
    {"id": "gnews_biz", "name": "Google 新聞", "kind": "rss",
     "url": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-TW&gl=TW&ceid=TW:zh-TW"},
    {"id": "cnyes", "name": "鉅亨網", "kind": "cnyes", "url": CNYES_API},
    {"id": "cna", "name": "中央社", "kind": "rss",
     "url": "https://feeds.feedburner.com/rsscna/finance"},
    {"id": "moneydj", "name": "MoneyDJ", "kind": "rss",
     "url": "https://www.moneydj.com/KMDJ/RssCenter.aspx?svc=NR&fno=1&arg=MB010000"},
    {"id": "ltn", "name": "自由時報", "kind": "rss",
     "url": "https://news.ltn.com.tw/rss/business.xml"},
]

SOURCE_PRIORITY = {
    "工商時報": 0,
    "經濟日報": 0,
    "中央社": 0,
    "鉅亨網": 1,
    "MoneyDJ": 1,
    "自由時報": 1,
    "Google 新聞": GOOGLE_PRIORITY,
}

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "oc",
})
_PUNCT = re.compile(r"[“”\"'「」『』（）()\[\]【】《》〈〉、，。：:；;！!？?．.·•…\-–—　\s]+")
_SOURCE_SUFFIX = re.compile(r"\s+[-–—]\s+[^-–—]{1,20}$")


def news_dir(root) -> Any:
    from pathlib import Path

    return Path(root) / "data" / "news"


def parse_published(text: str | None) -> datetime | None:
    """Parse RSS pubDate / ISO timestamps into aware Asia/Taipei datetime."""
    if not text:
        return None
    s = text.strip()
    if not s:
        return None
    dt: datetime | None = None
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        iso = s.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_TAIPEI)
    return dt.astimezone(TZ_TAIPEI)


def clean_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _TRACKING_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept, doseq=True), ""))


def strip_source_suffix(title: str, source: str | None = None) -> str:
    t = re.sub(r"\s+", " ", (title or "").strip())
    if source:
        suf = f" - {source}"
        if t.endswith(suf):
            return t[: -len(suf)].rstrip()
    return _SOURCE_SUFFIX.sub("", t).strip() or t


def normalize_headline(title: str) -> str:
    s = strip_source_suffix(title)
    s = s.lower()
    s = _PUNCT.sub("", s)
    return s


def headlines_similar(a: str, b: str, threshold: float = SIMILARITY) -> bool:
    na, nb = normalize_headline(a), normalize_headline(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 10 and shorter in longer:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_rss_items(xml_text: str, default_source: str) -> list[dict[str, Any]]:
    """Extract title / link / published_at / source only. Never keeps description."""
    text = (xml_text or "").lstrip("\ufeff")
    root = ET.fromstring(text)
    items: list[dict[str, Any]] = []
    for node in root.iter():
        if _local(node.tag) != "item":
            continue
        title = link = pub = source_name = ""
        source_url = ""
        for child in list(node):
            name = _local(child.tag)
            if name == "title":
                title = (child.text or "").strip()
            elif name == "link":
                link = (child.text or "").strip() or (child.attrib.get("href") or "")
            elif name == "pubDate":
                pub = (child.text or "").strip()
            elif name == "source":
                source_name = (child.text or "").strip()
                source_url = (child.attrib.get("url") or "").strip()
        title = strip_source_suffix(title, source_name or default_source)
        url = clean_url(link)
        published = parse_published(pub)
        if not title or not url:
            continue
        items.append(
            {
                "title": title,
                "url": url,
                "published_at": published,
                "source": default_source,
                "origin_source": source_name or default_source,
                "origin_home": source_url,
            }
        )
    return items


def parse_cnyes_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep only headline, article URL and publish time. Drop content/summary."""
    raw = (((payload or {}).get("items") or {}).get("data") or [])
    items: list[dict[str, Any]] = []
    for row in raw:
        news_id = row.get("newsId")
        title = strip_source_suffix(str(row.get("title") or ""))
        if not news_id or not title:
            continue
        published = None
        ts = row.get("publishAt")
        if isinstance(ts, (int, float)):
            published = datetime.fromtimestamp(int(ts), tz=TZ_TAIPEI)
        items.append(
            {
                "title": title,
                "url": CNYES_URL.format(news_id=news_id),
                "published_at": published,
                "source": "鉅亨網",
                "origin_source": "鉅亨網",
                "origin_home": "",
            }
        )
    return items


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": ACCEPT_RSS, "Accept-Language": "zh-TW,zh;q=0.9"})
    return s


def _get(session: requests.Session, url: str) -> requests.Response:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            time.sleep(SPACING if attempt == 0 else 1.2 * attempt)
            r = session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001 — retry then surface to caller
            last = exc
            logger.warning("news fetch attempt %s failed for %s: %s", attempt + 1, url, exc)
    assert last is not None
    raise last


def fetch_feed(session: requests.Session, feed: dict[str, str]) -> list[dict[str, Any]]:
    r = _get(session, feed["url"])
    if feed["kind"] == "cnyes":
        return parse_cnyes_items(r.json())
    # encoding: let requests detect; fall back to utf-8
    r.encoding = r.apparent_encoding or "utf-8"
    return parse_rss_items(r.text, feed["name"])


def include_prior_evening(now: datetime, today_count: int) -> bool:
    local = now.astimezone(TZ_TAIPEI)
    return local.hour < MORNING_HOUR or today_count < MIN_TODAY_ITEMS


def _item_ts(item: dict[str, Any]) -> datetime:
    dt = item.get("published_at")
    if isinstance(dt, datetime):
        return dt.astimezone(TZ_TAIPEI)
    return datetime(1970, 1, 1, tzinfo=TZ_TAIPEI)


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop near-identical headlines. Prefer official sources, then earlier pub time."""

    def sort_key(it: dict[str, Any]) -> tuple:
        pri = SOURCE_PRIORITY.get(it.get("source") or "", 5)
        return (pri, _item_ts(it))

    kept: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for it in sorted(items, key=sort_key):
        url = it.get("url") or ""
        if url and url in seen_urls:
            continue
        title = it.get("title") or ""
        if any(headlines_similar(title, k["title"]) for k in kept):
            continue
        kept.append(it)
        if url:
            seen_urls.add(url)
    return kept


def classify_items(
    items: list[dict[str, Any]],
    *,
    today: date,
    now: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    today_items: list[dict[str, Any]] = []
    evening_items: list[dict[str, Any]] = []
    yesterday = today - timedelta(days=1)
    evening_start = datetime(yesterday.year, yesterday.month, yesterday.day, PRIOR_EVENING_HOUR, tzinfo=TZ_TAIPEI)
    for it in items:
        dt = it.get("published_at")
        if not isinstance(dt, datetime):
            # undated: treat as today so the item is not silently dropped
            today_items.append(it)
            continue
        local = dt.astimezone(TZ_TAIPEI)
        if local.date() == today:
            today_items.append(it)
        elif evening_start <= local and local.date() == yesterday:
            evening_items.append(it)
    return today_items, evening_items


def _serialize_item(it: dict[str, Any], bucket: str) -> dict[str, Any]:
    dt = it.get("published_at")
    iso = dt.astimezone(TZ_TAIPEI).isoformat(timespec="seconds") if isinstance(dt, datetime) else None
    hm = dt.astimezone(TZ_TAIPEI).strftime("%H:%M") if isinstance(dt, datetime) else "—"
    origin = it.get("origin_source") or it["source"]
    # For Google News, show the underlying outlet when the feed provides it
    display_source = origin if it["source"] == "Google 新聞" and origin else it["source"]
    if it["source"] == "Google 新聞" and origin and origin != "Google 新聞":
        display_source = f"{origin}（Google 新聞）"
    return {
        "title": it["title"],
        "url": it["url"],
        "source": display_source,
        "source_id": it.get("source_id") or it["source"],
        "published_at": iso,
        "published_hm": hm,
        "bucket": bucket,
    }


def assemble_digest(
    collected: list[dict[str, Any]],
    source_status: list[dict[str, Any]],
    *,
    today: date,
    now: datetime,
    generated_at: str | None = None,
) -> dict[str, Any]:
    tagged = []
    for it in collected:
        row = dict(it)
        tagged.append(row)
    today_items, evening_items = classify_items(tagged, today=today, now=now)
    # Dedupe within today, then maybe keep prior-evening leftovers
    today_kept = dedupe_items(today_items)
    evening_kept = []
    if include_prior_evening(now, len(today_kept)):
        for it in dedupe_items(evening_items):
            if any(headlines_similar(it["title"], k["title"]) for k in today_kept):
                continue
            evening_kept.append(it)

    def newest_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(rows, key=_item_ts, reverse=True)

    today_sorted = newest_first(today_kept)
    evening_sorted = newest_first(evening_kept)
    items = [_serialize_item(it, "today") for it in today_sorted] + [
        _serialize_item(it, "prior_evening") for it in evening_sorted
    ]
    ok_names = []
    fail_names = []
    seen_ok: set[str] = set()
    seen_fail: set[str] = set()
    per_source: dict[str, int] = {}
    for st in source_status:
        name = st["name"]
        if st.get("ok"):
            if name not in seen_ok:
                ok_names.append(name)
                seen_ok.add(name)
        else:
            if name not in seen_fail:
                fail_names.append(name)
                seen_fail.add(name)
    for it in items:
        # count by primary outlet family (before Google annotation)
        key = it["source"].split("（")[0]
        per_source[key] = per_source.get(key, 0) + 1
    return {
        "as_of_date": today.isoformat(),
        "generated_at": generated_at or now.astimezone(TZ_TAIPEI).isoformat(timespec="seconds"),
        "sources": source_status,
        "ok_sources": ok_names,
        "failed_sources": fail_names,
        "today_count": len(today_sorted),
        "prior_evening_count": len(evening_sorted),
        "total": len(items),
        "per_source": per_source,
        "items": items,
        "note_futu": "富途牛牛沒有可穩定使用的官方公開 RSS／API，因此未列入來源。",
    }


def update_news(root, *, session_factory: Callable[[], requests.Session] | None = None) -> dict[str, Any]:
    """Fetch all feeds, write data/news/latest.json. Never raises into the pipeline."""
    from pathlib import Path

    root = Path(root)
    now = datetime.now(TZ_TAIPEI)
    today = now.date()
    collected: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []
    try:
        session = (session_factory or _session)()
        for feed in FEEDS:
            try:
                rows = fetch_feed(session, feed)
                for row in rows:
                    row["source_id"] = feed["id"]
                collected.extend(rows)
                status.append(
                    {
                        "id": feed["id"],
                        "name": feed["name"],
                        "ok": True,
                        "count": len(rows),
                        "error": None,
                    }
                )
                logger.info("news %s: %s items", feed["id"], len(rows))
            except Exception as exc:  # noqa: BLE001 — one feed must not break others
                logger.exception("news source failed: %s", feed["id"])
                status.append(
                    {
                        "id": feed["id"],
                        "name": feed["name"],
                        "ok": False,
                        "count": 0,
                        "error": str(exc)[:240],
                    }
                )
        digest = assemble_digest(
            collected, status, today=today, now=now, generated_at=now_taipei_iso()
        )
    except Exception:  # noqa: BLE001
        logger.exception("news update failed")
        digest = {
            "as_of_date": today.isoformat(),
            "generated_at": now_taipei_iso(),
            "sources": status,
            "ok_sources": [],
            "failed_sources": [s["name"] for s in status],
            "today_count": 0,
            "prior_evening_count": 0,
            "total": 0,
            "per_source": {},
            "items": [],
            "note_futu": "富途牛牛沒有可穩定使用的官方公開 RSS／API，因此未列入來源。",
            "error": "update_news failed",
        }
    write_json(news_dir(root) / "latest.json", digest)
    return digest


def build_news_view(root) -> dict[str, Any] | None:
    from pathlib import Path

    path = news_dir(Path(root)) / "latest.json"
    if not path.is_file():
        return None
    try:
        data = read_json(path)
    except Exception:  # noqa: BLE001
        logger.exception("failed to read news digest")
        return None
    if not isinstance(data, dict):
        return None
    items = data.get("items") or []
    ga = str(data.get("generated_at") or "")
    data["generated_at_display"] = (ga.replace("T", " ").split("+")[0][:16] if ga else "—")
    data["preview"] = [it for it in items if it.get("bucket") == "today"][:10]
    if len(data["preview"]) < 10:
        extra = [it for it in items if it.get("bucket") != "today"]
        data["preview"] = (data["preview"] + extra)[:10]
    data["today_items"] = [it for it in items if it.get("bucket") != "prior_evening"]
    data["evening_items"] = [it for it in items if it.get("bucket") == "prior_evening"]
    return data
