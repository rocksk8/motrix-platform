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
`routers/vouchers.py`（M06）直接 import `routers.vendor_contractors._dispatch_row`（M04 私有函式）；
`routers/reports.py`（M08）import 了但沒有呼叫，已刪除。

| 欄位 | 內容 |
|---|---|
| 提供方 | M04 外包工班：`routers/vendor_contractors.py::_dispatch_row` |
| 使用方 | M01 `helpers/recognition.py::dispatch_entries`（應計派工成本，營運報表支出用）；M06 `routers/vouchers.py::_case_expense_sources`（傳票摘要來源的承攬商派工） |
| 形式 | provider，單一提供者（`core.registry`）。M04 尚未搬進 `modules/`，暫以 `registry.provide()` 在匯入時登記；搬遷後改寫進 `ModuleSpec.providers`，這一行刪除 |
| 語法 | 提供：`_registry.provide("dispatch.row", "subcontract", _dispatch_row)`<br>取用：`fn = registry.single_provider("dispatch.row")`；`None` ⇒ 退化。兩個以上提供者 ⇒ `RuntimeError`（兩份實作在搶，不隨便挑） |
| 回傳 | `fn(row: sqlite3.Row) -> dict`。`row` 是 `contractor_dispatches` 一列（可 JOIN `vendor_contractors.name AS vendor_name`）。使用方讀的欄位：`id`、`quoteNo`、`vendorName`、`scope`、`items`、`personnel`、`totalAmount`、`personnelTotal`、`grandTotal`（含稅承攬商費用＋外包人員）、`invoiceNo`、`acceptedAt` |
| 對方不在時 | recognition：應計派工回 `[]` 並記 WARNING ⇒ 營運報表少了承攬商這一類支出，其餘照常。現金口徑讀匯款申請快照，不受影響。<br>vouchers：案件支出來源只剩額外支出，不列承攬商派工。<br>皆不丟例外。<br>**明說（稽核 X-1，2026-09-25）**：`_collect_expenses` 與 `/api/reports/expenses-monthly`（含待補登 `recognitionFlags`）回 `unavailable: [{"category": "contractor", "reason": "外包工班模組未安裝：承攬商派工的應計成本沒有列入（不是 0 筆）"}]`（`helpers.recognition.dispatch_unavailable(basis)`；現金口徑為 `[]`），報表頁顯示紅框 `data-testid="expense-unavailable"`；`/api/vouchers/summary-sources` 回 `unavailable: [{"category": "contractor_dispatch", …}]`，傳票頁帶入面板顯示 `data-testid="source-unavailable"` |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/tests/platform/test_dispatch_connector.py`：①提供者存在且回傳含全部使用欄位 ②registry 重複／多提供者規則 ③**反向控制**：同一批資料先確認派工那一類非空，拿掉提供者後三處照常回結果、只少派工 ④全 backend 不再有人 `import _dispatch_row`。突變驗證：拿掉退化判斷、拿掉 M04 登記、vouchers 不看提供者，三者皆轉紅。⑤（X-1）`test_absence_is_said_in_report_flags_and_voucher_sources`：提供者在 ⇒ `unavailable` 空（正對照）；拿掉 ⇒ 報表、待補登、傳票來源三處都有，現金口徑沒有；`test_pages_render_the_absence` 頁面綁定。突變 6 種皆轉紅 |

**尚未處理（不在 A6 範圍）**：`routers/reports.py::_live_dispatch_totals_by_quote` 自己又算了一次
grandTotal（直接讀 `contractor_dispatches`，沒有經過 `_dispatch_row`）。這是同一算法的第二份實作，
也是 M08 直接讀 M04 的表；應改用 IP-1，另開題。
（2026-09-25 主持裁示：等 M08 搬遷時再處理。）

---

## IP-2　`voucher.draft`＋`voucher.account_check`：建立傳票草稿（M06 → M07）

對應 DEPENDENCY-MAP §3 #19（ROADMAP A7）。原本 `helpers/bonus_vouchers.py`（M07）直接 import
`routers.vouchers.insert_draft_voucher／_line_sources／_amount_lines`、`routers.accounting_export.validate_account_code`、
`helpers.voucher.classify_category`（皆 M06）。

| 欄位 | 內容 |
|---|---|
| 提供方 | M06 會計：`routers/vouchers.py::_provide_voucher_draft`、`routers/accounting_export.py::validate_account_code` |
| 使用方 | M07 `helpers/bonus_vouchers.py`（進入待發放 ⇒ 轉帳草稿；標記已發放 ⇒ 支出草稿；科目設定頁的驗證）、`routers/bonus.py`（標記已發放時驗出納選的銀行科目） |
| 形式 | provider，單一提供者（`core.registry`；M06 尚未搬進 `modules/`，以 `registry.provide()` 在匯入時登記） |
| 語法 | 提供：`_registry.provide("voucher.draft", "accounting", _provide_voucher_draft)`、`_registry.provide("voucher.account_check", "accounting", validate_account_code)`<br>取用：`registry.single_provider("voucher.draft")(conn, voucher_date=…, summary=…, lines=[{account_code, summary, debit, credit}], created_by=…, now=…)`；`registry.single_provider("voucher.account_check")(conn, code)` |
| 回傳 | draft：`{"id": int, "voucher_no": str}`；在呼叫端的交易裡寫入 `vouchers_all`＋`voucher_lines`，**不 commit**（呼叫端的狀態與傳票連結一起成功、一起失敗）。分錄正規化與傳票類別由 M06 決定。<br>account_check：`(ok: bool, err: str)` |
| 對方不在時 | **獎金核准／標記已發放照常成立**，不產生傳票，而且明說：回傳 `notice`＝「未產生傳票：會計模組未安裝（獎金狀態照常更新；需要傳票請由會計手動開立）」（前端 `_withNotice` 顯示）。出納帶了銀行科目也不驗、不擋發放。科目設定：GET 的 `problems` 每一項為「會計模組未安裝，無法驗證科目」；PUT 回 400 並寫明原因，一個都不寫入（驗證不了就不存）。<br>**實體缺席（稽核 Y-2，2026-09-25）**：M07 的 `helpers/bonus_pdf.py` 組獎金分潤單預覽／PDF 要用 M06 的 `helpers.voucher`、`helpers.voucher_pdf`；已改成函式內延遲載入，M06 檔案不在包裡時 M07 照常載入，只有舊流程的預覽／PDF 端點回 503「會計模組未安裝：無法產生獎金分潤單預覽／PDF」。這仍是 M07 → M06 的相依（`l2_import_baseline` 兩筆），要清掉得把三支共用函式下沉 L1 |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/tests/platform/test_voucher_connectors.py`：①提供者存在、draft 真的寫出草稿與分錄且不 commit、account_check 對錯都對 ②**反向控制**：同一條流程有 M06 時產生兩張草稿（正對照），拿掉提供者後獎金照走、零張傳票、notice／voucherNotice／problems 都有明確提示 ③M07 不再 import M06 ④頁面綁定 `detail.voucherNotice`。突變驗證：不查 M06、默默略過（notice 空）、仍驗銀行、銀行清單不處理缺席，四者皆轉紅 |

**尚未處理（不在 A7 範圍）**：`helpers/bonus_vouchers.py::withdraw_accrual`（退回時作廢轉帳草稿）與
`linked_vouchers`（明細列出連結的傳票）仍直接讀寫 M06 的 `vouchers_all`。M06 不在時表仍在（凍結 migration），
行為不會壞，但屬 M07 直接寫 M06 的表（DEPENDENCY-MAP §4）；應由 M06 再公開「作廢草稿」「查傳票狀態」兩個連接器，另開題。
➡ 2026-09-25 已處理：見 IP-4。

---

## IP-3　`accounting.settings`：會計設定（付款銀行）（M06 → M07）

對應 DEPENDENCY-MAP §3 #18（ROADMAP A7）。原本 `routers/bonus.py:1885` 函式內 import `routers.accounting_export._t100_config`。

| 欄位 | 內容 |
|---|---|
| 提供方 | M06 會計：`routers/accounting_export.py::_provide_accounting_settings` |
| 使用方 | M07 `routers/bonus.py::_payout_bank_choices`（待發放時給出納選付款銀行） |
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
| 提供方 | M06 會計：`routers/vouchers.py::_provide_voucher_void_draft`、`_provide_voucher_status` |
| 使用方 | M07 `helpers/bonus_vouchers.py`：`withdraw_accrual`（獎金退回 ⇒ 作廢未送審的轉帳草稿）、`linked_vouchers`（明細列出連結的傳票）、`create_accrual`（殘留草稿防護） |
| 形式 | provider，單一提供者（同 IP-2） |
| 語法 | 提供：`_registry.provide("voucher.void_draft", "accounting", _provide_voucher_void_draft)`、`_registry.provide("voucher.status", "accounting", _provide_voucher_status)`<br>取用：`registry.single_provider("voucher.void_draft")(conn, voucher_id, voided_by=…, now=…, reason=…)`；`registry.single_provider("voucher.status")(conn, voucher_id)` |
| 回傳 | void_draft：`{"result": "voided"｜"not_draft"｜"gone", "voucher_no", "status"}`——只作廢「草稿」；已送審 ⇒ `not_draft` 不動；不存在或早已作廢 ⇒ `gone`。status：`{"id", "voucher_no", "status", "voided"}`，不存在 ⇒ `None`。兩者都在呼叫端的交易裡，**不 commit** |
| 對方不在時 | **退回照常**成立；不作廢、**保留連結**（之後查得到是哪一張），回傳 `notice`＝「未作廢傳票（#id）：會計模組未安裝；退回照常，請會計另行處理那一張傳票」。明細仍列出每一張連結的傳票，標 `unavailable` 與「會計模組未安裝，無法查詢狀態」，頁面不給連結（不讓傳票從畫面消失）。<br>**M06 回來後**：再次進入待發放時，若舊連結仍是未作廢的草稿 ⇒ 不另開、不覆蓋，notice 明說「上一張轉帳傳票草稿 … 尚未作廢」；舊連結已送審 ⇒ 照原行為另開新草稿 |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/tests/platform/test_voucher_status_connectors.py`：①void_draft 三種結果＋status 形狀＋不 commit ②**反向控制**：有 M06 時退回會作廢（正對照）；拿掉後不作廢、有提示、連結保留、M06 的表沒被動、明細標無法查詢 ③M06 回來：殘留草稿不另開不覆蓋；已送審的舊連結照常另開 ④M07 原始碼不再出現 `vouchers_all`、頁面有 unavailable 分支。突變 5 種皆轉紅（默默略過、傳票從明細消失、拿掉殘留防護、防護放太寬擋到已送審、M06 不在仍解除連結） |

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
| 提供方 | M05 `routers/invoice_vouchers.py`（`invoice_voucher`）、`routers/payment_requests.py`（`payment_request`）；M03 `routers/shipping_notes.py`（`shipping_note`）；M01 `routers/quotations.py`（`quotation`、`case_stage`） |
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
| 單據凍結 | 使用方存 `version` 與整份 `rules` 快照；修改舊單沿用快照，使用者明確選擇才重挑（勞報單的做法見 `routers/payslips.py::update_payslip`） |
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
| 提供方 | M07 薪資獎金：`helpers/bonus_payouts.py::_Payouts`（`pending`／`paid`） |
| 使用方 | M05 `routers/cashier.py`：`GET /api/cashier/bonus-queue`（出納頁「獎金待發放」子頁籤）、`_execution_history`（執行歷史「獎金分潤發放」區塊）、`GET /api/cashier/export`（Excel 第三張「獎金發放明細」）；頁面 `pages/cashier.html`、`js/cashier.js` |
| 形式 | provider，單一提供者（`core.registry`；M07 尚未搬進 `modules/`，以 `registry.provide()` 在匯入時登記） |
| 語法 | 提供：`registry.provide("bonus.payouts", "payroll", _Payouts)`<br>取用：`p = registry.single_provider("bonus.payouts")`；`None` ⇒ 退化。`p.pending(conn)`；`p.paid(conn, start, end)`（YYYY-MM-DD，含首尾，比發放日） |
| 回傳 | `pending`：`[{quoteNo, customer, project, total, people, approvedAt}]`（舊的在前）。`paid`：`[{quoteNo, customer, project, total, people, paidAt, paidBy, withholding, nhiPremium, net}]`；扣繳快照不存在（U4 接上前發放的）⇒ 後三者 **`None`（不是 0）**。只回案件合計與人數，**不回個人金額**（個人明細在獎金頁，C1 可見範圍） |
| 對方不在時 | `bonus-queue` 回 200 `{"available": false, "visible": true, "notice": "薪資獎金模組未安裝：出納頁不顯示獎金分潤", "items": []}`，頁面顯示那一句；執行歷史 `bonusPaid: []`＋`bonusNotice`；Excel 第三張只有那一句。待付款／待收款／匯出其餘照常。**可見範圍**：只有最高管理者與出納（cashier）看得到獎金；出納頁的財務（finance）`visible: false`、不顯示該子頁籤、Excel 沒有第三張 |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/tests/platform/test_bonus_payout_connectors.py`：`test_cashier_queue_mark_paid_is_the_same_action_and_history`（佇列→同一支 mark-paid→離開佇列、進執行歷史與 Excel；財務看不到）、`test_cashier_page_binds_bonus_mark_paid`（頁面綁定）、`test_reverse_without_payroll_cashier_still_works_and_says_so`（**反向控制**）。突變：M07 不在時默默略過、財務看得到獎金 ⇒ 皆轉紅 |

---

## IP-9　`expense.entries`：其他模組登記的支出（M07 → M08 報表）

對應 CORE-SPEC「使用者裁示」獎金分潤：財務報表——以**發放日**列為支出，進營運報表與月支出。

| 欄位 | 內容 |
|---|---|
| 提供方 | M07 薪資獎金：`helpers/bonus_payouts.py::_expense_entries`（名稱 `bonus`） |
| 使用方 | M08 `routers/reports.py::_collect_expenses`（⇒ `/api/reports/expenses-monthly`、`/api/reports/financial`（JSON／Excel／PDF）、每月營運報表信、首頁儀表板支出） |
| 形式 | provider，**多提供者、以名稱區分**（`registry.providers("expense.entries")`；依名稱排序逐一呼叫）。之後其他模組的支出（例：勞報單）可登記同一個名稱空間，報表不用改 |
| 語法 | 提供：`registry.provide("expense.entries", "bonus", _expense_entries)`<br>取用：`for name, fn in sorted(registry.providers("expense.entries").items()): fn(conn, d0, d1)` |
| 回傳 | `[{date, quoteNo, desc, amount, category}]`；`date`＝發放日（權責與現金兩種口徑相同），`category`＝`"獎金分潤"`。一案一筆，`desc`＝「獎金分潤（N 人）」，**不列個人**。報表把它併進「其他支出」（`details.other[].category` 區分；首頁 otherBreakdown 依 category 自動多一塊），部門篩選照 `quoteNo` 歸屬 |
| 對方不在時 | 沒有提供者 ⇒ 支出少了獎金這一類，其餘照常，不丟例外。**不另加提示**：M07 不在時獎金分潤這個功能不存在，沒有應列而未列的支出（⚠ 例外：M07 曾經安裝、之後被停用而資料還在 ⇒ 報表少列那些已發放的獎金。觀察項，見 RUN-PLAN §6 本項回報） |
| 契約版本 | 1（2026-09-25） |
| 守門 | 同上測試檔：`test_report_counts_bonus_on_paid_date`（待發放不算、發放後出現在發放月、月合計差額＝發放總額）、`test_reverse_without_payroll_report_still_works`（**反向控制**）。突變：報表不讀提供者 ⇒ 轉紅 |

**案件頁相關傳票（同一項裁示）**：不新增串接點。獎金產生的兩張傳票草稿，每一行都帶摘要來源 `source_type="case"`、`source_key=案件單號`（JV36），經 IP-2 `voucher.draft` 寫入；案件頁的 `GET /api/vouchers/by-case/{單號}` 本來就依這個來源找。IP-2 的 `lines` 因此多了兩個**選填**欄位（只加不改，契約版本不變）。守門：`test_case_page_related_vouchers_show_bonus_vouchers`；突變：拿掉來源 ⇒ 轉紅。⚠ 這次之前已產生的獎金傳票沒有來源、不回填（開發機測試資料）。

---

## IP-16　`bonus.module_status`：獎金分潤入口該不該出現（M07 → L1 system）

對應 DEPENDENCY-MAP #27（M07 搬遷前置，2026-09-26）。原本 L1 `routers/system.py::get_bonus_module_status` 直接 import M07 的 `helpers.bonus.bonus_module_on`。編號為暫定（同時期多條線暫用 IP-10～15），由列車依合回順序定號。

| 欄位 | 內容 |
|---|---|
| 提供方 | M07 薪資獎金：`helpers/bonus.py::bonus_module_on`（匯入時登記；搬進 `modules/` 後改寫進 `ModuleSpec.providers`） |
| 使用方 | L1 `routers/system.py::get_bonus_module_status`（`GET /api/system/bonus-module-status`；側欄、`bonus.html`、案件結案頁都問它） |
| 形式 | provider，單一提供者 |
| 語法 | 提供：`_registry.provide("bonus.module_status", "payroll", bonus_module_on)`<br>取用：`fn = registry.single_provider("bonus.module_status")`；`None` ⇒ 退化。`fn() -> bool` |
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
| 使用方 | M07 `helpers/bonus_deductions.py::legal_params_for` → `deductions_for_award`：`POST /api/bonus/cases/{單號}/mark-paid`（撥付）、`GET /api/bonus/cases/{單號}`（待發放試算；已發放顯示快照）；頁面 `pages/bonus.html`「扣繳與補充保費」、`pages/cashier.html` 標記已發放對話框 |
| 形式 | L1 函式直接呼叫（非 provider） |
| 語法 | `params_from_legal_version(lp.rules_for_date(lp.load_versions(), 撥付日))` |
| 回傳 | 讀一版的 `version`、`resident["50"].tax_rate`／`tax_threshold`（非每月給付薪資扣繳 5%、起扣標準）、`nhi.rate`、`nhi.max_single_payment`、`nhi.bonus_insured_multiple`（獎金超過投保金額的倍數；主持裁示由 R 在合回前加入並列為必填）。轉成 `bonus_deductions.PARAM_KEYS` 五個鍵；計算結果連同 **`version` 與參數快照**存進 `mark_paid` 那一筆編寫紀錄（長期記憶、不可改刪），已發放的單一律顯示快照，不再依現行參數重算 |
| 讀不到時 | **拒絕撥付**：沒有適用版本（`lp.NoApplicableRules`）、欄位不齊（`DeductionParamsError`，例如缺倍數）⇒ `mark-paid` 回 409「無法計算扣繳與補充保費：<原因>；未標記已發放。」，狀態不變；明細的 `deductionNotice` 同一句，兩頁都顯示、按鈕照常可按但後端會擋。名單上有人沒有投保金額 ⇒ 409 列出名字。**不以 0 或預設值代替**（主持裁示 2026-09-25）。會計模組（M06）不在時照算、照發，只是沒有傳票（IP-2 的退化） |
| 契約版本 | 1（2026-09-25）；依 IP-7 的版本結構 |
| 守門 | `backend/tests/platform/test_bonus_payout_connectors.py`：純函式邊界（起扣 90,500／90,501、同一人跨類別先合併、4 倍門檻跨越與已超過、單次上限、四捨五入、缺投保金額≠0、參數缺欄位不猜）、撥付拒絕（缺投保金額、沒有適用版本）、撥付入傳票（借 應付＝貸 實發＋代扣稅款＋代收補充保費）、MOTRIX 以外累計計入門檻、版本與參數快照存在單據上、會計模組不在時照算照發。突變 14 種皆轉紅 |

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
