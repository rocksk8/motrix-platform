# 匯入精靈 更新紀錄

## 1.0.0 — 2026-11-13（feat/import-wizard；T85 匯入精靈 B0～B3：客戶／料號／員工）
- 新增模組：`GET /api/importer/templates/{kind}`（範本 .xlsx：資料＋說明工作表、灰底範例列、角色下拉）、`POST /api/importer/parse`（xlsx／csv 解析，無狀態、不寫資料表）、`GET /api/importer/status`（探針）；頁面 `import-wizard.html`。
- 設定中心群組 `import_wizard`（`enabled` 預設 0、`max_file_mb` 預設 5）；設定關閉時範本與解析回 404。
- 客戶／料號沿用既有 import-rows（預覽→確認）；員工走 L1 新端點 `POST /api/users/import-rows`（見 core CHANGELOG）。
