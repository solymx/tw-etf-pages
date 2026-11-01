from tw_etf_pages.taiwan_vix import level_of, parse_month_file

SAMPLE = """交易日期\t時間(時/分/秒/毫秒)\t臺指選擇權波動率指數\t收盤前1分鐘平均指數
--------\t-------------------\t--------------------\t-------------------
20261029\t13450000\t\t\t28.25\t\t28.26
20261030\t13450000\t\t\t30.95\t\t30.88
"""


def test_parse_month_file():
    rows = parse_month_file(SAMPLE)
    assert rows == [
        {"date": "2026-10-29", "close": 28.25, "close_1m_avg": 28.26},
        {"date": "2026-10-30", "close": 30.95, "close_1m_avg": 30.88},
    ]


def test_levels():
    assert level_of(31) == "high"
    assert level_of(26) == "elevated"
    assert level_of(22) == "normal"
    assert level_of(17) == "low"
