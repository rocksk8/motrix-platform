# 報價單／估價單「備註事項」欄位＋規格 PDF 併入 — 設計（待使用者確認，未開工）

日期 2026-11-17　分支 `feat/quote-extra-notes-page`（基底 `train/t87-int` 1a3ec9382）　審查 hichan-16
示意圖：`QUOTE-EXTRA-NOTES-mockup.html`（左：編輯畫面；右：PDF 簽章頁之後的備註頁與併入附件）

## 1. 現況查到的事實（影響設計）
- PDF 由 `backend/pdf_gen.py::_build_quote_html_core`（預覽、PDF、內部版共用一支）→ Edge 轉 PDF。簽章區塊在最後，其後只有頁尾。估價單共用同一支，只換用語。
- **專案已有 `pypdf>=6.0.0`**（requirements.txt，JV5 傳票附件合併用）。`modules/accounting/voucher_pdf.py::_merge_pdfs` 已處理三個坑：壞檔在 `PdfReader()` 就丟；**加密檔在 `PdfReader()` 不丟、到讀頁數才丟**；**零頁 PDF 不丟任何例外**。→ 不需要新增套件。
- 報價單**目前沒有「規格附件」機制**：`signed_files_json`（客戶回簽單）是另一件事（已送出後才能傳、不是輸出內容）；「詳細規格於附件檔案」只是品項備註文字，系統內查不到對應功能。→ 需新增「規格文件」清單，但**沿用同一組上傳工具**（`save_document_files`、`append_json_list`、`remove_json_item`、`files_txn`、`upload_path_key`），不另寫一套。
- 簽核「內容指紋」(`content_fp.py`) 是 denylist：**未知鍵一律算內容**。新鍵不必改指紋規則，內容一變，已簽的簽核自動判過期，與其他欄位同機制。
- 送簽變更註記＝`quotations.py::_TRACKED_QUOTE_FIELDS`（editHistory 欄位層級摘要）。新鍵要加在這裡，否則只會顯示成「其他內容」。
- 條款範本現況：`system_settings.quote_terms_presets`（估價單另有 `estimate_terms_presets`），API 在 `routers/system.py`，由最高管理者在報價單編輯頁內維護。

## 2. 資料鍵（報價單與估價單同一組，存在 `data_json`）
| 鍵 | 型別 | 說明 |
|---|---|---|
| `extraNotes` | string | 備註事項全文，純文字。上限 20,000 字（伺服器強制）。沒填＝缺鍵或空字串 |
| `mergeFiles` | string[] | 要併入輸出的規格文件 id，**陣列順序＝併入順序** |

- 標題固定為「備註事項」，不做成欄位。範例裡的「備註事項：」首行是內容的一部分，由使用者／範本自己寫。
- 規格文件本體：新欄位 `quotations.spec_files_json`（模組 migration `0013`，預設 `'[]'`，與 `signed_files_json` 同形狀），檔案存 `uploads/quotations/<單號>/`（沿用既有路徑規則與路徑守門）。「上傳過」與「要併入」分開：只有進 `mergeFiles` 的才影響輸出與簽核。
- 舊單沒有這兩個鍵 ⇒ 輸出**逐位元相同**（golden 不變）；用測試鎖住。

## 3. 輸出（HTML 與 PDF）
- `_build_quote_html_core`：`extraNotes.strip()` 非空才在簽章區塊之後加 `<section class="extra-notes">`，CSS `break-before: page`（另起新頁）、`white-space: pre-wrap`（換行、空行、`- ` 條列照原樣）、內容一律 `esc()`（HTML 跳脫）。太長由瀏覽器列印自動接下一頁。沒填 ⇒ 不產生任何標籤與樣式（不多一頁）。
- 客戶版與內部版相同；預覽 HTML 也顯示備註頁（預覽不併附件，畫面註明「規格文件於下載 PDF 時併入」）。
- 實作時要驗：`pdf_scripts.FIT_A4_MULTI`（A4 縮放腳本）與新頁不衝突；以真實 Edge 轉檔檢查頁數。

## 4. 規格 PDF 併入流程
1. 現有流程照舊產出本體 PDF（`generate_pdf_bytes`）。
2. `mergeFiles` 非空才進合併：新 helper `helpers/pdf_merge.py`，邏輯取自 `voucher_pdf._merge_pdfs` 的三個坑處理（**不改 voucher_pdf**，降低風險；之後可再讓它改用共用 helper）。
3. 逐檔：id 查 `spec_files_json`、路徑守門 → `PdfReader` → 檢查加密／零頁／頁數 → append。**任一檔有問題只略過該檔**，其餘照合併，PDF 照常輸出。
4. 略過的檔名與原因：下載端點回應標頭 `X-Pdf-Merge-Skipped`（URL 編碼）＋編輯畫面該檔旁即時標示（上傳時就試開一次，加密／損毀／零頁當場提示，不等到輸出）。
5. 上限（建議值，待確認）：最多 10 檔、單檔 20 MB（沿用現有上傳上限）、合計 50 MB、併入附件合計 ≤ 300 頁、最終 PDF ≤ 80 MB。超過：上傳當下擋（數量／大小）；頁數於合併時略過超出的檔並說明。
6. 只收 PDF（本功能）。檔案順序＝`mergeFiles` 順序；刪檔時一併從 `mergeFiles` 移除。
7. 其他產 PDF 的入口：背景存檔版本（`_generate_quotation_pdf` → docVersions）也走同一個 builder。建議**存檔版本含併入附件**（「當初寄給客戶的是什麼」才完整，與 QL25 凍結精神一致）；代價是版本檔變大（受上述 80 MB 上限）。→ 待確認（見 §8 D2）。

## 5. 範本
- 存放：`system_settings.quote_extra_notes_templates = {templates:[{key, name, category, text}]}`；報價單與估價單**共用一份**（備註內容性質相同；若要分開再比照 `estimate_*` 另開一組）。
- API：`GET /api/settings/quote-notes-templates`（能編輯報價單的人可讀）、`PUT`（僅最高管理者；比照 `set_quote_terms_presets` 的驗證、稽核與「誰改了什麼」通知）。上限 100 個範本、每個 20,000 字。
- 畫面：備註框上方「套用範本」下拉；**超過 10 項時出現分類篩選 chip＋搜尋框**（不逐項展開）。套用＝把範本文字**複製**進備註框（框內已有內容時先詢問「取代」或「接在後面」），之後可自由修改，**不與範本連動**（與條款組「存的是複製過去的文字」同一原則）。
- 維護：最高管理者「管理範本」對話框（新增／編輯／刪除／分類）。位置預設與條款組同處（報價單編輯頁內、僅最高管理者看得到入口）；若使用者希望放進設定中心，另加入口，資料與 API 不變。→ 待確認（D5）。

## 6. 送簽註記
- `_TRACKED_QUOTE_FIELDS` 加 `("extraNotes", "備註事項")`、`("mergeFiles", "併入輸出的規格文件")`；`_fmt_change_value` 針對這兩個鍵顯示「N 字」「N 個檔」而不是截斷的內文（長文截 60 字沒有資訊量）。
- 簽核內容指紋：新鍵天然算內容（見 §1），不改規則；以測試鎖住「改備註 ⇒ 已簽簽核判過期」。
- 規格文件的上傳／刪除與編輯同閘門：**只有可編輯狀態（草稿、被退回；解鎖編輯期間）才能改 `mergeFiles` 與增刪檔**；簽核中不能偷換附件。

## 7. 會碰到的檔案
- 後端：`backend/pdf_gen.py`；`backend/helpers/pdf_merge.py`（新）；`backend/modules/case/api/quotations.py`（上傳／刪除端點、PDF 下載端點併入、`_TRACKED_QUOTE_FIELDS`、PUT／POST 驗證 `extraNotes` 長度與 `mergeFiles` 只能引用自己的檔）；`backend/modules/case/migrations/0013_*.py`（新）；`backend/routers/system.py`（範本 API）；`backend/modules/case/api` 的複製報價單處（複製時帶 `extraNotes`，**不帶檔案**，待確認 D3）。
- 前端：`frontend/pages/quotation-form.html`（備註框、套用範本、規格文件面板、管理範本對話框）；報價單／估價單共用，不改 `quotations.html`。
- 測試／文件：後端單元（builder 輸出、跳脫、舊單 golden 不變、合併三種壞檔、上限、權限／閘門、指紋、註記）、e2e（編輯→套範本→上傳→勾選排序→下載 PDF 頁數）、route_registry／locale 守門、CHANGELOG、MODULE-GUIDE。

## 8. 待使用者確認
- **D1** 上限數字（§4.5）。
- **D2** 存檔版本（docVersions）是否含併入附件（建議含）。
- **D3** 「複製為新報價單」：複製備註文字（建議是）；規格文件**不複製**（避免一份檔案被多張單共用、刪一張影響另一張）。
- **D4** 備註框是否也要出現在「內部版」以外的其他輸出（例如列印預覽、案件結案報告）——預設只有報價單／估價單 PDF 與預覽。
- **D5** 範本維護入口：報價單編輯頁內（建議，與條款組一致）或設定中心。

## 9. 工時（單人序列，含審查回修）
| 項目 | 天 |
|---|---|
| 備註欄位：資料鍵、builder 輸出、驗證、註記／指紋測試 | 1.0 |
| 範本：API、編輯畫面套用＋篩選、管理對話框 | 1.5 |
| 規格文件：migration、上傳／刪除／閘門、`pdf_merge` helper、下載併入、略過提示 | 2.5 |
| 編輯畫面：規格文件面板（勾選、排序、狀態提示） | 1.0 |
| e2e、golden 驗證、守門測試、文件 | 1.0 |
| 審查回修 | 0.5 |
| **合計** | **約 7.5 天** |

建議分兩段交：**A＝備註欄位＋範本（約 3 天）**，**B＝規格 PDF 併入（約 4.5 天）**。A 可先上線，B 不阻擋 A。

## 10. 可沿用盤點（2026-11-17，使用者裁示 A＋B 一次做完、動工前先查；D1～D5 已定案：10 檔／20MB／50MB／300 頁；docVersions 含併入附件；複製只複製備註文字；範本在 quotation-form 內管理）

**結論：新增 `quotations.spec_files_json`（與 `signed_files_json` 同形狀）。系統裡沒有「通用附件表」**——所有附件都是「各單據自己的 JSON 欄位＋uploads 資料夾」，再由擁有模組向 L1 登錄三件東西：①`uploads.path_access`（誰能讀這個路徑）②`attachments.for_document`／`catalog`（檔案中心、開檔、搜尋）③`save_document_files` 存檔。所以「掛到既有附件表」不存在；最一致的作法就是照 `quotation_signed` 的樣子加一個新來源類型。

| # | 項目 | 能不能用 | 理由／要改什麼 |
|---|---|---|---|
| 1 | 檔案中心 `file-center.html`／`/api/filehub/search`／`/api/attachments/open` | **要接上（小改，不改檔案中心本身）** | 它不存檔，是讀各模組 `attachments.catalog` 提供者的結果。新來源類型 `quotation_spec` 登錄進 M01 提供者（`modules/case/attachments.py`：`SOURCE_TYPES`、`_docs`、`_quote_of`、`_read`、`_READ_RULE`＝`case_page_readable`、`_FOLDER_SOURCE`、`_CATALOG_FOLDER`、`CATEGORIES`），規格文件就自動出現在檔案中心、可預覽、可搜尋，且可見範圍＝報價單本身（不寬不嚴）。**不登錄＝存得進去但檔案中心看不到、開檔 404**。資料夾用新的 `quotation_specs`（不與回簽共用 `quotations`，因為 `_FOLDER_SOURCE` 是「資料夾→單一來源類型」） |
| 2 | 案件附件上傳工具 `save_document_files`／`files_txn`／`append_json_list`／`remove_json_item`／`upload_path_key`／`pick_file` | **直接用** | 與回簽檔同一組；T83 的寫鎖重讀、失敗回收實體檔、路徑綁單據（W3）、魔術位元組檢查（`_check_upload_magic`，副檔名與內容不符會擋）全部現成。**要補兩點**：①這組上傳白名單是 jpg／png／pdf，沒有「只收 PDF」的資料夾級設定 ⇒ 在新端點先擋非 `.pdf`；②`UPLOAD_LIMITS_BY_SUBFOLDER` 加 `quotation_specs`＝`max_files 10`、`max_request_bytes 50MB`（單檔 20MB 沿用） |
| 3 | 客戶回簽檔 `signed_files_json`：上傳／刪除端點、前端預覽 | **端點樣式照抄、不共用端點** | 它的閘門是「報價單已送出才能傳」（`_signed_back_gate`）、刪除規則是上傳者本人或 admin+，和規格文件（送出前、跟著編輯狀態）相反，不能直接共用。前端預覽直接用 `MotrixFilePreview.openFile`（回簽附件現在就是這樣開的）；列表 chip 的樣子可沿用 |
| 4 | 派發／出納附件（`contractor_dispatches`、`shipping_notes`、`quotation_payment_items`…） | **不適用（但證實了模式）** | 各自綁自己的單據與讀取規則；都是同一個「JSON 欄＋資料夾＋提供者」模式，沒有可共用的儲存。出納只是對收付款項目附件加金額遮蔽規則，與本案無關 |
| 5 | 報價條款範本 `quote_terms_presets`（`routers/system.py`） | **照抄做法、不共用資料** | 整組覆寫 PUT（≤30 組）、僅最高管理者寫／能編輯者讀、稽核 `_audit`、變更通知 `_notify_quote_terms_changed`＋`_quote_terms_change_rows`、「存的是複製過去的文字」原則 ⇒ 範本 API 完全照這個形狀（鍵改 `quote_extra_notes_templates`，上限 100 組、每組 20,000 字）。通知函式要新增一支等價的（行內容是範本名稱／字數差異），不改條款組的 |
| 6 | `voucher_pdf._merge_pdfs`（傳票 PDF 合併） | **邏輯可用、不能直接 import** | 25 行純函式，已踩過三個坑（壞檔在開檔丟／加密到取頁才丟／零頁不丟）。它在 `modules/accounting` 內（私有函式）；M01 不能依賴會員模組（L2 模組可拆分，accounting 不在時案件頁仍要能輸出）⇒ 在 L1 新增 `helpers/pdf_merge.py`，帶同樣三個處理＋新增頁數／大小上限；**傳票那邊先不動**（不擴大本案影響面，之後可讓它改用共用件）。**一個刻意的差異**：傳票在末尾加一頁「併不進去清單」；報價單是客戶版文件，不能把我們內部的問題印給客戶看 ⇒ 缺口改用「上傳當下提示＋下載回應標頭＋畫面提示＋稽核」輸出（仍符合該檔的原則：不靜默略過） |
| 7 | 自訂欄位／模組建構器：長文字欄位 | **不適用** | 內建畫面（報價單）的自訂欄位型別只有 text／date／select／checkbox，文字上限預設 200 字，單據 JSON 上限 8KB（`builtin_fields.py`）；`textarea` 只有自訂模組有。備註事項要 20,000 字、純文字原樣保留 ⇒ 自己存 `data_json.extraNotes` |
| 8 | 自訂欄位／建構器：附件欄位 | **不適用** | `custom_files`（file／image 欄位）只服務「自訂模組的紀錄」（資料夾 `custom_records`，檔案綁在模組＋欄位）。附件插槽 `attachment_slots`（BP-4）目前只開放完工單、且在旗標 `builder_slots` 後面；都不是報價單用的 |
| 9 | 前端共用上傳元件 | **直接用 `AttachPicker`（`static/attach-picker.js`）** | 累加挑檔、逐一移除、送出前擋副檔名／單檔大小／數量／合計大小；預設值剛好就是 10 檔／20MB／50MB，我們只傳 `exts:['.pdf']`。與伺服器同一組限制，伺服器仍會再擋 |
| 10 | 前端共用可排序清單 | **不用；用 ↑↓ 按鈕** | `list-sort.js` 是「清單排序偏好」（存個人偏好），不是拖曳元件；報價單頁的 SortableJS 只綁品項表且有一整套鎖定規則。≤10 個檔案，↑↓ 按鈕更簡單、鍵盤與手機都可用（示意圖就是這樣畫） |

### 因盤點而追加的工作（都是追加，不改既有設計方向）
1. **M01 附件提供者登錄 `quotation_spec`**（見 #1）＋ `UPLOAD_LIMITS_BY_SUBFOLDER`／PDF-only 擋（#2）。守門測試要跟著補（新資料夾必須有 path_access 登錄、檔案中心找得到、跨單據路徑開不了）。
2. **簽核佇列的報價單詳情**（`quotations.py` 約 7395 行 `AT1` 區）：目前只列「付款條件」與附件；要加「備註事項」一列與「併入輸出的規格文件」（附件名稱前綴【規格文件】），簽核人才看得到將送給客戶的內容。附件檔案走該處既有的 `file_entries`，簽核人讀檔方式實作時驗證（不放寬 `case_page_readable`）。
3. **範本變更通知**新增專用函式（#5）；範本 PUT 要有稽核紀錄。
4. 檔案中心分類名稱：「報價單規格文件」（`CATEGORIES` 的 label）。

### 工時修正
盤點讓 B 段略增（提供者登錄＋守門測試＋簽核佇列詳情，約 +1 天），但省掉自寫上傳元件與排序元件（約 −0.5 天）；合計仍約 **8 個工作天**（一次交 A＋B）。
