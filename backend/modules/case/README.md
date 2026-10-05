# M01 案件（case）

報價單、案件管理（階段、執行進度、動態、額外支出、叫料、完工單、案件整包）、簽核佇列與簽核歷史、業務訂單（`/api/sales-orders`）。

## 內容

| 檔 | 說明 |
|---|---|
| `api/quotations.py` | `/api/quotations*`、`/api/approval-queue*`、`/api/approval-history`、`/api/case-batch`、`/api/case-changes`、`/api/next-quote-no`、`/api/sales-orders` |
| `api/case_action_items.py` | 案件待辦 |
| `api/case_extra_expenses.py` | 案件額外支出（含變更申請） |
| `api/completion_notes.py` | `/api/completion-notes*` |
| `api/material_orders.py` | 叫料 |
| `quotations.py` | 報價單熱欄位同步、驗證；提供者：`case.access`、`case.summary`、`case.locations`、`case.recognition`、`case.default_terms`、`case.doc_version` |
| `recognition.py` | 收入認列／支出歸月／待補登（經 `case.recognition` 給 M08） |
| `quote_terms.py` | 報價條款預設值、送審原因 |
| `case_deadlines.py` | 每日到期檢查（`daily.check`） |
| `case_stage_tasks.py` | 執行進度勾選 → 每日工作事項 |
| `completion_pdf.py` | 完工單 PDF |

表：quotations、quote_seq、case_stages、case_stage_visits、case_updates、case_action_items、case_change_requests、case_extra_expenses、completion_notes（凍結 migration 建立）。
頁面 8 頁仍在 `frontend/pages/`（模組頁面尚無服務路徑）；案件頁的 `js/case-management-*.js` 11 支同。

## 串接點

- 提供：見上表與 INTEGRATION-POINTS（IP-12 case.access、case.summary、case.locations、case.recognition、case.default_terms、case.doc_version、IP-17 quotation.append_items、IP-6 calendar.writeback（另：款項收款／預計收款日 ⇒ 行事曆事件 `receipt_logged`／`receivable_due`，`receipt_calendar.py`）；另：請款預定付款日（`planned_pay_date`）⇒ 提醒信 `payable_reminders.py`＋行事曆 `payable_due`（`payable_calendar.py`）、approval.reassign 的 quotation／completion_note、IP-11 daily.check）
- 取用：IP-1／IP-14／IP-15（M04）、IP-18／IP-19（M03）、approval.queue_items／approval.reassign／approval.detail（各單據模組）、case.default_terms 的取用方是 L1 system

## 預定付款日、提醒信、行事曆（2026-10-05）

- **欄位**：`case_extra_expenses.planned_pay_date`（case migration v7，選填 YYYY-MM-DD；舊列 ''）。**不是實際付款日**（`paid_date`／`remit_date` 由出納登錄）；付款後保留當歷史。寫入：請款頁建立／編輯（`plannedPayDate`）、`PATCH …/extra-expenses/{id}/dates`（任何狀態可補登改期，已付款後 409）。IP-100 `payables.pending` 項目帶 `plannedPayDate`。
- **提醒信**（`payable_reminders.py`，`daily.check` 每日 08:00／啟動補跑）：對象＝已核准、未付款、未作廢、要出納付款的類型（`kind=''`／採購單／差旅／零用金；請購單不含）、有預定日。名義日＝預定日−3 天（`payable_due_soon`）與預定日（`payable_due_today`）；名義日落在週六日 ⇒ 提前到前一個工作日（週一至週五）寄；兩封折到同一天 ⇒ 只寄「今日到期」。**國定假日尚未納入**（唯一的官方假日表在 M11；接上只改 `is_working_day`）。冪等 key＝（案件, 種類, 預定日, 寄信日）。信內不放金額。收件人＝財務郵件群組（類型登記在 `mail_types` group `finance`、寄信 `to_group=True`、不另帶 usernames：在職、有 Email、未退訂的財務角色＋最高管理者，並套收件設定頁的覆寫）；沒有收件人 ⇒ 不寄也不寫 guard。
- **行事曆**（L1 事件種類，皆預設關、只對開啟後的變更生效、不回補既有資料）：`receipt_logged`／`receivable_due`（`receipt_calendar.py`，款項期別前後比對，三條寫入路徑 commit 後推）、`payable_due`（`payable_calendar.py`，跟著現況走：核准／改預定日／清空／作廢；出納付款由 M05 以 IP-100 的 `來源:key` 收回）。事件以（種類, key）唯一識別，不存 event id、不新增表。**事件不含任何金額**（標題與說明；使用者 2026-10-05 裁示）。

## 本模組不在時（別人怎麼辦）

- L1：`routers/system` 報價條款端點 404 並明說；`pdf_gen` 不記版本紀錄；地圖不列案件（case.locations）
- M08 報表：權責收入 `incomeNotice`、支出 `unavailable` 列案件類、待補登 {}；成案月份 {}
- M10 網路規劃：綁案件改用 case.access（IP-12）的「不在」分支
- M12 每日工作：`/api/sales-orders` 不在 ⇒ 待④（M01-PLAN §5）

## 尚未處理

- ③ 提供者改成 ModuleSpec 宣告（CA-O3）；④ SO 提示與補題；⑤ ATT（A 的 attachments.for_document）已知例外＋到期守門
- 其他模組直接讀本模組的表（M01-PLAN §2-B）：讀取連接器另案

## 精算完結的護欄（35c；0c 稽核四項已知限制已於同班處理）

- 對「已完結」的案件再 PUT（超級管理員的重新開啟路徑）一律要非空白理由（≤500 字），理由記入編輯歷程與稽核紀錄 `quotation.settlement`；再存成完結時與第一次完結同樣重算比對並補蓋 `dispatchBasis`。舊的已凍結案讀取不重驗、不改寫。
- 舊口徑頁面（沒有 `dispatchBasis`、送含稅數字）直接再存會被 409 擋下：請先重新開啟再完結。
- 409 訊息前綴為中性說法，差異欄位清單才是重點。
- 自訂模組支出非 0 的完結 fixture 已有測試（`test_settlement_finalize_integrity_2026_10_03.py`）。
- 重新開啟理由是自由文字，只有財務檢視（`money_visible()`）的帳號看得到：單筆案件 GET、`/versions`、`/case-bundle` 的編輯歷程對其他帳號只留誰／何時／事件、不含理由（沿用 CM13 遮蔽，`helpers/financial_mask.py::strip_history_reasons`）。稽核紀錄 `audit_log` 的 detail 仍帶理由，由 `audit_log` 模組權限把關。
- 對**舊口徑（含稅）**的已完結案「重新開啟再完結」會把它轉成新口徑（未稅）：淨利基數 +0.99×承攬商稅額；已發放的獎金不會被重算。這是刻意的，改之前要知道。
