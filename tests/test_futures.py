import html
import json

from openpyxl import Workbook

from tw_etf_pages.config import PlaceholderPolicy
from tw_etf_pages.futures import build_futures_view, parse_uni_data_asset
from tw_etf_pages.parse import parse_uni_excel

ROWS = [
    ("資料日期：115/11/05",),
    ("淨資產", "NTD 246,149,202,190"),
    ("項目", "金額", "權重"),
    ("期貨(名目本金)", "NTD 7,262,338,800", "2.95%"),
    ("股票", "NTD 226,587,083,485", "92.05%"),
    ("項目", "金額"),
    ("現金", "NTD 13,031,125,882"),
    ("期貨保證金", "NTD 1,272,801,442"),
    ("期貨(名目本金)",),
    ("期貨代號", "期貨名稱", "持股權重", "口數", "契約年月"),
    ("TX", "台指期貨", "2.95%", "867", "2026/11"),
    ("股票",),
    ("股票代號", "股票名稱", "股數", "持股權重"),
    ("2330", "台積電", "1,000,000", "9.5%"),
    ("2317", "鴻海", "500,000", "3.1%"),
]


def _xlsx(tmp_path, rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(list(r))
    p = tmp_path / "u.xlsx"
    wb.save(p)
    return p


def test_uni_parser_keeps_stocks_and_adds_futures(tmp_path):
    snap = parse_uni_excel(_xlsx(tmp_path, ROWS), "00981A", PlaceholderPolicy(max_shares=1000, max_weight_pct=0.01, exclude_from_changes=True))
    assert [h["stock_code"] for h in snap["holdings"]] == ["2330", "2317"]
    assert snap["futures"] == [
        {"code": "TX", "name": "台指期貨", "weight_pct": 2.95, "contracts": 867, "month": "2026/11",
         "position": "B", "position_source": "excel_inferred"}
    ]
    assert snap["assets"]["futures_margin"]["amount"] == 1272801442.0
    assert snap["assets"]["futures_notional"]["weight_pct"] == 2.95


def test_uni_parser_without_futures(tmp_path):
    rows = [r for r in ROWS if r[0] not in ("期貨代號", "TX")]
    snap = parse_uni_excel(_xlsx(tmp_path, rows), "00403A", PlaceholderPolicy(max_shares=1000, max_weight_pct=0.01, exclude_from_changes=True))
    assert snap["futures"] == [] and len(snap["holdings"]) == 2


def test_data_asset_position():
    data = [{"AssetCode": "GD", "Details": [{"DetailCode": "TX", "MTH": "2026/11", "Position": "B", "Share": 867.0,
                                             "Amount": 7262338800.0, "MoneyType": "NTD", "TranDate": "2026-11-05T00:00:00"}]}]
    page = '<div id="DataAsset" data-content="' + html.escape(json.dumps(data, ensure_ascii=False)) + '"></div>'
    d = parse_uni_data_asset(page)
    assert d[0]["position"] == "B" and d[0]["contracts"] == 867.0 and d[0]["tran_date"] == "2026-11-05"


def _snap(d, futures):
    return {"etf_ticker": "X", "as_of_date": d, "holdings": [], "futures": futures}


def test_futures_view_base_then_delta(tmp_path):
    root = tmp_path / "X"
    root.mkdir()
    (root / "2026-11-04.json").write_text(json.dumps({"etf_ticker": "X", "as_of_date": "2026-11-04", "holdings": []}))
    tx = lambda n, w, m="2026/11": {"code": "TX", "name": "台指期貨", "weight_pct": w, "contracts": n, "month": m, "position": "B"}
    (root / "2026-11-05.json").write_text(json.dumps(_snap("2026-11-05", [tx(867, 2.95)])))
    v = build_futures_view(tmp_path, "X")
    assert v["prev_as_of_date"] is None and v["rows"][0]["status"] == "base"
    assert v["tracked_since"] == "2026-11-05"
    (root / "2026-11-06.json").write_text(json.dumps(_snap("2026-11-06", [tx(900, 3.1)])))
    v = build_futures_view(tmp_path, "X")
    r = v["rows"][0]
    assert v["prev_as_of_date"] == "2026-11-05"
    assert r["delta_contracts"] == 33 and r["status"] == "up" and abs(r["delta_weight"] - 0.15) < 1e-9
    (root / "2026-11-07.json").write_text(json.dumps(_snap("2026-11-07", [])))
    assert build_futures_view(tmp_path, "X")["rows"][0]["status"] == "closed"


def test_futures_view_none_without_key(tmp_path):
    (tmp_path / "X").mkdir()
    (tmp_path / "X" / "2026-11-04.json").write_text(json.dumps({"etf_ticker": "X", "as_of_date": "2026-11-04", "holdings": []}))
    assert build_futures_view(tmp_path, "X") is None
