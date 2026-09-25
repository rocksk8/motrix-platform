# 稽核：A 的串接點 IP-1～IP-4 與 row_access（X 稽核，2026-09-25）

> 依 CORE-SPEC §9d／PLAYBOOK §E。原本分給 B，B 忙打包線，改由獨立稽核者 X 執行（X 沒有寫過受稽核的程式碼）。
> 對象：`eeaf95b0`（IP-1）、`ba370f96`（IP-2／IP-3）、`5e0a591e`（IP-4）、`ee5dab65`／`50e8c2cc`／`0411f818`（row_access）。
> 基準：`origin/platform` @ `23cd8d56`，detached worktree。
> 分級：**必修**（不修不能關）／**建議**／**觀察**。關閉規則：被稽核者回覆，由 X 確認才關。
> 路徑前綴 `backend/`。`RQ`＝`routers/quotations.py`、`HQ`＝`helpers/quotations.py`、`RA`＝`helpers/row_access.py`、`BV`＝`helpers/bonus_vouchers.py`。

## 0. 結論

- 四個串接點的**註冊與取用方式**都符合規格：提供方一律 `core.registry.provide`，使用方一律 `single_provider`／`providers`；文件記錄的 6 項與程式碼一致（§1）。
- row_access 的**行為面**是真的：15 條單筆讀取路徑對無權限使用者全部回 403；列表、搜尋、動態牆、匯出都查不到那一筆（§3.2，X 實測）。9 個套用點的突變，8 個有題目轉紅；業務開發案列表那一個存活（§3.3、X-3）。
- **必修 3 項**：
  - X-1：IP-1 在提供者缺席時是**靜默的**。營運報表、傳票來源、待補登清單都只少了一類，使用者看不到任何提示，只有伺服器端 log。
  - X-2：CORE-SPEC §5 寫「登記表由守門測試驗證與程式碼一致」，但這個守門不存在。
  - X-3：突變 `dev_crm` 列表的 row_access 套用點後，沒有任何題目轉紅。
- 建議 5 項、觀察 6 項。
- 驗證：
  - 相關題 `tests/platform/test_{dispatch,voucher,voucher_status}_connectors.py`、`tests/test_row_access_{2026_09_25,callers_2026_09_25}.py`：**70 passed**。
  - 突變用題組（85 檔、892 題，不含 e2e）基準：**892 passed**。

## 1. 逐項驗收：IP-1～IP-4

| 串接點 | 提供（`provide`） | 取用（`single_provider`） | 缺席時照常＋明說 | 6 項與程式碼一致 | 證據 |
|---|---|---|---|---|---|
| IP-1 `dispatch.row` | ✅ `routers/vendor_contractors.py:173` | ✅ `helpers/recognition.py:242`、`routers/vouchers.py:582` | ⚠ 照常 ✅；**明說 ✗**（X-1） | ✅（缺席行為照實寫了「皆不丟例外」，但沒有使用者提示） | `test_consumers_degrade_when_provider_is_absent` 綠 |
| IP-2 `voucher.draft`＋`voucher.account_check` | ✅ `routers/vouchers.py:1790`、`routers/accounting_export.py:607` | ✅ `BV:51-52,59,83`；`routers/bonus.py:2381` | ✅ `notice`＝`ACCOUNTING_MISSING…`（`BV:77-78`）；科目 GET 列 problems、PUT 400 | ✅ 簽名 `(conn, *, voucher_date, summary, lines, created_by, now)`、回 `{id, voucher_no}`、不 commit | `test_voucher_connectors.py` 綠 |
| IP-3 `accounting.settings` | ✅ `routers/accounting_export.py:618` | ✅ `routers/bonus.py:1888` | ✅ `bankAccounts: []`＋`voucherNotice`（`routers/bonus.py:1889-1891`），頁面有綁定 | ✅ 恰好兩個鍵 | 同上 |
| IP-4 `voucher.void_draft`＋`voucher.status` | ✅ `routers/vouchers.py:1818-1819` | ✅ `BV:93,134,150` | ✅ 退回照常、保留連結、notice；明細標 `unavailable` | ✅ `result ∈ voided/not_draft/gone`、status 形狀、不 commit | `test_voucher_status_connectors.py` 綠 |

其他檢查：

- 全 backend 已經沒有 `_dispatch_row`、`_check_quotation_owner`、`_visible_case_filter_sql`、`_can_access_case` 的呼叫端（`git grep`，排除 tests）。
- 未搬遷模組的登記存放在 `registry._LEGACY_PROVIDERS`，**不受** 9c②③ 啟停與授權影響。M04／M06 仍在 `routers/`，目前無法停用，所以「模組停用 ⇒ 提供者消失」這條路今天只能用 monkeypatch 模擬。三份測試都是這樣做，所以綠燈證明的是**連接器層**的退化，不是實體缺席（見 Y-2）。

## 2. 逐項驗收：row_access

| 項目 | 驗收 | 證據 |
|---|---|---|
| 一份宣告產生單筆與 SQL | ✅ | `RA:104-157`；等價測試用自己的 kind（`_t_case`／`_t_dev`），**不綁 M01／M02**；有「不是全空也不是全部」的正對照（`test_positive_control_sets_are_not_trivial`） |
| 未登錄 ⇒ fail closed | ✅（兩處例外見 Z-2） | `RA:64-70`、`RA:131-133` |
| 單筆讀取 | ✅ | §3.2 表，15 條路徑，無權限者全部 403，擁有者不是 403 |
| 列表／搜尋／動態牆 | ✅ | `/api/quotations`、`/api/search`、`/api/dashboard/activity-feed`、`gate-matrix`、`case-activity`：擁有者看得到、外人看不到 |
| 匯出 | ✅ | `/api/case-batch/export`：擁有者 `[MQ-AUD3-0925]`，外人 `[]` |
| 舊實作全部改走 row_access | ✅ | `ee5dab65` 當時 11 個檔的呼叫端，現在全數改掉 |
| 模組搬遷後，守門的掃描範圍 | ⚠ | row_access **沒有靜態守門**，保護全部靠 HTTP 行為題；行為題跟著端點走，搬遷不會失效。`core.source_tree` 本身有缺口，見 Y-3 |

## 3. 反向控制（X 實跑）

### 3.1 提供者缺席

| 做法 | 結果 |
|---|---|
| 既有三份測試：從 `_LEGACY_PROVIDERS` 拿掉 `dispatch.row`／accounting 系列 | 70 passed：照常、不丟例外；IP-2～4 有 notice |
| X 補做：拿掉 `dispatch.row` 後直接呼叫 `reports._collect_expenses(2026, basis="accrual")` | 回傳鍵只有 `details`、`monthly`、`totals`，**整份回應沒有任何「未安裝」「notice」「M04」字樣** ⇒ X-1 |
| X 補做：讓 `helpers.voucher`、`helpers.voucher_pdf` 無法匯入（模擬 M06 檔案不在包裡） | `helpers.bonus_vouchers` 可以匯入 ✅；`helpers.bonus_pdf` 匯入失敗（`ModuleNotFoundError`）⇒ `routers/bonus.py:44` 一起失敗 ⇒ Y-2 |

### 3.2 無權限使用者（X 暫存題，不 commit）

設定：`aud3_owner` 是業務，`aud3_out` 也是業務，兩人模組相同（`dashboard`、`quotation`）；案件 `MQ-AUD3-0925` 屬於 owner。

| 路徑 | owner | 外人 | 外人回應含單號／客戶 |
|---|---|---|---|
| `GET /api/quotations/{no}` | 200 | **403** | 否 |
| `…/case-bundle` | 200 | **403** | 否 |
| `…/pdf-download` | 200 | **403** | 否 |
| `…/versions`、`…/versions/1/download` | 200／404 | **403**／**403** | 否 |
| `…/closing-report-pdf`、`…/project-report-pdf` | 400／200 | **403**／**403** | 否 |
| `…/settlement`、`…/finance-summary`、`…/close-gates` | 200 | **403** | 否 |
| `…/updates`、`…/stages`、`…/extra-expenses` | 200 | **403** | 否 |
| `/api/shipping-notes?quote_no=`、`/api/completion-notes?quote_no=` | 200 | **403** | 否 |
| 列表 `/api/quotations`、`gate-matrix`、`/api/search`、`activity-feed`、`case-activity` | 看得到 | 看不到 | — |
| 匯出 `POST /api/case-batch/export` | `[MQ-AUD3-0925]` | `[]` | — |
| `GET /api/dev-cases`（列表）／`/api/dev-cases/{id}`（單筆） | 看得到／200 | 看不到／**403** | — |
| `GET /api/quotations/last-received-bank-account?customerName=` | — | **200，回 `{name:"稽核銀行", acctCode:"1113-AUD3"}`** | ⇒ Y-1 |

- `stage-board` 對 owner 也看不到（這筆不在看板範圍），所以那一列的「外人看不到」**不構成證據**。
- `/api/map/points` 會觸發地圖圖磚的外連，被 NETGUARD 擋下，所以沒有放進這張表；地圖由 M6 突變另外驗證。

### 3.3 突變 row_access 的套用點

做法：每次只改一處，assert 剛好命中一處；跑完用 `git checkout` 還原並比對內容。題組是含 row_access 相關字樣的 85 個檔（不含 e2e）；M6、M8、M9 改跑目標題（不平行、低優先權）。

| # | 突變 | 位置 | 結果 | 抓到的題 |
|---|---|---|---|---|
| M1 | GET 單筆拿掉 `require` | `RQ:1289` | 🔴 | `test_case_bundle…::test_no_access_to_the_case_means_no_bundle`、`test_case_project_merge::test_assigned_user_can_see_case_visibility` |
| M2 | 批次匯出拿掉 `filter_sql` | `RQ:6816-6818` | 🔴 | `test_case_batch_ops…::test_batch_export_is_xlsx_with_visible_cases_and_masked_amounts` |
| M3 | 全域搜尋拿掉 `filter_sql` | `routers/search.py:53-54` | 🔴 | `test_row_access_callers…::test_global_search_matches_case_list_rule` |
| M4 | L1 `guard_case_access` 恆放行 | `HQ:95` | 🔴 | `test_module_permission_fixes…`（2 題）、`test_case_project_merge::test_action_item_two_stage_approval` |
| M5 | router `_guard_case` 拿掉 `require` | `RQ:439` | 🔴 | `test_module_permission_fixes…`（2 題） |
| M6 | 地圖逐筆過濾拿掉 | `routers/map_points.py:360` | 🔴（只在 mp6 檔） | `test_mp6_map_case_locations…::test_mp6_each_salesperson_sees_only_their_own_and_assigned_cases`。85 檔題組**抓不到**：這個檔含 playwright，被 X 的「不含 e2e」篩選排除，見 Y-4 |
| M7 | 未讀標記拿掉 `filter_sql` | `routers/item_reads.py:184` | 🔴 | `test_item_reads_server_side…::test_unread_only_answers_for_cases_the_caller_can_see` |
| M8 | 動態牆案件恆可見 | `routers/dashboard.py:1000` | 🔴 | `test_row_access_callers…::test_activity_feed_matches_case_list_rule` |
| M9 | 業務開發案列表拿掉 `visible` | `routers/dev_crm.py:290` | 🟢 **存活** | 含 dev_case／dev-crm 字樣的 19 檔、259 題全綠 ⇒ X-3。X 的暫存題 `test_aud3_dev_case_outsider` 在未突變時綠、突變後紅，證明這題寫得出來 |

## 4. 發現

### 必修

**X-1　IP-1 缺席時是靜默的：報表少一類，使用者看不到原因**
- 位置：
  - `helpers/recognition.py:242-245`：只記 WARNING，回傳 `[]`。
  - 消費端 `routers/reports.py:3593`（營運報表／月支出）、`helpers/recognition.py:354`（待補登清單 `dispatch_no_invoice`）、`routers/vouchers.py:581-588`（傳票摘要來源）。三處的回應都沒有任何欄位說明「承攬商派工沒有算」。
- 為什麼是必修：
  - 交辦要求寫明「明說缺了什麼，不可以靜默送出空值」。IP-2～IP-5 都有 `notice`，只有 IP-1 沒有。
  - 營運報表顯示「承攬商支出 0」，看起來和「這期沒有派工」一模一樣；待補登清單顯示「0 筆派工未補發票」，看起來像「都補齊了」。這正是〈降級之後它還是會動〉那一類：壞掉會有人報修，少算不會。
- 重現：見 §3.1 第 2 列。拿掉提供者後 `_collect_expenses` 的回應鍵只有 `details`、`monthly`、`totals`，沒有任何提示。
- 建議修法：
  - `dispatch_entries` 回傳「缺了哪一類」（例如 `(entries, missing)`，或讓呼叫端先問 `single_provider` 是否存在）。
  - 報表、待補登、傳票來源的回應加上 `unavailable: [{"category": "contractor", "reason": "外包工班模組未安裝"}]`，頁面顯示出來。
  - 守門：拿掉提供者後斷言回應**有**這個欄位，並用突變證明（拿掉提示 ⇒ 紅）。
  - INTEGRATION-POINTS IP-1「對方不在時」改寫成實際的使用者提示。

**X-2　「登記表與程式碼一致」的守門不存在**
- 位置：CORE-SPEC.md:67 寫「登記表：`docs/platform/INTEGRATION-POINTS.md`，由守門測試驗證與程式碼一致」。`git grep INTEGRATION-POINTS -- backend/tests` 只出現在三份連接器測試的 docstring，沒有任何一題讀這份文件。
- 現況：程式碼裡的 8 個 capability（`dispatch.row`、`voucher.draft`、`voucher.account_check`、`accounting.settings`、`voucher.void_draft`、`voucher.status`、`daily_task.external`、`calendar.writeback`）目前都有登記。**今天是一致的，但沒有東西會在它不一致時轉紅**。新增一個 `provide()` 卻忘了登記，或登記了卻沒實作，都會是綠燈。
- 依 PLAYBOOK §C-5：沒有守門的規則要標「⚠ 未守門」，排進階段 G；目前兩者都沒有。
- 建議修法：`tests/platform/test_integration_points_registered.py`：
  - 解析文件每一節的 `` `capability` ``；
  - 匯入 main 之後（或用 AST 掃 `product_files()` 的 `provide(` 與 `ModuleSpec(providers=…)`）取得實際的 capability 集合；
  - 兩邊必須相等。
  - 反向控制：暫存一份多一個 capability 的文件 ⇒ 紅。

**X-3　業務開發案列表的 row_access 套用點沒有守門（突變存活）**
- 位置：`routers/dev_crm.py:289-290`，`list_dev_cases` 的 `rows = [r for r in rows if row_access.visible("dev_case", user, r)]`。
- 突變：改成 `rows = list(rows)`，也就是任何持 dev_crm 模組的人都看得到全部業務開發案。含 dev_case／dev-crm 字樣的 19 個檔、259 題**全綠**（§3.3 M9）。
- 既有的 dev_case 題只測 admin 的樂觀鎖、刪除審核等；`test_row_access_callers` 只驗 `case` 的搜尋與動態牆。`0411f818` 把 `_can_access_case` 換成 row_access 時，列表這條路徑沒有補行為題。
- 為什麼是必修：交辦的最低要求是「突變 row_access 的其中一個套用點 ⇒ 要有題目紅」，這一點不成立。
- 重現：突變內容見 §3.3 M9，跑上述 19 個檔。
- 建議修法：
  - 正式補一題：兩個持 dev_crm 的業務，其中一人建案；外人的列表看不到、單筆 403，owner 看得到。X 的暫存題 `test_aud3_dev_case_outsider` 就是這個寫法：未突變時綠、M9 時紅。
  - 同時涵蓋 `dev_crm.py` 其他讀取路徑的 `visible` 呼叫點：`:341` 單筆、`:735` 統計、`:810` 紀錄列表。
  - 用突變 M9 證明新題會轉紅。

### 建議

- **Y-1　`last-received-bank-account` 沒有 row_access，也沒有模組檢查**（`RQ:1145-1177`）
  - 任何登入者輸入客戶名稱，都能拿到該客戶最近一次收款的入帳銀行名稱與科目。這也是一個「這個客戶有沒有已收款案件」的探測點（§3.2 最後一列，外人 200）。
  - 讀的是 `quotations.data_json`，卻不在 row_access 的套用範圍內。
  - 建議：要求 `cashier` 模組（呼叫端只有出納頁），或套 `filter_sql("case", …, scope="read")`。
- **Y-2　IP-2～IP-4 的「M07 不再 import M06」只涵蓋兩個檔；M07 其實仍依賴 M06**
  - `test_m07_no_longer_imports_m06_functions` 與 `test_m07_no_longer_touches_vouchers_all` 只讀 `helpers/bonus_vouchers.py`、`routers/bonus.py` 兩個寫死的路徑（`tests/platform/test_voucher_connectors.py:123-130`、`test_voucher_status_connectors.py:152-155`）。
  - M07 的 `helpers/bonus_pdf.py:35-36` 仍在匯入時 import M06 的 `helpers.voucher`、`helpers.voucher_pdf`（`l2_import_baseline.json:19-20` 列為債）。`routers/bonus.py:44` 匯入 bonus_pdf ⇒ **M06 不在包裡時，M07 整支 router 載不起來**（§3.1 第 3 列實測）。
  - 所以 INTEGRATION-POINTS 寫的「對方不在時：獎金核准照常」只在「M06 檔案仍在、只是提供者沒登記」時成立。這是〈證據的適用範圍〉那一類：綠燈是真的，證明的是連接器層。
  - 建議：
    - IP-2 的「對方不在時」加一句前提：「M07 經 bonus_pdf 仍依賴 M06（baseline 2 筆），在那兩筆清掉之前，不可以出『有 M07 沒有 M06』的產品組合」。
    - 兩題邊界守門改從 modules.json 取 M07 的全部單位，不寫死檔名。
- **Y-3　`core.source_tree.router_files()`／`logic_files()` 沒有涵蓋 CORE-SPEC §3 的子目錄結構**
  - `core/source_tree.py:23` 只收 `modules/<key>/api.py`，`:31` 只收模組第一層的 `*.py`。CORE-SPEC §3 規定的是 `api/`、`service/` **目錄**；按照規格搬遷的模組會被這兩支**靜默漏掉**。只有 `product_files()`（`:44-56`）有用 rglob。
  - 用 `router_files()` 的守門：`test_write_endpoints_are_audited`、`test_exception_detail_leak`、`test_system_audit`、`test_module_keys_consistency`、`test_write_lock_deadlock_guard`。
  - 另外 `test_no_credentials_in_query_2026_09_22.py:57,97`、`test_exception_detail_leak_2026_09_23.py:74` 仍然寫死 `routers/`。
  - 建議：
    - `router_files()` 改成收 `api.py`，或 `api/` 底下的全部 `*.py`；`logic_files()` 收 `service/` 等子目錄。
    - 加一題正對照：在沙盒建一個 `modules/zz/api/x.py`，斷言它出現在 `router_files()`。
- **Y-4　`test_mp6_map_case_locations` 的 API 題會被檔案中段的 `importorskip` 一起跳過**
  - `tests/test_mp6_map_case_locations_2026_09_24.py:158` 在**模組層**呼叫 `pytest.importorskip("playwright.sync_api")`。沒有裝 playwright 的環境，會連同上方 5 題 API 可見性題（`:103-148`，地圖逐筆可見性的唯一守門）一起 skip。
  - skip 不是綠，但全量摘要裡很容易被當成綠。
  - X 實測的連帶效果：X 用「檔案含 playwright 就排除」來篩掉 e2e，結果地圖突變 M6 在 85 檔題組裡**存活**；單獨跑 mp6 檔才轉紅。任何用同樣方式挑「非 e2e」的人，或沒有裝 playwright 的環境，都會漏掉地圖可見性的唯一守門。
  - 建議：把 e2e 段拆到獨立檔，或改成在 e2e 函式內 importorskip。
- **Y-5　案件守門有兩份實作，而且已經漂移**
  - `RQ:396` `_guard_case`＋`RQ:374` `_is_case_approver`，與 `HQ:67` `guard_case_access`＋`HQ:41` `is_document_approver`。
  - 兩份都走 row_access，但「簽核人放行」那一段是兩份：helpers 版多支援 `approval_json` 的無外層形狀（`HQ:51-54`），router 版沒有。
  - 這正是 row_access 要消除的「兩份各自實作就一定會漂移」。
  - 建議：router 版改成呼叫 helpers 版，`skip_if_semi_unlocked` 當參數傳入。

### 觀察

- **Z-1**：`registry.providers()`（`core/registry.py:126-136`）以 name 合併 legacy 與 `ModuleSpec.providers`。M06 搬遷時，如果 legacy 的 `provide()` 忘了刪，而 ModuleSpec 用**同一個 name** 登記，後者會靜默覆蓋前者，不會觸發「多提供者」錯誤。建議搬遷時加一題：legacy 與 ModuleSpec 的 `(cap, name)` 不可重疊。另外，建議守門禁止 `modules/` 底下呼叫 `registry.provide()`：它繞過載入器的停用與授權判斷。
- **Z-2**：三處在介面外自己判斷 admin，繞過 fail closed（`routers/item_reads.py:179`、`RQ:1113`、`routers/dev_crm.py:289`）。`case` 沒有登錄時，admin 仍然直通。影響小（admin 回來的是自己送進去的鍵），但 RA 檔頭寫「呼叫端不必也不該再自己判斷 role」。
- **Z-3**：批次匯出的稽核紀錄寫的是**要求的**單號（`RQ:6852` `",".join(nos[:20])`），包含看不到的那些；件數用的是實際匯出數。建議寫實際匯出的單號。另外，匯出時看不到的案件被靜默略過；不提示是否是刻意設計（避免洩漏存在與否），建議在 docstring 寫明。
- **Z-4**：IP-1 的 `test_no_one_imports_the_private_function_anymore` 比對的是字面 `"import _dispatch_row"`（`test_dispatch_connector.py:119`）。`vendor_contractors._dispatch_row` 屬性存取或跨行的 `import (\n _dispatch_row)` 抓不到；通用的 L2 邊界守門（AST）有補到大部分。
- **Z-5**：row_access 的範圍只有 `case`／`dev_case`。子資源（`/api/contractor-dispatches?quote_no=`、`/api/vouchers/by-case/{no}`）只做模組檢查，不做逐案檢查。這可能是刻意的（採購、會計看全部），但沒有寫進任何規格；建議在 MODULE-GUIDE 寫明「哪些讀取路徑受 row_access 管、哪些只受模組管」。
- **Z-6（環境）**：
  - 共用的 `D:\MOTRIX-PLATFORM\.venv` 在 22:08 被重建或誤刪，X 那時跑的 M1 回 exit 3。依主持指示，那一輪**不列為發現**；X 改用自建 venv 重跑全部突變。
  - `-n 8` 的突變跑會搶全機測試鎖（`conftest.py:850-863`）。23:05 起兩格都被別的 e2e 全量佔住，X 的 M8、M9 排隊約 20 分鐘；X 停掉之後，改成不平行、低優先權的目標題（PLAYBOOK §C-13）。
  - 在舊 .venv 上，若沒有設 `PYTHONDONTWRITEBYTECODE`，`client` 題會被 BK19 誤擋（寫 `.venv` 的 `__pycache__`），全部變成 ERROR；B 已經在 `wip/b-venv` 修正。

## 5. 假綠燈檢查

- **正對照綁特定模組**：
  - row_access 的 L1 等價測試用 `_t_case`／`_t_dev`，不綁模組 ✅。
  - 呼叫端題（`test_row_access_callers`）綁 M01／M02，這是應該的：驗的就是它們的登錄。
- **斷言驗到自己設的值**：
  - 三份連接器測試的反向控制都是「同一批資料，先斷言那一類非空（正對照），再拿掉提供者」✅。
  - `test_registered_rules_are_the_verified_ones` 把正式登錄的規則與等價測試用的宣告比對，擋住「等價測試驗的是另一份規則」✅。
- **證明的是別件事**：
  - Y-2：連接器層的退化 ≠ 實體缺席。
  - Y-4：skip 被讀成綠。
  - §3.2 的 stage-board 那一列不構成證據（owner 也看不到）。

## 6. 回覆欄（被稽核者 A 填；X 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | X 確認 |
|---|---|---|---|
| X-1 | | | |
| X-2 | | | |
| X-3 | | | |
| Y-1 | | | |
| Y-2 | | | |
| Y-3 | | | |
| Y-4 | | | |
| Y-5 | | | |
| Z-1 | | | |
| Z-2 | | | |
| Z-3 | | | |
| Z-4 | | | |
| Z-5 | | | |
| Z-6 | （環境，不需 A 回覆） | | |
