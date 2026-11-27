from datetime import date

from tw_etf_pages.strategy_common import any_to_date, percentile_rank, roc_ym_to_iso, third_wednesday
from tw_etf_pages.strategy_daily import parse_mi_index, parse_twt93u
from tw_etf_pages import strat_futures as fut
from tw_etf_pages import strat_revenue as rev
from tw_etf_pages import strat_sbl as sbl
from tw_etf_pages import strat_divlowvol as dv


def test_dates():
    assert any_to_date("1151125") == date(2026, 11, 25)
    assert any_to_date("115/11/25") == date(2026, 11, 25)
    assert any_to_date("20261125") == date(2026, 11, 25)
    assert any_to_date("2026/11/25") == date(2026, 11, 25)
    assert any_to_date("990105") == date(2010, 1, 5)
    assert roc_ym_to_iso("11510") == "2026-10"
    assert third_wednesday(2026, 11) == date(2026, 11, 18)


def test_percentile():
    assert percentile_rank([1, 2, 3, 4], 3) == 75.0


def test_parse_mi_index_keeps_common_and_0050():
    js = {"stat": "OK", "date": "20261125", "tables": [{"fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"],
           "data": [["2330", "台積電", "1", "1", "1,000,000", "", "", "", "2,150.00"],
                    ["0050", "元大台灣50", "1", "1", "500", "", "", "", "90.30"],
                    ["00981A", "主動", "1", "1", "500", "", "", "", "10"],
                    ["2881A", "特", "1", "1", "500", "", "", "", "60"],
                    ["9999", "停", "0", "0", "0", "", "", "", "--"]]}]}
    out = parse_mi_index(js, "20261125")
    assert set(out) == {"2330", "0050"}
    assert out["2330"] == ["台積電", "上市", 2150.0, 1000000.0]


def test_parse_twt93u_positions():
    fields = ["代號", "名稱", "前日餘額", "賣出", "買進", "現券", "今日餘額", "次一營業日限額", "前日餘額", "當日賣出", "當日還券", "當日調整", "當日餘額", "次一營業日可限額", "備註"]
    js = {"stat": "OK", "date": "20261125", "fields": fields,
          "data": [["2330", "台積電", "0", "0", "0", "0", "46,000", "x", "0", "0", "0", "0", "17,286,514", "0", ""],
                   ["00400A", "ETF", "0", "0", "0", "0", "1", "x", "0", "0", "0", "0", "5", "0", ""]]}
    out = parse_twt93u(js, "20261125")
    assert out == {"2330": ["台積電", "上市", 17286514, 46000]}


FUT_CSV = """\ufeff日期,商品名稱,身份別,多方交易口數,多方交易契約金額(千元),空方交易口數,空方交易契約金額(千元),多空交易口數淨額,多空交易契約金額淨額(千元),多方未平倉口數,多方未平倉契約金額(千元),空方未平倉口數,空方未平倉契約金額(千元),多空未平倉口數淨額,多空未平倉契約金額淨額(千元)
20261125,臺股期貨,自營商,1,1,1,1,0,0,1,1,1,1,-651,0
20261125,臺股期貨,外資及陸資,1,1,1,1,0,0,1,1,1,1,-105709,0
20261125,小型臺指期貨,外資及陸資,1,1,1,1,0,0,1,1,1,1,-1977,0
"""


def test_parse_fut_csv():
    assert fut.parse_fut_csv(FUT_CSV) == {"2026-11-25": -105709}


def test_futures_score():
    rows = []
    for i in range(70):
        d = date(2026, 1, 1).toordinal() + i
        rows.append({"date": date.fromordinal(d).isoformat(), "foreign_net": -100000 + i * 100, "pc_oi": 50 + (i % 10)})
    out = fut.compute(rows)
    last = out[-1]
    assert last["f_score"] == 1  # rising and above 20d avg
    assert last["score"] == last["f_score"] + last["p_score"]
    assert last["pct60"] == 100.0 and last["extreme"]


def test_revenue_classify():
    assert rev.classify(25, 22, 1, True) == ("bull", "偏多（強）")
    assert rev.classify(25, 22, 1, False) == ("bull", "偏多")
    assert rev.classify(-1, -2, 5, False) == ("bear", "偏空")
    assert rev.classify(25, 10, 1, False)[0] == "neutral"


def test_revenue_mops_parse():
    html = ("<table><tr><th>產業別：半導體業</th></tr><tr align=right><td align=center>2330</td><td align=left>台積電</td>"
            "<td nowrap> 586,890,319</td><td nowrap> 511,857,399</td><td nowrap> 367,473,051</td><td nowrap> 14.65</td>"
            "<Td nowrap> 59.70</td><td nowrap> 4,485,617,293</td><td nowrap> 3,130,436,902</td><td nowrap> 43.29</td>"
            "<td align=left>說明</td></tr></table>")
    out = rev.parse_mops_html(html, "上市")
    assert out["2330"] == ["台積電", "上市", "半導體業", 586890319.0, 59.7, 14.65, 43.29]


def test_revenue_compute_thermometer_and_excludes_financial():
    months = {"2026-10": {"1111": ["A", "上市", "半導體業", 100, 30, 5, 25],
                          "2222": ["B", "上市", "食品工業", 100, -5, 1, -3],
                          "2880": ["金", "上市", "金融保險業", 100, 50, 1, 50]}}
    v = rev.compute(months)
    assert [x["code"] for x in v["items"]] == ["1111", "2222"]
    assert v["share_pos"] == 50.0 and v["verdict"] == "neutral"


def test_sbl_classify():
    assert sbl.classify(95, 1) == "bear"
    assert sbl.classify(95, -30) == "relief"
    assert sbl.classify(85, 5) == "neutral"
    assert sbl.classify(None, 5) == "neutral"


def test_div_parsers():
    js = {"stat": "OK", "fields": ["資料日期", "股票代號", "股票名稱", "x", "y", "z", "權/息"],
          "data": [["", "2330", "台積電", "", "", "", "息"], ["", "4109", "加捷", "", "", "", "權"], ["", "00940", "ETF", "", "", "", "息"]]}
    assert dv.parse_twt49u(js) == {"2330"}
    js2 = {"tables": [{"fields": ["除權息日期", "代號", "名稱", "息值"], "data": [["", "6488", "環球晶", "2.5"], ["", "4109", "加捷", "0"]]}]}
    assert dv.parse_exdailyq(js2) == {"6488"}
    assert dv.rebalance_key(date(2026, 11, 26)) == "2026-06"
    assert dv.rebalance_key(date(2026, 12, 1)) == "2026-12"
    assert dv.rebalance_key(date(2026, 3, 1)) == "2025-12"


def test_parse_fut_any_json():
    js = '[{"Date":"20261125","ContractCode":"臺股期貨","Item":"外資及陸資","OpenInterest(Net)":"-105709","OpenInterestContractAmount(Net)":"-1"},' \
         '{"Date":"20261125","ContractCode":"臺股期貨","Item":"投信","OpenInterest(Net)":"100918","OpenInterestContractAmount(Net)":"1"}]'
    assert fut.parse_fut_any(js) == {"2026-11-25": -105709}
    assert fut.parse_fut_any(FUT_CSV) == {"2026-11-25": -105709}


from tw_etf_pages import strat_52week as wk
from tw_etf_pages import strat_buyback as bb
from tw_etf_pages import strat_insider as ins
from tw_etf_pages import strat_attention as att


def test_52week_adjust_and_classify():
    closes = [("2026-01-02", 100.0), ("2026-01-05", 100.0), ("2026-01-06", 95.0)]
    adj = wk.adjusted(closes, [["2026-01-06", 0.95]])
    assert adj == [95.0, 95.0, 95.0]
    assert wk.classify(0.95, False, True) == "bull"
    assert wk.classify(0.95, False, False) == "neutral"
    assert wk.classify(0.8, False, True) == "neutral"
    assert wk.classify(0.6, False, True) == "bear"
    assert wk.classify(1.0, True, True) == "bull"


def test_twt49u_factors():
    js = {"stat": "OK", "fields": ["資料日期", "股票代號", "股票名稱", "除權息前收盤價", "除權息參考價"],
          "data": [["115年06月11日", "2330", "台積電", "2,000.00", "1,994.00"], ["115年06月11日", "00940", "ETF", "9", "8.9"]]}
    assert wk.parse_twt49u_factors(js) == {"2330": [["2026-06-11", 0.997]]}


DESC = ("1.董事會決議日期:115/11/26\r\n2.買回股份目的:維護公司信用及股東權益並註銷股份\r\n4.買回股份總金額上限(元):1\r\n"
        "5.預定買回之期間:115/11/27~116/01/26\r\n7.買回區間價格(元):75.00~197.00，公司股價低於區間價格下限，將繼續買回\r\n"
        "9.預定買回股份占公司已發行股份總數之比率(%):2.41\r\n")


def test_buyback_parse_and_filter():
    d = bb.parse_desc(DESC)
    assert d["lo"] == 75.0 and d["hi"] == 197.0 and d["ratio"] == 2.41
    assert d["from"] == "2026-11-27" and d["to"] == "2027-01-26"
    assert "註銷" in d["tags"] and "維護股東權益" in d["tags"]
    js = [{"發言日期": "1151126", "公司代號": "6902", "公司名稱": "X", "主旨 ": "公告本公司董事會決議買回庫藏股", "符合條款": "第35款", "說明": DESC},
          {"發言日期": "1151126", "公司代號": "6903", "公司名稱": "Y", "主旨 ": "公告本公司買回庫藏股執行完畢", "符合條款": "第35款", "說明": DESC},
          {"發言日期": "1151126", "公司代號": "6904", "公司名稱": "Z", "主旨 ": "公告更名", "符合條款": "第51款", "說明": ""}]
    rows = bb.parse_rows(js, "上市")
    assert [r["code"] for r in rows] == ["6902"]
    assert bb.classify(rows[0], 0.2) == "bull"
    assert bb.classify(rows[0], 0.7) == "neutral"


def test_insider_classify():
    base = {"method": "一般交易", "identity": "董事本人", "ratio": 12.0}
    assert ins.classify(base) == "bear"
    assert ins.classify({**base, "method": "贈與"}) == "neutral"
    assert ins.classify({**base, "ratio": 2.0}) == "neutral"
    assert ins.classify({**base, "ratio": 5.0}) == "watch"
    assert ins.classify({**base, "identity": "經理人本人"}) == "watch"


def test_attention_parse():
    assert att.parse_info("最近六個營業日累積收盤價漲幅達59.00%﹝第一款﹞。") == ("第1款", "漲幅")
    assert att.parse_info("當日沖銷成交量占總成交量比率達65.99%（第十三款)") == ("第13款", "其他")
    assert att.parse_info("跌幅達48.92%(第一款)") == ("第1款", "跌幅")
    assert att.cn_num("二十一") == 21
    assert att.classify("漲幅", 3)[0] == "bear"
    assert att.classify("漲幅", 6)[0] == "neutral"


from tw_etf_pages import strat_cb as cbm
from tw_etf_pages import strat_dilution as dlm
from tw_etf_pages import strat_lottery as ltm


def test_cb_parse_and_kinds():
    js = [{"IssuerCode": "2492", "IssuerName": "華新科", "BondCode": "24922", "ShortName": "華新科二", "ListingStatus": "2",
           "IssueDate": "20261106", "ListingDate": "20261106", "IssueAmount": "4500000000", "OutstandingAmount": "4500000000",
           "Conversion/ExchangePriceAtIssuance": "497.0000"},
          {"IssuerCode": "00009815", "BondCode": "", "ListingStatus": "5", "IssueDate": "20260309"},
          {"IssuerCode": "1234", "BondCode": "1234E", "ListingStatus": "2", "IssueDate": "20260309"}]
    rows = cbm.parse_rows(js)
    assert list(rows) == ["24922"] and rows["24922"]["listing_date"] == "2026-11-06"
    assert cbm.change_kind("債權人執行賣回權") == "redeem"
    assert cbm.change_kind("債權人執行轉換") == "convert"
    assert cbm.trading_days_since("2026-11-20", ["2026-11-20", "2026-11-23", "2026-11-24"]) == 2


def test_dilution_parsers():
    t48 = [{"Date": "1151207", "Code": "2646", "Name": "星宇航空", "SubscriptionRatio": "0.09970967", "SubscriptionPricePerShare": "尚未公告"},
           {"Date": "1151208", "Code": "00400A", "Name": "ETF", "SubscriptionRatio": ""},
           {"Date": "1151208", "Code": "2330", "Name": "台積電", "SubscriptionRatio": ""}]
    rows = dlm.parse_twt48u(t48)
    assert len(rows) == 1 and rows[0]["ratio"] == 9.971 and rows[0]["ex_date"] == "2026-12-07" and rows[0]["price"] is None
    pre = [{"ExRrightsExDividendDate": "1151203", "SecuritiesCompanyCode": "6160", "CompanyName": "欣技",
            "SubscriptionRatioToNewSharesIssued": "0.16060945", "SubscriptionPricePerShare": "註4"},
           {"ExRrightsExDividendDate": "1151117", "SecuritiesCompanyCode": "00740B", "SubscriptionRatioToNewSharesIssued": "0.00000000"}]
    r2 = dlm.parse_tpex_pre(pre)
    assert len(r2) == 1 and r2[0]["ratio"] == 16.061 and r2[0]["price_note"] == "尚未公告"


def test_lottery_returns_use_exright_reference_and_drop_limits():
    mk = lambda d, c: {"date": d, "rows": {"1111": ["A", "上市", c, 1e8], "2222": ["B", "上市", 10.0, 1e8]}}
    series = [mk("2026-01-02", 100.0), mk("2026-01-05", 95.0), mk("2026-01-06", 120.0)]
    series[0]["rows"]["2222"][2] = 10.0
    rets = ltm.daily_returns(series, {"1111": [["2026-01-05", 0.95]]})
    assert abs(rets[1]["1111"]) < 1e-9          # ex-dividend day is flat vs reference
    assert "1111" not in rets[2]                # +26% exceeds price limit → excluded


# ---------------------------------------------------------------- batch 4: regime / option seller
from datetime import date as _date

from tw_etf_pages import strat_options as sop
from tw_etf_pages import strat_regime as srg


def test_regime_parsers_roc_and_openapi():
    js = {"stat": "OK", "data": [["115/11/26", "38,100.10", "38,500.00", "37,900.50", "38,200.00"]]}
    assert srg.parse_rwd(js) == [{"date": "2026-11-26", "open": 38100.1, "high": 38500.0, "low": 37900.5, "close": 38200.0}]
    assert srg.parse_rwd({"stat": "很抱歉"}) == []
    rows = srg.parse_openapi([{"Date": "1151102", "OpeningIndex": "45034.53", "HighestIndex": "45156.17",
                               "LowestIndex": "44399.10", "ClosingIndex": "44920.14"}])
    assert rows[0]["date"] == "2026-11-02" and rows[0]["close"] == 44920.14


def test_yahoo_drops_today_and_never_overrides_official():
    ts = [1764000000, 1764086400]  # 2025-11-25 / 26 (UTC+8 dates)
    js = {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [
        {"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, 2]}]}}]}}
    d1 = srg.datetime.fromtimestamp(ts[1], srg.timezone(srg.timedelta(hours=8))).date()
    rows = srg.parse_yahoo(js, d1)
    assert len(rows) == 1 and rows[0]["src"] == "yahoo"
    by = {rows[0]["date"]: {"date": rows[0]["date"], "open": 9, "high": 9, "low": 9, "close": 9, "src": "twse"}}
    assert srg.merge_rows(by, rows, "yahoo") == 0 and by[rows[0]["date"]]["close"] == 9


def _synthetic(closes):
    return [{"date": f"2020-01-{i:03d}", "open": c, "high": c * 1.005, "low": c * 0.995, "close": c}
            for i, c in enumerate(closes)]


def test_regime_trend_and_range_classification():
    up = srg.indicators(_synthetic([100 * 1.004 ** i for i in range(260)]))
    last = up[-1]
    assert last["adx"] > 25 and last["pdi"] > last["mdi"] and last["er20"] > 0.9
    assert last["regime"] == "趨勢盤" and last["direction"] == "偏多"
    flat = [100 + (0.3 if i % 2 else -0.3) for i in range(260)]
    o = srg.indicators(_synthetic(flat))[-1]
    assert o["er20"] < 0.1 and o["regime"] != "趨勢盤"
    assert srg.classify({"adx": 38.8, "pdi": 18.8, "mdi": 42.6, "er20": 0.26, "width_pct": 98.7, "range20": 10}) == ("高波動動盪", "偏空")
    assert srg.classify({"adx": 22, "pdi": 20, "mdi": 18, "er20": 0.3, "width_pct": 50, "range20": 8}) == ("過渡", "中性")
    assert srg.classify({"adx": 15, "pdi": 20, "mdi": 18, "er20": 0.2, "width_pct": 25, "range20": 6}) == ("低波動盤整", "中性")


def test_dca_advice_and_margin():
    assert srg.dca_advice("低波動盤整", "中性", 170)["text"] == "照常扣款"
    a = srg.dca_advice("高波動動盪", "偏空", 145)
    assert a["text"].startswith("照常扣款，但不加碼、不借錢加碼") and "先降槓桿" in a["text"] and a["label"]["cls"] == "bear"
    assert srg.dca_advice("過渡", "中性", None)["label"]["cls"] == "neutral"


def test_option_expiry_and_picks():
    assert sop.expiry_of("202612W1")[0] == _date(2026, 12, 2)
    assert sop.expiry_of("202611F4") == (_date(2026, 11, 27), "weekly")
    assert sop.expiry_of("202612") == (_date(2026, 12, 16), "monthly")
    picks = sop.pick_contracts("2026-11-26", {"202611F4": [], "202612W1": [], "202612": [], "202701": []})
    assert picks == {"weekly": "202611F4", "monthly": "202612"}
    rows = [[k, cp, None, 10.0, 100, 5] for k in range(36000, 44001, 100) for cp in "CP"]
    t = sop.strike_table(rows, 40000)
    assert [(r["cp"][:2], r["strike"]) for r in t] == [("賣權", 38000), ("賣權", 36000), ("買權", 42000), ("買權", 44000)]
    assert t[0]["twd"] == 500


def test_option_light_and_vix_stable():
    calm = [{"date": f"d{i}", "close": 16.0} for i in range(30)]
    ok, _ = sop.vix_stable(calm)
    assert ok is True
    spike = calm[:-1] + [{"date": "x", "close": 21.0}]
    assert sop.vix_stable(spike)[0] is False
    assert sop.light("低波動盤整", True)["color"] == "green"
    assert sop.light("低波動盤整", False)["color"] == "yellow"
    assert sop.light("高波動動盪", True)["text"] == "紅（偏空，不碰賣方）"
    assert sop.light("趨勢盤", True)["text"] == "紅（不碰賣方）"
    assert sop.light("過渡", True)["color"] == "yellow"


def test_parse_opt_regular_session_only():
    raw = [{"Date": "20261126", "Contract": "TXO", "ContractMonth(Week)": "202612W1", "StrikePrice": "38000",
            "CallPut": "賣權", "Close": "120", "SettlementPrice": "118", "OpenInterest": "1,234", "Volume": "50",
            "TradingSession": "一般"},
           {"Date": "20261126", "Contract": "TXO", "ContractMonth(Week)": "202612W1", "StrikePrice": "38000",
            "CallPut": "賣權", "Close": "-", "SettlementPrice": "-", "OpenInterest": "-", "Volume": "0",
            "TradingSession": "盤後"},
           {"Date": "20261126", "Contract": "CAO", "ContractMonth(Week)": "202612", "StrikePrice": "1",
            "CallPut": "買權", "TradingSession": "一般"}]
    d, c = sop.parse_opt(raw)
    assert d == "2026-11-26" and c == {"202612W1": [[38000.0, "P", 120.0, 118.0, 1234.0, 50.0]]}


def test_strategy_intro_blocks_have_five_parts():
    from tw_etf_pages.strat_intro import INTROS
    keys = {"revenue", "dividend-lowvol", "futures-pc", "sbl", "52week", "buyback", "insider", "attention",
            "cb", "dilution", "lottery", "regime", "option-seller"}
    assert set(INTROS) == keys
    for k, d in INTROS.items():
        assert list(d) == ["what", "why", "how", "evidence", "limits"], k
        assert all(str(v).strip() for v in d.values()), k
        assert "不構成投資建議" in d["limits"], k
    assert "doi.org" not in INTROS["regime"]["evidence"] and "連結待查證" in INTROS["regime"]["evidence"]
    assert "期刊論文（臺灣銀行季刊）" in INTROS["option-seller"]["evidence"]
