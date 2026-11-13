# SETTINGS-MATRIX-ROLLOUT：系統設定全面改版（設計階段，使用者看過才實作）

負責：hichan-4（總負責：盤點總表、共用元件規格、UX-PRINCIPLES 設定頁章節）；mockup：hichan-3、hichan-12、hichan-4；審查：hichan-11。
base：T82 凍結頭 `435e761de`。**只做文件與 mockup，不跑重型測試。**
版本：r2（已納入 PM 2026-11-13 裁示 M1～M3、N1～N6 與 hichan-11 對 81be1f49d 的審查）。

## 一、分工（數字來自 `helpers/settings_registry` 實際登錄；T83 凍結後重產，預期 51 群組／186 欄）

設定中心＝**50 群組、183 欄**（型別：int 125／str 34／bool 13／float 11；欄位 risk：ops 70／none 63／security 22／money 19／legal 9）。
信件類型 **67**（不是舊文件的 42）。

| 份 | 負責 | 設定中心（群組／欄） | 設定中心以外（第四段） | 獨立頁 |
|---|---|---|---|---|
| **甲 業務與財務規則** | hichan-3 | 20／76：quote_alt、quote_approval、quote_output、quote_privacy、quote_defaults、quote_backfill、profit_warning、profit_rules、overhead、project_margin、material_order、material_recognition、finance_reports、finance_cashier、case_close_gates、completion_note、payslip_dispatch_picker、alerts、legal_params_reminder、change_control | bonus 預設、憑證帳戶、扣款設定、overhead 模式與公益模式（settlement.html）、營運目標（reports.js）、T100 匯出（cashier.js）、報價條款與付款條件（quotation-form.html） | approval-settings、approval-delegates、expense-types、remit-kinds-settings、ledger-settings、legal-params、account-items |
| **乙 系統、安全、畫面與自訂** | hichan-12 | 30／107：builder_* 13 群組、download_name、external_login、account_security、uploads、retention、recycle_bin、system_hub、ui_format、list_prefs、list_view、各 *_labels、brand、login_greeting、tender_closing、lodging_freshness；**T83 新增的 monitoring 群組歸乙** | 回收桶隔離目錄、標案雷達排程、backup-monitor 頁（T83 加入）、custom-module 審核設定（先確認 builder_governance 有沒有涵蓋） | module-builder、report-templates、company-profile-settings、storage-settings、module-settings |
| **丙 通知／權限／我的帳號＋總成** | hichan-4 | — | my-account 全頁 | notification-settings（寄信、LINE、月報）、mail-settings（67 種信＋9 列僅行事曆）、LINE 70 事件（沿用 hichan-6 稿）、google-calendar-settings、個人 Email 通知偏好（78 事件）、permission-matrix、users（30 個權限鍵）、duty-roles、org-structure |
| 不在範圍 | — | — | 只有 API、沒有畫面：ledger `fiscal_year_start_month`、`remit_require_payslip`（不替它們發明畫面） | — |

`system-hub` 是導覽入口，不算任何一份的設定項目（PM N6）。`contractor-voucher-approval-settings` 已是跳轉頁，不做。

## 二、共用規則（PM 裁示；所有人遵守）

1. **目錄**：mockup 放 `docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/<h3|h12|h4>/`，每人一個子資料夾；格式照 LINE 稿：`index.html`＋`design-notes.html`＋`shots/`。假資料用 `settings_registry` 的真實欄位與選項（取自 `data/settings_groups.json`）。
2. **批次（M1，取代「只開放 none」）**：欄位 `risk` 為 `none` 或 `ops` 才可批次（`ops` 要確認視窗）；`security`／`money`／`legal` 與一切受 change_control 管的欄位（待生效／放寬／雙人核准）**永不進批次**。批次只做三種事：**套用建議值／套用預設組合／重設為預設值**；寫入一律走既有 `apply_profile`／`publish()`，不另開寫入點。文字類欄位（download_name、各種 labels）不畫勾選格，做成「逐列直接編輯＋預覽」。
3. **復原（N2）**：不做欄位層級的 6 秒復原。套用後可「**復原這一批**」，前提是涉及的群組在這段時間沒被別人改過（版本檢查）；有衝突就拒絕並顯示誰、何時改的。需在 `publish()` 加 expected-version 檢查（規格見 SPEC §5）；mockup 只能照這個行為畫。
4. **「?」說明（N4，取代 settings_help.json）**：不另建說明檔。四段（這是什麼／什麼時候要改／改了會影響什麼／建議值）由登錄表既有的 `help`、`question`、`impact`、`riskText`、`recommended` 產生，「什麼時候要改」新增為 `SettingDef.when`；只維護一個來源（SPEC §6）。
5. **每一列都要有**：中文名稱、小字代碼、標籤（需外部設定、影響大…）、篩選條件「與預設不同」。
6. **生效值來源（N3）**：只有「公司」「預設」「等待生效」「舊位置」；「個人」只在真有個人設定層的欄位（login_greeting、列表偏好、個人通知偏好）才顯示。
7. **群組風險（N5）**：群組標題不標高低風險，只標「內含高風險項目」；風險依欄位層級顯示，不得與欄位矛盾。
8. **白話化**：每個項目都要有白話名稱＋一句說明（影響什麼、預設值是什麼）；選項用白話描述後果、不用代碼或工程用語；相關項目分組；影響別人或危險的標示出來。
9. **用語表**：標籤、來源、篩選、按鈕、確認句型、套用樣式詞彙，統一見 `SPEC.md` §11。

## 三、資料與重現

| 檔 | 內容 |
|---|---|
| `data/gen_seed.py` | **產生器**（唯讀：只 import 程式，不連 DB）。在 `backend/` 下執行：`MOTRIX_DISABLE_SCHEDULERS=1 PYTHONUTF8=1 python -I ../docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/data/gen_seed.py`。T83 凍結後重產一次。**重跑會覆蓋「【填】」欄**，所以重產後請用 diff 合併，或先備份手填版 |
| `data/settings_groups.json` | 設定中心全部群組／欄位的完整 meta（`SettingDef.meta()`） |
| `data/settings-center-items.csv` | 一～三段：183 欄逐欄一列（分工甲／乙、可批次？、現名稱／問句／說明／影響／選項後果／風險已預填）；第四段「設定中心以外」14 列（含僅 API 兩項） |
| `data/bing-items.csv` | 丙份 254 列：信件類型 67、LINE 事件 70、個人 Email 通知事件 78、個人權限鍵 30、簽核單據類型 9 |
| `data/survey-A-…md`、`data/survey-B-…md` | 盤點代理人原始報告（含 file:line 證據；數字是 python 實跑，點擊數是推算） |
| `SPEC.md` | 共用元件規格 r2（元件、列契約、批次規則、復原、說明來源、API、用語表） |
| `INVENTORY.md` | 頁面總表、優先順序、API 彙總、要使用者決定的事 |
| `h3/`、`h12/`、`h4/` | 各人 mockup 與設計說明 |

填寫欄位（CSV 的「【填】」欄）：建議白話名稱、一句說明、選項白話後果、目前生效值與來源、影響別人／危險標示、套用樣式（只能用 SPEC §11 的詞）、備註。

## 四、已知限制

- `settings_groups.json` 反映的是 T82 凍結頭；T83 加入 `monitoring` 群組後會是 51／186。
- 「模組自行登記」的設定群組：grep 只在 `settings_groups.py` 見 `register_group`，未啟動伺服器載入模組驗證。
- 點擊數與痛度／頻率是依介面結構推算的判斷，不是實測。
