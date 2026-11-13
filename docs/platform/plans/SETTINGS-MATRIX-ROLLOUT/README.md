# SETTINGS-MATRIX-ROLLOUT：系統設定全面改版（設計階段，使用者看過才實作）

負責：hichan-4（總負責：盤點表合併、共用元件規格、UX-PRINCIPLES 設定頁章節）；mockup：hichan-3、hichan-12、hichan-4；審查：hichan-11。
base：T82 凍結頭 `435e761de`。只做文件與 mockup，不跑重型測試。

## 一、分工（依實際欄位數切；數字來自 `helpers/settings_registry` 實際登錄，見 `data/settings_groups.json`）

設定中心＝50 個群組、183 個欄位（型別：int 125／str 34／bool 13／float 11；risk：ops 70／none 63／security 22／money 19／legal 9）。
各模組的獨立設定頁（`frontend/pages/*.html`）另列。

| 份 | 負責 | 內容 | 規模 |
|---|---|---|---|
| **甲 業務與財務規則** | hichan-3 | 設定中心 20 群組 76 欄：quote_alt、quote_approval、quote_output、quote_privacy、quote_defaults、quote_backfill、profit_warning、profit_rules、overhead、project_margin、material_order、material_recognition、finance_reports、finance_cashier、case_close_gates、completion_note、payslip_dispatch_picker、alerts、legal_params_reminder、change_control。獨立頁：approval-settings、approval-delegates、contractor-voucher-approval-settings、expense-types、remit-kinds-settings、ledger-settings、legal-params、account-items | 76 欄＋8 頁 |
| **乙 系統、安全、畫面與自訂** | hichan-12 | 設定中心 30 群組 107 欄：builder_* 13 群組（layout、governance、rules、menu、custom_fields、actions、slots、exports、option_lists、notify、stage_templates、custom_modules、status_display）、download_name、external_login、account_security、uploads、retention、recycle_bin、system_hub、ui_format、list_prefs、list_view、netplan_labels、procurement_labels、lodging_labels、brand、login_greeting、tender_closing、lodging_freshness。獨立頁：module-builder、report-templates、company-profile-settings、storage-settings、module-settings、system-hub | 107 欄＋6 頁 |
| **丙 通知／權限（矩陣型）＋總成** | hichan-4 | notification-settings（寄信、LINE、月報）、mail-settings（42 種信）、LINE 70 事件（沿用 hichan-6 稿）、google-calendar-settings、使用者個人通知偏好、permission-matrix、users（30 個權限鍵）、duty-roles、org-structure。另：共用元件規格、UX-PRINCIPLES 設定頁章節、盤點總表合併 | 矩陣型 9 頁 |

分群組的完整對照見 `data/settings-center-items.csv`（183 列，已預填現名稱／問句／說明／影響／型別／預設／選項後果／風險；「【填】」欄由各人填）。

## 二、共用規則（PM 裁示，所有人遵守）

1. mockup 放 `docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/<h3|h12|h4>/`，每人一個子資料夾；格式照 LINE 稿：`index.html`＋`design-notes.html`＋`shots/`。假資料用 `settings_registry` 的真實欄位與選項（取自 `data/settings_groups.json`）。
2. **批次只開放 `risk=none` 的欄位**（目前 63 欄）；高風險（money／legal／security／ops）不進批次。
3. **批次絕不繞過 change_control**：受「確認期間」（`requires_pending`）或「雙人核准」（`loosen`）管的欄位，在批次裡要嘛排除、要嘛逐項進各自的流程。
4. 「?」說明走 `settings_help.json`（尚不存在，由實作階段新增；schema 見共用元件規格），每項四段：這是什麼／什麼時候要改／改了會影響什麼／建議值；不寫死在 HTML。
5. 每一列都要有：**中文名稱、小字代碼、標籤（需外部設定／影響大）**，以及篩選條件「**與預設不同**」。
6. 每個項目：白話名稱＋一句說明（影響什麼、預設值是什麼）；選項用白話後果、不用代碼；相關項目分組；影響別人或危險的標示；盡量顯示「目前生效的值與來源（公司／個人／預設）」。
7. 套用樣式的詞彙（盤點表「套用樣式」欄只能填這幾個）：`矩陣`、`勾選批次`、`群組全開全關`、`搜尋篩選`、`預設組合`、`套用前確認＋6秒復原`、`手機卡片`、`單項表單`（不需批次的單一選項）、`精靈`。

## 三、資料夾

- `data/settings_groups.json`：設定中心所有群組／欄位的完整 meta（機器產生，唯讀參考）。
- `data/settings-center-items.csv`：逐欄盤點表骨架（183 列）。
- `h3/`、`h12/`、`h4/`：各人 mockup 與設計說明。
- `SPEC.md`、`INVENTORY.md`（hichan-4 彙整，盤點表總表＋共用元件規格＋優先順序＋要使用者決定的事）。
