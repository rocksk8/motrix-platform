# 業務開發 更新紀錄

## (next) — 2026-11-14（feat/t87-b2-h12；T87 B2 自訂報表；版號由列車取）
- 新增（行為、API、欄位、權限語意不變）：`report_source.py` 登記自訂報表來源 `dev_case`（商機；列範圍＝`row_access` dev_case、排除已刪除；預估金額欄依金額檢視權限）。測試：`tests/platform/test_report_runner_t87.py`。

## 1.2.10 — 2026-11-14（train/t86-int；整合者：篩選欄位標記）
- 前端（行為不變）：業務開發頁新增的狀態變更原因欄補上 `data-saved-field`（view_filter 守門：名稱像篩選的欄位需標明是看法類或存檔欄位）。

## 1.2.9 — 2026-11-14（train/t86-int；整合者：T86 文字最後一輪）
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：商機頁（dev-crm）最後一輪用語（尚未指定業務開發、僅建立者與主管可檢視…）；此條補寫於 T86 整合最後一次合併之後。
- **（併入）(next) — 2026-11-14（feat/t86-b1-h2；T86 文字：中性正式用語補正）**
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：說明與提示改依「正式＋中性」準則用語（此條補寫於 T86 整合合併 #17 之後）。
- **（併入）(next) — 2026-11-14（feat/t86-b1-h2；T86 文字：看得到／看到等權限與顯示用語）**
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：說明與提示中的「看得到／看不到／看到」依語境改為「可檢視／無法檢視」（權限）或「顯示／所見」（畫面），並補正前一批漏改的空狀態文字。
- **（併入）(next) — 2026-11-14（feat/t86-short-labels-h2；T86 短標籤專業化）**
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：按鈕、卡片標題、表頭、空狀態與提示等短標籤改為正式、一致的用語（前往／查看、尚無／查無符合條件的…、僅顯示、無法…等）；前後對照見整合者的 T86 前後對照表。
- **（併入）(next) — 2026-11-14（feat/t86-devcrm-e-h7；T86 業務開發 #17 預估金額／預計成交日；版號由列車取）**
- **schema +1：crm 模組 schema 版本 4→5**（模組 migration `0005_dev_case_expected`，`dev_cases` 新增 `expected_amount INTEGER NULL`、`expected_close_date TEXT NULL`；可重跑、表不存在時回報原因不報錯）。核心 `db.py` `CURRENT_VERSION`（V9 基準 118）不變——核心 migration 已凍結，新欄位走模組 migration。
- API（只增不減）：`GET/POST/PATCH /api/dev-cases…` 的案件物件多 `expectedAmount`（整數，無金額權限時為 null）、`expectedAmountVisible`、`expectedCloseDate`（`YYYY-MM-DD`）；寫入欄位 `expectedAmount`／`expectedCloseDate`（未帶＝維持原值，`null` 或空字串＝清除）。金額須為 0 至 9,999,999,999 的整數、日期須為有效日期（過去日期允許），否則 400。
- 權限：金額跟既有財務檢視權限（`can_see_financial`）走；沒有權限的人看到 null（頁面顯示「—」），填寫金額回 403「無權限填寫預估金額」，送 null 則維持原值。稽核紀錄不含金額（只記「已設定／已變更」）。
- 新增 `GET /api/dev-cases/expected-summary`：漏斗「預估金額合計」由後端算（依案件可見範圍、排除已刪除），回傳 `visible`、`total`、`count`、`missing`（未填金額件數）與各狀態 `byStatus`；沒有金額權限時 `total` 為 null。清單 `GET /api/dev-cases` 仍是純陣列，所以合計另開端點。
- 前端 `dev-crm.html` 不在本批（由頁面負責視窗接）。
- 測試：`tests/test_dev_case_expected_2026_11_14.py`；`tests/test_dev_log_directive_2026_11_04.py` 的 crm 版本釘住改為 5；`tests/platform/response_keys_baseline.json`、`route_inventory.json` 同步。

## 1.2.8 — 2026-11-14（train/t85-text；T85 文字專業化；版號由列車取）
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：畫面、通知、錯誤提示與說明文字改為正式、一致的用語（您、尚未／尚無、是否、其他使用者、無法／不可等），標點與中英文間距依 `docs/platform/plans/TEXT-STYLE-GUIDE.md`；同一提交同步更新斷言字串的測試。逐項前後對照見 `docs/platform/plans/TEXT-DIFF-TABLE.md`。

## 1.2.7 — 2026-11-13（feat/upload-files-txn-4；T86；版號由列車取）
- 修正（內部，API 路徑與回應形狀不變）：業務開發記錄刪附件（`DELETE /dev-logs/{id}/files/{fid}`）改用 `remove_json_item`（鎖內重讀、commit 後才刪實體檔，並發補附件不被整包覆寫）；刪整筆記錄（`DELETE /dev-logs/{id}`）原本在 commit 之前刪檔，改為同一把寫鎖內讀＋DELETE、commit 之後才刪（路徑經 `canonical_upload_path` 驗證）。 測試：`tests/test_upload_files_txn4_2026_11_13.py`。
- **（併入）(next) — 2026-11-13（feat/upload-files-txn-2；T84；版號由列車取）**
- 變更（內部，API 路徑與回應形狀不變）：業務開發記錄（`POST /api/dev-cases/{id}/logs`）改用 `helpers.uploads.files_txn`：寫庫失敗，或案件在上傳途中被刪（鎖內重查 `is_deleted=0`，回 404），都回收剛存的檔。 測試：`tests/test_upload_files_txn2_2026_11_13.py`。

## 1.2.6 — 2026-11-13（fix/estimate-static-labels；估價單用語）
- 用語：轉建彈窗／按鈕／連結異動彈窗與輸入框提示改為中性「報價單／估價單」（輸入框提示不再寫 MQ 字首）；「轉建」站內通知與信件主旨依連結單號字首顯示「轉建報價單」或「轉建估價單」。連結時「單號不存在」三句（轉建連結、申請修改連結、核准）依單號字首顯示「報價單」或「估價單」；其餘 API 錯誤訊息不變。

## 1.2.5 — 2026-11-13（feat/ux-p15-dashboard；UX P1.5）
- 前端（文字）：頁面 `<title>` 後綴「專案管理系統」一律改為「MOTRIX PLATFORM」（系統標語改由公司設定 `brand.tagline` 決定，預設 MOTRIX PLATFORM）；不動 API／資料／權限。

## 1.2.4 — 2026-11-13（fix/t81-line-reds；T81 LINE 全信件接線的 CHANGELOG 補記，版號由列車取）
- 變更（內部，不影響對外介面）：`api.py` 接上 LINE 獨立通道——案件建立／狀態變更（`crm_case_created`／`crm_case_status`，收件人＝業務、企劃、被指派人、建立者）、指派／取消指派／期限調整（`dev_case_assigned`／`dev_case_unassigned`／`dev_case_deadline_changed`）；泛用的 module_activity 對這幾件事不重複推 LINE。LINE 只送給有業務開發權限（`dev_crm`）的人。無 API／資料變更。
- 測試：`tests/test_line_events_all_2026_11_13.py`、`tests/test_line_crm_perm_filter_2026_11_13.py`。

## 1.2.3（next，未取號）— 2026-11-13（ui/mobile-tablet-combined 的改動；條目由 fix/mobile-cases-layout-v2 補，依各頁 git 歷史照實記錄；僅前端版面，不動 API／資料／權限判斷）〔train_number：1.2.2 → 1.2.3〕
- `dev-crm.html`：手機（≤767px）案件清單與詳情改上下切換——詳情開啟時清單收起，新增「← 案件列表」返回鈕（`data-testid="dc-m-back"`，僅手機顯示）；其餘為觸控目標與間距調整。桌機版不變。

## 1.2.2 — 2026-11-13（fix/backlog-bugs-20261113；T81 backlog 修正，版號由列車取）
- 前端（`dev-crm.html`）：無權限說明加上「剛被開通請重新登入」；擋人前先查 `/api/auth/me` 的即時模組清單（審查 L4）。無 API／資料／權限判斷變更。
- 測試：`tests/test_e2e_dev_crm_no_access_notice_2026_11_13.py`。

## 1.2.1 — 2026-11-11（feat/ux-navigation-hierarchy；UX 提案批次 1+2「導覽與資訊架構＋視覺層級」；不動 API／資料／權限判斷；K 審後補：業務開發名次欄放寬；L1 介面不變）
- 頁頭（B6）：`customers.html` 眉標改為麵包屑（客戶與業務 › 客戶管理）；客戶管理從「廠商與採購」移到「客戶與業務」群組（order 30），入口與權限不變。
- 前端視覺（D3）：本模組頁面內文字最小 12px（原有 9～11px 一律拉到 12px）；文字色改用語意 token（`--text-secondary` #595959／`--text-dim` #666666／深底 `--text-on-dark-dim` #A3A3A3，在頁底 #F5F4F0 上對比 ≥4.5:1）。只改 CSS 值，不改版面結構、不改 API、資料、權限。規格見 `docs/UI-HEADER-COLOR-SPEC.md`。
- 補修（K 審 N4）：`dev-crm.html` 的活動排行名次欄由固定 14px 寬改為最小 16px，12px 字級下兩位數名次不再撐版。
- 測試：`tests/test_e2e_nav_hierarchy_2026_11_11.py`（7 項真瀏覽器：每個舊入口仍可達、群組與報表中心頁籤、權限過濾、頁頭麵包屑）。

## 1.2.0 — 2026-11-04 13:40（wip/hichan8-dev-log-directive-v1：開發記錄「批示」，見 docs/platform/plans/DEV-LOG-DIRECTIVE-PLAN.md）
- 新增：`migrations/0004_dev_log_directive.py`（`module_schema_versions.crm` 3→4，冪等）：新表 `dev_log_directive`（批示與回覆同表，`parent_id` 只一層；只增不改不刪）、`dev_log_directive_target`（通知／待回覆對象，`must_reply`、首次回覆時間 `replied_at`，`UNIQUE(directive_id, user_id)`）；兩張都帶 `owner_unit_id`。**不碰 `dev_logs`**（不連動客戶拜訪、行事曆、接洽統計、報價單動態），**不重置 `dev_cases.updated_at`**（那是 30 天停滯警報的依據）。
- 路由：`GET /api/dev-cases/{id}/directives`（整案批示＋回覆＋對象＋`canDirect` 旗標）、`POST /api/dev-cases/{id}/directives`（下批示）、`POST /api/dev-cases/{id}/directives/{directive_id}/replies`（回覆）。沒有修改／刪除端點：寫錯就再發一筆。
- 權限：新能力 `crm.dev_log_directive.comment`「對開發記錄下批示」（`module.json`，沿用既有動作 `comment`；legacy＝admin ⇒ 上線當天只有管理員／最高管理者，之後在權限矩陣可勾給別人）。下批示＝業務開發模組 ＋ 此能力 ＋ 看得到該案件；回覆不需要此能力（批示作者與被列為對象的人可回）。對象 1～10 人、不含自己、去重；每人須在職、有業務開發權限（或管理員）、看得到該案件，否則 400 並列出名字。
- 可見度（使用者裁示）：只有管理員、批示作者、被列為對象的人看得到批示與回覆；其他人 GET 什麼都不回、回覆得到 404（不洩漏存在）。
- 通知：站內通知給所有對象（`dev_log_directive`／`dev_log_directive_reply`）；信件只寄 `must_reply=1` 的對象（新 mail type `dev_log_directive`，本文不放批示全文）；**不呼叫 `notify_module_activity`**（它會把全文寄給全體 admin）。稽核 `dev_log.directive`／`dev_log.directive_reply`（標籤只放前約 40 字）。
- 既有行為唯一變動：`DELETE /api/dev-logs/{id}` 若該紀錄已有批示 ⇒ 409（單一陳述 `DELETE … WHERE NOT EXISTS`，與同時新增批示不會交錯；訊息不提「批示」）。`PUT` 編輯不受影響（已知限制：被批示的紀錄仍可被改內容）。
- 前端 `dev-crm.html`：開發記錄卡「編輯」「刪除」旁加「批示」鈕（有能力才顯示）、批示／回覆串顯示在記錄卡下方（待回覆標示）。
- 備份／展示庫：`archive.py` 備份匯出加「業務開發批示」「業務開發批示對象」；`db.py` `DEMO_CLEARED_TABLES` 加兩張新表。
- 測試：`modules/crm/tests/test_dev_log_directive_2026_11_04.py`。

## 1.1.0 — 2026-11-04 10:55（wip/hichan3-dev-case-progress-v2：業務開發案件「指派／進度回報」重設計，見 docs/platform/plans/DEV-CASE-PROGRESS-REDESIGN-PLAN.md）
- 新增：`migrations/0003_dev_case_progress.py`（`module_schema_versions.crm` 2→3，冪等）：新表 `dev_case_progress(id, case_id, author_id, content, created_at)`（進度回報歷史，只增不改不刪）；`dev_cases` 加 `assigned_at`／`assigned_by`（只在換人、首次指派、取消指派時更新）。既有 `progress_report` 非空的案件搬成第一筆進度（作者＝當時的 `assigned_to`、沒有被指派人則留空顯示「（舊資料）」；時間＝`updated_at`），已指派案件的 `assigned_at` 設成 `updated_at`（遷移當下不會把有回報的案件誤判逾期）。舊欄位 `progress_report` 保留不再使用。
- 路由（破壞性變更，僅限本模組前端使用）：**移除** `PATCH /api/dev-cases/{id}/progress`（整段覆寫、管理員可代填）；**新增** `POST /api/dev-cases/{id}/progress`（新增一筆；**只有目前被指派人本人可以；不是被指派人的管理員（含 superadmin）403，管理員本人就是被指派人時可寫**；內容 1～4000 字不得空白）與 `GET /api/dev-cases/{id}/progress`（歷史，新到舊，依 `row_access` 可見者）。沒有修改／刪除端點：寫錯就再新增一筆。
- 案件回傳欄位：`progressReport` 移除；新增 `currentProgress`（目前被指派人自指派之後寫的最新一筆，沒有＝null）、`progressCount`、`overdueDays`、`assignedAt`、`assignedById`、`assignedByName`。
- `PATCH /api/dev-cases/{id}/assign` 只有真的變才動作：對象與期限都沒變＝不寫 DB／不稽核／不通知／`updated_at` 不動；換人＝新負責人站內＋信、前任站內「不再負責」；取消指派＝只通知前任（站內）；只改期限＝只通知被指派人（站內，不寄信）。期限早於今天回 400（期限有改動，或換人／首次指派時沿用過期期限都算；同人同期限原封不動重存仍是 no-op）；取消指派時回覆期限一併清空；日期格式嚴格 `YYYY-MM-DD`（Python 3.11 的 `fromisoformat` 也收 `20261201`，存進去會讓逾期判斷的字串比較錯位）。
- 逾期提醒（新）：洽談中、期限已過（當天不算）、被指派人自指派後沒有任何進度 ⇒ 詳情與清單標紅「逾期 N 天未回報」；每日排程 `_check_dev_case_reply_overdue()`（與停滯提醒同一支排程）提醒一次（站內＋信，新 mail type `dev_case_reply_overdue`），guard key＝案件＋期限＋被指派人，收件人＝被指派人＋指派人，任一方停用或沒有紀錄（舊資料）另加全體 admin。
- 前端 `dev-crm.html`：進度區改成「目前進度（作者·時間）＋新增輸入（僅被指派人）＋歷史紀錄（可展開）」，不是被指派人的管理員唯讀；清單卡片與詳情顯示逾期標示；期限日期欄 `min`＝今天。
- 備份／展示庫：`archive.py` 備份匯出加「業務開發進度回報」；`db.py` `DEMO_CLEARED_TABLES` 加 `dev_case_progress`。
- 測試：`modules/crm/tests/test_dev_case_progress_redesign_2026_11_04.py`（進度權限與內容、只增不改、換人後歷史、指派只有真的變才動作與通知對象、逾期端點與排程收件人／只提醒一次／重新武裝、信件登記與寄信函式、migration 0003 用 T73 之後含舊進度文字的資料實測且冪等）；`test_dev_case_assignment_2026_11_03.py` 的 v2 進度三題移除（由上列取代）、固定日期改相對今天。

## 1.0.19 — 2026-11-04（train/t73-int；T73 列車整合後第二輪獨立稽核必修修正）
- 修正（內部邏輯，無新介面）：每日排程 `_check_dev_case_stale()` 的 SELECT 補 `assigned_to`，收件人併入被指派人，
  與 1.0.18 已修正的其他 4 處手列欄位同一模式（獨立稽核 T73A-M1，`docs/platform/audit/AUDIT-pm-sub-t73.md`）。
  題：`test_assignee_gets_the_daily_stale_reminder_notification`。

## 1.0.18 — 2026-11-03（已由 train_number.py assign 取號；wip/t73-dev-case-assignment-r1：T73 業務開發案件指派成員／回覆期限／進度回報）
- 新增（只增）：`dev_cases` 加 `assigned_to`／`reply_deadline`／`progress_report` 三欄（`migrations/0002_dev_case_assignment.py`）。
- `DEV_CASE_ACCESS`（`row_access.OwnerRule`）加 `owner_id_col="assigned_to"`：被指派人取得與業務／企劃同等的完整存取（使用者裁示），list/get/update/status/convert/relink/logs 全部既有端點自動套用；另外手列欄位的 5 處（`item_reads.py` 未讀標記、本模組 activity-stats、analytics 停滯提醒與動態牆、本模組每日排程 `_check_dev_case_stale`）SELECT 補上 `assigned_to`，避免同樣的可見性判斷在不同出口漂移（審查發現，`helpers/row_access.py` 開頭就是在講這個問題；第 5 處由列車整合後的獨立稽核補發現，見 `docs/platform/audit/AUDIT-pm-sub-t73.md` T73A-M1）。`_check_dev_case_stale` 的通知收件人也補上被指派人（原本只有 sales_persons／planners／created_by 落空時才退回備援，現在一律同等收提醒）。
- 新端點 `PATCH /api/dev-cases/{id}/assign`（admin 限定，指派成員＋設定回覆期限，站內通知＋email）、`PATCH /api/dev-cases/{id}/progress`（被指派人或 admin 填寫進度回報）。
- 前端 `dev-crm.html` 加對應 UI（指派下拉＋期限日期、進度回報 textarea）。
- 測試：`modules/crm/tests/test_dev_case_assignment_2026_11_03.py`、`test_dev_case_assignee_visibility_hichan10_2026_11_03.py`（後者 2026-11-04 補每日停滯通知＋ops-alerts／activity-feed 兩個端點的真實呼叫測試）。

## 1.0.17 — wip/t63-status-labels-r1（狀態顯示尾巴：dev-crm）
- 開發案件頁（`dev-crm.html`）的案件狀態徽章、漏斗標籤、歷史列、記錄狀態快照與兩個狀態下拉的選項文字，可由設定中心「狀態顯示名稱與顏色」改顯示字（旗標 `builder_status_display.enabled` 預設關＝與過去逐字相同）；只換字：徽章樣式、篩選、狀態更新請求與 SQL 一律用原始狀態值。無 migration、無新路由、無權限變更。

## 1.0.16 — 2026-10-01（wip/w1-attach-p3-a3：附件目錄 P3）
- 附件目錄 P3：`_CrmCatalog` 加 `search`／`count`（開發記錄附件；權限＝`_DevLogPathAccess.readable` 逐開發案）。

## 1.0.15 — 2026-10-01（暫用號，列車取號；wip/w3-local-date）
- 本地日期（使用者 2026-10-01：凌晨建的單日期變前一天）：業務開發頁的記錄日期預設值改用本地日期（static/motrix-date.js）。

## 1.0.14 — 2026-09-30（暫用號，列車取號；wip/w2-open-bind：附件開檔路徑綁單據（安全審查 W3））
- 附件目錄提供者 `open()` 加路徑綁單據檢查（`helpers.uploads.upload_path_key`）：檔案路徑不在這張單據自己的資料夾 ⇒ 當作沒有這個檔。

## 1.0.13 — 2026-09-30（暫用號，列車取號；wip/w2-referrer：業務開發新增「介紹人」）
- 新增案件欄位「介紹人」（`dev_cases.referrer`，自由文字、選填、去頭尾空白、最多 60 字；超過或型別不對 400）：由本模組自己的 migration（`migrations/0001_dev_cases_referrer.py`，只新增一欄、冪等）建立；新增／編輯視窗、列表卡片、詳情、搜尋框（也搜介紹人）、編輯稽核 old→new；備份匯出的 `SELECT *` 自動含此欄。不帶到轉建的報價單（報價單沒有對應的自由「來源」欄位）。

## 1.0.12 — 2026-09-30（暫用號，列車取號；wip/w2-attach-p2：附件目錄 P2）
- 新增 `attachments.py::_CrmCatalog`（`attachments.catalog`／`crm`，IP-105）：開發記錄附件開檔；權限＝`_DevLogPathAccess`（模組規則＋row_access dev_case）。

## 1.0.11 — 2026-09-30（暫用號，列車取號；wip/w1-file-preview 共用檔案預覽 P1）
- 業務開發頁的附件開啟改用 L1 共用預覽元件（頁內預覽，不再開新分頁／換 photo-token）。

## 1.0.10 — 2026-09-30（暫用號，列車取號；wip/cal-toggle 行事曆推送可選）
- 行事曆「業務開發案件更新」（預設關，事件種類開關在 L1）：新增開發紀錄 commit 之後推 `push_event_for_module('dev_case_update', …)` ⇒ 標題「○○案件更新」、說明＝紀錄內容（管道／內容／下一步）、同一案件同一天合併。題 `modules/crm/tests/test_dev_case_update_calendar_2026_09_30.py`
## 1.0.9 — 2026-09-30（暫用號，列車取號；wip/sec-p0 安全修正 P0）
- 安全修正 P0：新增提供者 `uploads.path_access`／`crm`（IP-104，`api._DevLogPathAccess`）：`dev_logs/<案 id>/` 的附件只簽給 `GET /dev-cases/{id}/logs` 放行的人（admin+ 或 dev_crm，且 row_access `dev_case`）。原本任何登入者都拿得到簽章。

## 1.0.8 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`dev-crm.html`

## 1.0.7 — 2026-09-26〔稽核 X C4-S5：c-probes 先上第八班、用了 1.0.6 ⇒ 本段改 1.0.7〕
- D7 演練：`module.json` 宣告 `provides.probes`（`/api/dev-cases`、`/api/dev-logs/pending`、`/api/dev-crm/activity-stats`）——純讀的 GET、在本模組前綴下、模組在時回 200（守門 `tests/platform/test_product_drill_probes.py`、`test_probe_side_effects.py`：不寫表、不寄信、不排程、不把回應值寫進 log）
- 選單宣告搬進本模組：`dev-crm.html` 的 `pages[].menu`（原寫在 L1 的 `core/menu_l1.json`；group／order／perm／badge 原值照搬）。階段 C／C4（主持裁示 A）：本模組不在時它的入口隨宣告一起消失，不再靠前端寫死的頁面⇒模組對照表；版號與 c-probes／h-probes 交會，列車取號

## 1.0.5 — 2026-09-26
- 稽核 D M02-S2 觀察：補核准端點（刪除／重新連結）的外人題，並分開角色與列權限——建立者（有列權限）申請 403、管理員（不在名單）申請成功；外人／建立者／管理員核准 403 且資料不變，最高管理者核准成功；突變（兩個核准放寬成管理員、兩個申請不擋角色）皆紅〔原為 1.0.3（wip/c-m02-s2b 6e2e15a7）；第五班定 1.0.4 之後改號〕

## 1.0.4 — 2026-09-26
- 第五班列車反向控制（§B-11）：刪報價單「M02 在 ⇒ 沒有 notice」的 e2e 正對照需要本模組，自模組外拆進 `modules/crm/tests/test_e2e_crm_quote_delete_no_notice_2026_09_26.py`

## 1.0.3 — 2026-09-26
- 第五班列車：IP 定號（`crm.quote_deleted` IP-11→IP-13；origin 已用到 IP-12 `case.access`）

## 1.0.2 — 2026-09-26
- 稽核 D M02-S2：補「改不了」的題——外人修改內容、狀態、轉建、新增開發記錄一律 403 且資料不變，刪除／重新連結申請只准管理員；突變（四個端點各拿掉列權限檢查）皆紅

## 1.0.1 — 2026-09-26
- 稽核 D M02-M1：需要本模組的 33 題搬進 `modules/crm/tests/`（整檔 2、拆出 7 檔；混合檔只拆業務開發那幾題），本模組不在時跟著消失
- `module.json` 補 `customization`（P3：目前沒有宣告可自訂點）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/dev_crm.py` 搬入 `modules/crm/api.py`（PLAYBOOK §B）；路由自帶 `/api` 前綴，由載入器掛載；每日 08:00 的停滯／暫緩到期檢查改由 `ModuleSpec.schedulers` 宣告
- 新增串接點 IP-13 `crm.quote_deleted`：報價單刪除時解除轉建連結改由本模組提供（原本 M01 直寫 `dev_cases`）
- 報價單清單刪除時顯示 IP-13 的 notice（原本只看成功與否）
