from datetime import datetime

from tw_etf_pages.news import (
    assemble_digest,
    classify_items,
    dedupe_items,
    headlines_similar,
    include_prior_evening,
    normalize_headline,
    parse_cnyes_items,
    parse_published,
    parse_rss_items,
    strip_source_suffix,
)
from tw_etf_pages.utils import TZ_TAIPEI

CTEE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>工商時報 證券</title>
  <item>
    <title>大盤反彈千點 台積電收紅</title>
    <link>https://www.ctee.com.tw/news/20261126700001-430201</link>
    <description>完整內文不應被保存或使用</description>
    <pubDate>2026-11-26T20:55:23</pubDate>
  </item>
  <item>
    <title>  </title>
    <link>https://www.ctee.com.tw/news/empty</link>
    <pubDate>2026-11-26T20:00:00</pubDate>
  </item>
</channel></rss>
"""

UDN_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title><![CDATA[美光桃園廠勞資爭議持續延燒]]></title>
    <link>https://money.udn.com/money/story/5612/9904382?utm_source=rss&amp;utm_medium=RSS</link>
    <pubDate>Thu, 26 Nov 2026 20:40:44 +0800</pubDate>
    <description><![CDATA[摘要也不該留下]]></description>
  </item>
</channel></rss>
"""

GNEWS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>台股勁揚逾1200點後拉回 台積電平盤2150元 - Yahoo新聞</title>
    <link>https://news.google.com/rss/articles/CBMiABC?oc=5</link>
    <pubDate>Thu, 26 Nov 2026 03:37:41 GMT</pubDate>
    <source url="https://tw.news.yahoo.com">Yahoo新聞</source>
    <description>HTML snippet must not be kept</description>
  </item>
</channel></rss>
"""


def test_parse_rss_keeps_only_headline_link_time():
    items = parse_rss_items(CTEE_RSS, "工商時報")
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "大盤反彈千點 台積電收紅"
    assert it["url"].startswith("https://www.ctee.com.tw/news/")
    assert it["published_at"] == datetime(2026, 11, 26, 20, 55, 23, tzinfo=TZ_TAIPEI)
    assert "完整內文" not in repr(it)
    assert "description" not in it


def test_parse_rfc2822_and_strips_tracking():
    items = parse_rss_items(UDN_RSS, "經濟日報")
    assert items[0]["published_at"] == datetime(2026, 11, 26, 20, 40, 44, tzinfo=TZ_TAIPEI)
    assert "utm_" not in items[0]["url"]
    assert items[0]["url"] == "https://money.udn.com/money/story/5612/9904382"


def test_google_news_keeps_article_link_and_strips_source_suffix():
    items = parse_rss_items(GNEWS_RSS, "Google 新聞")
    assert len(items) == 1
    assert items[0]["title"] == "台股勁揚逾1200點後拉回 台積電平盤2150元"
    assert items[0]["url"].startswith("https://news.google.com/rss/articles/")
    assert "oc=" not in items[0]["url"]
    assert items[0]["origin_source"] == "Yahoo新聞"
    # GMT 03:37 = Taipei 11:37
    assert items[0]["published_at"] == datetime(2026, 11, 26, 11, 37, 41, tzinfo=TZ_TAIPEI)


def test_cnyes_extracts_url_and_drops_body():
    payload = {
        "items": {
            "data": [
                {
                    "newsId": 6673237,
                    "title": "外資連4賣仍大漲7%",
                    "publishAt": 1795697734,
                    "content": "<p>不應出現在結果裡</p>",
                    "summary": "也不該留下",
                }
            ]
        }
    }
    items = parse_cnyes_items(payload)
    assert items[0]["url"] == "https://news.cnyes.com/news/id/6673237"
    assert items[0]["title"] == "外資連4賣仍大漲7%"
    assert items[0]["published_at"] == datetime(2026, 11, 26, 20, 55, 34, tzinfo=TZ_TAIPEI)
    assert "content" not in items[0] and "summary" not in items[0]


def test_parse_published_naive_iso_is_taipei():
    assert parse_published("2026-11-26T07:00:00").hour == 7
    assert parse_published("Thu, 26 Nov 2026 00:00:00 GMT").hour == 8


def test_normalize_and_similar_headlines():
    a = "台股勁揚逾1200點後拉回  台積電平盤2150元 - Yahoo新聞"
    b = "台股勁揚逾1200點後拉回，台積電平盤2150元"
    assert normalize_headline(a) == normalize_headline(strip_source_suffix(b)) or headlines_similar(a, b)
    assert headlines_similar(a, b)
    assert not headlines_similar("台積電法說會重點一次看", "聯電法說會重點一次看")


def _item(title, source, hour, minute=0, day=26, url=None):
    return {
        "title": title,
        "url": url or f"https://example.com/{source}/{hour}{minute}{title}",
        "published_at": datetime(2026, 11, day, hour, minute, tzinfo=TZ_TAIPEI),
        "source": source,
        "origin_source": source,
        "source_id": source,
    }


def test_dedupe_prefers_official_over_google():
    official = _item("大盤反彈千點 台積電收紅", "工商時報", 19)
    google = _item("大盤反彈千點，台積電收紅", "Google 新聞", 20)
    kept = dedupe_items([google, official])
    assert len(kept) == 1
    assert kept[0]["source"] == "工商時報"


def test_dedupe_same_url_and_near_identical():
    a = _item("施振榮：台灣可攜手國際引領AI智慧化", "中央社", 20, url="https://www.cna.com.tw/a")
    b = _item("施振榮：台灣可攜手國際引領AI智慧化", "經濟日報", 20, 12, url="https://www.cna.com.tw/a")
    c = _item("施振榮談台灣可攜手國際引領AI智慧化", "自由時報", 20, 30)
    kept = dedupe_items([a, b, c])
    assert len(kept) == 1


def test_morning_includes_prior_evening_and_midday_does_not():
    today = [
        _item("今日早報", "中央社", 6, day=26),
        _item("今日盤勢", "工商時報", 7, day=26),
    ]
    evening = _item("昨晚收盤", "經濟日報", 21, day=25)
    morning = datetime(2026, 11, 26, 7, 0, tzinfo=TZ_TAIPEI)
    t, e = classify_items(today + [evening, _item("昨天中午", "中央社", 12, day=25)], today=morning.date(), now=morning)
    assert len(t) == 2
    assert [x["title"] for x in e] == ["昨晚收盤"]

    afternoon = datetime(2026, 11, 26, 17, 0, tzinfo=TZ_TAIPEI)
    many = today + [_item(f"盤中{i}", "鉅亨網", 10, i, day=26) for i in range(10)]
    t2, e2 = classify_items(many + [evening], today=afternoon.date(), now=afternoon)
    assert len(t2) == 12
    assert [x["title"] for x in e2] == ["昨晚收盤"]  # filter applied later in assemble_digest


def test_include_prior_evening_when_today_is_thin():
    noon = datetime(2026, 11, 26, 12, 0, tzinfo=TZ_TAIPEI)
    assert include_prior_evening(noon, 3) is True
    assert include_prior_evening(noon, 20) is False
    dawn = datetime(2026, 11, 26, 7, 0, tzinfo=TZ_TAIPEI)
    assert include_prior_evening(dawn, 20) is True


def test_assemble_digest_sorts_newest_first_and_labels_buckets():
    now = datetime(2026, 11, 26, 7, 5, tzinfo=TZ_TAIPEI)
    items = [
        _item("昨晚收盤整理", "經濟日報", 18, day=25),
        _item("稍早快訊", "中央社", 6, 30, day=26),
        _item("最新快訊", "工商時報", 7, 0, day=26),
    ]
    status = [
        {"id": "ctee_stock", "name": "工商時報", "ok": True, "count": 1, "error": None},
        {"id": "udn_stock", "name": "經濟日報", "ok": True, "count": 1, "error": None},
        {"id": "cna", "name": "中央社", "ok": True, "count": 1, "error": None},
        {"id": "cnyes", "name": "鉅亨網", "ok": False, "count": 0, "error": "403"},
    ]
    digest = assemble_digest(items, status, today=now.date(), now=now, generated_at="2026-11-26T07:05:00+08:00")
    assert [x["title"] for x in digest["items"]] == ["最新快訊", "稍早快訊", "昨晚收盤整理"]
    assert digest["items"][0]["bucket"] == "today"
    assert digest["items"][-1]["bucket"] == "prior_evening"
    assert digest["today_count"] == 2 and digest["prior_evening_count"] == 1
    assert digest["ok_sources"] == ["工商時報", "經濟日報", "中央社"]
    assert digest["failed_sources"] == ["鉅亨網"]
    assert digest["items"][0]["published_hm"] == "07:00"
