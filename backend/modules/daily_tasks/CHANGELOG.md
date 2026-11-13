# 每日任務 更新紀錄

## 1.0.18 — 2026-11-14（train/t85-text；T85 文字專業化；版號由列車取）
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：畫面、通知、錯誤提示與說明文字改為正式、一致的用語（您、尚未／尚無、是否、其他使用者、無法／不可等），標點與中英文間距依 `docs/platform/plans/TEXT-STYLE-GUIDE.md`；同一提交同步更新斷言字串的測試。逐項前後對照見 `docs/platform/plans/TEXT-DIFF-TABLE.md`。

## 1.0.17 — 2026-11-13（feat/onepipe-p4；一條龍 P4a：現場人員自建案件事項；旗標 `onepipe.entry_unify`，預設開（升級後一條龍功能預設開啟；關閉＝與今天逐位元相同））
- 一條龍 P4b-③（旗標 `onepipe.entry_unify`）：`daily-tasks.html?case_no=<案號>` ⇒ 最高管理者直接開「新增事項」並帶好案件；現場人員在旗標開、且 `GET /api/daily-tasks/case-options` 列得出該案件（＝他看得到）時開自建小視窗並選好案件，列不出＝視窗照開、下拉維持空白（不替他選）。沒帶參數／旗標關 ⇒ 什麼都不做。純前端，無新端點。
- **升級後一條龍功能預設開啟（T84 使用者裁示：一條龍上線就開啟）：群組 `onepipe` 每個旗標預設 1；既有環境啟動時一次性遷移把存成 0 的改成 1（經設定中心引擎、稽核「系統升級」、只跑一次，之後使用者自己關掉的保留）；仍可在設定中心逐項關閉，關閉＝與今天逐位元相同。** 本模組：現場人員「新增我的案件事項」升級後即可用（可在設定中心關閉 `entry_unify`）。
- 新增端點 `GET /api/daily-tasks/case-options?q=`（h9 審查修正）：現場人員自建小視窗的案件清單，**只回案號／客戶／案名（沒有金額）**；範圍＝伺服器建立事項時接受的同一組（已成案、且本人看得到：`row_access` `case`／owner，與 `require_case` 同一條規則），最多 100 筆；旗標 `onepipe.entry_unify` 關或案件模組不在 ⇒ 404。前端改用這支（原本用 `/api/sales-orders`，那支只給財務／最高管理者，現場人員會是空清單）；沒有案件／無權限／載入失敗時小視窗會說出原因，不留空白下拉。最高管理者的案件選單不變。
- 修正：新增時案號先去前後空白再存（原本檢查用去空白版、存的是原值）。範圍說明（D5＝A）：伺服器接受任何「看得到的案件」（含未成案、已結案）；畫面只列已成案的——不是漏洞，是刻意讓選單保守、守門寬鬆於選單。
- 新增（使用者裁示 D5＝A）：旗標開時，有「每日工作事項」權限的非最高管理者可新增事項，限定：一定掛在自己看得到的案件（看不到＝同案件端點的 404）、只能指派給自己（伺服器強制補成本人、不接受他人或主管）、只能單次；稽核記「現場自建，案件 X」；不發站內通知給自己。修改、刪除維持最高管理者；誰看得到事項不變（被指派者本人＋主管）。
- 旗標關＝與今天逐位元相同（403「僅最高管理者可建立工作事項」）；最高管理者建立不受旗標影響。
- 前端：`daily-tasks.html` 工具列旗標開時多「新增我的案件事項」（小視窗：日期、案件、標題、說明）。
- 測試：`tests/test_onepipe_p4a_staff_create_2026_11_13.py`（旗標關 403、旗標開建立、本人以外看不到、六種越界 403、看不到的案件＝不存在的案件、無模組權限、改刪仍限最高管理者、最高管理者不受旗標影響、不通知自己）、`tests/test_e2e_onepipe_p4a_2026_11_13.py`。

## 1.0.16 — 2026-11-13（feat/ux-p15-dashboard；UX P1.5）
- 前端（文字）：頁面 `<title>` 後綴「專案管理系統」一律改為「MOTRIX PLATFORM」（系統標語改由公司設定 `brand.tagline` 決定，預設 MOTRIX PLATFORM）；不動 API／資料／權限。

## 1.0.15（next，未取號）— 2026-11-13（ui/mobile-tablet-combined 的改動；條目由 fix/mobile-cases-layout-v2 補，依各頁 git 歷史照實記錄；僅前端版面，不動 API／資料／權限判斷）
- `daily-tasks.html`：手機（≤767px）任務清單與詳情上下排（選到任務才顯示詳情，`dt-has-sel`）、詳情頂列可換行、觸控目標加大。桌機版不變。

## 1.0.14 — 2026-11-11（wip/ux-density-c456；C6 每日工作事項工具列與日曆收密）
- `pages/daily-tasks.html`（只改呈現）：日曆視圖預設只展開當月，前一個月收成一條標題列（按一下展開）；工具列只留「今日」（新增：回到當月／回報彙整時回到今日）、「日曆視圖」與已解鎖時的「新增工作事項」，「回報彙整／月曆總覽／看板／解鎖管理視角」收進「更多」選單（動作、權限不變；進入某視圖後列上會多一顆「← 返回列表」）；手機寬度工具列改為可換行。無 API、無 migration、無設定變動。
- 測試：新增 `tests/test_e2e_daily_tasks_density_2026_11_11.py`（5 題）。

## 1.0.13 — 2026-11-11（feat/ux-navigation-hierarchy；UX 提案批次 1+2「導覽與資訊架構＋視覺層級」；不動 API／資料／權限判斷；L1 介面不變）
- 前端視覺（D3）：本模組頁面內文字最小 12px（原有 9～11px 一律拉到 12px）；文字色改用語意 token（`--text-secondary` #595959／`--text-dim` #666666／深底 `--text-on-dark-dim` #A3A3A3，在頁底 #F5F4F0 上對比 ≥4.5:1）。只改 CSS 值，不改版面結構、不改 API、資料、權限。規格見 `docs/UI-HEADER-COLOR-SPEC.md`。
- 測試：`tests/test_e2e_nav_hierarchy_2026_11_11.py`（7 項真瀏覽器：每個舊入口仍可達、群組與報表中心頁籤、權限過濾、頁頭麵包屑）。

## 1.0.12 — 2026-10-14（wip/t61-bp3-templates-r1；每日任務歷程 CSV 可套用匯出範本）；t62 整合 r8
- 每日任務歷程 CSV（`GET /api/daily-tasks/{id}/history/export`）可套用匯出範本（設定中心「自訂匯出」`builder_exports.enabled`，**預設關閉**）：最高管理者可選要匯出的欄位、標題與順序，發布前先預覽；沒有權限看的欄位不會出現。關閉或沒有已發布範本時，匯出檔與今天逐位元相同。頁面多載入 `export-editor.js`（旗標關／不是最高管理者時什麼都不畫）。無 migration、無權限變更。

## 1.0.11 — 2026-10-14（wip/t61-xl-safe-r1；匯出公式注入中和；歷程 CSV）
- 匯出公式注入中和（資安小切片，無旗標）：每日任務歷程 CSV（工作事項標題、指派人員、回報內容）開頭是 `=` `+` `-` `@` Tab CR 的 CSV 儲存格前面補一個單引號（`helpers.xlsx_out.csv_safe`），Excel 開啟 CSV 時當文字、不再當公式（CWE-1236）；真正的數字（含負數）不受影響，其餘儲存格逐格相同。無 migration、無新路由、無權限變更。

## 1.0.10 — 2026-10-13（wip/t57-download-name-p2-r1；A7 下載檔名第二期）
- 每日任務歷程 csv 下載的 `Content-Disposition` 改用 `content_disposition()`（檔名不變）。

## 1.0.9 — 2026-10-06（wip/t43-phase2-events）：區間工作事項結束日的行事曆事件（預設關；對帳失敗會重試）
- `api.py` 新增 `_sync_range_task_calendar`，每次 `run_daily_checks` 先跑；尚有負責人未完成的區間工作事項才有事件，全員完成、刪除、改結束日由對帳處理。事件不含負責人姓名與金額。事件種類開關關閉（預設）⇒ 不讀資料庫、不打 Google。
- 上線注意：第一次打開時，所有尚有人未完成的區間工作事項會補建事件；每次每日檢查最多處理 100 個項目（每個約 2 次 Google 請求），所以第一次打開會分散在數天內建完。

## 1.0.8 — 2026-10-01（暫用號，列車取號；wip/t31-builder-b-c7：掛載點）
- `module.json` 新增 `mount_points`：`daily-tasks`（頁面 daily-tasks.html、kind=tab、perm any）——自訂模組（建構器方案 B）可掛成「工作事項詳情頁籤列」的頁籤；頁面加掛載元件容器（`data-mount-point="daily_tasks.daily-tasks"`）與 `static/mount-tabs.js`。沒有自訂模組掛上去時頁面行為不變。

## 1.0.7 — 2026-10-01（暫用號，列車取號；wip/w3-local-date）
- 本地日期（使用者 2026-10-01：凌晨建的單日期變前一天）：每日任務頁：日報日期、週／日切換、歷史週別改用本地日期（原本用 UTC 日期，且本地午夜轉 UTC 會差一天）。

## 1.0.6 — 2026-09-30（暫用號，列車取號；wip/w3-export-pdf）
- 匯出規則（使用者 2026-09-30）：工作事項歷史匯出（CSV）每次寫稽核（`export.csv`）。

## 1.0.5 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`daily-tasks.html`

## 1.0.4 — 2026-09-26（C，M01-PLAN §5 ④ SO；列車取號）
- 頁面：案件模組（M01）不在 ⇒ `/api/sales-orders` 404 ⇒「關聯案件」選單停用並顯示「案件模組未安裝：無法關聯案件（其他欄位照常可填）」，不再是看起來沒有已成案案件的空清單；e2e `modules/daily_tasks/tests/test_e2e_daily_tasks_without_case_module.py`（攔截 404＋正對照）

## 1.0.3 — 2026-09-26
- 選單宣告搬進本模組：`daily-tasks.html` 的 `pages[].menu`（原寫在 L1 的 `core/menu_l1.json`；group／order／perm／badge 原值照搬）。階段 C／C4（主持裁示 A）：本模組不在時它的入口隨宣告一起消失，不再靠前端寫死的頁面⇒模組對照表；〔rebase 到 origin：h-probes 已取 1.0.2 ⇒ 本段 1.0.3〕

## 1.0.2 — 2026-09-26
- 宣告 `provides.probes`（D7 演練與產品演練打這幾支確認模組在；純讀、無副作用，D7-CHECKLIST §4）

## 1.0.1 — 2026-09-26
- 第四班列車：IP 定號（`daily.check` IP-10→IP-11、`case.access` IP-11→IP-12，cb4667b1）
- `module.json` 補 `customization`（本模組目前沒有可自訂點：寫出空類別＝有人決定過）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/daily_tasks.py` 搬入 `modules/daily_tasks/api.py`（PLAYBOOK §B；搬自基底 84c53670，原檔拆成本檔與 L1 三檔，`git log --follow` 追不到，請以此查舊歷史）
- 每日 08:00 排程拆出：系統健康檢查下沉 L1（`helpers/system_checks.py`）、案件類檢查歸 M01（`helpers/case_deadlines.py`）、執行器在 L1（`helpers/daily_checks.py`）；本模組只留逾期與區間到期，以 IP-11 `daily.check` 登記
- 簽核催辦失敗的端點 `/api/settings/reminder-send-failures` 移到 L1 `routers/system.py`
- 提供者（IP-5、IP-11）改由 `ModuleSpec.providers` 宣告：模組未載入即不登記
