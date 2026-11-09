import json
from datetime import date

from tw_etf_pages.ctbc_derivatives import build_ctbc_derivatives_view, normalize, update_ctbc_derivatives


def _data(d, opts, fut=None):
    return {
        "FundAssets": [{"資料日期": d, "基金淨資產": "144,036,896,860"}],
        "FundAssetsDetail": [
            {"Code": "STOCK", "Sum": 83.02, "Data": [{"invtp_": "STOCK", "code_": "2330"}]},
            {"Code": "FUTURE", "Sum": 20.85, "Data": fut or []},
            {"Code": "OPTION", "Sum": round(sum(float(o["weights_"]) for o in opts), 2), "Data": opts},
        ],
    }


def _opt(code, qty, w, right="C"):
    return {"invtp_": "OTO", "code_": code, "name_": "臺指選擇權", "ename_": right, "ym_": "202611", "qty_": qty, "weights_": w, "amount_": "1"}


TX = [{"invtp_": "FUTURE", "code_": "TX", "name_": "臺股期貨", "ym_": "202611", "qty_": "3,620.00", "weights_": "20.85"}]


def test_normalize_sell_call():
    s = normalize("00406A", _data("2026/11/09", [_opt("TX2", "-15,000.00", "-16.74")], TX))
    assert s["as_of_date"] == "2026-11-09"
    o = s["options"][0]
    assert (o["side"], o["right"], o["contracts"], o["weight_pct"]) == ("sell", "C", 15000, -16.74)
    assert "strike" not in o  # never invented
    assert s["futures"][0]["side"] == "long" and s["futures"][0]["contracts"] == 3620


class FakeClient:
    def __init__(self, by_date):
        self.by_date = by_date

    def auth(self):
        pass

    def fid_map(self):
        return {"00406A": "E0038"}

    def holding_weight(self, fid, d):
        return self.by_date.get(d.isoformat()) or _data("2026/11/06", [])


def test_update_skips_non_matching_dates_and_view_deltas(tmp_path):
    days = {
        "2026-11-06": _data("2026/11/06", [_opt("TXV", "-5,000.00", "-4.86"), _opt("TX2", "-15,000.00", "-12.49")], TX),
        "2026-11-09": _data("2026/11/09", [_opt("TX2", "-16,000.00", "-16.74"), _opt("TX3", "-1,000.00", "-1.00")], TX),
    }
    n = update_ctbc_derivatives(tmp_path, ["00406A"], today=date(2026, 11, 9), client=FakeClient(days), pause=0)
    assert n == {"00406A": 2}  # weekend / unpublished days return another 資料日期 → skipped
    v = build_ctbc_derivatives_view(tmp_path, "00406A")
    assert v["prev_as_of_date"] == "2026-11-06" and v["cap_pct"] == 25.0
    rows = {r["code"]: r for r in v["option_rows"]}
    assert rows["TX2"]["delta_contracts"] == 1000 and rows["TX2"]["status"] == "up"
    assert rows["TX3"]["status"] == "new"
    assert rows["TXV"]["status"] == "closed" and rows["TXV"]["contracts"] == 0
    assert v["sold_call_contracts"] == 17000


def test_view_base_day_and_none(tmp_path):
    d = tmp_path / "data" / "derivatives" / "00406A"
    d.mkdir(parents=True)
    (d / "2026-11-09.json").write_text(json.dumps(normalize("00406A", _data("2026/11/09", [_opt("TX2", "-15,000.00", "-16.74")]))))
    v = build_ctbc_derivatives_view(tmp_path, "00406A")
    assert v["prev_as_of_date"] is None and v["option_rows"][0]["status"] == "base"
    e = tmp_path / "data" / "derivatives" / "00995A"
    e.mkdir()
    (e / "2026-11-09.json").write_text(json.dumps(normalize("00995A", _data("2026/11/09", []))))
    assert build_ctbc_derivatives_view(tmp_path, "00995A") is None
