# BP-3 匯出盤點（靜態，未跑測試）— 現況輸出路徑、歸屬與中和缺口

> 作者 hichan-1f，2026-10-14。基準：`origin/train/t59-int` 4ebc55cc8 的樹（`D:\wt-t59-bp1`）。方法：grep `Workbook(`／`csv.writer`／`text/csv`／`application/pdf`／`html_to_pdf_bytes`／`export_logged`／`add_pdf_sibling` 與前端 `Blob`／`XLSX.`；**沒有執行任何測試**。
> 設計見 `BP3-EXPORT-FUNNEL-DESIGN-T61.md`（同分支）。

## 0. 先看結論
1. **已經有一個集中輸出層**：`helpers/xlsx_out.py`（L1）＝ `xl_safe`（公式中和）、`set_row`、`check_export_rate`、`export_logged`（稽核）、`add_pdf_sibling`（xlsx→PDF 姊妹）、`xlsx_to_html`。BP-3 是**擴充它**，不是從零開始。
2. **公式中和不是集中的，覆蓋不齊**：`xl_safe` 只認 `= + - @`（不含 `\t`／`\r`）；7 個產 xlsx 的檔案裡 **3 個完全沒用**（案件批次匯出、外包名冊、網路規劃），其餘部分使用（`reports.py` 61 處 `ws.cell/append` 對 40 處 `xl_safe/set_row`）。openpyxl 會把 `=` 開頭的字串存成**真公式**，所以沒用 `xl_safe` 的 `ws.append([使用者自由文字])` 是實際注入面。
3. **CSV 有 5 條路徑，只有 1 條有中和**：`lodging/api_records.py:217 _csv_cell`（有 `\t \r`，正確）；`daily_tasks/api.py:789`（回報內容、工作事項標題未中和）；前端 `ledger-reports.js:104`、`ledger-statements.js:153`（科目名稱、摘要未中和）。
4. **PDF 全走同一個引擎**：`pdf_gen.html_to_pdf_bytes`（`pdf_gen.py:696`，Edge headless）；各單據的 HTML 由模組自己寫（`*_pdf.py`／端點內），**沒有宣告式範本層**；`helpers/doc_render.py`（27 行）→ `doc_template.py` 只服務報價單版型。
5. **前端 SheetJS 匯出 3 處**（客戶、料號、供應商）：`json_to_sheet` 會把字串存成字串儲存格（不是公式），風險低於 openpyxl，但仍繞過稽核（無 `export.*` 紀錄）與匯出速率限制。

## 1. Excel（xlsx）產出路徑

| # | 模組（擁有者） | 端點／稽核名 | 產生處 file:line | 用 `export_logged` | PDF 姊妹 | 公式中和 |
|---|---|---|---|---|---|---|
| 1 | accounting | T100 傳票匯出 `t100-vouchers` | `modules/accounting/api/accounting_export.py:425`（`Workbook()`）、`:513` 裝飾、`:532` Response、`:668` 姊妹 | ✔ | ✔ | `xl_safe/set_row` ✔（4 處） |
| 2 | accounting | 分類帳報表 `ledger-statements` | `modules/accounting/api/ledger_closing.py:121`、`:134`、`:142`；builder `modules/accounting/ledger/export.py:34,84` | ✔ | ✔ | builder 內 `xl_safe/set_row` ✔（14 處） |
| 3 | accounting | 營業稅 401 `ledger-tax401` | `modules/accounting/api/ledger_tax.py:66`、`:83`、`:181`；builder 同上 | ✔ | ✔ | ✔（經 builder） |
| 4 | analytics | 財務報表 `financial-report` | `modules/analytics/api/reports.py:850`（Workbook）、`:1827`、`:2520`、`:2550` | ✔（另有 `:2556` PDF 版） | PDF 版獨立端點 | **部分**：`reports.py` 全檔 61 處 `ws.cell/append`、40 處 `xl_safe/set_row` |
| 5 | analytics | 銷項稅額匯出 `tax-export` | `reports.py:2751`、`:2799`、`:2804`、`:2828`、`:3975`（姊妹） | ✔ | ✔ | 同上（部分） |
| 6 | arap | 出納執行歷史 `cashier-history` | `modules/arap/api/cashier.py:623`、`:640`、`:759`、`:764`、`:905` | ✔ | ✔ | ✔（14 處） |
| 7 | case | 案件批次匯出 `case-batch` | `modules/case/api/quotations.py:6578`、`:6608`（`Workbook()`＋`ws.append`）、`:6633`、`:6639`、`:6856` | ✔ | ✔ | **✘ 完全沒用**（`customer_name`／`project_name`／`tag`／`sales_person` 為自由文字） |
| 8 | subcontract | 外包名冊 `contractors` | `modules/subcontract/api/contractors.py:243`、`:253`（`openpyxl.Workbook()`＋`ws.append`）、`:273`、`:276`、`:529` | ✔ | ✔ | **✘ 完全沒用**（姓名、銀行、備註等自由文字） |
| 9 | netplan | 網路規劃 `network-plan` | `modules/netplan/api.py:314`、`:326`；builder `modules/netplan/export.py:186–248`（`ws.cell(value=…)` 8 處） | ✔（另有 `:332` PDF） | 有獨立 PDF 端點 | **✘ 完全沒用**（`log.note`、標籤等自由文字） |
| — | supply | 沒有自己的 xlsx 產出（`modules/supply/tests/test_stock_batch_payment.py:171–175` 只是讀回 #1 T100 匯出驗證） | — | — | — |

> 守門：`tests/platform/test_export_pdf_and_audit_2026_09_30.py::test_every_xlsx_and_csv_export_endpoint_is_logged_and_xlsx_has_a_pdf_sibling`（AST）— 每個回 xlsx／csv 的端點要有 `export_logged` 與 PDF 姊妹。**沒有守門檢查「每個 `ws.append/ws.cell` 都經 `xl_safe`」**。

## 2. CSV 產出路徑

| # | 擁有者 | 位置 | 稽核 | 中和 |
|---|---|---|---|---|
| 1 | lodging | `modules/lodging/api_records.py:249`（`csv.writer`）、`:257` Response、`:217 _csv_cell`（`_CSV_FORMULA_LEAD=("=","+","-","@","\t","\r")`） | `log_export`（import `:22`） | ✔（正確版本，BP-3 應以它為準） |
| 2 | daily_tasks | `modules/daily_tasks/api.py:789`（`_csv.writer`）、`:808` Response | `log_export "csv"` | **✘**（`d["title"]`、`c["report"]` 自由文字） |
| 3 | 前端 ledger-reports | `frontend/js/ledger-reports.js:104`（`Blob text/csv`，`'"'+…replace(/"/g,'""')` 手拼） | 無（純前端，資料來自已載入畫面） | **✘** |
| 4 | 前端 ledger-statements | `frontend/js/ledger-statements.js:153` 同上 | 無 | **✘** |
| 5 | tools（非產品路徑） | `tools/overhead_migrate.py:122`、`tools/charity_migrate.py:124` | — | 遷移用，不計 |

## 3. PDF 產出路徑（全部經 `pdf_gen.html_to_pdf_bytes`，`pdf_gen.py:696`）

| # | 擁有者 | 端點產出處 file:line | 版型來源 |
|---|---|---|---|
| 1 | case 報價單 | `modules/case/api/quotations.py:5658, 5766, 5799, 5827`（4 個 PDF 端點） | `helpers/doc_template.py`＋`helpers/output_templates/`（報價單版型；BP-6 遷移對象） |
| 2 | case 完工單 | `modules/case/api/completion_notes.py:823`；樣板 `modules/case/completion_pdf.py` | 模組內手寫 HTML |
| 3 | case 費用單 | `modules/case/api/expense_form_pdf.py:105` | 手寫 HTML |
| 4 | accounting 傳票 | `modules/accounting/api/vouchers.py:1560`；樣板 `modules/accounting/voucher_pdf.py` | 手寫 |
| 5 | arap 請款單／發票傳票 | `modules/arap/api/payment_requests.py:869`、`invoice_vouchers.py:777` | 手寫 |
| 6 | subcontract 承攬傳票 | `modules/subcontract/api/contractor_vouchers.py:927` | 手寫 |
| 7 | supply 出貨單 | `modules/supply/api/shipping_notes.py:754` | 手寫 |
| 8 | payroll 薪資單／獎金 | `modules/payroll/api/payslips.py:668, 686`；`bonus.py:1067`；`bonus_pdf.py` | 手寫 |
| 9 | analytics 財務報表 | `modules/analytics/api/reports.py:2469 _html_to_pdf`、`:2579`、`:2589`（StreamingResponse）、`:2999`（寄信用） | `_build_report_html` |
| 10 | netplan | `modules/netplan/api.py:348, 491` | `modules/netplan/export.py` |
| 11 | 自訂模組 | `routers/custom_records.py:313, 573` | 輸出範本定義（`output_template` kind） |
| 12 | 定義預覽 | `routers/definitions.py:538`（`POST /api/definitions/output_template/{key}/preview`） | 同上 |
| 13 | xlsx→PDF 姊妹 | `helpers/xlsx_out.py:303 add_pdf_sibling`（`:321` 呼叫引擎、`:327` Response） | `xlsx_to_html` |
| 14 | 寄信附件 | `helpers/email_notify.py:1596`（結案報表 PDF）、`:1718/:1801/:1807`（附件 MIME） | 同財務報表 |

## 4. 前端 SheetJS（客戶端 xlsx）
| 頁面 | 位置 | 備註 |
|---|---|---|
| customers.html | `frontend/pages/customers.html:995–999`（匯出）、`:1009`（匯入） | 無稽核、無冷卻、**資料量全由客戶端載入的列決定（遮蔽已在 API 層）** |
| parts.html | `frontend/pages/parts.html:619–623`、`:633` | 同上 |
| suppliers.html | `frontend/pages/suppliers.html:1064–1068`、`:1078` | 同上 |

## 5. 檔名、稽核、速率（現況共通設施，BP-3 沿用）
- 檔名：`helpers/download_name`（`content_disposition()`、`DownloadName.headers()`；A7 守門：金額標籤不能成為檔名變數）。
- 稽核：`export_logged`／`log_export`（action `export.xlsx|pdf|csv`；detail 只留 module／name／篩選摘要／列數）。
- 速率：Excel 5 秒、PDF 30 秒（`xlsx_out.check_export_rate`）；公司資料第二道閘門 `company_identity.require_for_output`。
- PDF 引擎上限與「PDF 外部載入全關」：`pdf_gen.html_to_pdf_bytes`（H-J 寫死項）。

## 6. 缺口一覽（餵設計）
| 缺口 | 位置 | 嚴重度 |
|---|---|---|
| G1 公式中和不集中、字元集不全（缺 `\t`、`\r`） | `xlsx_out.xl_safe` | 高 |
| G2 三個 xlsx 檔完全不中和 | #7 #8 #9 | 高（實際注入面） |
| G3 `reports.py` 61 對 40：部分 `ws.cell/append` 繞過 | #4 #5 | 中（需逐格盤） |
| G4 CSV 4 條路徑 3 條無中和 | daily_tasks、前端兩支 | 高 |
| G5 沒有守門檢查「寫儲存格必經中和」 | 測試層 | 高（沒守門就會回退） |
| G6 PDF 沒有宣告式範本層（浮水印／頁首頁尾無處放） | 12 個手寫 HTML | 設計課題 |
| G7 SheetJS 3 頁繞過稽核／冷卻 | §4 | 中 |
| G8 欄位／標題／順序寫死在各端點 | 全部 | 設計課題（範本化對象） |
