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
