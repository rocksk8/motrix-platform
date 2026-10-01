# 營業稅 401 媒體申報檔：路由與畫面設計（只設計，未實作）

狀態：設計稿（2026-10-02，W1/a3）。前提：`modules/accounting/ledger/tax401_media.py`（純函式產生器）已在 platform；本文件說明「會計確認三個待決點之後」要補哪些路由／畫面／守門。**不改任何程式。**

## 1. 待會計確認（沒確認前不接路由）

| # | 問題 | 預設（產生器現況） | 影響 |
|---|---|---|---|
| Q1 | 收檔軟體是否接受**純正數數字**，還是金額欄一律要末位帶符號字元（零＝`…{`）？ | 一律 overpunch（附件六 S9 屬性） | 決定 `encode_s9` 是否要有「純數字」模式；若收檔軟體兩種都收，維持預設 |
| Q2 | 最後一筆記錄後面要不要再加 CRLF？ | 不加（筆間 CRLF） | `to_file_bytes(trailing_newline=…)` 已有開關，路由只需讀設定 |
| Q3 | 文字欄長度以**字元**還是**位元組**計？（C＝中文字以字元數計，X＝？） | 字元 | 純函式內單點，改 `clean_text` |
| Q4（新增） | 欄 93～95（代號 113／114／115）公式？ | 沒給＝0＋列入 `manual` | 畫面要讓會計手填，不可靜默輸出 0 |

## 2. 資料從哪來

- 金額：`ledger/tax401.py::summarize(conn, year, period, invoices)` 已依官方代號彙總（`lines`：代號→金額）。媒體檔的 `amounts` = 該彙總的代號對照，**不另讀單據**（單一來源，沿用 401 的原則）。
- 公司登記與申報資料（參數）：統編、稅籍編號、總繳代號、縣市代號、申報人身分證／姓名／電話、代理人證書號等。**不寫死**。放在哪：
  - 優先 `company_profile`（已有統編；其餘欄位新增 `tax401_filing` 區塊於公司設定，存 `settings` 表一個 JSON key `tax401_filing`），只有最高管理者／會計主管可編輯。
  - 申報人身分證字號是個資（F2 級）：存入前先確認備份分流規則（`data_class`），**不進稽核 detail**，匯出檔案本身含之為預期（申報要求）。
- 每期變動的參數（檔案編號、所屬年月、發票份數、申報類別）：匯出對話框輸入，不存。

## 3. 路由（accounting 模組 `api/ledger_tax.py` 內，同檔同守門）

| 路由 | 說明 |
|---|---|
| `GET /api/ledger/tax401/media/preview?year&period&file_no&invoice_count&filing_kind` | 回 JSON：`record`（112 欄逐欄 序號／名稱／值，供畫面核對）、`manual`（需人工的代號）、`warnings`（缺參數、對帳不平、期間未結帳）。**唯讀、不產檔**。權限＝`_require_tax_read` |
| `POST /api/ledger/tax401/media` body `{year,period,file_no,invoice_count,filing_kind,manual_amounts:{113:..,114:..,115:..}}` | 產檔並下載（`application/octet-stream`，檔名 `YYYYMM-401.txt`，UTF-8 無 BOM）。權限＝`_require_tax_write`（產生申報檔是對外動作）。用 `@export_logged("txt","accounting","ledger-tax401-media")`＋`check_export_rate`，稽核 `ledger.tax401.media`（detail：期別、筆數、是否含 manual；**不含**身分證字號） |
| 公司申報參數 `GET/PUT /api/ledger/tax401/filing-params` | 讀寫 `tax401_filing`；PUT 驗證（統編 8 碼＋`ubn_valid`、稅籍 9 碼、縣市代號 1 碼…沿用 `tax401_media._EXACT_LEN`），寫稽核（只記「改了哪些鍵」，不記值） |

旗標：沿用 `_flag(conn)`（401 功能開啟才可用）。模組關閉／旗標關 ⇒ 409（同現有 401 路由）。

## 4. 畫面（`ledger-hub.html` 的 401 區塊 `data-testid="hb-tax"` 內加一段，不新增頁面）

1. 「申報檔」摺疊卡（預設收合）：
   - 先看「公司申報資料」是否齊全；缺 ⇒ 紅字清單＋「去設定」按鈕（開參數編輯抽屜）。
   - 輸入：檔案編號（8 位，預設該年序號）、發票份數、申報類別（下拉：一般申報／更正…依附件六代碼，白話）。
   - 「113／114／115」三欄手填（空＝0，旁邊小字「官方附件沒有計算公式；請依你的申報書填」）。
   - 「預覽」→ 表格列出 112 欄（序號、名稱、值），金額欄同時顯示「原始金額」與「檔案內字串」，S9 末位字元用小註解（「末位 `{`＝正 0」）。
   - 「下載申報檔」→ POST；成功後顯示筆數與「請用官方申報軟體檢查」提示。
2. R3（白話＋說明＋例）：每個輸入附一句說明與例子；不出現「S9／overpunch」等術語（進階展開才顯示）。

## 5. 測試與守門

- 後端：preview 回的 112 欄與 `build_record` 同源；權限（read 可預覽／不可下載；write 才可）；旗標關 409；缺參數 400 且訊息點名欄位；稽核不含身分證字號；`manual` 非空時預覽有警示；下載位元組＝`to_file_bytes`。反向控制：拿掉 `_require_tax_write` ⇒ 紅。
- e2e（單檔）：填參數→預覽見 112 列→下載內容 111 個「|」、無 BOM、CRLF。
- 靜態：新增檔案歸屬登記（`modules.json`）、CHANGELOG（accounting）、SPEC 編號（避免 `S9` 當編號——測試函式名勿以 `s9_` 開頭）。

## 6. 風險

- 申報人身分證字號進 DB：F2 個資分流與備份要先確認；若不想存，改成匯出時輸入（不存）——**請會計／使用者裁示**。
- 與電子申報實際收件軟體的相容性只能由會計實測：交付前必須用官方「401 檢核程式」（若有）跑一次產出檔；本設計不假設它存在。
- 113～115 公式未知：若日後官方補公式，只改 `tax401_media`（一處），路由與畫面不動。
