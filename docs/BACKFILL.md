# 歷史持股回補（Backfill）

## 結論（00981A／統一投信）

**不可行（一次回補 ~20 交易日）。**

- 統一 ezmoney `AssetExcelNPOI?fundCode=` 只回傳**最新**投資組合 Excel。
- 調查與實測：無依日期參數的公開歷史 endpoint。
- 第三方 `zdsetf.com` 僅有 `/snapshot`、`/changes`（最新一日），`/history` 等回 404。
- 因此 **00981A、00988A、00403A** 的近 20 日趨勢必須靠本站 **每日 Actions 自行歸檔** 累積；上線初期天數會少於 20。

## 復華（00991A）

- `https://www.fhtrust.com.tw/api/assetsExcel/ETF23/{YYYYMMDD}` 可依日期下載。
- 可手動／腳本回補後以 `parse_fh_excel` 寫入 `data/snapshots/00991A/`。
- 請遵守發行人公開揭露用途；勿高頻爬取。

## 產品行為

趨勢圖與「間歇加碼」標示在天數不足時顯示 Traditional Chinese 空狀態／提示，不偽造歷史點。

## 群益（00992A／00982A／Capital Fund）

- 官網投組頁：`00992A` → `https://www.capitalfund.com.tw/etf/product/detail/500/portfolio`；`00982A` → `https://www.capitalfund.com.tw/etf/product/detail/399/portfolio`。
- **無公開 Excel／依日期 API** 可供本站直接下載。
- 本站以 `zdsetf.com/api/etfs/{TICKER}/snapshot` 作為主來源（JSON 內 `source_url` 指向群益官網）；僅最新一日，**無法一次回補**。
- 歷史天數靠每日 Actions 累積；異動資料日選單仍最多 10 日。

## 富邦（00405A／Fubon）

- 官網投組頁：`https://websys.fsit.com.tw/FubonETF/Fund/Profile.aspx?stkId=00405A`。
- **無穩定公開 Excel／CSV URL** 可供本站直接下載。
- 本站以 `zdsetf.com/api/etfs/00405A/snapshot` 作為主來源（JSON 內 `source_url` 指向 websys.fsit.com.tw）；僅最新一日，**無法一次回補**。
- 歷史天數靠每日 Actions 累積；異動資料日選單仍最多 10 日。

## 中信（00406A／CTBC）

- 官網 PCF／投組頁：`https://www.ctbcinvestments.com/etfprod/00406A/pcf`。
- **無穩定公開 Excel／CSV API** 可供本站直接下載。
- 本站以 `zdsetf.com/api/etfs/00406A/snapshot` 作為主來源（JSON 內 `source_url` 指向 ctbcinvestments.com）；僅最新一日，**無法一次回補**。
- 歷史天數靠每日 Actions 累積；異動資料日選單仍最多 10 日。

## 野村（00980A／00985A／Nomura）

- 官網產品／投組頁：`00980A` → `https://www.nomurafunds.com.tw/ETFWEB/product-description?fundNo=00980A`；`00985A` → `https://www.nomurafunds.com.tw/ETFWEB/product-description?fundNo=00985A`（亦可 `tab=basic`；zdsetf `source_url` 指向 `tab=Shareholding`）。
- **無穩定公開 Excel／CSV API** 可供本站直接下載（官網為 SPA，無穩定自動化下載 URL）。
- 本站以 `zdsetf.com/api/etfs/{TICKER}/snapshot` 作為主來源（JSON 內 `source_url` 指向 nomurafunds.com.tw）；僅最新一日，**無法一次回補**。
- 歷史天數靠每日 Actions 累積；異動資料日選單仍最多 10 日。

## 安聯（00984A／00993A／Allianz）

- 官網產品／投組頁：`00984A` → `https://etf.allianzgi.com.tw/etf-info/E0001`；`00993A` → `https://etf.allianzgi.com.tw/etf-info/E0002`（zdsetf `source_url` 指向 `https://etf.allianzgi.com.tw/list-trade`）。
- **無穩定公開 Excel／CSV API** 可供本站直接下載。
- 本站以 `zdsetf.com/api/etfs/{TICKER}/snapshot` 作為主來源（JSON 內 `source_url` 指向 etf.allianzgi.com.tw）；僅最新一日，**無法一次回補**。
- 歷史天數靠每日 Actions 累積；異動資料日選單仍最多 10 日。

## 國泰（00400A／Cathay）

- 官網產品／投組頁：`https://www.cathaysite.com.tw/ETF/detail/EEA`（zdsetf `source_url` 指向 `https://www.cathaysite.com.tw/`）。
- **無穩定公開 Excel／CSV API** 可供本站直接下載。
- 本站以 `zdsetf.com/api/etfs/00400A/snapshot` 作為主來源（JSON 內 `source_url` 指向 cathaysite.com.tw）；僅最新一日，**無法一次回補**。
- 歷史天數靠每日 Actions 累積；異動資料日選單仍最多 10 日。

## 摩根（00401A／J.P. Morgan AM Taiwan／jpm）

- 官網產品頁：`https://am.jpmorgan.com/tw/zh/asset-management/twetf/products/jpmorgan-taiwan-taiwan-equity-high-income-active-etf-tw00000401a1`（行銷頁：`…/funds/jpmorgan-tw-equity-high-income-etf/`）。
- **無穩定公開 Excel／CSV API** 可供本站直接下載（zdsetf `source_url` 雖可能指向 am.jpmorgan.com 上的 PCF xlsx dam 路徑，但不視為穩定可自動化 API）。
- 本站以 `zdsetf.com/api/etfs/00401A/snapshot` 作為主來源（JSON 內 `source_url` 指向 am.jpmorgan.com）；僅最新一日，**無法一次回補**。
- **權重 caveat**：zdsetf 快照中 `weight_pct` 可能全為 `null`（與國泰 `00400A` 相同）；parser 正規化為 `0.0`，**不臆造權重**。
- 歷史天數靠每日 Actions 累積；異動資料日選單仍最多 10 日。

## 台新（00987A／Taishin／taishin）

- 官網產品頁：`https://www.tsit.com.tw/ETF/Home/ETFSeriesDetail/00987A`；PCF／投組：`https://www.tsit.com.tw/ETF/Home/Pcf/00987A`（zdsetf `source_url` 指向此 PCF 頁）。
- **無穩定公開 Excel／CSV API** 可供本站直接下載（官網為 HTML 投組／PCF 頁）。
- 本站以 `zdsetf.com/api/etfs/00987A/snapshot` 作為主來源（JSON 內 `source_url` 指向 tsit.com.tw）；僅最新一日，**無法一次回補**。
- **權重 caveat**：zdsetf 快照中 `weight_pct` 可能全為 `null`（與國泰 `00400A`／摩根 `00401A` 相同）；parser 正規化為 `0.0`，**不臆造權重**。
- 歷史天數靠每日 Actions 累積；異動資料日選單仍最多 10 日。

## 第一金（00408A／FSITC／fsitc）

- 官網產品／投組頁：`https://www.fsitc.com.tw/FundDetail.aspx?ID=183`（zdsetf `source_url` 指向此頁；基金代號 ID=183）。
- **無穩定公開 Excel／CSV API** 可供本站直接下載（`FormDownload.aspx`／`ETFAccWeb`／`ETFList.aspx` 未提供可自動化的 00408A 持股 Excel／CSV URL）。
- 本站以 `zdsetf.com/api/etfs/00408A/snapshot` 作為主來源（JSON 內 `source_url` 指向 fsitc.com.tw）；僅最新一日，**無法一次回補**。
- 歷史天數靠每日 Actions 累積；異動資料日選單仍最多 10 日。
