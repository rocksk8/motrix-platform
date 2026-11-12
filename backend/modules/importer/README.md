# 匯入精靈（importer）

讓新買家把既有的客戶、料號、員工資料搬進系統：**下載範本 → 上傳 Excel／CSV → 解析與預覽 → 確認 → 結果**。設定中心群組 `import_wizard`（預設**關閉**）。

## 設計
- **無狀態**：本模組只做「範本下載」與「檔案解析」，**不寫任何資料表、不存上傳檔、沒有批次表**。
- **不另開寫入路徑**：解析出來的列由頁面送到 L1 既有的 import-rows 端點（`dryRun` 預覽 → `planHash` 確認）：
  `POST /api/customers/import-rows`、`POST /api/parts/import-rows`（匯入不再抹掉拜訪紀錄、空白不更新、整批一個交易）；員工用 `POST /api/users/import-rows`（只有最高管理者、只新增、臨時密碼只顯示一次）。
- 客戶頁、料號頁原有的匯入按鈕**維持不變**，旁邊多一個「或用匯入精靈（含範本與預覽）」連結（設定開啟時才顯示）。

## 端點
- `GET /api/importer/status`（探針）、`GET /api/importer/templates/{kind}`、`POST /api/importer/parse`（multipart：`kind`＋`file`）。
- 權限：客戶／料號＝與既有匯入相同的模組權限；員工＝只有最高管理者。設定關閉時範本與解析回 404。

## 解析規則（`parser.py`）
只收 .xlsx／.csv（.xls、.xlsm 白話拒絕）；檔案上限預設 5 MB（設定可調 1～20）；列數上限 客戶／料號 5000、員工 300；欄數 60、儲存格 2000 字；
拒絕含巨集、解壓過大、缺 workbook 的 zip；公式儲存格不匯入（當空白並警告）；只讀可見的「資料」工作表；CSV 依 UTF-8（含 BOM）→ Big5 解碼；
表頭容錯（全半形、大小寫、空白、星號、同義表頭）；同一欄位出現兩次＝錯誤；未知欄位列在「未使用的欄位」；範例列（開頭「（範例，請刪除）」）略過；
空白儲存格輸出空字串（絕不輸出 0／null）；新增的檢查（統編檢查碼、Email 格式）只是警告。

## 資料分類
無資料表、無檔案。上傳內容只在請求記憶體裡，不留暫存；稽核只記對象、檔名、檔案雜湊前 16 碼、列數與警告數，不放儲存格內容。

## 串接點與對方不在時
- 依賴 L1：`helpers/company_setup.ubn_valid`、`routers/{customers,parts,auth}.py` 的 import-rows、設定群組 `import_wizard`。
- 本模組不在：入口與頁面不顯示，客戶頁、料號頁原有的匯入照舊；L1 的 import-rows 端點仍可用。
