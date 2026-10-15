# T67 切片設計：設定中心補群組（管銷％、資源回收筒、總帳設定、提醒寄送失敗）（design only，無程式）

基底：origin/train/t65-int @4de2ac1f8。原則：框架先行、一個設定面、不新增獨立頁面（PM 2026-10-16）。
引擎能力（已讀碼）：`register_group(group, label, fields, sensitive, risk, legacy_key, cross_check, help, owner)`（`helpers/settings_registry.py:186`）；欄位型別只有 `int｜float｜bool｜str`＋`choices`（`:32`）；`requires_pending`／`loosen` ⇒ 待生效＋第二位超管核准（`:650`、`:818-840`）；`legacy_key` 雙寫舊鍵（`_write_legacy`）；`cross_check(values)` 只拿到本群組的值（純函式，無 I/O 約定）。**沒有**發布前／後副作用鉤子，也沒有唯讀「狀態欄位」。

> 修正：我在 `reports/ui-coverage-20261016.md` 第 3 項把資源回收筒設定寫成「保留天數／啟用」，實際 `PUT /api/recycle-bin/settings` 只設**隔離目錄路徑**（`modules/recyclebin/api.py:172`）；保留天數是程式常數 `RB.RETENTION_DAYS=30`（`service.py:33`）。另外 `PUT /api/ledger/settings` 只有 `fiscal_year_start_month`（建年度後鎖死，`ledger_periods.py:87`），`PUT /api/ledger/roles` 才是角色→科目對應（`ledger_reports.py:179`）。以下以此為準。

## 逐項適配判斷
| 項目 | 資料形狀 | 適合設定中心？ | 建議落點 |
|---|---|---|---|
| A 管銷％預設值 `overhead_default_pct` | 純量 float（0–100、1 位小數） | **是** | 新群組 `overhead`（SO-S1） |
| A' 管銷口徑 `overhead_rule_mode` legacy/v2、公益基數 `charity_basis_mode` | 切換有前置條件與副作用（遷移完成標記必須存在；退回 legacy 要刪標記並強制公益基數回 direct，`case/api/overhead.py:55-95`） | **否（現況）**：引擎無副作用鉤子 | 保留 `PUT /api/overhead/settings` 作切換入口；設定中心只放**唯讀狀態列**或連結（見 SO-S1 決議 1） |
| B 回收筒隔離目錄 `recycle_bin_dir` | 字串路徑；寫入要查檔案系統（樹外、非 uploads 底下、上層存在、會 mkdir）＋「暫存區還有項目就拒絕」（`api.py:172-205`） | **部分**：驗證需 I/O＋DB 狀態，`cross_check` 純函式辦不到 | 建議：在既有 `recycle-bin.html` 加一個設定面板（不是新頁），或引擎先加 `precondition` 鉤子（SO-S3） |
| B' 回收筒保留天數 | 目前是程式常數 30 | **是**（新欄位；框架化債） | 群組 `recycle_bin`，欄位 `retention_days`（SO-S2） |
| C 總帳 `fiscal_year_start_month` | 一次性、建年度後鎖死；現權限是 `_require_write` 不是超管 | **否**：不是可調政策 | 併入「建立會計年度」流程（ledger-hub／ledger-settings），並改為超管 |
| C' 總帳角色→科目 `gl_account_roles` | 表格資料（role×scope×生效日→科目） | **否**：設定中心是純量欄位 | `ledger-settings.html` 加「角色對應」分頁（該頁已有科目／報表列／類別對應，同一介面家族）；設定中心留一個連結 |
| D 提醒寄送失敗清單 | 唯讀事件清單（`system_checks.reminder_send_failures()`；`routers/system.py:3210`） | **否**：不是設定 | 系統中心「稽核」區加一張唯讀卡片，或 `notification-settings.html` 頁尾面板（那裡才能補 email 修復）；建議後者＋hub 卡片連結 |

PM 的原假設「四項都進設定中心群組」只有 A、B' 成立。其餘要嘛需引擎擴充（B），要嘛形狀不對（C、C'、D）。這是本稿最需要 PM 裁示的點。

## SO-S1 管銷％（群組 `overhead`）
- 欄位：`default_pct` float 0–100（`legacy_key` 雙寫 `overhead_default_pct`，`profit_guard.DEFAULT_KEY`；解析沿用 `PG.parse_pct`，1 位小數）；`risk="money"`。
- 寬嚴方向（**待裁示**）：調低管銷％ ⇒ 營業利益與獎金基數變大（金額外流風險）。建議 `loosen="down"`（放寬＝需第二位超管核准＋確認期間），調高即時生效。只影響之後新建報價單，不回改既有單（現況註解 `overhead.py:55`）。
- 唯讀狀態：口徑（legacy/v2）與遷移完成旗標以說明文字呈現（`GET /api/overhead/settings` 已提供 `ruleMode/migrationDone/charity*`）；切換按鈕連到既有端點（SO-S1 決議 1：不重做切換流程）。
- 讀取端：`PG.default_pct()` 改為嚴格讀取（讀不到取今日預設 25，沿用 `quote_terms._strict_number` 模式）；`PUT /api/overhead/settings` 的 `defaultPct` 分支改呼叫 `settings_registry.publish`，避免兩條寫入路徑（否則繞過第二人核准——見 D-K1 稽核表 W10）。
- 入口：hub 卡片 `overhead-settings`（`case/module.json:383`，`planned`）改指向 `settings-center.html#overhead` 並移除 `planned`；不新增 `overhead-settings.html`。
- 其他使用端：精算頁 `ohEdit`（`settlement.html:1166`）改的是**單張報價單**比率（`PUT /api/quotations/{no}/overhead-pct`，`profit_guard.change_pct`），屬於個案調整，保留；頁面加一句連到全域預設。

## SO-S2 回收筒保留天數（群組 `recycle_bin`）
- 欄位 `retention_days` int，下限 7（≥ 清理工作間隔；避免誤設 0 立即清空）、上限 365、預設 30（今日行為）；`risk="legal"`（資料保存）；縮短 ⇒ 更快永久刪除 ⇒ `loosen="down"`。
- 接線：`RB.RETENTION_DAYS` → 讀取函式（嚴格讀取；讀不到＝30）；`purge_after_for`（`service.py:32`）與 `jobs.py:63` 改用它。**既有列的 `purge_after` 不回改**（寫入時已定），只影響之後刪除的項目；頁面文案要說清楚。
- 與使用者 10-10 裁示「僅超管復原、30 天、第一期 10 類單據」相容：預設仍 30。

## SO-S3 回收筒隔離目錄
兩案（PM 擇一）：
1. **面板放 `recycle-bin.html`**：頁面已是超管限定、已有 `status` 回傳 `dir/defaultDir`；新增表單呼叫既有 `PUT /api/recycle-bin/settings`。成本 S，零引擎改動。缺點：設定面分散。
2. **引擎加 `precondition(values, conn)->[問題]` 鉤子**＋群組 `recycle_bin.dir`：成本 M（引擎改動屬 L1 契約，需升版、全部群組的守門重驗）。優點：一個設定面、版本帳本與還原。風險：還原到舊路徑可能指向已不存在的資料夾。
建議案 1（路徑屬部署環境事實、不是政策；與 `storage-settings.html` 同類，後者也是專頁）。

## SO-S4 總帳（不進設定中心）
- C'：`ledger-settings.html` 新增「角色對應」分頁，呼叫既有 `PUT /api/ledger/roles`；**目前沒有對應的 GET 端點**（`modules/accounting/api` 只有 `ledger_reports.py:179` 的 PUT），需新增唯讀 GET（列出 role／scope／生效日／科目）。目前權限＝超管、**無第二人核准**、無生效日以外的待生效；角色對應決定分錄過帳科目（金額流向），建議納入 D-K1 同一規則或至少加原因欄與稽核前後值。
- C：`PUT /api/ledger/settings` 權限由 `_require_write` 升為超管；UI 併入建立第一個會計年度的精靈。
- 以上為 UI 整併案（B 系列）而非設定中心群組；列入 T67 第 2 優先的子項但落點不同，需 PM 同意改寫範圍。

## SO-S5 提醒寄送失敗檢視
- 面板放 `notification-settings.html`（簽核提醒設定同頁），資料來自既有 `GET /api/settings/reminder-send-failures`（超管、最新在前）；每列顯示單據別、單號、階段、原因、嘗試次數，並連到使用者管理（補 email）。
- hub 卡片（`audit` 區，唯讀）：數量徽章＞0 時顯示；沿用 `system_hub` 既有 badge 機制。
- 不新增端點、不新增頁面。

## 測試與守門（實作時；本稿不跑）
- 新群組：`test_settings_registry_t54.py` 系列（欄位必填 question/label/help/impact/risk_text、白話守門 `test_settings_ui_plain_language.py`）、`settings_deploy_baseline.json`（零行為變更：無列＝程式預設）。
- 嚴格讀取：讀不到／壞值取最嚴格（沿用 D-K1 模式）；**legacy 雙寫與舊端點同一交易**，並加測：舊端點與設定中心不得產生兩個不同的值。
- route golden／`response_keys_baseline`（設定中心 settings keys 已在基準，t65-int `3101cb0f9`）／L1 快照／`test_map` 重產。
- hub 卡片 `planned` 旗標移除要同步 `test_system_hub*`；`pages` 不新增檔案，所以 `test_module_pages_match_units` 不受影響。

## 相依
- T66 列表偏好（`list_view` 群組已註冊，`settings_groups_list_view.py`）：同一設定面、不同群組，無資料相依；只共用 `response_keys_baseline` 與 `settings_deploy_baseline.json`，兩片的基準重錄要排序避免衝突（先合先錄）。
- F7 欄位政策：無直接相依；若 F7 加「受保護欄位確認期」群組，沿用同一 `confirm_period_days`。
- T65 閘門：本片全部在 T65 之後。

## 待 PM 裁示
1. 範圍是否改寫為「A、B' 進設定中心；B 走面板；C/C'/D 走既有頁面」？
2. 管銷％調低是否算放寬（需第二位超管）？
3. 回收筒保留天數下限（建議 7）。
