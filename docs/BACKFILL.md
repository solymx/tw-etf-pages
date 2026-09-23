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

## 群益（00992A／Capital Fund）

- 官網投組頁：`https://www.capitalfund.com.tw/etf/product/detail/500/portfolio`。
- **無公開 Excel／依日期 API** 可供本站直接下載。
- 本站以 `zdsetf.com/api/etfs/00992A/snapshot` 作為主來源（JSON 內 `source_url` 指向群益官網）；僅最新一日，**無法一次回補**。
- 歷史天數靠每日 Actions 累積；異動資料日選單仍最多 10 日。

