from tw_etf_pages.sitc_first_buy import (
    first_buy_for,
    parse_t86,
    parse_tpex_closes,
    parse_tpex_insti,
    parse_twse_closes,
)

T86 = {
    "fields": ["證券代號", "證券名稱", "投信買進股數", "投信賣出股數", "投信買賣超股數"],
    "data": [
        ["2330", "台積電  ", "1", "1", "1,234,000"],
        ["2317", "鴻海", "0", "0", "0"],
        ["00981A", "主動統一台股增長", "0", "0", "5,000"],
        ["2882A", "國泰金甲特", "0", "0", "1,000"],
        ["3008", "大立光", "0", "0", "-45,000"],
    ],
}


def test_parse_t86_keeps_only_nonzero_stocks():
    rows = parse_t86(T86)
    assert set(rows) == {"2330", "3008"}
    assert rows["2330"] == {"n": "台積電", "m": "上市", "net": 1234000}
    assert rows["3008"]["net"] == -45000


def test_parse_twse_closes_sign():
    js = {
        "tables": [
            {
                "fields": ["證券代號", "證券名稱", "a", "b", "c", "d", "e", "f", "收盤價", "漲跌(+/-)", "漲跌價差"],
                "data": [
                    ["2330", "台積電", "", "", "", "", "", "", "1,000.00", "<p style= color:red>+</p>", "10.00"],
                    ["3008", "大立光", "", "", "", "", "", "", "2,000.00", "<p style= color:green>-</p>", "20.00"],
                    ["9999", "停牌", "", "", "", "", "", "", "--", " ", "0.00"],
                ],
            }
        ]
    }
    assert parse_twse_closes(js) == {"2330": (1000.0, 10.0), "3008": (2000.0, -20.0)}


def _tpex_row(code, name, net):
    z = ["0", "0", "0"]
    inv = ["0", "0", f"{net:,}"]
    return [code, name] + z + z + z + inv + z + z + z + ["0"]


def test_parse_tpex_insti_uses_investment_trust_columns():
    fields = ["代號", "名稱"] + ["買進股數", "賣出股數", "買賣超股數"] * 7 + ["三大法人買賣超股數合計"]
    js = {"tables": [{"fields": fields, "data": [_tpex_row("6488", "環球晶", 300000), _tpex_row("3293", "鈊象", 0)]}]}
    assert parse_tpex_insti(js) == {"6488": {"n": "環球晶", "m": "上櫃", "net": 300000}}


def test_parse_tpex_closes():
    js = {"tables": [{"data": [["6488", "環球晶", "400.50", "+5.00"], ["1111", "x", "----", "---"]]}]}
    assert parse_tpex_closes(js) == {"6488": (400.5, 5.0)}


def _day(rows):
    return {"rows": {c: {"n": c, "m": "上市", "net": n, "c": 100.0, "chg": 1.0} for c, n in rows.items()}}


def test_first_buy_requires_no_buy_in_previous_10_days():
    days = [_day({"1101": -5}) for _ in range(10)]
    days[0] = _day({"2330": 1000, "1101": -5})   # 2330 bought 10 days ago → still within window
    days[9] = _day({"2454": 2000})               # 2454 bought yesterday
    days.append(_day({"2330": 3000, "2454": 4000, "3008": 5000, "1101": 0, "2603": -1}))
    items = first_buy_for(days, 10)
    assert [x["code"] for x in items] == ["3008"]
    # 11 days ago is outside the window → 2330 qualifies again
    days2 = [_day({"2330": 1000})] + [_day({"1101": -5})] + days[1:]
    got = {x["code"] for x in first_buy_for(days2, 11)}
    assert "2330" in got and "2454" not in got


def test_sort_by_amount_and_fields():
    days = [_day({}) for _ in range(10)]
    last = {"rows": {
        "2330": {"n": "台積電", "m": "上市", "net": 1000000, "c": 100.0, "chg": 5.0},
        "6488": {"n": "環球晶", "m": "上櫃", "net": 2000000, "c": 400.0, "chg": -10.0},
        "1234": {"n": "無價", "m": "上櫃", "net": 9000000},
    }}
    items = first_buy_for(days + [last], 10)
    assert [x["code"] for x in items] == ["6488", "2330", "1234"]
    assert items[0]["amount"] == 800000000 and items[0]["chg_pct"] == -2.44
    assert items[1]["chg_pct"] == 5.26 and items[1]["net_lots"] == 1000
    assert items[2]["amount"] is None


def test_window_contiguity_detects_gap_and_honours_holidays():
    from tw_etf_pages.sitc_first_buy import window_is_contiguous

    # 2026-11-02 .. 11-13 are 10 consecutive weekdays, 11-16 is the target
    dates = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06",
             "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16"]
    assert window_is_contiguous(dates, 10, set())
    gap = [d for d in dates if d != "2026-11-05"]
    assert not window_is_contiguous(gap, 9, set())            # missing day, not a known holiday
    assert window_is_contiguous(gap, 9, {"2026-11-05"}) is False  # only 9 prior days stored → too few
    ext = ["2026-10-30"] + gap
    assert window_is_contiguous(ext, 10, {"2026-11-05"})      # known holiday skipped, window shifts back
