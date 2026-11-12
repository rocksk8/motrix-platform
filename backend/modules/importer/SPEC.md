# 匯入精靈（importer）· 規格條件

> 2026-11-13 建立（T85；提案 `docs/platform/plans/IMPORT-WIZARD-PROPOSAL.md`）。格式同 `modules/filehub/SPEC.md`。

## 用途與 API

- 範本下載與檔案解析（無狀態）。端點：`GET /api/importer/status`、`GET /api/importer/templates/{kind}`、`POST /api/importer/parse`。

## 規格條件

- **IMW1.** 解析與範本**不寫任何業務資料表**；上傳檔只在請求記憶體裡，不存檔、不留暫存。
- **IMW2.** 寫入一律走 L1 既有的 import-rows 端點（客戶、料號、員工），本模組沒有第二條寫入路徑。
- **IMW3.** 空白儲存格輸出空字串，絕不輸出 0 或 null（既有規則：空白＝不更新）；數字儲存格不帶小數點尾巴（`12345`，不是 `12345.0`）。
- **IMW4.** 檔案安全：只收 .xlsx／.csv；拒絕 .xls／.xlsm／含巨集／解壓過大／內容與副檔名不符；公式儲存格不匯入；只讀可見的資料工作表；超過列數上限整檔拒絕並說明如何拆檔。**資源上限（hichan-9 審查 H1）**：解析前先串流掃一遍工作表 XML（不信檔案自己宣告的範圍），儲存格 >25 萬、欄 >50（訊息指出是哪一欄）、列號 >10 萬、工作表 XML >30MB 在讀內容前就白話拒絕；整個解析 10 秒期限；同時最多 2 個解析。空白區段不讓讀取提早結束（只在資料列之間出現空白時警告「第 N 列後有空白區段，之後的資料已一併讀取」），列數上限算「有內容的列」（CSV 的空白行不算）。
- **IMW5.** 員工匯入的檔案不收密碼：密碼欄被忽略並警告，解析輸出只記「有沒有填」，密碼值不出現在任何輸出。
- **IMW6.** 設定 `import_wizard.enabled` 預設 0；關閉時範本與解析回 404；客戶頁、料號頁原有的匯入不受影響。

## 範圍

### THIS
- 本模組：`parser.py`、`api.py`、頁面 `import-wizard.html`。

### NEXT
- 歷史報價匯入（待使用者裁示，不在 v1）。

## 測試

- `backend/modules/importer/tests/test_importer_t85.py`、`backend/tests/test_user_import_t85_2026_11_13.py`。
