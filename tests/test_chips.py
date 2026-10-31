from tw_etf_pages.chips import TdccQuery


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _Sess:
    def __init__(self, text):
        self._t = text

    def post(self, *a, **k):
        return _Resp(self._t)


def _html(total_level):
    return (
        '<input name="SYNCHRONIZER_TOKEN" value="tok2" />'
        "<span>資料日期：115年10月22日</span><table>"
        "<tr><td>15</td><td>1,000,001以上</td><td>1,476</td><td>21,893,080,824</td><td>84.42</td></tr>"
        f"<tr><td>{total_level}</td><td>合 計</td><td>3,166,709</td><td>25,932,370,067</td><td>100.00</td></tr>"
        "</table>"
    )


def test_query_parses_level15_and_total_both_layouts():
    for lvl in (16, 17):
        q = TdccQuery(_Sess(_html(lvl)))
        q.token = "tok"
        v = q.query("2330", "20261022")
        assert v == {
            "big_holders": 1476,
            "big_shares": 21893080824,
            "big_pct": 84.42,
            "total_holders": 3166709,
            "total_shares": 25932370067,
        }
        assert q.token == "tok2"
