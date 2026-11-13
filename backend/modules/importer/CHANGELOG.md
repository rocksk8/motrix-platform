# 匯入精靈 更新紀錄

## 1.0.2 — 2026-11-13（hichan-9 Low＋全量守門收尾）
- CSV：單格內容過長、引號不成對給具體訊息（不再是籠統的「讀不出來」）。
- 範本 .xlsx 的所有文字寫入都經 `helpers.xlsx_out.xl_safe_xlsx`（公式注入中和；範本內容本來都是程式自己的字，這是讓守門掃描器認得）。
- 登記：`docs/platform/upload_points.json`（`POST /api/importer/parse`＝不存檔、不進附件目錄）、`docs/platform/modules.json` 的 L1 單位（`helper:user_import`、`helper:settings_groups_import_wizard`）。

## 1.0.1 — 2026-11-13（hichan-9 對抗審查 H1／M4／L1／L2／L6 修正）
- H1：xlsx 解析前先串流預掃工作表 XML（1MB 一塊；數格數、列數、列號、欄；不依賴檔案宣告的大小，也不再讓 openpyxl 依宣告範圍補空格）；上限 25 萬格／50 欄／列號 10 萬／工作表 30MB，超過就白話拒絕；整個解析 10 秒期限；同時最多 2 個解析（忙碌回 429）。實測 100 萬格的檔案 0.3 秒拒絕、尖峰記憶體遠低於 100MB；5000 列×19 欄的正常檔解析約 1 秒、尖峰約 15MB。
- M4：不再「連續 500 個空白列就停止」；空白區段後面的資料一併讀取並警告（「第 N 列後有空白區段，之後的資料已一併讀取」）。
- L1：統編欄不是數字（N/A、無）逐列警告並當成沒有統編；數字格的電話開頭 0 可能被吃掉、數字格的料號逐列／彙總警告；範本整欄設文字格式（不只前 500 列）。
- L2：CSV 空白行不算進列數上限。L6：欄數超過上限時訊息指出是哪一欄（例如「AY 欄」），不再是籠統的「欄位太多」。

## 1.0.0 — 2026-11-13（feat/import-wizard；T85 匯入精靈 B0～B3：客戶／料號／員工）
- 新增模組：`GET /api/importer/templates/{kind}`（範本 .xlsx：資料＋說明工作表、灰底範例列、角色下拉）、`POST /api/importer/parse`（xlsx／csv 解析，無狀態、不寫資料表）、`GET /api/importer/status`（探針）；頁面 `import-wizard.html`。
- 設定中心群組 `import_wizard`（`enabled` 預設 0、`max_file_mb` 預設 5）；設定關閉時範本與解析回 404。
- 客戶／料號沿用既有 import-rows（預覽→確認）；員工走 L1 新端點 `POST /api/users/import-rows`（見 core CHANGELOG）。
