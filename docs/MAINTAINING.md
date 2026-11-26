# tw-etf-pages 維護與開發手冊（給接手的 Grok Bot）

> 本文件撰寫日期：2026-11-26（台灣時間）。內容是讀過 repo 原始碼、`git log`、GitHub Actions 執行紀錄、Pages 狀態，以及舊 bot「台股ETF Pages」（舊 bot ID `4353a6bd-2986-43bf-8dcb-5c1900b97888`，約 1,120 筆對話紀錄）之後整理的。
> 讀者：未來要**維護並繼續開發**這個專案的 Grok Bot（也包含使用者本人 GitHub `solymx`）。
> 語言：與使用者溝通一律用**繁體中文（台灣用語）**。

---

## 0. 三十秒總覽（先看這裡）

| 項目 | 內容 |
|---|---|
| 專案 | 台灣主動式／被動式 ETF **每日持股異動**靜態報告（不是股價報表），另附大盤指標（KD、融資維持率、台版 VIX）與千張大戶籌碼 |
| Repo | https://github.com/solymx/tw-etf-pages （**公開**，`main` 分支，無分支保護） |
| 正式站 | https://solymx.github.io/tw-etf-pages/ （GitHub Pages，Source = GitHub Actions） |
| 技術 | Python 3.11 + Jinja2 靜態輸出、資料以 JSON 存回 git；Node.js 20 僅元大（yuanta）抽取用 |
| 排程 | GitHub Actions `Update ETF holdings`：平日 17:00 台灣時間（cron `0 9 * * 1-5` UTC）＋週六 12:00 台灣時間只更新千張大戶籌碼（cron `0 4 * * 6`），也可手動 `workflow_dispatch`。另有 `Update Taiwan finance news`：每天 07:00 台灣時間（cron `0 23 * * *` UTC）與週六日 17:00（cron `0 9 * * 0,6` UTC）；平日 17:00 新聞由 holdings 的 `run_live` 一併更新。兩個 workflow 共用 concurrency group `pages-update` |
| Secrets | **不需要任何自訂 Secrets**（只用內建 `GITHUB_TOKEN`；資料來源皆為公開端點） |
| 觀察清單 | 32 檔（21 檔主動型 `…A`＋11 檔被動型），見附錄 A |
| 測試 | `pytest` 90 個測試全數通過（2026-11-26 在 Python 3.11+ 本機驗證） |
| 部署狀態（2026-11-26 16:30 台灣時間） | 見 §8.1：**間歇性失敗**（Pages 部署偶爾找不到剛上傳的 artifact），目前正式站是 11/25 21:48（台灣時間）那次成功部署的內容；資料本身都有正常 commit |
| 最重要的坑 | ① GitHub 排程常延遲數小時 ② Pages 部署間歇性失敗 ③ push 與手動 dispatch 撞車 ④ 約 16 檔 ETF 的主來源是第三方 `zdsetf.com` 鏡像 |

**接手後第一件事**：照 §12 的「給新 Grok Bot 的開場指令」做，然後依 §9 在新帳號重建三個 routines，再跑一次 §8.2 的健康檢查。

---

## 1. 專案目的與使用者需求

### 1.1 目的

使用者（GitHub `solymx`，資安工程師，台灣）想每天看**主動式 ETF 持股變化**，判斷經理人買賣了哪些股票。最原始需求（2026-09-23 對話第一句）：

> 我要的是每天的持股變化，要顯示：那些股票是第一次買、那些股票是加碼（包含加碼幾天了）、那些股票減碼（包含減碼幾天）、那些股票全部出清。

最初只追 `00981A`、`00988A`、`00991A`、`00403A` 四檔，之後依使用者**一次一檔**的指示擴充到 32 檔。

### 1.2 使用者明確提出過的需求（按時間序）

| 日期 | 需求 | 現況 |
|---|---|---|
| 09-23 | 新建乾淨公開 repo `tw-etf-pages`；排程平日 18:00（後來改 17:00） | ✅ |
| 09-23 | 參考 `ref.html`（PressPlay「法人情報站」2026-09-22 的「處置預估&熱門ETF持股變動」文章，SingleFile 存檔）「盡可能做到像他的功能」 | ✅ 日報風格首頁；**處置預估、AUM、申贖、淨買超金額未做**（無可靠來源，刻意不造假） |
| 09-23 | 單一 ETF 近 20 天持股趨勢圖，看是否「斷斷續續買」；**最重要觀察標的是 00981A** | ✅ Chart.js 折線圖＋「間歇加碼」排序 |
| 09-23 | 日期下拉選單切換不同日期的買賣清單；每天保留持股清單在 GitHub | ✅ 「異動資料日」下拉，**最多 10 天** |
| 09-23 | 假日／颱風休市時 Actions 有沒有 try/except 防護 | ✅ 每檔 ETF、每個外部模組各自 try/except；`as_of_date` 取自來源資料，不是執行日 |
| 09-23 起 | 持續對照 `ref.html` 提到、尚未支援的 ETF，**一次只加一檔**（怕出問題）；後來連被動型也要 | ✅ 32 檔；有 routine 巡檢 |
| 10-13/14 | 「為何今天又沒更新」→ 排程改 17:00；每天 18:47 巡檢順便手動補跑 | ✅ |
| 10-18 | 加權指數 KD 指標：<20 亮燈（超賣）、>80 亮燈（超漲） | ✅ KD(9,3,3) |
| 10-19 | 大盤融資維持率與每日增減；再加「距離斷頭線（130%）還剩多少」 | ✅ 自算（TWSE 官方資料）；150/140/130 三段警示 |
| 10-31 | 每週六針對網站所有 ETF 的持股，看大戶籌碼增減並對照上週；「你做到 GitHub Pages 做追蹤啊」 | ✅ `chips.html`，口徑＝集保「持股 1,000 張以上」 |
| 11-01 | 台灣版 VIX | ✅ 期交所臺指選擇權波動率指數 |
| 11-05 | 「別人說 00981A 今天有買期貨，你的沒有」→ 加上期貨追蹤 | ✅ 統一系（uni）ETF 期貨口數／多空／比重，逐日比較 |
| 11-05/06 | 平日 21:30 自動補當天融資維持率（因為 17:00 時證交所融資資料還沒出） | ✅ routine |
| 11-08/09 | 「00406 有掩護性買權你沒寫」→ 補上 | ✅ 中信（ctbc）選擇權＋期貨區塊，10/27 起有歷史 |
| 11-20 | 補 `00418A` 主動復華台灣新星（並回補 10/30–11/19） | ✅ |
| 11-26 | 換 Grok Bot 帳號；要求本手冊，未來仍要 Grok Bot 維護並繼續開發 | 本文件 |

### 1.3 使用者偏好與工作方式（務必遵守）

1. **繁體中文、台灣用語**；回報要簡短、先講結論。
2. **一次只加一檔 ETF**，加完驗證上線、回報網址，再等下一檔（使用者怕一次改太多出問題）。
3. **不造假資料**：沒有可靠來源的欄位（AUM、申贖、淨買超金額、處置預估、選擇權履約價）寧可標「尚無資料」。
4. 例行巡檢（routine）**沒事就保持安靜**，只有「有新數字、有缺口、修不好」才通知。
5. 融資維持率回報格式固定：今天維持率、與前一交易日差幾個百分點、融資餘額增減、離 130% 還有多少（約再跌幾 %），附首頁連結，並註明**「這不是投資建議」**。
6. 發現自己先前講錯要**直接更正**（舊 bot 曾因「一兩分鐘後就會更新」說太早而更正）。
7. push 前先 `git pull --rebase`，避免和 Actions 的自動 commit 撞車；部署後要驗證正式站 HTTP 200 且看得到新內容。
8. 不繞過網站條款、不高頻爬取；只用公開資料。
9. 使用者問「為什麼別人說有 X 但你沒有」時，先查證（官方揭露 vs 策略允許 vs 實際部位），**不要從持股變化臆測交易**。

---

## 2. 架構與資料流

```
                         GitHub Actions: Update ETF holdings
 排程(平日17:00 TW) ─┐   ┌────────────────────────────────────────────┐
 排程(週六12:00 TW) ─┼──▶│ python -m tw_etf_pages run | chips         │
 workflow_dispatch ──┘   └──────────────┬─────────────────────────────┘
                                        │
 ┌──────────────────────────────────────▼───────────────────────────────┐
 │ pipeline.run_live()                                                   │
 │  for etf in config.yaml:                                              │
 │    fetch.fetch_etf_holdings() ─► data/raw/…（gitignored）             │
 │    parse.parse_*()  ─► 標準化 snapshot(JSON)                          │
 │    compare.save_snapshot() ─► data/snapshots/{T}/{as_of}.json         │
 │    compare.compare_snapshots(prev,curr) ─► data/changes/{T}/{as_of}.json │
 │  update_kd()      ─► data/taiex/kd.json                               │
 │  update_margin()  ─► data/margin/ratio.json, last_closes.json         │
 │  update_vix()     ─► data/vix/taiwan_vix.json                         │
 │  update_ctbc_derivatives() ─► data/derivatives/{00406A,00995A}/*.json │
 │  update_chips()   ─► data/chips/weeks/YYYYMMDD.json, latest.json      │
 │  render.render_site() ─► site/*.html, site/data/*-changes.json, assets│
 │  寫 data/last_run.json（含每檔 errors）                               │
 └──────────────────────────────────────┬───────────────────────────────┘
                                        ▼
        git add data/… site → commit「chore: update ETF holdings snapshots YYYY-MM-DD」
        → git pull --rebase → git push
                                        ▼
        configure-pages → upload-pages-artifact(path: site) → deploy-pages
                                        ▼
                   https://solymx.github.io/tw-etf-pages/
```

設計重點：

- **資料即歷史**：沒有資料庫，`data/` 底下的 JSON 進 git 就是歷史；`site/` 也進 git（重新產生的檔案，常是 merge 衝突來源，見 §10）。
- **以「股數」比對、不用權重**：key 是 `stock_code`，`shares` 相減；連續加碼／減碼天數往回掃已歸檔快照計算（`compare.compute_streaks`）。
- **占位列政策**：`shares ≤ 1000` 且 `weight_pct < 0.01` 視為占位（統一投信常見的雜訊列），快照保留並標 `is_placeholder`，但不進四類異動表（`config.yaml → placeholder`）。
- **期貨／選擇權獨立存放**：不混進 `holdings`，不影響股票異動管線。統一系期貨放在 snapshot 的 `futures` 欄位；中信選擇權放 `data/derivatives/`。
- **容錯**：`run_live` 對每檔 ETF 各自 `try/except`，錯誤收進 `data/last_run.json` 的 `errors`；KD／融資／VIX／中信衍生品／籌碼每個模組也各自 try/except（失敗只記 log，**不會讓 workflow 失敗**）。⇒ **workflow 綠燈 ≠ 全部資料都抓到**，要看 `data/last_run.json`（見 §8.2）。
- **時區**：資料日（`as_of_date`）取自來源檔，不一定等於執行日；顯示用 `Asia/Taipei`。
- 同一個 `as_of_date` 重跑會覆寫同一份快照（冪等），所以 workflow 可安全重跑。

### 2.1 快照／異動 JSON 格式

`data/snapshots/{TICKER}/{YYYY-MM-DD}.json`：

```json
{
  "etf_ticker": "00981A", "as_of_date": "2026-11-25",
  "source": "uni_excel",            // uni_excel | fh_excel | zdsetf | yuanta | cathay | uobam | capital | kgi
  "fetched_at": "2026-11-26T03:06:17+08:00",
  "raw_file": "…", "raw_file_hash": "sha256…",
  "holdings_count": 51, "placeholder_count": 12,
  "holdings": [{"stock_code":"2330","stock_name":"台積電","shares":20216000,"weight_pct":16.06,"is_placeholder":false}],
  "futures":  [{"code":"TX","name":"台指期貨","contracts":1533,"month":"2026/12","position":"B","weight_pct":4.32,"notional":11688511800.0}],  // 僅 uni 系
  "meta": {…}, "assets": {…}
}
```

`data/changes/{TICKER}/{as_of}.json`：`as_of_date`、`prev_as_of_date`、`summary{first_buy,increase,decrease,full_exit}`，以及四個陣列，每列含 `stock_code/stock_name/prev_shares/curr_shares/shares_delta/prev_weight_pct/curr_weight_pct/streak_days`。

---

## 3. 資料來源與各家怪癖

### 3.1 ETF 持股來源矩陣（`fetch.fetch_etf_holdings` 的分派邏輯）

| issuer（投信） | 本站 ETF | 抓取方式（`source` 值） | 怪癖／風險 |
|---|---|---|---|
| `uni` 統一 | 00981A、00988A、00403A、00939 | ezmoney `AssetExcelNPOI?fundCode=`（`uni_excel`）；需先 GET 官網取得 WAF cookie；期貨另從 `Fund/Info` 頁的 `#DataAsset` JSON 補（`futures.py`） | **只有最新一日**，無歷史 API → 漏抓一天就永遠缺那天；Excel 有大量占位列；失敗才 fallback zdsetf（zdsetf 不收 00939） |
| `fh` 復華 | 00991A、00418A、00929 | `api/assetsExcel/{ETFxx}/{YYYYMMDD}`（`fh_excel`），從今天往回最多 7 天找有資料的日期 | **可依日期回補歷史**（00418A 就是回補 10/30–11/19）；無資料時回 JSON 而非 Excel；被動 00929 Excel 末段的期貨列略過 |
| `capital` 群益 | 00992A、00982A、00919 | 先試 zdsetf；失敗改官網 `POST /CFWeb/api/etf/buyback`（body `{"fundId":195}`，`capital`） | 被動 00919 在 zdsetf 是 404，走官網（真實股數＋權重；略過附買回／期貨／保證金） |
| `cathay` 國泰 | 00400A、00881、00878 | 主動 00400A：zdsetf；被動：官網 cwapi `GetIndexStockWeights?fundCode=CR/CN`（`cathay`） | cwapi 擋非瀏覽器 UA（用 Chrome UA）；**被動檔只有權重，股數是 weight×1e6 合成** → 這兩檔「股數增減」其實反映權重變化，不是真實買賣張數；00400A zdsetf 的 `weight_pct` 為 null → 顯示 0 |
| `fubon` 富邦 | 00405A | zdsetf 鏡像（`zdsetf`） | 官網僅有 ASP.NET 下載鈕，無穩定 URL |
| `ctbc` 中信 | 00406A、00995A | zdsetf 鏡像（`zdsetf`）＋官方 PCF API 補衍生品 | 見 §3.2 |
| `nomura` 野村 | 00980A、00985A、00999A | zdsetf 鏡像 | 官網為 SPA |
| `allianz` 安聯 | 00984A、00993A | zdsetf 鏡像 | — |
| `jpm` 摩根 | 00401A | zdsetf 鏡像 | `weight_pct` 為 null → 正規化為 0.0（頁面權重顯示 0，2026-11-26 仍如此） |
| `taishin` 台新 | 00987A | zdsetf 鏡像 | 曾為 null，現在 2026-11-25 的快照已有權重 |
| `fsitc` 第一金 | 00408A、00994A | zdsetf 鏡像 | — |
| `mega` 兆豐 | 00996A | zdsetf 鏡像 | — |
| `yuanta` 元大 | 0050、0056、00713、00940 | 官網 `product/detail/{T}/ratio` 的 Nuxt SSR，用 **Node.js** `eval` 抽 `window.__NUXT__.weightData.FundWeights`（`yuanta`） | 需要 Node；部分 OpenSSL 環境憑證驗證失敗時有 curl fallback；被動指數日調倉少，日對日異動常為空 |
| `uobam` 大華銀 | 00918 | 官網 `json/reply/WebSitePcfRequest?fundID=88329556`（`uobam`） | 真實股數；略過 Cash／Margin；**中繼憑證不全時會 `verify=False`**（見 §10 技術債）；2026-11-23 的 log 看得到 verify=True 失敗後重試 |
| `kgi` 凱基 | 009816 | 官網 `Fund/Detail?fundID=J023` 伺服器端渲染的「持股比重」HTML 表（`kgi`） | 無 Excel／CSV；HTML 表格抓取，官網改版會壞；略過期貨／現金；有自訂 non-strict X509 adapter |

> **`zdsetf.com` 是單點風險**：它是第三方網站（非官方），`/api/etfs/{TICKER}/snapshot` 鏡像各投信官網的投組頁，**約 16 檔 ETF 的主來源**（富邦、中信、野村、安聯、摩根、台新、第一金、兆豐共 13 檔只靠它；群益 2 檔主動、國泰 00400A 優先用它；統一／復華官方失敗時也會 fallback 到它）就是它，且只有最新一日、沒有歷史。若它掛了或改 API：這 13 檔會抓不到；優先用它的 3 檔（群益 00992A／00982A、國泰 00400A）會自動改走官方 API（`capital` buyback／`cathay` cwapi），但官方端點對主動檔是否可用未經實測（`last_run.json` 的 `errors` 會列出）。備案是逐家改成官方來源（參考 `fetch_capital_buyback`／`fetch_kgi_holdings` 的做法）。

### 3.2 中信（ctbc）衍生品與「掩護性買權」

- 來源：官方「投資組合」頁背後的資料服務 `https://www.ctbcinvestments.com.tw/API/`（匿名 session token：`home/AuthToken` → `etf/ETFCNOList` 取 FID → `etf/ETFHoldingWeight` 逐日取），和一般訪客瀏覽器所用相同。
- 只存官方表格有揭露的欄位：商品代碼／買賣權／商品名稱／口數／契約年月／權重（%）；**履約價官方未揭露，所以不存、不猜**。
- 檔案：`data/derivatives/{00406A,00995A}/{官方資料日}.json`；首次回補 14 天（目前有 10/27 起）；每天抓一次，**某一天失敗就停在那天，下次從該日續抓（不留靜默缺口）**。
- 頁面：`00406A.html#options`（掩護性買權／選擇權）與期貨，逐日顯示口數增減。
- 概念釐清（使用者問過）：「策略允許使用」≠「目前有部位」。公開說明書規定未沖銷賣出買權名目價值 ≤ 淨資產 25%（`COVERED_CALL_CAP_PCT`），這是**上限不是實際部位**。

### 3.3 大盤／籌碼資料來源

| 功能 | 模組 | 來源 | 重點 |
|---|---|---|---|
| 加權指數 KD(9,3,3) | `taiex_kd.py` | TWSE `rwd/zh/TAIEX/MI_5MINS_HIST`（月檔日 OHLC） | 首次抓 8 個月暖機；每次從最早一天以 K=D=50 為種子重算，結果確定性；<20 超賣亮綠燈、>80 超漲亮紅燈；標黃金／死亡交叉。與券商軟體可能差 ≤1 點，找不到可逐點對照的公開數值 |
| 大盤融資維持率 | `margin_ratio.py` | TWSE `MI_MARGN`（逐檔融資今日餘額＋市場融資金額）＋ `MI_INDEX`（逐檔收盤價） | 公式：Σ(融資餘額張×1000×收盤價) ÷ 融資金額 ×100；**僅上市（含上市 ETF），不含上櫃**；與「愛玩股」公布值對照 10/15、10/16 完全一致、多數日差距 <0.1；缺收盤價的股票沿用前一交易日；每次最多補 6 個交易日（`MAX_DAYS_PER_RUN`）；TWSE 偶爾回傳別天的快取（有 `date mismatch` 檢查）；SSL 失敗會重試 `verify=False`；**當天資料晚上才公布**，所以 17:00 那輪通常只到前一交易日 → 21:30 routine 補 |
| 融資警示 | `build_margin_view` | — | 距 130% 追繳線：`<150` 橘燈、`<140` 紅燈、`<130` 紅燈閃爍；顯示「約再跌 X% 碰線」＝(1−130/ratio)。**130% 是個人整戶維持率，大盤平均很少真的碰到** |
| 台版 VIX | `taiwan_vix.py` | 期交所月檔 `https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/YYYYMMnew.txt`（Big5 TSV） | 免費檔只涵蓋當月＋前 3 個月，所以歷史靠本站累積；燈號門檻（≥30 高度恐慌、25–30 警戒、≤18 低恐慌）是**自訂經驗值，非官方** |
| 千張大戶籌碼 | `chips.py` | 集保（TDCC）開放資料 `opendata.tdcc.com.tw/getOD.ashx?id=1-5`（最新一週全市場）；歷史週走 `tdcc.com.tw/portal/zh/smWeb/qryStock` 逐檔 | 口徑固定：持股分級 15＝持有 1,000,001 股以上（≥1,000 張）的人數／股數／占庫存比；對象＝所有觀察清單 ETF 持有的股票（去重，約 260 檔）；「明顯」門檻＝週變化 ≥0.5 個百分點；回補每次最多 400 檔 |
| 統一期貨 | `futures.py` | ezmoney `Fund/Info` 頁 `#DataAsset`（`AssetCode == "GD"`） | 只有 uni 系；`B` 多單／`S` 空單；2026-11-05 才開始存，之前無法回補 |

---

## 4. 檔案與目錄地圖

```
tw-etf-pages/
├─ .github/workflows/update.yml     # 唯一的 workflow（排程＋部署）
├─ config.yaml                      # 觀察清單（32 檔）、占位政策、fetch 參數、路徑
├─ pyproject.toml / requirements.txt# 依賴：openpyxl、PyYAML、Jinja2、requests（pytest 不在 requirements，要自行裝）
├─ README.md                        # 使用說明（部分段落已過時，見 §11）
├─ docs/
│  ├─ BACKFILL.md                   # 各投信能否回補歷史
│  └─ MAINTAINING.md                # ← 本文件
├─ ref.html                         # 使用者提供的參考頁（PressPlay 文章，7MB SingleFile）；routine 用它找缺口
├─ samples/                         # 離線 dry-run／單元測試用的發行人 Excel／JSON
├─ scripts/dry_run.sh               # 離線 dry-run 包裝
├─ src/tw_etf_pages/
│  ├─ __main__.py                   # CLI：dry-run | run | render | chips（--no-fallback、-v、--root）
│  ├─ config.py                     # 載入 config.yaml（EtfConfig、PlaceholderPolicy）
│  ├─ pipeline.py                   # dry_run / run_live / run_chips；每檔 try/except
│  ├─ fetch.py                      # 各投信下載（含重試、UA、WAF warmup、Node 抽取）
│  ├─ parse.py                      # 各來源 → 標準化 snapshot（parse_*）
│  ├─ compare.py                    # 快照比對、連續天數、存檔
│  ├─ trend.py                      # 近 20 天持股趨勢、間歇加碼統計
│  ├─ futures.py                    # 統一期貨補抓與逐日檢視
│  ├─ ctbc_derivatives.py           # 中信選擇權／期貨
│  ├─ taiex_kd.py / margin_ratio.py / taiwan_vix.py / chips.py
│  ├─ render.py                     # Jinja2 輸出全站；change history 最多 10 天（CHANGE_HISTORY_MAX_DAYS）
│  ├─ utils.py                      # 數字／民國日期解析、台北時間、JSON 讀寫
│  ├─ templates/                    # base/index/etf/taiex_kd/chips ＋ _kd/_margin/_vix/_chips macros
│  └─ static/                       # app.js（日期選單、趨勢圖、切換）、style.css
├─ tests/                           # 90 個 pytest（每個發行人一個、加上 compare/trend/futures/chips/vix/ctbc）
├─ data/
│  ├─ snapshots/{TICKER}/YYYY-MM-DD.json   # 歸檔主體（約 1,275 檔）
│  ├─ changes/{TICKER}/YYYY-MM-DD.json     # 異動報告（約 1,243 檔）
│  ├─ taiex/kd.json  margin/{ratio,last_closes}.json  vix/taiwan_vix.json
│  ├─ chips/{latest.json, weeks/YYYYMMDD.json}
│  ├─ derivatives/{00406A,00995A}/*.json
│  ├─ raw/                                 # 原始檔，gitignore
│  └─ last_run.json                        # 最近一次 pipeline 狀態與 errors
└─ site/                            # 生成物（進 git）：index.html、{TICKER}.html、taiex-kd.html、chips.html、data/{T}-changes.json、assets/
```

正式站頁面錨點：首頁 `#part_kd`、`#part_margin`、`#part_vix`、`#part_chips`、`#part_water`（水位變動）、`#act_{TICKER}`；ETF 頁 `#trend`、`#futures`、`#options`、`#snapshot`；`taiex-kd.html#margin`、`taiex-kd.html#vix`；`{TICKER}.html?date=YYYY-MM-DD`。

---

## 5. GitHub Actions：排程與 Secrets

`.github/workflows/update.yml`（workflow 名稱 `Update ETF holdings`，單一 job `build-and-deploy`，`ubuntu-latest`、Python 3.11、Node 20）：

| 觸發 | cron（UTC） | 台灣時間 | 行為 |
|---|---|---|---|
| 平日 | `0 9 * * 1-5` | 17:00 | `python -m tw_etf_pages run`（全部更新） |
| 週六 | `0 4 * * 6` | 12:00 | `python -m tw_etf_pages chips`（只更新千張大戶籌碼，再重繪） |
| 手動 | — | — | `workflow_dispatch`，`mode`＝`run`（預設）或 `chips` |

步驟：checkout → setup-python（pip cache）→ setup-node → `pip install -r requirements.txt && pip install -e .` → 執行 → `git add data/snapshots data/changes data/last_run.json data/taiex data/margin data/chips data/vix data/derivatives site` → 有變更才 commit（`chore: update ETF holdings snapshots $(date -u +%Y-%m-%d)`）→ `git pull --rebase` → `git push` → `configure-pages@v5` → `upload-pages-artifact@v3`（path `site`）→ `deploy-pages@v4`。

- 權限（workflow 內宣告）：`contents: write`、`pages: write`、`id-token: write`；`concurrency: group pages-update, cancel-in-progress: false`。
- repo 層設定：Pages **Source = GitHub Actions**（`build_type: workflow`）；Actions 預設權限是 `read`，但 workflow 自己宣告了所需權限，所以可行；`github-pages` environment 有「自訂分支政策」（只允許指定分支部署）。
- **Secrets 名稱：無。** `gh secret list`、`gh variable list` 皆為空。只用內建 `GITHUB_TOKEN`。若未來新增需要 API key 的來源，請用 repo Secrets，**不要寫進程式或 `config.yaml`**，並在本節補記名稱（不記值）。
- **GitHub 排程會嚴重延遲**：例如 11/25 的 17:00 排程實際在 11/26 03:05（台灣時間）才開始（UTC 19:05）；排程 run 的建立時間常落在 UTC 14:00–21:00。這是平台行為，不是程式問題；這就是為什麼有 18:47 巡檢 routine 補跑。
- 新帳號需要：能 push 到 `solymx/tw-etf-pages`、能觸發 workflow 的 GitHub 授權（`gh` 的 token scope 需含 `repo`、`workflow`）。

---

## 6. 如何在本機執行

```bash
git clone https://github.com/solymx/tw-etf-pages.git && cd tw-etf-pages
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
pip install -e .

pytest -q                          # 90 passed
python -m tw_etf_pages dry-run     # 離線，用 samples/ 產生 site/（不需網路）
python -m tw_etf_pages render      # 只用現有 data/ 重繪 site/
python -m tw_etf_pages run -v      # 線上抓取（需連得到各投信；元大需要 node）
python -m tw_etf_pages chips       # 只更新千張大戶籌碼
python -m http.server -d site 8000 # 本機預覽 http://localhost:8000
```

注意：

- `run` 會**修改 `data/` 與 `site/`**（也會新增當天 snapshot）。只是想看輸出時請先用 `render` 或 `dry-run`；不要把測試用的 `run` 結果直接 commit（除非你明確要補資料）。
- `dry-run` 內有寫死的 `_sample_map`（`pipeline.py`），新增 ETF 不一定要補樣本。
- 沙箱常連不到 GitHub 或部分投信（舊 bot 曾遇過 `git pull` 失敗），這時用 `gh api` 看 commit 清單判斷。
- 元大抽取需要 `node`（`fetch.py` 以 `node -e` 執行內嵌 JS）；GitHub runner 已有。

---

## 7. 擴充指南

### 7.1 新增一檔 ETF（照使用者習慣：一次一檔）

1. **查發行人與代號**：確認是哪家投信、官方持股揭露在哪、是否 `ref.html` 提到。先看 `config.yaml` 現有 issuer 能不能沿用。
2. **查來源**：
   - 先試 `curl -s -o /dev/null -w "%{http_code}" https://zdsetf.com/api/etfs/{TICKER}/snapshot`。回 200 且 `holdings` 有股數 → 只需加 config（見下）；
   - 404（被動 ETF 多半如此）或沒有股數 → 找官方 API／頁面，仿照 `fetch_capital_buyback`、`fetch_uobam_pcf`、`fetch_kgi_holdings`、`fetch_cathay_weights` 新增 `fetch_xxx` + `parse_xxx`。
3. **加進 `config.yaml`**（`ticker/name/issuer/fund_code/source_page`）。若是**新 issuer**，還要改：
   - `config.py`（`EtfConfig.issuer` 註解）、`fetch.fetch_etf_holdings`（分派）、`pipeline._parse_fetched`（kind → parser）、`parse.py`（新 parser，產生標準 holding：`stock_code/stock_name/shares/weight_pct/is_placeholder`，略過現金／期貨／保證金）；
   - 加 `samples/` 一份真實回應與 `tests/test_{issuer}_{ticker}.py`（參考 `tests/test_kgi_009816.py`）。
4. **本機只驗證這一檔**（沒有單檔 CLI，用一小段 Python）：

   ```bash
   python - <<'PY'
   from tw_etf_pages.config import load_config
   from tw_etf_pages.pipeline import process_etf
   from tw_etf_pages.render import render_site
   cfg = load_config()
   print(process_etf(cfg, cfg.etf("00xxxA"))["snapshot"]["as_of_date"])
   render_site(cfg)
   PY
   pytest -q
   ```
5. **能回補就回補**：復華（fh）可用 `fetch_fh_excel(cfg, etf, dest, as_of=某日)` + `parse_fh_excel` + `save_snapshot` 逐日補（`00418A` 就是這樣補 10/30–11/19）；`render.ensure_change_reports` 會替連續快照補出異動 JSON。其他投信多半只能靠每天累積（`docs/BACKFILL.md`）。
6. **commit 只放該檔相關變更**：`feat: add 00xxxA 名稱 (issuer via 來源)`；`git pull --rebase` → push → 手動觸發 workflow → 確認 `https://solymx.github.io/tw-etf-pages/00xxxA.html` 回 200，且首頁清單有這檔。
7. **回報**：用繁中給使用者網址、資料來源、限制（例如「只有 1 天資料，要等下個交易日才有異動」「權重為 0 是來源 null」），並說明剩餘待選。

### 7.2 新增一個資料欄位（例如某投信揭露的新資訊）

原則：**不要污染股票異動管線**，另存、另看；失敗不能弄壞整站。

1. 在 parser 裡取出欄位，放進 snapshot 的**獨立頂層 key**（如 `futures`），不要塞進 `holdings`；或像中信衍生品另開 `data/<新目錄>/`。
2. 寫一個 `build_xxx_view()`（回傳 `None` 表示該區塊不顯示），在 `render.py` 以 try/except 呼叫，結果傳給模板；模板放 macro 或 `etf.html` 區塊（加錨點 id）。
3. 若是新的資料目錄：**必須同步修改 `.github/workflows/update.yml` 的 `git add …` 清單**，否則資料不會被 commit、隔天就消失。
4. 在 `pipeline.run_live` 加 `try/except`（參考 `update_kd` 等區塊）。
5. 補測試（`tests/`），更新 README／本文件。
6. 舊快照沒有新欄位是正常的；差異（DoD）只從「連續兩天都有欄位」開始算，不要偽造歷史。

### 7.3 新增一個市場指標（KD／融資／VIX 同模式）

`update_xxx(root)`（抓取、累積歷史、永不 raise）＋ `build_xxx_view(root)`（算燈號／距離）＋ macro 模板 ＋ `run_live` try/except ＋ workflow `git add` 路徑。燈號門檻放模組常數，並在頁面註明「非官方」。

### 7.4 調整常見參數

| 想改 | 位置 |
|---|---|
| 異動資料日下拉天數（使用者指定 10） | `render.CHANGE_HISTORY_MAX_DAYS` |
| 占位列門檻 | `config.yaml → placeholder` |
| 近 20 天趨勢天數 | `trend.build_holdings_trend` |
| 排程時間 | `update.yml` 的 cron（UTC！台灣 = UTC+8）；同步改 README／本文件 §5 |
| 融資警示線 | `margin_ratio.CALL_LINE`、`build_margin_view` 的 150／140 |
| 籌碼「明顯」門檻 | `chips.NOTABLE_PP`（0.5 個百分點） |
| KD 週期／超買賣線 | `taiex_kd.PERIOD / OVERSOLD / OVERBOUGHT` |

---

## 8. 部署與疑難排解 Runbook

### 8.1 目前部署狀態（2026-11-26 16:30–16:35 台灣時間實測）

- **GitHub 狀態頁**：All Systems Operational。
- **最近一次 workflow**：run `45681751953`（排程觸發，11/25 19:05 UTC＝11/26 03:05 台灣時間）→ **failure**，唯一失敗步驟是 **Deploy to GitHub Pages**；前面「抓資料 → commit/push → upload artifact」全部成功（資料已 commit：`36c75fec`，11/26 03:07 台灣時間）。
- **上一次成功部署**：run `45627183020`（手動，11/25 13:47 UTC＝21:47 台灣時間），正式站 `Last-Modified: Wed, 25 Nov 2026 13:48:59 GMT`，頁面「產生時間 2026-11-25T21:48:51+08:00」，已含 11/25 融資維持率 151.61%。
- **結論**：正式站 HTTP 200、內容是 11/25 晚上的版本，**只落後 11/26 03:07 那次產生的內容（差異以時間戳為主，少數檔案有資料差異）**；不是長期掛掉，而是**間歇性失敗**。當天（11/26）17:00 的排程在我查詢時（16:35）還沒開始跑。
- **repo 沒有 open issue／PR**；`main` 無分支保護。

### 8.2 日常健康檢查（建議每次接手或收到「沒更新」時先跑）

```bash
cd tw-etf-pages && git pull --rebase
gh run list --workflow update.yml -L 10                       # 最近 10 次結果
gh run view <run-id> --log-failed | tail -60                  # 失敗原因
curl -sI https://solymx.github.io/tw-etf-pages/ | grep -iE 'HTTP/|last-modified'   # 要是今天（台灣時間）
curl -s https://solymx.github.io/tw-etf-pages/ | grep -o '產生時間：[^。]*'
cat data/last_run.json                                        # errors 必須是 []（workflow 綠燈不代表每檔都成功）
gh api repos/solymx/tw-etf-pages/pages --jq .build_type       # 應為 workflow
```

判斷「今天有沒有更新」的標準：workflow 在**今天（台灣日期）**有成功 run，且 Pages `Last-Modified` 是今天（台灣時間），且 `last_run.json.errors` 為空。

### 8.3 症狀 → 原因 → 處置

| 症狀 | 原因 | 處置 |
|---|---|---|
| 「今天網頁沒更新」，Actions 沒有今天的 run | **GitHub 排程延遲**（常見延後 3–10 小時，甚至隔天凌晨才跑） | 等 18:47 巡檢；或直接 `gh workflow run "Update ETF holdings" --repo solymx/tw-etf-pages` 手動補跑，確認完成 |
| `Deploy to GitHub Pages` 失敗：`Fetching artifact metadata failed… No artifacts named "github-pages" were found`（日誌同時顯示 upload 成功、`Found 0 artifact(s)`） | 見 §8.4：artifact 剛上傳完立刻查不到（GitHub 側最終一致性），因為 upload 與 deploy 在**同一個 job、間隔不到 2 秒** | 重跑（`gh workflow run` 或 UI 的 Re-run）通常 1–4 次內成功；長期解法見 §8.4 |
| `Commit data snapshots` 失敗：`error: could not apply … chore: update ETF holdings snapshots` | `git pull --rebase` 時與另一個 push（本機手動 commit 或另一個 run）在 `site/*.html`、`data/last_run.json` 等**生成檔**上衝突（11/21、11/24 各發生一次） | 重跑即可（會重新產生）。**自己要 push 前先 `git pull --rebase`，並避免在 Actions 正在跑時 push**；長期解法見 §10 |
| workflow 綠燈但某檔 ETF 沒更新 | 該檔抓取失敗被吞掉（只記在 `last_run.json.errors`） | 看 `errors`；多檔同時失敗且 issuer 是 fubon/ctbc/nomura/allianz/jpm/taishin/fsitc/mega → 先懷疑 `zdsetf.com` |
| 某家投信全掛 | 官網改版／WAF／憑證 | 看 `fetch.py` 對應函式與 log；統一需 warmup cookie；國泰／大華銀／凱基需瀏覽器 UA |
| 融資維持率停在前一天 | 證交所當日融資資料晚上才公布 | 晚上 21:30 routine 補；或手動 `run` / dispatch。`NoData` 屬正常 |
| 融資缺日 | 例如 routine 當天因額度用完失敗 | `update_margin` 每次最多補 6 個交易日，重跑即補齊 |
| 異動表空白 | 該檔只有 1 個快照、或被動指數當日無調倉、或來源資料日沒變（休市） | 正常；等下一個資料日 |
| 部分 ETF 權重全是 0 | 來源（zdsetf）`weight_pct` 為 null（00400A、00401A） | 已知限制；若要根治，需改接官方來源 |
| Pages 404／Actions 無法部署 | Pages Source 被改回分支發布、或 environment 分支政策擋住 | Settings → Pages → Source 必須是 **GitHub Actions**；檢查 `github-pages` environment 的 deployment branches 含 `main` |
| routine 沒跑／失敗 | Grok Bot 用量用完（11/14–11/16 發生過） | 確認新帳號方案額度；恢復後讓巡檢補跑（融資會自動補缺日） |

### 8.4 2026-11-25 Pages 部署失敗：根因與建議修法（僅記錄，**尚未修改任何程式或重跑**）

**事實**

- 失敗訊息固定是：`Fetching artifact metadata failed. Is githubstatus.com reporting issues…` → `Found 0 artifact(s)` → `No artifacts named "github-pages" were found for this workflow run`。
- 但同一次 log 前面 `upload-pages-artifact@v3` 明確顯示 `Artifact github-pages has been successfully uploaded! … Artifact ID 15054302723`。也就是**上傳成功、立刻查詢卻查不到**。
- 失敗是**間歇性**的、與程式碼內容無關：成功與失敗的 run 使用完全相同的 action 版本與同一份流程。最近一輪的紀錄（皆為 `Update ETF holdings`）：
  - 11/23：10:53Z 失敗（artifact）、10:56Z 成功；21:08Z 排程失敗（artifact）
  - 11/24：約 10:50Z 失敗（push 衝突）、10:54Z 成功；13:39Z 失敗（artifact）、13:44Z 成功；20:04Z 排程成功
  - 11/25：13:32Z、13:34Z、13:40Z、13:43Z **連續四次失敗**（artifact）→ 13:47Z 成功；19:05Z 排程失敗（artifact）
  - 最早的 artifact 類失敗出現在 11/23 10:53Z；在那之前，100 筆內的失敗只有 push 衝突（10/13、11/21 各一次）。11/21 起（含）共 10 次失敗，其中 8 次是 artifact 類、2 次是 push 衝突；11/24 另有一次 push 衝突，已含在內。
- 每次失敗時，資料與 `site/` 其實已先 commit／push 成功（所以 repo 有最新資料，只是 Pages 沒更新）。
- 另一個無害警告：`Node.js 20 is deprecated … forced to run on Node.js 24: checkout@v4, configure-pages@v5, deploy-pages@v4, setup-node@v4, setup-python@v5, upload-artifact@v4`。

**根因判斷（推測，標示為推測）**：`actions/deploy-pages@v4` 以 Actions artifact API 依 run id 查 `github-pages`，GitHub 側在上傳完成後的短時間內偶爾查不到（最終一致性）。本 workflow 把 build 與 deploy 放在**同一個 job**，`upload-pages-artifact` 結束後約 1 秒就 `deploy-pages`，最容易踩到。官方範本的做法是**拆成 build / deploy 兩個 job**（中間有 job 排隊延遲）。這不是 token 權限問題（權限宣告正確，成功 run 同樣設定）。

**建議修法（依序，尚未實作）**

1. 把 workflow 拆成兩個 job：`build`（checkout → 抓資料 → commit/push → configure-pages → upload-pages-artifact）與 `deploy`（`needs: build`、`environment: github-pages`、`permissions: {pages: write, id-token: write}`，只跑 `actions/deploy-pages@v4`）。好處：失敗時 UI 可只 **Re-run failed jobs**（只重新部署，不會重新抓資料）。
2. 在 `deploy` 加簡單重試：第一次 `deploy-pages` 設 `continue-on-error: true` 且 `id: d1`，失敗後 `sleep 45`，再跑第二個 `deploy-pages` step（`if: steps.d1.outcome == 'failure'`）；`environment.url` 要改成取有成功的那個 step 的 output。
3. 順手把 action 升到支援 Node 24 的最新大版本，並實測一次（`workflow_dispatch`）。
4. 做完後連續觀察 3–5 個交易日，確認 artifact 類失敗消失。

**目前待辦（接手後第一個處置）**：這是「是否要改 workflow」的決定，建議先請使用者同意；在改之前，只要手動 dispatch 一次讓正式站補上最新內容即可。

---

## 9. 要在新帳號重建的 Routines（完整 prompt）

> 舊帳號共有 **3 個 routine**（搬家包原本的 handoff 只列了 2 個，且 prompt 是「重建」版；以下是從舊 bot 對話紀錄還原的**實際最後版本**，排程以 `CRON_TZ=Asia/Taipei` 表示台灣時間）。三個都把結果交給「這個聊天裡的使用者」；routine 失敗在 11/14–11/16 曾因舊帳號 Grok Bot 用量用完而中斷。
> 重建時用 UpdateRoutine（`action: create`）；建完請確認 `gh` 授權已連好，否則巡檢無法觸發 workflow。

### 9.1 `ref.html 待支援 ETF 巡檢`（舊 folder id `ref-html-etf`）

- 排程：`CRON_TZ=Asia/Taipei 47 18 * * 1-5`（平日 18:47 台灣時間）
- 目的：①「更新保險」——GitHub 排程常延遲，所以每天 18:47 檢查今天有沒有更新，沒有就手動觸發；② 對照 `ref.html` 找尚未支援的 ETF。沒事保持安靜。
- Prompt（2026-10-14 最後版本，原文）：

```text
每個平日 18:47（台灣時間）做兩件事，對象是 solymx/tw-etf-pages（本機 /workspace/tw-etf-pages）。

1. 更新保險：查今天（台灣日期）有沒有 "Update ETF holdings" workflow 成功跑完，也看 https://solymx.github.io/tw-etf-pages/index.html 的 Last-Modified 是不是今天。如果都還沒更新，而且沒有正在跑的 run，就用 `gh workflow run "Update ETF holdings" --repo solymx/tw-etf-pages` 手動觸發，等它跑完，再確認 Pages 回 HTTP 200，而且 Last-Modified 是今天。成功就不用通知用戶；失敗的話查 log、能修就修，然後用繁體中文簡短回報。如果是 push 被拒絕這種撞車，重跑一次即可。

2. ref.html 巡檢：拉最新的 main，把 ref.html 提到的主動型與被動型 ETF 跟 config.yaml 比對。顏色碼、日期、文章 ID、base64 字串都不是 ETF，不要算進去。沒有缺口就保持安靜；有缺口就一次只補一檔，接進現有的抓資料流程，推上去、觸發部署、驗證 Pages，最後用繁體中文回報。
```

- 巡檢實務備註（來自歷次執行）：被動標籤列 0050、0056、00713、00881、00878、00918、00919、00929、00939、00940 與 `#xxxxA` 主動代號已全部支援；`#003349`、`#00661a`、`0864A`、`000000` 之類是 CSS 色碼／base64 的誤判；`#009816` 一度被當錯字略過，**後來確認是真實代號（凱基台灣TOP50），已於 10/12 加入**。目前 `ref.html` 沒有待補缺口。
- 建議（新帳號可考慮）：部署遇到 §8.4 的 artifact 錯誤時「重跑」是預期處置；若 §8.4 修法已上線，可把這段保險說明相應簡化。

### 9.2 `平日晚間融資維持率補更新`（舊 folder `automation-1793979825200`）

- 排程：`CRON_TZ=Asia/Taipei 30 21 * * 1-5`（平日 21:30 台灣時間）
- 目的：17:00 那輪跑時，證交所當天融資資料還沒公布，所以晚上補。**有新數字才通知；已最新或還沒公布就安靜。**
- Prompt（2026-11-06 建立，原文）：

```text
每個平日 21:30（台灣時間）專門補更新 solymx/tw-etf-pages（本機 /workspace/tw-etf-pages，正式站 https://solymx.github.io/tw-etf-pages/）的大盤融資維持率。

原因：平日 17:00 那輪跑時，證交所當天融資資料通常還沒公布，網站上的維持率常停在前一交易日。

做法：查證交所是否已公布「今天（台灣日期）」的融資資料。若已公布且網站／data 還沒有該日維持率，就抓取並寫入 data/margin、重算維持率與距 130% 距離，再安全部署到 Pages（pull --rebase、避開撞車；必要時觸發部署）。ETF 持股、KD、VIX、大戶籌碼等其他流程不要弄壞；融資抓失敗只記原因，不要讓整站掛掉。

結果交給這個聊天裡的用戶：成功且數值有更新時，用繁體中文極短回報最新日期、維持率、增減百分點、融資餘額變化，並附首頁連結；若今天資料還沒公布、或網站已經是最新，保持安靜不要打擾。只有失敗才簡短說明原因。
```

- 回報範例（使用者認可的格式）：「今天 11/25 的大盤融資維持率是 151.61%，比昨天 11/24 的 162.07% 少了 10.46 個百分點。融資餘額 4,341.38 億，少了 193.67 億。離 130% 的斷頭線還剩約 21.6 個百分點，大概再跌 14.3% 左右會碰到。這不是投資建議。」
- 實作提示：`update_margin(root)` 會自動從最後一筆之後補到「今天（若為平日）」；因為 `date.today()` 用的是執行環境（runner 為 UTC）日期，21:30 台灣時間＝13:30 UTC，同一天，沒問題。

### 9.3 `週六 ETF 持股大戶籌碼對照`（舊 folder `etf`）

- 排程：`CRON_TZ=Asia/Taipei 56 16 * * 6`（每週六 16:56 台灣時間）
- 注意：Actions 週六 12:00（台灣時間）已會自動跑 `chips` 更新資料與頁面；這個 routine 的角色是**確認頁面更新並回報重點**。使用者在 10/31 明確要求「做到 GitHub Pages 追蹤，不是只在聊天貼報告」。
- Prompt（2026-10-31 最後版本，原文）：

```text
每週六更新 solymx/tw-etf-pages（本機 /workspace/tw-etf-pages，正式站 https://solymx.github.io/tw-etf-pages/）的「ETF 持股 × 大戶籌碼週對照」頁面／區塊，讓用戶在 GitHub Pages 上追蹤，不是只在聊天裡貼報告。

範圍：從最新 config.yaml 與持股快照，彙整所有追蹤中主動／被動 ETF 持有的股票（去重）。

大戶籌碼口徑（固定，並寫在頁面上）：優先「持股千張以上大戶」週增減；來源不可用才改次佳公開來源並註明。不要混用不一致口徑。以本週最新可取得交易日對照上一週，標增加／減少／持平與變化量。查不到標「無資料」，不編造。

實作：把歷史與當週結果存進 data/，在 Pages 做清楚的追蹤頁或首頁區塊（明顯增加／明顯減少、資料日、來源），接進既有更新流程或週六可安全觸發的部署。push 前 pull --rebase，避開撞車；部署後確認正式站 HTTP 200 且看得到新內容。

回報：結果交給這個聊天裡的用戶。成功時用繁體中文極短回覆，附上 Pages 網址與一句整體偏增／偏減／混雜；失敗或完全抓不到資料時才詳說原因。這不是投資建議。
```

- 回報範例：「週六的 ETF 千張大戶籌碼對照已更新（資料日 2026-11-20 對 11-13，264 檔都有資料）。整體是混雜、略偏減：增 117、減 135、持平 12；其中明顯增加 41、明顯減少 55。頁面在 chips.html。這不是投資建議。」

---

## 10. 已知問題、技術債與 Roadmap

### 10.1 已知問題（按優先順序）

1. **Pages 部署間歇性失敗**（§8.4）。建議第一個修。
2. **push 撞車／rebase 衝突**：`site/` 是生成物卻進 git，每次產生都會改一大批檔案（時間戳），只要有第二個 push（本機、另一個 run）就可能衝突。建議：（a）`site/` 不再 commit（Pages 本來就從 artifact 部署，不需要它在 repo；注意 `update.yml` 的 `git add … site` 要同步拿掉）；（b）commit 步驟改成 `git pull --rebase -X theirs`（rebase 時 `theirs` 是自己要重放的新資料）或失敗時 `rebase --abort` → `reset --hard origin/main` → 重新 `render` 再 commit。
3. **GitHub 排程延遲**：目前靠 18:47 routine 補跑；可考慮把 `cron` 再提早、或接受延遲。
4. **zdsetf.com 單點依賴**：fubon/ctbc/nomura/allianz/jpm/taishin/fsitc/mega 共 13 檔只靠它；capital 主動 2 檔與 cathay 00400A 優先用它；uni／fh 官方失敗時 fallback 到它。無歷史、第三方、無 SLA。
5. **權重缺漏**：00400A、00401A（zdsetf 的 `weight_pct` 為 null → 顯示 0；00401A 有 `market_value` 可據以推算權重，目前未做）。
6. **合成股數**：被動 00881、00878（國泰 cwapi 只有權重，`shares = weight × 1e6`）——「加碼／減碼」其實是權重變動，頁面上讀者可能誤解。
7. **統一只提供最新一日**：某日抓取失敗就永久缺那天（00981A/00988A/00403A/00939）；復華可回補。
8. **融資維持率只含上市**，不含上櫃；計算結果與外部數字差距通常 <0.1，但不是官方數字。
9. **TLS 驗證放寬**：`margin_ratio._get` 與 `fetch_uobam_pcf` 在憑證失敗時會 `verify=False`（有 log）；KGI 只關閉 X.509 strict 旗標（仍驗證鏈）。資安角度建議改成內建正確中繼憑證或 pin CA，而不是關驗證。
10. **統一期貨歷史**：2026-11-05 才開始存，之前無法回補；未來是否也要追其他投信的期貨／選擇權（目前只有 uni 期貨、ctbc 選擇權＋期貨）尚未決定。
11. **00406A 選擇權履約價**：官方表格未揭露，因此不存；若官方日後揭露再補。
12. **Actions 版本**：多個 action 被強制以 Node 24 跑（警告）。
13. **雜項**：`config.yaml` 的 `fetch.user_agent` 仍寫 `github.com/qsweb3/tw-etf-pages`（舊網址，與實際 `solymx` 不一致，無功能影響）；`pytest` 不在 `requirements.txt`；`dry_run` 的 `_sample_map` 寫死；`margin_ratio`／`taiex_kd`／`taiwan_vix` 以 `date.today()`（runner UTC 日期）判斷今天，台灣時間 00:00–08:00 的手動執行可能差一天。

### 10.2 Roadmap／可以繼續開發的方向

優先（直接對應使用者說過的需求）：

- **P0 穩定性**：§8.4 拆 job＋重試；移除 `site/` 進 git 或改衝突策略；`last_run.json` 有 errors 時讓 workflow 輸出醒目的 summary（`$GITHUB_STEP_SUMMARY`），必要時以 `exit 1` 或 issue 通知（舊 bot 描述的「失敗通知建議」尚未做）。
- **P0 ref.html 對齊**：處置預估（處置股名單）、熱門 ETF 區塊的其他欄位。注意：舊 bot 為避免造假，刻意不做 AUM／申贖／淨買超金額／處置預估；若要做，必須先找到可靠公開來源（例如證交所處置公告）並標明來源與資料日。
- **P1 去除 zdsetf 依賴**：優先改接資料量最大、最常查看的（00405A、00406A／00995A、野村三檔），逐家改官方；每改一家都做資料一致性比對再切換。
- **P1 期貨／選擇權擴大**：其他投信若揭露衍生品部位，仿 `futures.py`／`ctbc_derivatives.py` 補（使用者在乎「別人說有，你沒有」）。
- **P2 觀察力**：跨 ETF 的同時加碼／減碼（水位變動已有，可加通知門檻）、00981A 專屬重點區塊（使用者說最重要）、融資維持率補上櫃或加入「與加權指數同圖」。
- **P2 品質**：把各 fetch 的格式變動做成 schema 驗證與告警；`pytest` 納入 workflow（先跑測試再抓資料）。

操作紀律：每次只做一項變更、先 `pytest`、先 `render` 本機看輸出、再 push、再 dispatch、最後驗證正式站。

---

## 11. 文件漂移（README 與實況不一致的地方）

- README／workflow 檔頭註解仍寫「平日 18:00（cron `0 10 * * 1-5`）」；**實際是 17:00 台灣時間（cron `0 9 * * 1-5`，10/13 改）**，另有週六 `0 4 * * 6`。
- README 說「週一至週五 18:00 執行 `run` 後 `git add data/snapshots data/changes data/last_run.json site`」；實際 `git add` 還包含 `data/taiex data/margin data/chips data/vix data/derivatives`。
- README 關於「刻意省略 AUM／申贖／淨買超金額／處置預估」仍然屬實。
- README 的「研究紀錄見姊妹目錄調查報告」指的是本機 `/workspace/tw-etf-pages-research`（`REPORT.md`、`samples/`），**不在 repo 裡**；已收入搬家 repo `solymx/grokbot-migration` 的 workspace 備份（若有收錄）。
- 更新 README／workflow 時請一併更新本文件 §0、§5。

---

## 12. 給新 Grok Bot 的開場指令

把下面這段貼給新帳號的 bot（連好 GitHub 之後）：

```text
你是從我舊 Grok Bot 帳號搬過來的「台股ETF Pages」維護與開發者。專案是公開 repo solymx/tw-etf-pages（正式站 https://solymx.github.io/tw-etf-pages/），每天用 GitHub Actions 抓台灣主動／被動 ETF 持股、算出新建倉／加碼／減碼／出清，另有 KD、融資維持率、台版 VIX、千張大戶籌碼、統一期貨與中信掩護性買權頁面。請先讀 repo 裡的 docs/MAINTAINING.md（完整維護手冊，含架構、資料來源、Runbook、Routines 全文、已知問題與 Roadmap），再讀私人 repo solymx/grokbot-migration 裡 bots/台股ETF-Pages-4353a6bd/handoff.md 與 conversation-excerpt.md 了解背景與我的偏好。讀完後用繁體中文（台灣用語）簡短回報：你現在理解的專案狀態、目前 Pages 部署是否正常（請實際跑 MAINTAINING.md §8.2 的健康檢查）、以及你建議的第一個要處理的事（我預期是 §8.4 的 Pages 間歇性部署失敗）。然後依 §9 在這個帳號重建三個 routines：「ref.html 待支援 ETF 巡檢」（平日 18:47）、「平日晚間融資維持率補更新」（平日 21:30）、「週六 ETF 持股大戶籌碼對照」（週六 16:56），prompt 用手冊裡的原文，建立前先跟我確認。工作規則：一次只加一檔 ETF；沒有可靠來源就標「無資料」不要造假；routine 沒事保持安靜；push 前先 git pull --rebase；任何會改 workflow、新增排程、或大改資料來源的變更，先跟我說明再做；融資維持率回報要註明「這不是投資建議」；不要把任何密碼、token 寫進 repo 或文件。我不需要你補回 rou-downloads、vocab 截圖等大檔。
```

---

## 附錄 A：觀察清單（`config.yaml`，共 32 檔）

| 代號 | 名稱 | issuer | fund_code |
|---|---|---|---|
| 00981A | 主動統一台股增長 | uni | `49YTW` |
| 00988A | 主動統一全球創新 | uni | `61YTW` |
| 00991A | 主動復華未來50 | fh | `ETF23` |
| 00418A | 主動復華台灣新星 | fh | `ETF27` |
| 00403A | 主動統一升級50 | uni | `63YTW` |
| 00992A | 主動群益科技創新 | capital | `500` |
| 00405A | 主動富邦台灣龍耀 | fubon | `00405A` |
| 00406A | 主動中信台灣收益 | ctbc | `00406A` |
| 00980A | 主動野村臺灣優選 | nomura | `00980A` |
| 00985A | 主動野村台灣50 | nomura | `00985A` |
| 00999A | 主動野村臺灣高息 | nomura | `00999A` |
| 00982A | 主動群益台灣強棒 | capital | `399` |
| 00984A | 主動安聯台灣高息 | allianz | `E0001` |
| 00993A | 主動安聯台灣 | allianz | `E0002` |
| 00400A | 主動國泰動能高息 | cathay | `EEA` |
| 00401A | 主動摩根台灣鑫收 | jpm | `00401A` |
| 00987A | 主動台新優勢成長 | taishin | `00987A` |
| 00408A | 主動第一金優股息 | fsitc | `183` |
| 00994A | 主動第一金台股優 | fsitc | `182` |
| 00995A | 主動中信台灣卓越 | ctbc | `00995A` |
| 00996A | 主動兆豐台灣豐收 | mega | `23` |
| 0050 | 元大台灣卓越50 | yuanta | `0050` |
| 0056 | 元大台灣高股息 | yuanta | `0056` |
| 00713 | 元大台灣高息低波 | yuanta | `00713` |
| 00881 | 國泰台灣科技龍頭 | cathay | `CR` |
| 00878 | 國泰永續高股息 | cathay | `CN` |
| 00918 | 大華優利高填息30 | uobam | `88329556` |
| 00919 | 群益台灣精選高息 | capital | `195` |
| 00929 | 復華台灣科技優息 | fh | `ETF21` |
| 00939 | 統一台灣高息動能 | uni | `46YTW` |
| 00940 | 元大台灣價值高息 | yuanta | `00940` |
| 009816 | 凱基台灣TOP50 | kgi | `J023` |

## 附錄 B：專案里程碑（`git log`，不含每日資料 commit）

| 日期 | 事件 |
|---|---|
| 2026-09-23 | 建 repo、四檔 ETF；改成 ref 風格日報；近 20 天趨勢；異動資料日選單（限 10 天）；一天內陸續加入 00992A、00405A、00406A、00980A、00982A、00984A、00400A、00401A、00987A、00408A、00993A、00985A、00995A、00994A、00996A、00999A，以及被動 0050、0056、00713、00881 |
| 2026-09-24 | 00878、00918、00919、00929、00939 |
| 2026-09-25 | 00940（被動佇列完成） |
| 2026-10-12 | 009816 凱基台灣TOP50（巡檢發現並補上） |
| 2026-10-13 | 排程改 17:00（台灣時間） |
| 2026-10-18 | 加權指數 KD(9,3,3) |
| 2026-10-19 | 大盤融資維持率＋距 130% 斷頭線警示 |
| 2026-10-31 | 週六千張大戶籌碼週對照（`chips.html`） |
| 2026-11-01 | 台版 VIX |
| 2026-11-05 | 統一系 ETF 期貨追蹤（TX 口數／多空／比重） |
| 2026-11-09 | 00406A（及 00995A）掩護性買權／選擇權＋期貨，回補 10/27 起 |
| 2026-11-14～16 | routine 因舊帳號用量用完而中斷 |
| 2026-11-20 | 00418A 主動復華台灣新星（回補 10/30–11/19） |
| 2026-11-21 起 | Pages 部署 artifact 類失敗開始增加（§8.4） |
| 2026-11-26 | 本手冊；搬家到新 Grok Bot 帳號 |

## 附錄 C：舊 bot 對話中使用者的原話（需求出處，節錄）

- 「我要的是每天的持股變化，要顯示 1. 那些股票是第一次買，那些股票是加碼(包含加碼幾天了)，那些股票減碼(包含減碼幾天)，那些股票全部出清」
- 「去修改 github pages，盡可能做到像他（ref.html）的功能那樣」
- 「你能否幫我增加一個功能是，可以單獨針對特定的 etf，去看他近 20 天的持股變化，我想知道他是否斷斷續續買哪個股票，要看到趨勢圖」「最重要的觀察是 00981a」
- 「異動資料日這個最多設定可以看 10 天內的即可」
- 「把它上面提到的 etf，但你現在還沒支援的，慢慢更新到 github pages 上面，但一次只更新一個，因為我怕出問題」「被動型也要，一樣一次只做一個」
- 「還是你把排程改到 17:00」「你先幫我手動更新今天的」
- 「可以幫我添加一個技術分析指標，是紀錄台股每天加權指數的 kd 指標，如果低於 20 要著重亮燈，代表超賣；如果高於 80 要著重亮燈，代表可能超漲」
- 「增加一個紀錄大盤融資維持率是多少，以及增加或減少多少」「大盤融資跌多少會斷頭，可以幫我註記剩餘多少會斷頭」
- 「你每週六幫我針對你做的台股 etf，把裡面的所有股票，去看他們的大戶籌碼是增加還是減少，要對照上一週」「你做到 github pages 做追蹤啊」
- 「台灣有像美國一樣的恐慌指數嗎，就是 vix，我也需要觀察」
- 「為何我看別人說 00981a 今天有買期貨，但我看你的 github pages 沒有」→「好，加上去」
- 「為何我看一堆人說 00406 有掩護性買權，但你沒有寫」→「補上去」
- 「幫我補上 00418a 進去」
