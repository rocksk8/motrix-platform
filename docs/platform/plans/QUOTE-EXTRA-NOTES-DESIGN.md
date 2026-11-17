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
