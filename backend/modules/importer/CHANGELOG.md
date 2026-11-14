# 匯入精靈 更新紀錄

## (next) — 2026-11-14（train/t86-int；整合者：h9 空值防護併入）
- 前端（行為不變，只補空值防護）：匯入精靈 `import-wizard.html` 的 `parsed.warnings`／`plan.errors` 在尚未載入時不再讀 null（pageerror）。（h9 `fix/home-widgets-null-t86-h9-r2`）

## 1.0.5 — 2026-11-14（feat/t86-b1-h2；T86 文字：中性正式用語與覆核修正）
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：依「正式＋中性，不用負面或催逼語意」準則調整畫面用語（例：收款追蹤、跟進、待處理、保固已到期），並補正少數「目前沒有」「看得到」「打開」等殘留與測試斷言。
- **（併入）(next) — 2026-11-14（feat/t86-short-labels-h2；T86 短標籤專業化）**
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：按鈕、卡片標題、表頭、空狀態與提示等短標籤改為正式、一致的用語（前往／查看、尚無／查無符合條件的…、僅顯示、無法…等）；前後對照見整合者的 T86 前後對照表。

## 1.0.4 — 2026-11-14（T84 診斷修正輪；整合者補登）
- 範本下載（`importer_template`）的 `Content-Disposition` 改走 `helpers.download_name.content_disposition`（下載檔名守門：不再手寫 attachment 標頭；檔名與內容不變）。
- 精靈頁標題改為「MOTRIX PLATFORM」（畫面不再寫「專案管理系統」；品牌用語守門）。

## 1.0.3 — 2026-11-13（rebase 到 T82 凍結 head f66dfd9ef；改用共用守門）
- 內部（行為與回應形狀不變）：xlsx 解析改走 `helpers.xlsx_guard.read_rows(slot_name="importer")`（T82 已有；預掃＋子行程隔離讀取＋硬逾時／記憶體上限＋同時解析數），刪掉自己的串流預掃（`_check_zip`／`_prescan_sheet`／`_sheet_part`）與 `MAX_UNZIPPED`／`MAX_CELLS`／`MAX_ROW_TAGS`／`MAX_SHEET_XML`。守門拒絕的白話訊息原樣轉成 ParseError（400）；同時解析太多 ⇒ XlsxBusy ⇒ 429。守門上限改採 helper 預設（單張工作表 XML 12MB、解壓總量 40MB；其餘同前）。
- 仍由本模組負責：選資料工作表（「資料」優先、否則第一張非「說明」的可見表）、公式儲存格不匯入、數字格警告、列數上限只算有內容的列。

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
