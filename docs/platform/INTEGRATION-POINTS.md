# 模組串接點登記（INTEGRATION-POINTS）

> 每一個跨組串接點都登記在這裡。L2 模組之間不可以直接 `import` 對方的程式（CORE-SPEC §2）；
> 需要對方的能力時，由擁有方公開一個串接點，使用方只依賴這裡寫下的契約。
> 判斷準則：**對方不在時，使用方要能少一項資訊，而不是壞掉。**

每一筆都要寫明六件事：

| 欄位 | 意思 |
|---|---|
| 形式 | provider（`core.registry`）／事件／HTTP… |
| 語法 | 提供方怎麼登記、使用方怎麼取用（可以直接複製的那一行） |
| 回傳 | 形狀與使用方實際讀的欄位 |
| 對方不在時 | 使用方的退化行為（必須可用，只少資訊） |
| 契約版本 | 目前版本；欄位只准加，改名／刪除要升版 |
| 守門 | 哪一題測試會在契約被破壞時變紅 |

---

## IP-1　`dispatch.row`：派工單列序列化（M04 → M01、M06）

對應 DEPENDENCY-MAP §3 #7、#8、#9（ROADMAP A6）。原本 `helpers/recognition.py`（M01）、
`modules/accounting/api/vouchers.py`（M06）直接 import `routers.vendor_contractors._dispatch_row`（M04 私有函式）；
`routers/reports.py`（M08）import 了但沒有呼叫，已刪除。

| 欄位 | 內容 |
|---|---|
| 提供方 | M04 外包工班：`modules/subcontract/api/vendor_contractors.py::_dispatch_row` |
| 使用方 | M01 `helpers/recognition.py::dispatch_entries`（應計派工成本，營運報表支出用）；M06 `modules/accounting/api/vouchers.py::_case_expense_sources`（傳票摘要來源的承攬商派工） |
| 形式 | provider，單一提供者（`core.registry`）。2026-09-26 M04 搬進 `modules/subcontract/`，改由 `ModuleSpec.providers` 宣告（模組未載入即不登記） |
| 語法 | 提供：`ModuleSpec(providers={("dispatch.row", "subcontract"): vendor_contractors._dispatch_row})`<br>取用：`fn = registry.single_provider("dispatch.row")`；`None` ⇒ 退化。兩個以上提供者 ⇒ `RuntimeError`（兩份實作在搶，不隨便挑） |
| 回傳 | `fn(row: sqlite3.Row) -> dict`。`row` 是 `contractor_dispatches` 一列（可 JOIN `vendor_contractors.name AS vendor_name`）。使用方讀的欄位：`id`、`quoteNo`、`vendorName`、`scope`、`items`、`personnel`、`totalAmount`、`personnelTotal`、`grandTotal`（含稅承攬商費用＋外包人員）、`invoiceNo`、`acceptedAt` |
| 對方不在時 | recognition：應計派工回 `[]` 並記 WARNING ⇒ 營運報表少了承攬商這一類支出，其餘照常。現金口徑讀匯款申請快照，不受影響。<br>vouchers：案件支出來源只剩額外支出，不列承攬商派工。<br>皆不丟例外。<br>**明說（稽核 X-1，2026-09-25）**：`_collect_expenses` 與 `/api/reports/expenses-monthly`（含待補登 `recognitionFlags`）回 `unavailable: [{"category": "contractor", "reason": "外包工班模組未安裝：承攬商派工的應計成本沒有列入（不是 0 筆）"}]`（`helpers.recognition.dispatch_unavailable(basis)`；現金口徑為 `[]`），報表頁顯示紅框 `data-testid="expense-unavailable"`；`/api/vouchers/summary-sources` 回 `unavailable: [{"category": "contractor_dispatch", …}]`，傳票頁帶入面板顯示 `data-testid="source-unavailable"` |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/tests/platform/test_dispatch_connector.py`：①提供者存在且回傳含全部使用欄位 ②registry 重複／多提供者規則 ③**反向控制**：同一批資料先確認派工那一類非空，拿掉提供者後三處照常回結果、只少派工 ④全 backend 不再有人 `import _dispatch_row`。突變驗證：拿掉退化判斷、拿掉 M04 登記、vouchers 不看提供者，三者皆轉紅。⑤（X-1）`test_absence_is_said_in_report_flags_and_voucher_sources`：提供者在 ⇒ `unavailable` 空（正對照）；拿掉 ⇒ 報表、待補登、傳票來源三處都有，現金口徑沒有；`test_pages_render_the_absence` 頁面綁定。突變 6 種皆轉紅 |

**尚未處理（不在 A6 範圍）**：`routers/reports.py::_live_dispatch_totals_by_quote` 自己又算了一次
grandTotal（直接讀 `contractor_dispatches`，沒有經過 `_dispatch_row`）。這是同一算法的第二份實作，
也是 M08 直接讀 M04 的表；應改用 IP-1，另開題。
（2026-09-25 主持裁示：等 M08 搬遷時再處理。）
〔更正（B，2026-09-26，稽核 ⑰ S-4）：下面的「✅ 已處理」只解決了**第二份算法**；**M08 直讀 M04 的表**這一半還在——`modules/analytics/api/reports.py::_live_dispatch_totals_by_quote` 仍自己 `SELECT … FROM contractor_dispatches LEFT JOIN vendor_contractors`，只把「列 → grandTotal」交給提供者。待 M04 公開「有效派工列表」提供者（ROADMAP M04），M08 改走它〕
〔✅ 已處理（B，2026-09-26，M08 搬遷 ⑤）：改用 `registry.single_provider("dispatch.row")` 的 `grandTotal`，算法只剩一份；提供者不在 ⇒ 回 None，`staleSettlementCount` 為 None 並附 `staleSettlementNote`「外包工班模組未安裝：無法檢查已完結的精算快照是否過期（不是 0 件）」，報表頁顯示 `data-testid="stale-settlement-unavailable"`。題：`backend/modules/analytics/tests/test_reports_dispatch_connector_2026_09_26.py`（等價、明說、正對照）；突變（不在時回 {}）⇒ 紅〕

---

## IP-2　`voucher.draft`＋`voucher.account_check`：建立傳票草稿（M06 → M07）

對應 DEPENDENCY-MAP §3 #19（ROADMAP A7）。原本 `helpers/bonus_vouchers.py`（M07）直接 import
`routers.vouchers.insert_draft_voucher／_line_sources／_amount_lines`、`routers.accounting_export.validate_account_code`、
`helpers.voucher.classify_category`（皆 M06）。

| 欄位 | 內容 |
|---|---|
| 提供方 | M06 會計：`modules/accounting/api/vouchers.py::_provide_voucher_draft`、`modules/accounting/api/accounting_export.py::validate_account_code` |
| 使用方 | M07 `modules/payroll/bonus_vouchers.py`（進入待發放 ⇒ 轉帳草稿；標記已發放 ⇒ 支出草稿；科目設定頁的驗證）、`modules/payroll/api/bonus.py`（標記已發放時驗出納選的銀行科目） |
| 形式 | provider，單一提供者（`core.registry`；M06 尚未搬進 `modules/`，以 `registry.provide()` 在匯入時登記） |
| 語法 | 提供：`_registry.provide("voucher.draft", "accounting", _provide_voucher_draft)`、`_registry.provide("voucher.account_check", "accounting", validate_account_code)`<br>取用：`registry.single_provider("voucher.draft")(conn, voucher_date=…, summary=…, lines=[{account_code, summary, debit, credit}], created_by=…, now=…)`；`registry.single_provider("voucher.account_check")(conn, code)` |
| 回傳 | draft：`{"id": int, "voucher_no": str}`；在呼叫端的交易裡寫入 `vouchers_all`＋`voucher_lines`，**不 commit**（呼叫端的狀態與傳票連結一起成功、一起失敗）。分錄正規化與傳票類別由 M06 決定。<br>account_check：`(ok: bool, err: str)` |
| 對方不在時 | **獎金核准／標記已發放照常成立**，不產生傳票，而且明說：回傳 `notice`＝「未產生傳票：會計模組未安裝（獎金狀態照常更新；需要傳票請由會計手動開立）」（前端 `_withNotice` 顯示）。出納帶了銀行科目也不驗、不擋發放。科目設定：GET 的 `problems` 每一項為「會計模組未安裝，無法驗證科目」；PUT 回 400 並寫明原因，一個都不寫入（驗證不了就不存）。<br>**實體缺席（稽核 Y-2，2026-09-25）**：M07 的 `helpers/bonus_pdf.py` 組獎金分潤單預覽／PDF 要用 M06 的 `helpers.voucher`、`helpers.voucher_pdf`；已改成函式內延遲載入，M06 檔案不在包裡時 M07 照常載入，只有舊流程的預覽／PDF 端點回 503「會計模組未安裝：無法產生獎金分潤單預覽／PDF」。這仍是 M07 → M06 的相依（`l2_import_baseline` 兩筆），要清掉得把三支共用函式下沉 L1 |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/modules/payroll/tests/test_voucher_connectors.py`：①提供者存在、draft 真的寫出草稿與分錄且不 commit、account_check 對錯都對 ②**反向控制**：同一條流程有 M06 時產生兩張草稿（正對照），拿掉提供者後獎金照走、零張傳票、notice／voucherNotice／problems 都有明確提示 ③M07 不再 import M06 ④頁面綁定 `detail.voucherNotice`。突變驗證：不查 M06、默默略過（notice 空）、仍驗銀行、銀行清單不處理缺席，四者皆轉紅 |

**尚未處理（不在 A7 範圍）**：`helpers/bonus_vouchers.py::withdraw_accrual`（退回時作廢轉帳草稿）與
`linked_vouchers`（明細列出連結的傳票）仍直接讀寫 M06 的 `vouchers_all`。M06 不在時表仍在（凍結 migration），
行為不會壞，但屬 M07 直接寫 M06 的表（DEPENDENCY-MAP §4）；應由 M06 再公開「作廢草稿」「查傳票狀態」兩個連接器，另開題。
➡ 2026-09-25 已處理：見 IP-4。

---

## IP-3　`accounting.settings`：會計設定（付款銀行）（M06 → M07）

對應 DEPENDENCY-MAP §3 #18（ROADMAP A7）。原本 `routers/bonus.py:1885` 函式內 import `routers.accounting_export._t100_config`。

| 欄位 | 內容 |
|---|---|
| 提供方 | M06 會計：`modules/accounting/api/accounting_export.py::_provide_accounting_settings` |
| 使用方 | M07 `modules/payroll/api/bonus.py::_payout_bank_choices`（待發放時給出納選付款銀行） |
| 形式 | provider，單一提供者（同 IP-2） |
| 語法 | 提供：`_registry.provide("accounting.settings", "accounting", _provide_accounting_settings)`<br>取用：`registry.single_provider("accounting.settings")()` |
| 回傳 | `{"bankAccounts": [{"name", "acctCode"}], "defaultBankAccountCode": str}`——**只公開這一小塊**，不給整份 T100 設定（其餘是會計內部設定） |
| 對方不在時 | 明細回 `bankAccounts: []`、`defaultBankAccountCode: ""`，並加 `voucherNotice`＝「未產生傳票：會計模組未安裝（標記已發放照常，不會產生支出傳票）」，獎金頁在「標記已發放」按鈕旁顯示 |
| 契約版本 | 1（2026-09-25） |
| 守門 | 同 IP-2 的測試檔（契約形狀＝恰好兩個鍵；反向控制檢查 `bankAccounts` 為空且 `voucherNotice` 有提示；頁面綁定） |

---

## IP-4　`voucher.void_draft`＋`voucher.status`：作廢草稿、查傳票狀態（M06 → M07）

接續 IP-2 的「尚未處理」。原本 `helpers/bonus_vouchers.py::withdraw_accrual`／`linked_vouchers`（M07）直接讀寫
M06 的 `vouchers_all`。

| 欄位 | 內容 |
|---|---|
| 提供方 | M06 會計：`modules/accounting/api/vouchers.py::_provide_voucher_void_draft`、`_provide_voucher_status` |
| 使用方 | M07 `modules/payroll/bonus_vouchers.py`：`withdraw_accrual`（獎金退回 ⇒ 作廢未送審的轉帳草稿）、`linked_vouchers`（明細列出連結的傳票）、`create_accrual`（殘留草稿防護） |
| 形式 | provider，單一提供者（同 IP-2） |
| 語法 | 提供：`_registry.provide("voucher.void_draft", "accounting", _provide_voucher_void_draft)`、`_registry.provide("voucher.status", "accounting", _provide_voucher_status)`<br>取用：`registry.single_provider("voucher.void_draft")(conn, voucher_id, voided_by=…, now=…, reason=…)`；`registry.single_provider("voucher.status")(conn, voucher_id)` |
| 回傳 | void_draft：`{"result": "voided"｜"not_draft"｜"gone", "voucher_no", "status"}`——只作廢「草稿」；已送審 ⇒ `not_draft` 不動；不存在或早已作廢 ⇒ `gone`。status：`{"id", "voucher_no", "status", "voided"}`，不存在 ⇒ `None`。兩者都在呼叫端的交易裡，**不 commit** |
| 對方不在時 | **退回照常**成立；不作廢、**保留連結**（之後查得到是哪一張），回傳 `notice`＝「未作廢傳票（#id）：會計模組未安裝；退回照常，請會計另行處理那一張傳票」。明細仍列出每一張連結的傳票，標 `unavailable` 與「會計模組未安裝，無法查詢狀態」，頁面不給連結（不讓傳票從畫面消失）。<br>**M06 回來後**：再次進入待發放時，若舊連結仍是未作廢的草稿 ⇒ 不另開、不覆蓋，notice 明說「上一張轉帳傳票草稿 … 尚未作廢」；舊連結已送審 ⇒ 照原行為另開新草稿 |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/modules/payroll/tests/test_voucher_status_connectors.py`：①void_draft 三種結果＋status 形狀＋不 commit ②**反向控制**：有 M06 時退回會作廢（正對照）；拿掉後不作廢、有提示、連結保留、M06 的表沒被動、明細標無法查詢 ③M06 回來：殘留草稿不另開不覆蓋；已送審的舊連結照常另開 ④M07 原始碼不再出現 `vouchers_all`、頁面有 unavailable 分支。突變 5 種皆轉紅（默默略過、傳票從明細消失、拿掉殘留防護、防護放太寬擋到已送審、M06 不在仍解除連結） |

---

## IP-5　`daily_task.external`：由外部來源建立／同步每日任務（M12 → M01）

對應 DEPENDENCY-MAP §3.1（ROADMAP A11）。原本 `helpers/case_stage_tasks.py`（M01）直接寫 M12 的 `daily_tasks`／`daily_task_completions`。

| 欄位 | 內容 |
|---|---|
| 提供方 | M12 每日任務：`modules/daily_tasks/api.py::_ExternalTasks`（`upsert`／`withdraw`） |
| 使用方 | M01 `helpers/case_stage_tasks.py::sync_daily_task_for_case_stage`（案件執行進度勾選完成 → 月曆上一筆「已完成」任務）、`delete_daily_task_for_case_stage`（階段刪除 → 收回）；`routers/quotations.py` 階段更新端點（回應的 `notice`） |
| 形式 | provider，單一提供者（`core.registry`；M12 以 `ModuleSpec.providers` 宣告，模組未載入即不登記） |
| 語法 | 提供：`ModuleSpec(providers={("daily_task.external", "daily_tasks"): api._ExternalTasks})`<br>取用：`t = registry.single_provider("daily_task.external")`；`None` ⇒ 退化。`t.upsert(conn, task_id=…, task_date=…, title=…, description=…, category=…, assignees=[…], created_by=…, case_no=…, completion_report=…, now=…) -> task_id`；`t.withdraw(conn, task_id, now)` |
| 回傳 | `upsert` 回任務 id（`task_id` 指到已刪除或不存在的列 ⇒ 新建）；替每個負責人寫完成紀錄（否則隔天寄逾期通知）。**在呼叫端的連線上寫、不 commit**：M01 把 id 記回 `case_stages.daily_task_id` 後一起 commit |
| 對方不在時 | **勾選照常存檔**，不產生每日任務；階段更新端點回應 `notice`＝「未建立每日任務：每日任務模組未安裝」（`helpers/case_stage_tasks.NOTICE_NO_DAILY_TASKS`）；背景同步記 INFO 後返回；取消勾選或刪除階段時，原本建立過任務（`case_stages.daily_task_id` 有值）⇒ `notice`＝「未收回每日任務：每日任務模組未安裝，原本建立的任務仍在」（`NOTICE_NOT_WITHDRAWN`；id 保留，M12 裝回後再勾選會收斂到同一筆），原本沒有任務 ⇒ 不帶 `notice`。案件頁以提示顯示 `notice`（2026-09-26，AUDIT-X-C-batch1 B-1）。皆不丟例外。**提供者在但失敗**（`upsert`／`withdraw` 丟例外）：同樣照常存檔、`notice` 為空、只記 WARNING——既有的 fire-and-forget 設計，畫面不會知道（X 稽核 C-2，2026-09-25 補記） |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/modules/daily_tasks/tests/test_ip5_daily_task_external.py`（隨 M12）：①M12 已登記 ②**正對照**：勾選 ⇒ 一筆任務＋完成紀錄、id 記回、取消勾選收回 ；`backend/tests/platform/test_case_stage_connectors.py`：③**反向控制**：拿掉提供者 ⇒ 200、`done=1`、零筆任務、`notice` 明說 ④M01 檔內不再有寫 `daily_tasks`／`daily_task_completions` 的 SQL；`table_write_exceptions.json` 對應兩筆 debt 已刪（邊界守門 ③）。突變：notice 不看提供者、提供者不寫完成紀錄 ⇒ 皆轉紅 |

---

## IP-6　`calendar.writeback`：行事曆事件 id 由擁有模組回寫（M01／M03／M05 → L1 行事曆）

對應 DEPENDENCY-MAP §3.1（ROADMAP A11）。原本 L1 `helpers/google_calendar.py` 直接 UPDATE 5 張 L2 表寫回 event id。

**選型（評估對呼叫端改動最小）**：採「擁有模組登記回寫的提供者」，不採「L1 只回傳 event id、各模組自己回寫」。後者要把 5 個 push 函式的呼叫端（6 支 router 的背景執行緒）全部改寫成「拿到 id 再回寫」，而那些呼叫是 fire-and-forget 的背景執行緒、拿不到回傳值；前者呼叫端**零改動**，只在擁有模組各加一支回寫函式。

| 欄位 | 內容 |
|---|---|
| 提供方 | M05 `modules/arap/api/invoice_vouchers.py`（`invoice_voucher`）、`modules/arap/api/payment_requests.py`（`payment_request`）；M03 `modules/supply/api/shipping_notes.py`（`shipping_note`）；M01 `routers/quotations.py`（`quotation`、`case_stage`） |
| 使用方 | L1 `helpers/google_calendar.py::_write_back`（`push_event_for_invoice_voucher`／`payment_request`／`shipping_note`／`quotation_won`／`case_stage_due`／`case_stage_done`） |
| 形式 | provider，**多提供者、以名稱區分**（`registry.providers("calendar.writeback")[kind]`） |
| 語法 | 提供：`_registry.provide("calendar.writeback", "<kind>", fn)`<br>取用：`registry.providers("calendar.writeback").get(kind)`；`None` ⇒ 退化。`fn(key, event_id, slot="default")`；`case_stage` 的 `slot` ∈ `due`（到期日事件）／`done`（完成日事件），其他值 ⇒ `KeyError`（不猜欄位） |
| 回傳 | 無。提供者自己開連線、**拿寫鎖、重讀、只寫入 event id**（事件建立是網路請求，不可以用建事件前讀到的 `data_json` 整包蓋回；原本只有 quotation 這樣做，invoice／payment／shipping 三支現在也一樣）。`event_id=""` ＝清除 |
| 對方不在時 | 事件照建（或照刪），只是不回寫；記 WARNING「…的擁有模組未安裝 —— event id 未回寫」。不丟例外 |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/tests/platform/test_case_stage_connectors.py`：①5 個 kind 全部登記 ②**正對照**：報價單成案、階段到期／完成兩個欄位分開寫回 ③**反向控制**：拿掉 `quotation` 提供者 ⇒ 不丟例外、`data_json` 沒有 event id、WARNING 說明原因 ④不認得的 slot 被拒 ⑤L1 檔內不再有寫這 5 張表的 SQL；`table_write_exceptions.json` 對應 5 筆 debt 已刪。既有 `test_quote_json_direct_writes_lost_update_2026_09_25::test_google_calendar_event_id`（空窗寫入不被蓋掉）照綠。突變：不登記 quotation 提供者、缺席時不記 WARNING ⇒ 皆轉紅。⑥（X 稽核 A-3 補，2026-09-25）假的 Google 每次回**不同**的 id：階段到期／完成各寫進自己的欄位（對調 ⇒ 紅）；invoice_voucher／payment_request／shipping_note 三支回寫各自執行、只寫自己那一列、其他欄位不動，建立事件期間別人改過單據不被蓋回（寫錯值、整包蓋掉 ⇒ 紅）。原本這三支只驗了「有登記」，沒有題目執行過 |

**尚未處理（不在 A11 範圍）**：L1 行事曆仍**直接讀** 5 張 L2 表來組事件標題與內容（`SELECT … FROM invoice_vouchers` 等）。寫入已歸位，讀取的相依還在；要切斷須改成各模組提供「事件內容」或把 push 函式移回各模組，另開題。

---

## IP-7　L1 法規參數讀取介面（L1 `helpers.legal_params` → 所有算扣繳／補充保費的模組；首個使用方：M07 勞報單，下一個：U4 獎金分潤）

L1 → L2 方向的公開介面（不是 provider：L1 永遠在，L2 直接 import）。規格：CUSTOMIZATION-SPEC §9.1。

| 欄位 | 內容 |
|---|---|
| 形式 | L1 函式（`from helpers import legal_params as lp`） |
| 語法 | `versions = lp.load_versions()`（依 effectiveFrom 排序的清單）<br>`rules = lp.rules_for_date(versions, "YYYY-MM-DD" 或 date)`：`effectiveFrom ≤ 日期` 的最新一版（深拷貝）；沒有 ⇒ 丟 `lp.NoApplicableRules`（`ValueError` 子類，訊息可直接給使用者）<br>`lp.rules_by_version(versions, "2026")` ⇒ dict 或 `None`<br>`lp.today()`：「今天」的唯一來源（測試 monkeypatch 它）<br>**法規金額的捨入**（2026-09-26，稽核 D-1）：`lp.round_half_up(amount, rate)`＝四捨五入到元（補充保費，健保署「角以下 4 捨 5 入」）；`lp.floor_amount(amount, rate)`＝元以下捨去（扣繳稅額）。金額與費率轉十進位計算，不經浮點乘積；**不可以用內建 `round()`**（銀行家捨入）或 `math.floor(g * rate)`。前端同一套：`frontend/static/legal-round.js` 的 `MotrixLegalRound.halfUp／floor` |
| 回傳 | 一版＝`{version, effectiveFrom, resident{50,9A,9B:{tax_rate,tax_threshold}}, non_resident{50:{tax_rate,tax_threshold,low_salary_rate},9A,9B}, nhi{rate, max_single_payment, thresholds{50,9A,9B}, bonus_insured_multiple}, minimum_wage{monthly}, sources[]}`。獎金（非每月薪資）扣繳用 `resident["50"]`（5%／起扣 90,501）；補充保費費率 `nhi.rate`、單次上限 `nhi.max_single_payment`；獎金補充保費門檻＝投保金額 × `nhi.bonus_insured_multiple`（115 年＝4，必填；舊資料讀取時補 4） |
| 單據凍結 | 使用方存 `version` 與整份 `rules` 快照；修改舊單沿用快照，使用者明確選擇才重挑（勞報單的做法見 `modules/payroll/api/payslips.py::update_payslip`） |
| 對方不在時 | 不適用（L1）。日期沒有適用版本 ⇒ 使用方**拒絕產生並說明**（不猜、不送 0） |
| 契約版本 | 1.2（2026-09-26，CORE_VERSION 1.12）。1.1＝`nhi.bonus_insured_multiple`（R 後加的必填欄位，當時漏升，稽核 O-4 補記）；1.2＝`round_half_up`／`floor_amount`。欄位只准加；再加欄位時照 MODULE-GUIDE §2 升次版號。〔更正（X-R，2026-09-26，稽核 O-4）：原寫「1（2026-09-25，CORE_VERSION 1.5）」，R 實際合回在 **1.7**（`backend/core/CHANGELOG.md` 1.7 節），1.5 是寫文件當下的暫用號〕 |
| 守門 | `tests/platform/test_legal_amount_rounding_guard.py`（讀法規參數的程式不可以直接 `round()`／`math.floor()`／`Math.round()`，一律走上面兩個函式）；`tests/test_legal_audit_d_r1_r3_2026_09_26.py`（20,000～2,000,000 逐元比對四捨五入）；`tests/test_legal_params_r1_2026_09_25.py`（選版、凍結、門檻＝最低工資）；`tests/platform/test_legal_params_single_source.py`（法規數字只能出現在 legal_params）；`tests/platform/test_l1_interface_snapshot.py`（介面變動要升版） |

---

## IP-8　`bonus.payouts`：獎金分潤待發放與發放紀錄（M07 → M05 出納）

對應 CORE-SPEC「使用者裁示」獎金分潤：送交出納（RUN-PLAN §5 A 線 ③）。出納頁（M05）原本沒有獎金分潤；
不 import M07，改由 M07 公開這一個讀取連接器。**「標記已發放」不經連接器**：出納頁直接打獎金那一支
`POST /api/bonus/cases/{單號}/mark-paid`（同一個動作只有一份實作；M07 不在時那支端點本來就不存在，出納頁也不會出現按鈕）。

| 欄位 | 內容 |
|---|---|
| 提供方 | M07 薪資獎金：`modules/payroll/bonus_payouts.py::_Payouts`（`pending`／`paid`） |
| 使用方 | M05 `modules/arap/api/cashier.py`：`GET /api/cashier/bonus-queue`（出納頁「獎金待發放」子頁籤）、`_execution_history`（執行歷史「獎金分潤發放」區塊）、`GET /api/cashier/export`（Excel 第三張「獎金發放明細」）；頁面 `pages/cashier.html`、`js/cashier.js` |
| 形式 | provider，單一提供者（`core.registry`；M07 尚未搬進 `modules/`，以 `registry.provide()` 在匯入時登記） |
| 語法 | 提供：`registry.provide("bonus.payouts", "payroll", _Payouts)`<br>取用：`p = registry.single_provider("bonus.payouts")`；`None` ⇒ 退化。`p.pending(conn)`；`p.paid(conn, start, end)`（YYYY-MM-DD，含首尾，比發放日） |
| 回傳 | `pending`：`[{quoteNo, customer, project, total, people, approvedAt}]`（舊的在前）。`paid`：`[{quoteNo, customer, project, total, people, paidAt, paidBy, withholding, nhiPremium, net}]`；扣繳快照不存在（U4 接上前發放的）⇒ 後三者 **`None`（不是 0）**。只回案件合計與人數，**不回個人金額**（個人明細在獎金頁，C1 可見範圍） |
| 對方不在時 | `bonus-queue` 回 200 `{"available": false, "visible": true, "notice": "薪資獎金模組未安裝：出納頁不顯示獎金分潤", "items": []}`，頁面顯示那一句；執行歷史 `bonusPaid: []`＋`bonusNotice`；Excel 第三張只有那一句。待付款／待收款／匯出其餘照常。**可見範圍**：只有最高管理者與出納（cashier）看得到獎金；出納頁的財務（finance）`visible: false`、不顯示該子頁籤、Excel 沒有第三張 |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/modules/payroll/tests/test_bonus_payout_connectors.py`：`test_cashier_queue_mark_paid_is_the_same_action_and_history`（佇列→同一支 mark-paid→離開佇列、進執行歷史與 Excel；財務看不到）、`test_cashier_page_binds_bonus_mark_paid`（頁面綁定）、`test_reverse_without_payroll_cashier_still_works_and_says_so`（**反向控制**）。突變：M07 不在時默默略過、財務看得到獎金 ⇒ 皆轉紅 |

---

## IP-9　`expense.entries`：其他模組登記的支出（M07 → M08 報表）

對應 CORE-SPEC「使用者裁示」獎金分潤：財務報表——以**發放日**列為支出，進營運報表與月支出。

| 欄位 | 內容 |
|---|---|
| 提供方 | M07 薪資獎金：`modules/payroll/bonus_payouts.py::_expense_entries`（名稱 `bonus`） |
| 使用方 | M08 `modules/analytics/api/reports.py::_collect_expenses`（⇒ `/api/reports/expenses-monthly`、`/api/reports/financial`（JSON／Excel／PDF）、每月營運報表信、首頁儀表板支出） |
| 形式 | provider，**多提供者、以名稱區分**（`registry.providers("expense.entries")`；依名稱排序逐一呼叫）。之後其他模組的支出（例：勞報單）可登記同一個名稱空間，報表不用改 |
| 語法 | 提供：`registry.provide("expense.entries", "bonus", _expense_entries)`<br>取用：`for name, fn in sorted(registry.providers("expense.entries").items()): fn(conn, d0, d1)` |
| 回傳 | `[{date, quoteNo, desc, amount, category}]`；`date`＝發放日（權責與現金兩種口徑相同），`category`＝`"獎金分潤"`。一案一筆，`desc`＝「獎金分潤（N 人）」，**不列個人**。報表把它併進「其他支出」（`details.other[].category` 區分；首頁 otherBreakdown 依 category 自動多一塊），部門篩選照 `quoteNo` 歸屬 |
| 對方不在時 | 沒有提供者 ⇒ 支出少了獎金這一類，其餘照常，不丟例外。**不另加提示**：M07 不在時獎金分潤這個功能不存在，沒有應列而未列的支出（⚠ 例外：M07 曾經安裝、之後被停用而資料還在 ⇒ 報表少列那些已發放的獎金。觀察項，見 RUN-PLAN §6 本項回報） |
| 契約版本 | 1（2026-09-25） |
| 守門 | 同上測試檔：`test_report_counts_bonus_on_paid_date`（待發放不算、發放後出現在發放月、月合計差額＝發放總額）、`test_reverse_without_payroll_report_still_works`（**反向控制**）。突變：報表不讀提供者 ⇒ 轉紅 |

**案件頁相關傳票（同一項裁示）**：不新增串接點。獎金產生的兩張傳票草稿，每一行都帶摘要來源 `source_type="case"`、`source_key=案件單號`（JV36），經 IP-2 `voucher.draft` 寫入；案件頁的 `GET /api/vouchers/by-case/{單號}` 本來就依這個來源找。IP-2 的 `lines` 因此多了兩個**選填**欄位（只加不改，契約版本不變）。守門：`test_case_page_related_vouchers_show_bonus_vouchers`；突變：拿掉來源 ⇒ 轉紅。⚠ 這次之前已產生的獎金傳票沒有來源、不回填（開發機測試資料）。

---

## IP-15　`dispatch.list_for_case`：案件整包的承攬派工段（M04 → M01）

對應 l2_import_baseline `M01 router:quotations -> M04 router:vendor_contractors`（M04 搬遷，2026-09-26）。原本 M01 案件整包（`/api/quotations/{no}/case-bundle`）直接 import `routers.vendor_contractors.list_dispatches`。編號為暫定（同時期 C 的 approval.queue_items、crm.quote_deleted 與 A 的 daily.check 也在暫用 IP-10、IP-11），由列車依合回順序定號。〔第六班列車定號（2026-09-26）：dispatch.list_for_case 暫用 IP-12→IP-15、quotation.append_items 暫用 IP-13→IP-17、contractor_voucher.public 維持 IP-14（origin 已用 IP-12 case.access、IP-13 crm.quote_deleted；IP-16＝M07 bonus.module_status）〕

| 欄位 | 內容 |
|---|---|
| 提供方 | M04 外包工班：`modules/subcontract/api/vendor_contractors.py::list_dispatches_for_case`（`list_dispatches` 的包裝） |
| 使用方 | M01 `routers/quotations.py::case_bundle`（`GET /api/quotations/{no}/case-bundle`）的 `parts.dispatches` |
| 形式 | provider，單一提供者（`core.registry`）；`ModuleSpec.providers` 宣告 |
| 語法 | 提供：`ModuleSpec(providers={("dispatch.list_for_case", "subcontract"): vendor_contractors.list_dispatches_for_case})`<br>取用：`fn = registry.single_provider("dispatch.list_for_case")`；`None` ⇒ 退化。`fn(quote_no, authorization) -> list`（同一份授權、權限判斷與單獨打 `/api/contractor-dispatches?quote_no=` 逐字相同） |
| 回傳 | 派工單列（`dispatch.row` 形狀）；權限不足 ⇒ `HTTPException(403)`，整包那一段照舊回 `{"ok": false, "status": 403}` |
| 對方不在時 | 整包照常回；`parts.dispatches`＝`{"ok": false, "status": 404, "detail": DISPATCHES_UNAVAILABLE}`（「外包工班模組未安裝：沒有承攬派工資料」），前端照「那一段回非 2xx」處理 |
| 契約版本 | 1（2026-09-26） |
| 守門 | 提供方（隨模組搬走）`backend/modules/subcontract/tests/test_subcontract_providers.py`：登記、正對照；取用方（外包工班不在也成立）`backend/tests/platform/test_subcontract_connectors.py`：拿掉提供者 ⇒ 整包照回、那一段 404 說明、其他段照常。突變：整包不看提供者、不登記 ⇒ 紅 |

---

## IP-17　`quotation.append_items`：把外部品項附加到草稿報價單（M01 → M04）

對應 l2_import_baseline `M04 router:vendor_contractors -> M01 helper:quotations`。原本 M04「派工品項匯入報價單」自己讀 `quotations`、組報價品項、呼叫 M01 的 `save_quotation_json` 寫回。報價單的格式與寫入歸 M01。編號為暫定（同時期 C 的 approval.queue_items、crm.quote_deleted 與 A 的 daily.check 也在暫用 IP-10、IP-11），由列車依合回順序定號。〔第六班列車定號（2026-09-26）：dispatch.list_for_case 暫用 IP-12→IP-15、quotation.append_items 暫用 IP-13→IP-17、contractor_voucher.public 維持 IP-14（origin 已用 IP-12 case.access、IP-13 crm.quote_deleted；IP-16＝M07 bonus.module_status）〕

| 欄位 | 內容 |
|---|---|
| 提供方 | M01 案件：`routers/quotations.py::_append_items_to_quotation` |
| 使用方 | M04 `modules/subcontract/api/vendor_contractors.py::import_dispatch_to_quote`（`POST /api/contractor-dispatches/{did}/import-to-quote`） |
| 形式 | provider，單一提供者；要與呼叫端同一筆交易（呼叫端已拿寫鎖）⇒ 不用事件 |
| 語法 | 提供：`_registry.provide("quotation.append_items", "quotations", _append_items_to_quotation)`<br>取用：`append = registry.single_provider("quotation.append_items")`；`None` ⇒ 退化。`append(conn, quote_no, header, items, now) -> now`；`items`＝`[{description, qty, unit, cost, note}]` |
| 回傳 | 在呼叫端連線上寫、不 commit。報價單不存在 ⇒ `HTTPException(404)`；不是草稿 ⇒ `409`（原本在 M04 的規則逐字搬來）。品項換成報價品項：成本＝cost、毛利 30%、售價由報價單自己算；前面加一列區段標題 |
| 對方不在時 | 匯入端點回 `409`＋`QUOTE_IMPORT_UNAVAILABLE`（「案件模組未安裝：無法把派工品項匯入報價單」），派工本身不動 |
| 契約版本 | 1（2026-09-26） |
| 守門 | `backend/modules/subcontract/tests/test_subcontract_providers.py`：經 M01 匯入（品項欄位逐一比對）、非草稿 409、M01 不在 ⇒ 409 且報價單不動；`test_quote_json_lost_update` 探針改包 M01。突變：匯入不看 M01、M01 不擋非草稿、成本放錯欄 ⇒ 紅 |

---

## IP-14　`contractor_voucher.public`＋`contractor_voucher.paid_between`：承攬商匯款申請的對外形狀（M04 → M05 出納、M06 會計匯出）

對應 l2_import_baseline `M05 router:cashier -> M04 router:contractor_vouchers`、`M06 router:accounting_export -> M04 router:contractor_vouchers`。原本兩處直接 import `_voucher_public`。編號為暫定（同時期 C 的 approval.queue_items、crm.quote_deleted 與 A 的 daily.check 也在暫用 IP-10、IP-11），由列車依合回順序定號。〔第六班列車定號（2026-09-26）：dispatch.list_for_case 暫用 IP-12→IP-15、quotation.append_items 暫用 IP-13→IP-17、contractor_voucher.public 維持 IP-14（origin 已用 IP-12 case.access、IP-13 crm.quote_deleted；IP-16＝M07 bonus.module_status）〕

| 欄位 | 內容 |
|---|---|
| 提供方 | M04 外包工班：`modules/subcontract/api/contractor_vouchers.py::_voucher_public`、`modules/subcontract/api/contractor_vouchers.py::_paid_between`（`contractor_voucher.paid_between`，2026-09-26 加：區間內已付款的憑據，形狀同 public） |
| 使用方 | M05 `modules/arap/api/cashier.py`（待付款 `_payable_queue`、執行歷史 `_execution_history`）；M06 `modules/accounting/api/accounting_export.py::_collect_paid_contractor_vouchers`（T100 傳票匯出） |
| 形式 | provider，單一提供者 |
| 語法 | 提供：`ModuleSpec(providers={("contractor_voucher.public", "subcontract"): contractor_vouchers._voucher_public})`<br>取用：`pub = registry.single_provider("contractor_voucher.public")`；`None` ⇒ 退化。`pub(row, include_snapshot=False) -> dict` |
| 回傳 | `row`＝`contractor_payment_vouchers` 一列；回 `voucherNo`、`quoteNo`、`vendorName`、`grandTotal`、`payableDate`、`isPaid`、`paidAt`、`paidBankAccountName／Code` 等（見函式） |
| 對方不在時 | 出納待付款：`404`＋`CONTRACTOR_MISSING`（「外包工班模組未安裝：出納頁不顯示承攬商匯款」），頁面顯示這一句；執行歷史：`outgoing` 空、`contractorNotice` 明說，Excel「已匯款明細」第一列寫同一句；T100 預覽：`notice`＝`T100_CONTRACTOR_MISSING`（匯出的 Excel 是 T100 匯入檔，不加說明列）。皆不丟例外 |
| 契約版本 | 1（2026-09-26） |
| 守門 | 提供方 `backend/modules/subcontract/tests/test_subcontract_providers.py`：正對照；取用方 `backend/modules/arap/tests/test_subcontract_connectors.py`（出納／T100 那一題，2026-09-26 隨 M05 搬）＋`backend/tests/platform/test_subcontract_connectors.py`（其餘）：待付 404＋原因、執行歷史 contractorNotice、Excel 第一列、T100 預覽 notice；畫面 `test_e2e_cashier_subcontract_absent_notice_2026_09_26`。突變：出納不看提供者、不說缺（兩處）、畫面吞掉 404 ⇒ 紅 |

**尚未處理**：M01／M05／M06／M08 與 L1（封存、PDF、報表、傳票附件）仍**直接讀** `contractor_payment_vouchers`、`contractor_dispatches`、`vendor_contractors`、`contractors`；M04 不在時表仍在（凍結 migration），讀取不會壞。讀取連接器另開題。


---

## IP-98　`receivables.income_items`：收款明細（M05 → M08 現金口徑收入）

對應 ROADMAP A8b（資料擁有權在 M05）。M08 搬遷 ③ 時先下沉 L1 `helpers/receivables.py` 當中繼；M05 搬遷（2026-09-26）收回 `modules/arap/receivables.py`，對外只經本串接點。**編號暫定（98），列車定號。**

| 欄位 | 內容 |
|---|---|
| 提供方 | M05 應收應付：`modules/arap/receivables.py::collect_income_items`（`ModuleSpec.providers`，模組沒載入就沒有登記） |
| 使用方 | M08 `modules/analytics/api/reports.py::_build_income_expense_scopes`（現金口徑：當月／今年度／季收入；權責口徑不用它）；L1 殼 `helpers/receivables.py::collect_income_items`（淘汰中，下一個主版號刪除） |
| 形式 | provider，單一提供者 |
| 語法 | 提供：`ModuleSpec(providers={("receivables.income_items", "arap"): receivables.collect_income_items})`<br>取用：`p = registry.single_provider("receivables.income_items")`；`None` ⇒ 退化。`p(d0, d1, department_id=None) -> list` |
| 回傳 | 已收款品項落在 `[d0, d1]` 的逐筆明細（欄位同 `collect_income_items` 的 docstring：quoteNo、customer、amount、netAmount、receivedAt…） |
| 對方不在時 | M08：收入清單為空，回應附 `incomeNotice`＝`RECEIVABLES_MISSING`（「應收應付模組未安裝：收款與銷項發票資料不提供…」），PDF 的空表說明換成這一句——**不是**「這個月沒有收款」；L1 殼回 `[]` |
| 契約版本 | 1（2026-09-26） |
| 守門 | 提供方 `backend/modules/arap/tests/test_receivables_providers.py`（登記＋正對照）；取用方 `backend/tests/platform/test_receivables_absent.py`（M05 不在：M08 incomeNotice、稅務匯出 404、T100 notice）；殼 `backend/tests/platform/test_receivables_shim.py` |

---

## IP-99　`receivables.tax_invoices`：銷項發票清單（M05 → M08 稅務匯出、M06 T100 收款事件）

同 IP-98 的沿革。**編號暫定（99），列車定號。**

| 欄位 | 內容 |
|---|---|
| 提供方 | M05 應收應付：`modules/arap/receivables.py::collect_tax_invoices` |
| 使用方 | M08 `modules/analytics/api/reports.py::tax_export_excel`（`/api/reports/tax-export`）；M06 `modules/accounting/api/accounting_export.py::_collect_t100_events`（收款事件）；L1 殼 `helpers/receivables.py::collect_tax_invoices`（淘汰中） |
| 形式 | provider，單一提供者 |
| 語法 | 提供：`ModuleSpec(providers={("receivables.tax_invoices", "arap"): receivables.collect_tax_invoices})`<br>取用：`p = registry.single_provider("receivables.tax_invoices")`；`p(year=None, month=None) -> list` |
| 回傳 | 已填發票號碼的收款品項（quoteNo、invoiceNo、date、invoiceDate、未稅／稅額／含稅…） |
| 對方不在時 | M08 稅務匯出：404＋`RECEIVABLES_MISSING`（沒有資料來源，不回空的 Excel 假裝沒有發票）；M06 T100：收款事件略過，預覽 `notice` 列出 `T100_RECEIVABLES_MISSING`（「應收應付模組未安裝：T100 匯出不含收款事件（銷項）」），與 IP-14 的缺口並列；L1 殼 404 |
| 契約版本 | 1（2026-09-26） |
| 守門 | 同 IP-98 |

---

## IP-16　`bonus.module_status`：獎金分潤入口該不該出現（M07 → L1 system）

對應 DEPENDENCY-MAP #27（M07 搬遷前置，2026-09-26）。原本 L1 `routers/system.py::get_bonus_module_status` 直接 import M07 的 `helpers.bonus.bonus_module_on`。編號為暫定（同時期多條線暫用 IP-10～15），由列車依合回順序定號。

| 欄位 | 內容 |
|---|---|
| 提供方 | M07 薪資獎金：`modules/payroll/bonus.py::bonus_module_on`（`ModuleSpec.providers` 宣告；模組沒載入就沒有登記） |
| 使用方 | L1 `routers/system.py::get_bonus_module_status`（`GET /api/system/bonus-module-status`；側欄、`bonus.html`、案件結案頁都問它） |
| 形式 | provider，單一提供者 |
| 語法 | 提供：`ModuleSpec(providers={("bonus.module_status", "payroll"): bonus.bonus_module_on})`<br>取用：`fn = registry.single_provider("bonus.module_status")`；`None` ⇒ 退化。`fn() -> bool` |
| 回傳 | 開著沒（`BONUS_MODULE_ENABLED`：`"0"` 關、預設開） |
| 對方不在時 | 200、`{"enabled": false, "notice": BONUS_MODULE_ABSENT}`（「薪資獎金模組未安裝：獎金分潤不提供」）⇒ 入口隱藏、頁面顯示暫停，與模組沒載入同一個結果。不丟例外 |
| 契約版本 | 1（2026-09-26） |
| 守門 | `backend/tests/platform/test_bonus_module_status_connector.py`：①正對照（跟著開關）②**反向控制**：拿掉提供者 ⇒ 200、關、notice ③system 不再 import helpers.bonus |

---

## U4 撥付時的扣繳與補充保費：使用 IP-7（L1 法規參數服務，R1）

不是新的串接點（M07 → L1 是合法相依，直接 `from helpers import legal_params as lp`）；寫在這裡，是因為它決定了「參數讀不到時」獎金撥付的行為。IP-7 的六項見 R1 的條目，以下是 M07 這一側的使用契約。

| 欄位 | 內容 |
|---|---|
| 提供方 | L1 `helpers/legal_params.py`（R1，IP-7） |
| 使用方 | M07 `modules/payroll/bonus_deductions.py::legal_params_for` → `deductions_for_award`：`POST /api/bonus/cases/{單號}/mark-paid`（撥付）、`GET /api/bonus/cases/{單號}`（待發放試算；已發放顯示快照）；頁面 `pages/bonus.html`「扣繳與補充保費」、`pages/cashier.html` 標記已發放對話框 |
| 形式 | L1 函式直接呼叫（非 provider） |
| 語法 | `params_from_legal_version(lp.rules_for_date(lp.load_versions(), 撥付日))` |
| 回傳 | 讀一版的 `version`、`resident["50"].tax_rate`／`tax_threshold`（非每月給付薪資扣繳 5%、起扣標準）、`nhi.rate`、`nhi.max_single_payment`、`nhi.bonus_insured_multiple`（獎金超過投保金額的倍數；主持裁示由 R 在合回前加入並列為必填）。轉成 `bonus_deductions.PARAM_KEYS` 五個鍵；計算結果連同 **`version` 與參數快照**存進 `mark_paid` 那一筆編寫紀錄（長期記憶、不可改刪），已發放的單一律顯示快照，不再依現行參數重算 |
| 讀不到時 | **拒絕撥付**：沒有適用版本（`lp.NoApplicableRules`）、欄位不齊（`DeductionParamsError`，例如缺倍數）⇒ `mark-paid` 回 409「無法計算扣繳與補充保費：<原因>；未標記已發放。」，狀態不變；明細的 `deductionNotice` 同一句，兩頁都顯示、按鈕照常可按但後端會擋。名單上有人沒有投保金額 ⇒ 409 列出名字。**不以 0 或預設值代替**（主持裁示 2026-09-25）。會計模組（M06）不在時照算、照發，只是沒有傳票（IP-2 的退化） |
| 契約版本 | 1（2026-09-25）；依 IP-7 的版本結構 |
| 守門 | `backend/modules/payroll/tests/test_bonus_payout_connectors.py`：純函式邊界（起扣 90,500／90,501、同一人跨類別先合併、4 倍門檻跨越與已超過、單次上限、四捨五入、缺投保金額≠0、參數缺欄位不猜）、撥付拒絕（缺投保金額、沒有適用版本）、撥付入傳票（借 應付＝貸 實發＋代扣稅款＋代收補充保費）、MOTRIX 以外累計計入門檻、版本與參數快照存在單據上、會計模組不在時照算照發。突變 14 種皆轉紅 |

**投保金額與全年累計**存在 `system_settings["payroll_insurance_profiles"]`＝`{username: {insuredAmount, ytdExternal: {年: 金額}}}`；
全年累計＝該年 MOTRIX 內已發放的獎金（依發放日）＋ `ytdExternal`（其他管道已發的）。端點 `GET /api/bonus/insurance`、`PUT /api/bonus/insurance/{username}`（最高管理者）；頁面在獎金頁「投保金額與全年累計」。
不新增資料表：模組 migration 執行器尚未實作（MODULE-GUIDE §4），V9 基準 v116 凍結。
⚠ 投保金額屬薪資等級資訊，端點只給最高管理者；而 `system_settings` 會進一般每日 JSON——資料分類（MODULE-GUIDE §3.2 是否列 F2）待 C 判定，見 RUN-PLAN §6 本項回報。

## IP-10　`approval.queue_items`：「待我簽核」佇列的其他來源（任何模組 → M01 佇列；首個提供方：L1 自訂模組引擎）

對應 CUSTOMIZATION-SPEC §3.7（P8）、主持 P8 前端缺口 #3（2026-09-26，C）。原本 `routers/quotations.py::get_approval_queue` 逐一寫死各單據表；自訂模組的單據是資料、表是共用的 `custom_records`，不能再寫死一種。

| 欄位 | 內容 |
|---|---|
| 提供方 | L1 `helpers/custom_modules.py::queue_items`（簽核中的自訂模組單據） |
| 使用方 | M01 `routers/quotations.py` 的 `GET /api/approval-queue`（列表）與 `GET /api/approval-queue/count`（角標），經 `_queue_provider_items(conn)` |
| 形式 | provider，多個提供者（`core.registry.providers()`；以名稱排序依序取用） |
| 語法 | 提供：`_registry.provide("approval.queue_items", "custom_modules", queue_items)`<br>取用：`for name, fn in sorted(registry.providers("approval.queue_items").items()): items.extend(fn(conn))` |
| 回傳 | 項目清單，形狀同佇列的其他類型：`type`（自訂模組＝`custom_record`）、`quoteNo`（單號）、`requestedBy`／`requestedByDisplay`／`requestedAt`、`tiers`／`currentTier`／`tierCount`／`currentApprovers`；自訂模組另帶 `moduleKey`、`moduleName`、`statusLabel`。**只列還沒簽完的**；誰看得到由使用方的 `_queue_visible_to` 決定（與其他類型同一條規則） |
| 對方不在時 | 沒有提供者 ⇒ 佇列只列內建單據（跟 P8 之前一樣）；某個提供者丟例外 ⇒ 那一類不列、記 exception，佇列與角標照常 |
| 契約版本 | 1（2026-09-26，CORE_VERSION 1.10 同一批）。欄位只准加 |
| 守門 | `backend/tests/test_custom_modules_engine_2026_09_25.py`：①正對照：送審後出現在簽核人的佇列與角標、簽完就消失 ②非簽核人（一般使用者）看不到別人的 ③反向控制：提供者丟例外 ⇒ 佇列 200、內建單據照列 |

---

## IP-11　`daily.check`：模組的每日 08:00 檢查（各模組 → L1 執行器）

M12 每日任務搬遷前置（PLAYBOOK §B 步驟 3）。原本 `routers/daily_tasks.py::schedule_overdue_check` 一支排程同時跑九種檢查（每日任務逾期、區間到期、案件階段到期、案件專案期間、保固、簽核催辦、憑證、備份新鮮度、磁碟／暫存）⇒ **停用每日任務會連帶停掉備份與磁碟告警**。改成：系統健康檢查下沉 L1（`helpers/system_checks.py`，永遠執行），各模組的檢查以本串接點登記給 L1 執行器（`helpers/daily_checks.py`）。

| 欄位 | 內容 |
|---|---|
| 提供方 | M12 `modules/daily_tasks/api.py::run_daily_checks`（名稱 `daily_tasks`：逾期、區間到期；啟動補跑用 `dt_overdue_last_check` 逐日補）；M01 `helpers/case_deadlines.py::run_daily_checks`（名稱 `case_deadlines`：案件階段到期、案件專案期間、保固到期） |
| 使用方 | L1 `helpers/daily_checks.py::run_module_checks`（由 `schedule_daily_checks()` 在啟動與每天 08:00 呼叫；main.py 啟動） |
| 形式 | provider，**多提供者、以名稱區分**（依名稱排序逐一呼叫；某一支丟例外只記錄，不影響其他支） |
| 語法 | 提供：`registry.provide("daily.check", "<名稱>", fn)`<br>取用：`for name, fn in sorted(registry.providers("daily.check").items()): fn(mode)` |
| 回傳 | 無。`fn(mode)`：`mode`＝`"startup"`（啟動補跑；要回溯幾天由模組自己決定）或 `"daily"`（每天 08:00） |
| 對方不在時 | 少那一類檢查，其餘照常；**系統健康檢查（憑證、備份、磁碟、暫存、簽核催辦、請求紀錄清理）不依賴任何 L2 模組，一律執行** |
| 契約版本 | 1（2026-09-26） |
| 守門 | `backend/tests/platform/test_daily_checks_connector.py`：①兩個提供者都已登記 ②**反向控制**：拿掉所有 `daily.check` 提供者 ⇒ 系統檢查兩種模式都照跑 ③一支提供者丟例外不影響其他支與系統檢查 ④逐日補跑行為照舊；`tests/test_backup_freshness_disk_2026_09_14.py::test_checks_are_wired_into_daily_schedule`（改為行為題）；登記表一致性由 `test_integration_points_registered.py` 守 |

---

## IP-12　`case.access`：案件的逐案權限與摘要（M01 → M10）

M10 網路規劃搬遷前置（PLAYBOOK §B 步驟 3）。原本 `routers/network_plans.py` 經 `helpers` 套件 import M01 的 `guard_case_access`，並直接讀 `quotations` 取客戶／專案名稱（l2_import_baseline「M10 router:network_plans -> M01 helper:quotations」）。

| 欄位 | 內容 |
|---|---|
| 提供方 | M01 `helpers/quotations.py::_CaseAccess`（`guard`／`summary`） |
| 使用方 | M10 `modules/netplan/api.py`：`GET /api/quotations/{quote_no}/network-plan`（`guard`）、`POST /api/network-plans` 綁定案件時（`summary`） |
| 形式 | provider，單一提供者（M01 尚未搬進 `modules/`，以 `registry.provide()` 在匯入時登記） |
| 語法 | 提供：`registry.provide("case.access", "case", _CaseAccess)`<br>取用：`ca = registry.single_provider("case.access")`；`None` ⇒ 退化。`ca.guard(conn, quote_no, user, allow_module=…)`；`ca.summary(conn, quote_no)` |
| 回傳 | `guard`：同 `guard_case_access`——案件不存在 404、無權限 403（擋下時關連線），通過回單列。`summary`：`{customer, project}`；案件不存在 ⇒ `None` |
| 對方不在時 | 規劃書照常建立、編輯、匯出；**不能綁定案件**：建立時帶案件單號 ⇒ 400「案件模組未安裝：規劃書無法綁定案件（不填案件單號即可建立獨立的規劃書）」；依案件查詢 ⇒ 404「案件模組未安裝：無法依案件查詢網路架構規劃書」 |
| 契約版本 | 1（2026-09-26） |
| 守門 | `backend/modules/netplan/tests/test_netplan_case_access.py`：①提供者已登記 ②正對照：綁定案件時帶出客戶名、依案件查詢有逐案權限（外人 403）③**反向控制**：拿掉提供者 ⇒ 不綁案件的建立照常、綁案件 400、依案件查詢 404，訊息明說；逐案守門的歸類由 `test_case_read_scope.py` 守 |

**L1 案件存取守門也以本串接點為「M01 在不在」的訊號**（主持裁示 2026-09-26，只留一個訊號；原本 C 另立的 `case.present` 已刪）：`helpers.case_access.case_module_present()` ＝ 有沒有 `case.access` 提供者；沒有 ⇒ `guard_case_access` 404、`case_access_allowed` False，表與資料在、超級管理員也一樣（稽核 D CA-M1）。守門 `tests/platform/test_case_access_l1.py`：拿掉 `case.access` ⇒ L1 守門 404，且取用方（網路規劃書）明說「案件模組未安裝」——兩條路結果一致。

---

## IP-13　`crm.quote_deleted`：報價單刪除時解除業務開發案件的轉建連結（M02 → M01）

對應 DEPENDENCY-MAP §4 `dev_cases`（M02 搬遷，2026-09-26）。原本 `routers/quotations.py` 刪報價單時直寫 M02 的 `dev_cases`。編號：第五班列車定號 IP-13（C 分支暫用 IP-11；origin 已用到 IP-12 `case.access`）。

| 欄位 | 內容 |
|---|---|
| 提供方 | M02 業務開發：`modules/crm/api.py::unlink_deleted_quote`（`ModuleSpec.providers`，模組未載入即不登記） |
| 使用方 | M01 `routers/quotations.py::delete_quotation`（只刪草稿） |
| 形式 | provider，單一提供者（`core.registry`）；要與刪報價單同一筆交易 ⇒ 不用事件 |
| 語法 | 提供：`ModuleSpec(providers={("crm.quote_deleted", "crm"): api.unlink_deleted_quote})`<br>取用：`unlink = registry.single_provider("crm.quote_deleted")`；`None` ⇒ 退化。`unlink(conn, quote_no) -> [{"id", "case_name"}]` |
| 回傳 | 被解除連結的案件（`converted_quote_no` 清空、狀態退回「洽談中」）。**在呼叫端的連線上寫、不 commit**；稽核 `dev_case.unlink_deleted_quote` 由 M01 以操作者身分寫 |
| 對方不在時 | 報價單**照刪**；案件不動（M02 不在時畫面本來就看不到這些案件）；回應 `notice`＝`routers/quotations.QUOTE_DELETED_CRM_ABSENT`（「若有業務開發案件轉建自這張報價單，它們的連結沒有自動解除」）；記 WARNING。不丟例外 |
| 契約版本 | 1（2026-09-26） |
| 守門 | 提供方（隨模組搬走）`backend/modules/crm/tests/test_crm_quote_deleted_provider.py`：①M02 已登記 ②**正對照**：刪草稿 ⇒ 連到它的案件解除、別張單的案件不動、稽核一筆；取用方（M02 不在也成立）`backend/tests/platform/test_crm_quote_deleted_connector.py`：③**反向控制**：拿掉提供者 ⇒ 200、`notice` 明說、案件不動、WARNING ④產品碼除了 M02 與凍結 migration 沒有寫 `dev_cases`／`dev_logs` 的 SQL；`table_write_exceptions.json` 對應 debt 已刪；畫面：`test_e2e_quote_delete_crm_absent_notice_2026_09_26`（M02 不在 ⇒ 報價清單顯示 notice）、`modules/crm/tests/test_e2e_crm_quote_delete_no_notice_2026_09_26`（在 ⇒ 只有「報價單已刪除」，隨模組搬走） |

**尚未處理**：`dev_cases`／`dev_logs` 仍被 L1（全站搜尋、未讀標記、行事曆標題、封存匯出、稽核目標檢查）與 M01（報價單動態）、M08（儀表板）**直接讀**。M02 不在時表仍在（凍結 migration 建立），讀取不會壞，可見性經 `row_access`（未登錄 ⇒ fail closed，連 admin 也看不到）；要切斷須由 M02 提供讀取連接器，另開題（DEPENDENCY-MAP §3 #2／#5／#6）。

---

## IP-18　`shipping.list_for_case`：案件整包的出貨單段（M03 → M01）

對應 DEPENDENCY-MAP §3 #22、l2_import_baseline `M01 router:quotations -> M03 router:shipping_notes`（M03 搬遷前置，2026-09-26）。原本 M01 案件整包（`/api/quotations/{no}/case-bundle`）直接 import `routers.shipping_notes.list_shipping_notes`。寫法同 IP-15（C 的 `dispatch.list_for_case`）。編號為暫定，由列車依合回順序定號。

| 欄位 | 內容 |
|---|---|
| 提供方 | M03 採購・庫存・出貨：`modules/supply/api/shipping_notes.py::list_shipping_notes_for_case`（`list_shipping_notes` 的包裝） |
| 使用方 | M01 `routers/quotations.py::case_bundle` 的 `parts.shippingNotes` |
| 形式 | provider，單一提供者（`core.registry`；`ModuleSpec.providers` 宣告，模組未載入即不登記） |
| 語法 | 提供：`ModuleSpec(providers={("shipping.list_for_case", "supply"): shipping_notes.list_shipping_notes_for_case})`<br>取用：`fn = registry.single_provider("shipping.list_for_case")`；`None` ⇒ 退化。`fn(quote_no, authorization) -> list`（同一份授權，權限判斷與單獨打 `/api/shipping-notes?quote_no=` 逐字相同） |
| 回傳 | 出貨單列；權限不足 ⇒ `HTTPException(403)`，整包那一段照舊回 `{"ok": false, "status": 403}` |
| 對方不在時 | 整包照常回；`parts.shippingNotes`＝`{"ok": false, "status": 404, "detail": SHIPPING_UNAVAILABLE}`（「採購・庫存・出貨模組未安裝：沒有出貨單資料」）。案件頁出貨單分頁顯示這一句（不顯示「尚未建立任何出貨單」），「新增出貨單」鈕不顯示 |
| 契約版本 | 1（2026-09-26） |
| 守門 | `backend/tests/platform/test_supply_connectors.py`（M03 不在的一側）；M03 在的一側隨模組 |

---

## IP-22　`voucher.by_case`：案件整包的傳票段（M06 → M01）

對應 M06-PLAN §1-C #7、l2_import_baseline `M01 router:quotations -> M06 router:vouchers`（M06 搬遷前置，2026-09-26）。原本 M01 案件整包（`/api/quotations/{no}/case-bundle`）直接 import `routers.vouchers.vouchers_by_case`。寫法同 IP-15／IP-18。編號為暫定，由列車依合回順序定號。

| 欄位 | 內容 |
|---|---|
| 提供方 | M06 會計：`modules/accounting/api/vouchers.py::vouchers_by_case`（傳票 by-case 端點的函式；ModuleSpec.providers 宣告） |
| 使用方 | M01 `routers/quotations.py::case_bundle` 的 `parts.vouchers` |
| 形式 | provider，單一提供者（`core.registry`） |
| 語法 | 取用：`fn = registry.single_provider("voucher.by_case")`；`None` ⇒ 退化。`fn(quote_no, authorization=…) -> {"vouchers": [...]}`（同一份授權，權限判斷與單獨打端點逐字相同） |
| 回傳 | `{"vouchers": [{id, voucher_no, voucher_date, status, summary}]}`（作廢單不列）；權限不足 ⇒ `HTTPException(403)`，整包那一段照舊回 `{"ok": false, "status": 403}` |
| 對方不在時 | 整包照常回；`parts.vouchers`＝`{"ok": false, "status": 404, "detail": VOUCHERS_UNAVAILABLE}`（「會計傳票模組未安裝：沒有傳票資料」）。案件頁的傳票連結不列（M06 不在時產品沒有傳票，沒有列才是對的） |
| 契約版本 | 1（2026-09-26） |
| 守門 | `backend/tests/platform/test_accounting_connectors.py`（M06 不在的一側） |

---

## IP-19　`stock.serial`：案件設備序號認領／釋放庫存（M03 → M01）

對應 DEPENDENCY-MAP §4 `stock_items`（M01 `routers/quotations.py::_sync_device_stock` 直寫）、`table_write_exceptions` 的 debt（已刪）。M03 搬遷前置，2026-09-26。編號為暫定。

| 欄位 | 內容 |
|---|---|
| 提供方 | M03 採購・庫存・出貨：`modules/supply/api/inventory.py::_StockSerials`（`claim`／`release`） |
| 使用方 | M01 `routers/quotations.py::_sync_device_stock`（案件設備登載 `devices[]` 的序號比對；即時存檔與半解鎖審核套用兩條路徑） |
| 形式 | provider，單一提供者（`core.registry`；`ModuleSpec.providers` 宣告，模組未載入即不登記） |
| 語法 | 提供：`ModuleSpec(providers={("stock.serial", "supply"): inventory._StockSerials})`<br>取用：`s = registry.single_provider("stock.serial")`；`None` ⇒ 退化。`s.claim(conn, sn, quote_no=…, device_id=…, actor=…, now=…) -> None｜狀態`；`s.release(conn, sn, device_id=…, now=…)` |
| 回傳 | `claim`：序號不在庫存系統 ⇒ `None`（不追蹤、不擋存檔）；在庫 ⇒ 標成 installed、回 `"in_stock"`；其他狀態 ⇒ 不動、回該狀態（M01 列為 `stockConflicts`）。**在呼叫端的連線上寫、不 commit**：與案件資料同一筆交易 |
| 對方不在時 | 案件存檔照常；序號不同步庫存；有序號變動時回應帶 `stockNotice`＝「設備序號未同步庫存：採購・庫存・出貨模組未安裝」，案件頁存檔狀態列顯示「已儲存；…」；沒有序號變動就不帶 |
| 契約版本 | 1（2026-09-26） |
| 守門 | `backend/tests/platform/test_supply_connectors.py`（M03 不在的一側）；M03 在的一側隨模組 |

---

## IP-20　`inventory.paid_batches`：期間內已付款的進貨批次（M03 → M06）

主持裁示 2026-09-26 11:16（M06 步驟表 §1-B #2，C 提出）。原本 `modules/accounting/api/accounting_export.py::_collect_paid_stock_batches` 直讀 M03 的 `stock_batches`、`stock_items`（並 JOIN L1 `parts`）。編號為暫定，由列車定號。

| 欄位 | 內容 |
|---|---|
| 提供方 | M03 採購・庫存・出貨：`modules/supply/api/inventory.py::paid_batches` |
| 使用方 | M06 `modules/accounting/api/accounting_export.py::_collect_paid_stock_batches`（T100 付款傳票：借 料件設備成本／貸 銀行存款） |
| 形式 | provider，單一提供者（`core.registry`；`ModuleSpec.providers` 宣告，模組未載入即不登記） |
| 語法 | 提供：`ModuleSpec(providers={("inventory.paid_batches", "supply"): inventory.paid_batches})`<br>取用：`fn = registry.single_provider("inventory.paid_batches")`；`None` ⇒ 退化。`fn(start, end) -> list[dict]` |
| 回傳 | 每批一列：`batch_no`、`part_no`、`supplier_name`、`invoice_no`、`paid_at`、`paid_bank_account_name`、`paid_bank_account_code`、`category`（料件分類，無則空字串）、`total_cost`（即時由 `stock_items.cost` 加總）；依 `paid_at` 排序。唯讀 |
| 對方不在時 | T100 匯出照常，不含料件進貨的付款傳票；預覽回應 `notice` 含「採購・庫存・出貨模組未安裝：本次匯出不含料件設備進貨的付款傳票」（與 IP-14 的說明以「；」並列），出納頁的 T100 區塊顯示 |
| 契約版本 | 1（2026-09-26） |
| 守門 | `backend/tests/platform/test_supply_connectors.py`（M03 不在的一側）；M03 在的一側 `backend/modules/supply/tests/test_stock_batch_payment.py`（批次流進 T100 匯出並可確認） |

---

## IP-21　`attachments.for_document`：單據的已上傳檔案（M01／M04／M05 → M06 傳票帶入附件）

主持裁示 M06-b（RUN-PLAN §5 D1 段），步驟表 `docs/platform/plans/ATTACHMENTS-PLAN.md`。原本 M06 `modules/accounting/voucher_attachments.py` 直讀九類來源的四張別組表（quotations、case_updates、case_extra_expenses、invoice_vouchers、contractor_dispatches）。編號為暫定，由列車定號。

| 欄位 | 內容 |
|---|---|
| 提供方 | M01 案件：`helpers/case_attachments.py::_CaseAttachments`（6 類；M01 未搬 ⇒ `registry.provide()`，M01 搬遷時改 ModuleSpec，同 CA-O3）；M04 外包工班：`modules/subcontract/attachments.py::_SubcontractAttachments`（2 類，ModuleSpec）；M05 應收應付：`modules/arap/api/invoice_vouchers.py::_InvoiceVoucherAttachments`（1 類，ModuleSpec） |
| 使用方 | M06 `modules/accounting/voucher_attachments.py`（`source_files`、`case_attachments`、`resolve_picks`、`line_source_files`）；`modules/accounting/api/vouchers.py` 的 `line-source-files` 端點回 `unavailable` |
| 形式 | provider，**多提供者、以模組 key 區分**；每個提供者宣告 `SOURCE_TYPES`（兩兩不重疊、聯集 ⊆ M06 白名單） |
| 語法 | 提供：`registry.provide("attachments.for_document", "<key>", Obj)` 或 `ModuleSpec(providers={("attachments.for_document", "<key>"): Obj})`；`Obj.SOURCE_TYPES`、`Obj.doc_nos_for_case(conn, source_type, quote_no, user) -> list[str]`、`Obj.files(conn, source_type, doc_no, user) -> list[dict]`〔更正（稽核 D AT-M1，主持裁示 (b)，2026-09-26）：原契約沒有 `user`，提供者無從依原單據權限過濾 ⇒ 加上（未發版，契約版本仍為 1）〕 |
| 回傳 | `files`：`save_document_files` 的 metadata 陣列；單據不存在 ⇒ `[]`；資料壞掉或編號不全 ⇒ raise L1 `helpers.uploads.AttachmentSourceError`（取用方原樣 400）；**使用者看不到原單據所屬案件 ⇒ raise `AttachmentNotVisible`**（判準 L1 `helpers.case_access.case_documents_readable`，同各單據清單；取用方：列清單不列、帶入／預覽 403）。〔更正（稽核 D AT-M1b，2026-09-26）：判準**不共用**——每一類用那張原單據**自己端點的同一支判斷函式**，附件的可見範圍不可以比原單據寬：extra_expense ⇒ `case_owner_readable`（額外支出各端點不放行 case_manage）、invoice_voucher ⇒ `routers/invoice_vouchers.py::_voucher_readable`（案件層＋金額層，含本單簽核人例外）、其餘 M01 類 ⇒ `case_documents_readable`〔再更正（稽核 D AT-M1c，2026-09-26）：存在報價單上的四類（quotation_signed／payment_item／material／material_invoice）⇒ `case_page_readable`（案件頁 `get_quotation` 同一支：放行 cashier、不放行 case_manage）；case_update 維持 `case_documents_readable`（案件動態端點）〕、M04 派工單 ⇒ `case_documents_readable`（比派工端點嚴，安全的方向，AT-O2）；`doc_nos_for_case` 可逐張過濾（讀不到的不列），整張案件讀不到時 raise `AttachmentNotVisible`〕〔再更正（主持裁示 2026-09-26：因權限沒列出要明說）：看不到（全部或部分）⇒ `raise AttachmentNotVisible(visible=[看得到的], hidden=沒列出的附件個數)`，不可以只回看得到的；取用方把個數加總進回應的 `hidden`（`[{category: "hidden:<type>", count, reason}]`，**只准這三個鍵**：不帶單號、檔名、路徑、金額——明說本身不可以外洩），傳票頁與 `unavailable` 並列顯示〕。唯讀、在呼叫端連線上 |
| 對方不在時 | 那幾類不列；`line-source-files?source_type=case` 回 `unavailable=[{category, reason}]`，傳票頁已上傳檔案欄顯示「XX模組未安裝：……的附件沒有列出」；帶入或列該類檔案 ⇒ 400「XX模組未安裝，無法帶入……附件」。已帶入的附件不受影響（已複製進傳票） |
| 契約版本 | 1（2026-09-26） |
| 守門 | `backend/tests/platform/test_attachments_providers.py`（取用方只讀自己的表、覆蓋與不重疊、缺席明說、M01／M05 提供者壞 JSON）；`backend/modules/subcontract/tests/test_subcontract_attachments_provider.py`；e2e `backend/tests/test_e2e_voucher_attachments_absent_source_2026_09_26.py` |
