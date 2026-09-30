# 案件 更新紀錄

## 1.0.32 — 2026-09-30（暫用號，列車取號；wip/w1-attach-p3 附件目錄 P3）
- 附件目錄 P3：`_CaseCatalog` 加 `search`／`count`（權限沿用各類 `_READ_RULE`／完工單 `case_documents_readable`）；案件管理頁新增「全部附件」頁籤（檔案中心在才出現，呼叫 `/api/filehub/search` 固定本案件，點檔用共用預覽元件）。

## 1.0.31 — 2026-09-30（暫用號，列車取號；wip/w1-builder3-s25 建構器 S2.5；1.0.26 已被 wip/cal-toggle 取用）
- `GET /api/quotations/{單號}/finance-summary` 多回 `customFinance`（自訂模組關聯到本案件的入帳金流：`expense.total`／`items`；`income` 因內建報價單已認列而標 `skipped`、累計 `skippedTotal`，不進 total；讀 L1 `helpers.custom_finance`）。案件管理財務 Tab 多兩個標籤（`fin-custom-expense`、`fin-custom-income-skipped`）。

## 1.0.30 — 2026-09-30（暫用號，列車取號；wip/w2-attach-p2：附件目錄 P2）
- 新增提供者 `attachments.catalog`／`case`（IP-105，`attachments.py::_CaseCatalog`）：quotation_signed、case_update、payment_item、material、material_invoice、extra_expense、completion_note 的開檔；權限沿用擁有單據的既有規則（不另寫第二份）；待核准暫存檔不進目錄。

## 1.0.29 — 2026-09-30（暫用號，列車取號；W4 總帳 C4b）
- 新增提供者 `gl.events`（IP-GL1）：已核准額外支出 E11（發票日→核准日→憑證日）與付款 E11b（付款日，含匯款手續費、已核可的實付差額）、叫料 E12（發票日，無則付款日）與付款 E12b。來源金額未拆稅，以全額列專案成本，進項稅額由會計在總帳補登。唯讀、不寫資料、不改欄位。

## 1.0.28 — 2026-09-30（暫用號，列車取號；W4 總帳 R12 畫面）
- 案件管理『標記已匯款』視窗：個人外包人員逐位挑選勞報單（R12），行為同出納頁。純畫面，無新端點、無 migration。

## 1.0.27 — 2026-09-30（暫用號，列車取號；wip/w1-file-preview 共用檔案預覽 P1）
- 案件管理、報價單、成本精算頁的附件開啟改用 L1 共用預覽元件（頁內預覽，不再開新分頁／換 photo-token）；報價表單 `FORM_VERSION` V3.12 → V3.13。

## 1.0.26 — 2026-09-30（暫用號，列車取號；wip/cal-toggle 行事曆推送可選）
- 行事曆「案件更新」（預設關，事件種類開關在 L1）：案件留言板新增留言（重要留言除外，重要的仍走「案件重要留言」）commit 之後推 `push_event_for_module('case_update', …, merge_key=案件編號)` ⇒ 標題「○○案件更新」、同一案件同一天合併成一個事件、說明累加。IP-100 `payables.pending` 的 `mark_paid` 回傳加 `title`／`payee`（加欄位、相容；出納推「支出付款」事件用）。題 `modules/case/tests/test_case_update_calendar_2026_09_30.py`
## 1.0.25 — 2026-09-30（暫用號，列車取號；wip/sec-p0 安全修正 P0）
- 安全修正 P0：`GET /api/completion-notes/{no}` 與 `POST /api/completion-notes/{no}/signed-files` 原本只要求登入（單號可列舉即可讀／上傳任何完工單）⇒ 改用完工單清單的規則 `guard_case_access(allow_module="case_manage")`（`_readable_note`）；看不到與查無同一句 404「完工單不存在」（不帶案件單號），上傳被擋時不寫檔。
- 新增提供者 `uploads.path_access`／`case`（IP-104，`attachments._CasePathAccess`）：quotations、quotation_payment_items、quotation_materials、quotation_materials_invoices、case_updates、case_extra_expense、completion_notes、_pending_case_changes 八個上傳資料夾依擁有單據的讀取規則判斷（同 IP-21 `_READ_RULE`；完工單＝清單規則；待核准變更＝申請人本人或案件頁規則，變更 id 必須屬於該案）。

## 1.0.24 — 2026-09-30（暫用號，列車取號；wip/w2-report-cash）
- 案件財務 Tab：實際淨收／實收淨額＝銀行入帳，不再減客戶內扣手續費（手續費另列費用）；「實收金額」標籤改「銀行實際入帳，已扣客戶內扣手續費」。案件結算單 PDF 的收款明細同步。

## 1.0.23 — 2026-09-30（暫用號，列車取號；wip/w3-approval-freeze，使用者回報正式機簽核時整個系統卡住約 3 秒）
- 修正（成因）：`approve_quotation` 在 `write_txn`（BEGIN IMMEDIATE）區塊內呼叫 `_notify`（另開連線 INSERT 通知）與 `notify_next_tier`，新連線等這個請求自己握著的寫鎖，等滿 busy timeout（30 秒）才失敗 ⇒ 下一層簽核人收不到站內通知，期間全體寫入被卡住；同一區塊在 commit 之前就 `spawn_bg_thread(PDF)`／`notify_approved` ⇒ PDF 可能讀到簽核前的狀態（浮水印錯）。改為寫鎖內只收集、commit 之後才執行（各自獨立、失敗只記 log，不讓已成立的簽核回 500）。量測：中間層核准 32.9 秒 → 0.10 秒，通知寫入。
- 效能（待簽佇列與側欄角標）：`approval_queue_items` 正常的單改由 SQLite 取 `$.approval`（巢狀 CASE 保證壞 JSON 不會讓整個查詢丟例外；其餘形狀照舊走 Python 的 L1 `approval_json_of`）；`case_summary` 的 deal_tag 欄位空時由 SQLite 取 `$.dealTag`（拿不準的形狀才把 data_json 撈回 Python）。200 張待簽、每張 data_json 約 60KB：佇列 441 → 113 ms，角標 400 → 88 ms。
- 新守門：`tools/platform/write_txn_scan.py`（全 repo 靜態掃描：寫鎖持有期間不得呼叫 _notify／_audit／spawn_bg_thread／notify_*／push_event_*／Thread／寄信）。
## 1.0.22 — 2026-09-30（暫用號，列車取號；N1 承攬商派工，接在 W1 之後）
- N1 承攬商派工（暫用號，列車取號）：報價單成本欄可逐項「帶入承攬商報價」（來源＝該案未取消的派工品項；帶入為預設、與承攬商報價不一致標差額；案件成本仍以承攬商實際派工金額計、不重複計）；`FORM_VERSION` V3.11 → V3.12

## 1.0.21 — 2026-09-30（暫用號，列車取號；W1 wip/w1-remit-fee）
- 稽核補修：`mark_paid` 查無 ⇒ 404 先於欄位檢查、格式不對 ⇒ 400（`BadRemit`）；登錄付款者不能自己核可／退回（403）；`recognition` 現金口徑項目帶 `remitPending`、手續費 entry 帶 `pending`；案件財務總覽（finance-summary）帶已匯款手續費 `payable.remitFeeTotal`／`settlementExtras.remitFeeTotal`
- W1 出納匯款手續費（暫用號，列車取號）：`case_extra_expenses` 加實付／手續費／差額審核欄位（migration v2 `0002_extra_expense_remit_fee`）；IP-100 提供者 `mark_paid` 多收 `remit`（實付、手續費、差額待審核）、加 `paid`（出納執行紀錄用）；提供 IP-102 `remit.reviews`（名稱 `case`）與 IP-9 `expense.entries`（名稱 `remit_fee_case`）；額外支出清單加 remitActual／remitFee／remitReview、回應加 `remitFeeTotal`；付款日清除 ⇒ 實付／手續費／審核一併清空；`recognition` 現金口徑改用實付金額（舊資料回退應付）

## 1.0.20 — 2026-09-29 14:45（暫用號，列車取號；wip/cloud-rowaccess-empty-name-2，D 稽核 RA-S1）
- 修正：案件清單「我負責的」（CM7 `_CASE_MINE_SQL`）舊資料比顯示名稱時空對空不算相符（同 L1 row_access 2026-09-29f）；原本顯示名稱空的 cashier 會把業務名稱空的舊案件全部歸成「我負責的」。守門 `modules/case/tests/test_case_mine_empty_name_2026_09_29.py`
## 1.0.19 — 2026-09-29（暫用號，列車取號；wip/payslip-void-signed）
- 款項日期存標準格式：儲存報價單時，`caseRecord.payment.items` 的收款日／預計收款日／發票日一律經 `helpers.norm_ymd` 存成 YYYY-MM-DD；銀行帳戶最近收款日比較同樣先正規化。

## 1.0.18 — 2026-09-28（暫用號，列車取號；E4 wip/e-company-gate-impl 第三段）
- 本公司資料設定閘門第二道（COMPANY-SETUP-GATE §5；D CG5-M1）：報價單、結案報告、專案執行報告、完工單 PDF 下載端點：`except Exception` 前先 `except HTTPException: raise`（第二道的 428 不被吞成 500）

## 1.0.17 — 2026-09-28（第十四班列車；列車上交會修正）
- `payment-request.html` 的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（與 H10 品牌設定其他頁一致；頁面在品牌包之後才出現，core-only 反向控制與 test_no_our_company_literals 抓到）
- 報價表單 `FORM_VERSION` V3.10 → V3.11（H10 已把 `quotation-form.html` 的 favicon 改讀品牌端點，漏遞增；test_form_version_bumped 抓到）

## 1.0.16 — 2026-09-28（第十四班列車取號，原暫用 1.0.15；B；稽核 D AUDIT-D-B41-payreq）
- PM1：case v1 migration 不再自己 commit（core.migrations.run_all 逐支 SAVEPOINT，由它 commit）
- PO2：核准後附件上鎖的訊息改成「發票可由填寫人、管理員或出納補上傳」（這則在權限檢查之前發出，原句讓沒有權限的人也以為可以補）

## 1.0.15 — 2026-09-28（第十四班列車取號，原暫用 1.0.14；B；使用者裁示 AB-S2／S8）
- AB-S8：付款日只准在已核准後設定（`PATCH …/dates`；出納、admin 都一樣）⇒ 未核准 409 並說明
- AB-S2：IP-100 提供者註明「出納為付款可見客戶／專案／事由，不因看不到案件而遮蔽」（行為不變）

## 1.0.14 — 2026-09-28（第十四班列車取號，原暫用 1.0.13；B；稽核 A AUDIT-A-B41-payreq 6cc497b7）
- AB-M1（必修）：`PATCH …/dates` 的 `paidDate` 只限出納或 admin+（本人設或清 ⇒ 403）；已有付款日的清除或改日期只限 admin+，另寫稽核動作 `extra_expense.paid_date_override`。發票日期、發票號碼照舊本人可登
- AB-S1：IP-100 `mark_paid` 改成帶條件的 UPDATE（已核准、付款日空白才寫）＋rowcount，後到的出納得到「已被登錄」、不蓋掉前者

## 1.0.13 — 2026-09-28（第十四班列車取號，原暫用 1.0.12；B；wip/b-payreq：使用者裁示 a／b／c，e70aa612）
- case v1 表不在 ⇒ 回原因（未完成）不記版號、下次啟動再補（2026-09-28 使用者裁示）；挑案件先過濾可見再取 30 筆、關鍵字的 `%`／`_` 照字面比對；核准後補發票的「或出納」須出納看得到該案件（註明，維持現狀）

## 1.0.12 — 2026-09-28（第十四班列車取號，原暫用 1.0.11；B；wip/b-payreq：請款流程）
- 請款流程（2026-09-27 使用者裁示；請款＝案件額外支出，不另建資料）：新頁 `payment-request.html`（我的工作 → 新增請款：挑案件 → 日期／金額／說明／附件 → 送審；「我的請款」看進度、核准後補發票）＋兩支查詢 `GET /api/extra-expenses/cases`、`/api/extra-expenses/mine`（可見範圍同 `case_owner_readable`）
- 附件分類 `kind`（invoice／other）：已核准後**只有發票類**可以直接補上傳（稽核動作 `extra_expense.invoice_after_approval`），其他類與刪除照 2026-09-11 裁示上鎖；舊附件沒有 kind ⇒ 視為其他、不回填
- 發票號碼 `invoice_no`（選填、最長 40 字、已核准也可以補，經 `PATCH …/dates` 的 `invoiceNo`）——**本模組第一支自己的 migration**（`migrations/0001_extra_expense_invoice_no.py`，case v1，只新增欄位）
- IP-100 `payables.pending` 提供者（`payables.py`）：已核准、付款日空白的額外支出給出納；出納登錄付款寫回付款日
- 月支出（IP-95 `extra_entries`）只計送審中（標待定）與已核准，草稿與已駁回不計（權責、現金兩種口徑）
- ⚠ 帶 `migrations/` ⇒ 單模組更新包（P7b）目前會被拒收，本模組只能整包出貨（RUN-PLAN 待辦）
- case v1 表不在 ⇒ 回原因（未完成）不記版號、下次啟動再補（2026-09-28 使用者裁示）；挑案件先過濾可見再取 30 筆、關鍵字的 `%`／`_` 照字面比對；核准後補發票的「或出納」須出納看得到該案件（註明，維持現狀）
## 1.0.11 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`quotations.html`、`quotation-form.html`、`case-management.html`、`case-stage-board.html`、`approval-history.html`、`settlement.html`、`completion-note-form.html`

## 1.0.10 — 2026-09-27（第十三班列車取號，原暫用 1.0.4；稽核 D 建議，主持派 B 代改：wip/b-m01-salesorders-page）
- `pages` 補 `sales-orders.html`（已退役、2026-09-13 起是導向案件管理的頁；不帶 menu、不進側欄）：modules.json 把它歸 M01，原本沒列入 pages ⇒ M01 缺席時產品選配不移除它、D7 前哨也不驗它回 404。守門 `tests/platform/test_module_pages_match_units.py`（wip/b-drill-absent404-2）

## 1.0.9 — 2026-09-27（第十三班列車取號；c-approval-l1-4，稽核 D QJ-M1）
- 待簽佇列提供者：簽核 JSON 存在獨立欄位的單（`approval_json`／`change_approval_json`）改經 L1 `approval_raw_of`：解析不了 ⇒ 跳過那一筆＋ERROR（原本 `tier_fields` 把壞 JSON 吞成 {} ⇒ 列給每個 superadmin、計角標，核准時才丟例外；稽核 D QJ-M1）
- 題：通用契約題的種資料改成案件要存在（孤兒單規則）

## 1.0.8 — 2026-09-27（第十三班列車取號；c-approval-l1-3：稽核 D AL2-M2＋主持更正）
- `case.summary`：deal_tag 改在 Python 逐筆解析（原本 SQL_DEAL_TAG 的 json_extract 遇到一張壞 data_json ⇒ 整個查詢丟例外：佇列詳情 500、傳票案件清單整支壞）；壞的那一筆 deal_tag 空字串＋ERROR（寫單號）
- 〔更正〕1.0.7 的理由 ~~當成沒有簽核層列出是降級（任一 superadmin 可簽）~~ ⇒ 列出了也簽不了（核准端點 500、狀態不變，D 實測）；能解析、沒有簽核層的報價單照列（題鎖住）

## 1.0.7 — 2026-09-27（第十三班列車取號，原暫用 1.0.6；c-queue-json，主持指派）
- 待簽佇列提供者：簽核 JSON 改用 L1 `helpers.approval_queue.approval_json_of` 在 Python 逐筆解析（原本 SQL `json_extract(data_json,'$.approval')` 遇到一筆 malformed JSON ⇒ 整個查詢丟例外 ⇒ 這一類待簽全部靜默消失）；壞的那一筆跳過並記 ERROR（寫單號、不寫內容）；〔更正〕~~壞的報價單當成沒有簽核層列出、角標計 1~~（1.0.6）：那是降級（任一 superadmin 可簽），改成跳過

## 1.0.6 — 2026-09-27（第十三班列車取號；c-approval-l1-2，稽核 D AL-M1／AL-S1／AL-O3／AL-O4／AL-O1）
- 佇列提供者：報價單、完工單的簽核 JSON 改在 Python 逐筆解析（原本 SQL `json_extract` 遇到一筆 malformed JSON ⇒ 整個查詢丟例外 ⇒ M01 的待簽全部消失；舊版是整支佇列 500）
- 題：已結案變更 selfViewBy 兩方向（沒有案件權限的申請人 200、外人 404 同查無）、完工單查無＝看不到、壞 JSON 報價單照列且不影響其他（稽核 D AL-M1／AL-S1／AL-O4）

## 1.0.5 — 2026-09-27（第十三班列車取號，原暫用 1.0.4；c-approval-l1，主持裁示）
- 「待我簽核」佇列／角標搬進 L1 `routers/approval_queue.py`（路徑不變、前端不改）；M01 改為 `approval.queue_items` 提供者 `approval_queue_items`（報價單、已結案變更、額外支出、完工單、額外支出變更），ModuleSpec 宣告
- 已結案變更的客戶名稱改一次 JOIN（原本逐筆查 quotations，結果相同）
- 詳情與轉簽端點也搬 L1：M01 改為 `approval.detail` 提供者 `detail_quotation`／`detail_completion_note`／`detail_extra_expense`／`detail_case_change`（找不到的 404 訊息同前；已結案變更給 `selfViewBy`＝申請人本人照看）；`_case_header`、`_guard_queue_detail`、金額遮蔽移至 L1
- `case.summary` 加欄 `deal_tag`（L1 詳情抬頭；既有欄位不變）
- 選單「簽核佇列」與頁面、`/api/approval-queue` 前綴歸回 L1（`core/menu_l1.json`、modules.json）

## 1.0.4 — 2026-09-27（第十三班列車取號，原暫用 1.0.3；M01-PLAN §3-8 ④）
- 題：`test_approval_providers.py` 隨模組搬進 `modules/case/tests/`；新增 `test_approval_detail_and_reassign_edges.py`（稽核 D 兩項觀察：詳情遮蔽看 dataUrl、M05 不在時轉簽簽核鏈讀不出來擋下）

## 1.0.3 — 2026-09-27（第十三班列車取號，原暫用 1.0.2；M01-PLAN §3-8 ③ CA-O3）
- 提供者 13 個一律改由 `__init__.py` 的 ModuleSpec.providers 宣告，刪除所有 import 時的 `registry.provide()`：模組停用／未授權／載入失敗 ⇒ 不登記，`case.access`（M01 在不在的唯一訊號）隨之消失
- ATT：A 的 `helpers/case_attachments.py`（attachments.for_document 的 M01 提供者）移入 `modules/case/attachments.py`，改 ModuleSpec 宣告（原規劃的已知例外不需要：a-attachments 已隨第十班合回）
- 守門 `tests/platform/test_case_module_spec.py`（無 import 時登記＋反向控制、宣告清單、執行期不在 import 時登記表）

## 1.0.2 — 2026-09-27（第十二班列車，隨 M06 會計搬遷帶入）
- `modules/case/api/quotations.py::case_bundle` 的 `parts.vouchers` 改經 IP-22 `voucher.by_case`（M06 提供）取用，不再直接 import `routers.vouchers`／`modules.accounting.api.vouchers`；M06 不在時該段回 404 並明說（`VOUCHERS_UNAVAILABLE`）

## 1.0.1 — 2026-09-26（c-case404，M01-O1；列車取號）
- 看不到＝不存在：`_guard_case` 與 13 處單筆讀寫改走 L1 `helpers.case_access` 的 `deny_case`／`require_case`——逐案被拒與查無案件同一個 404（訊息逐字相同），audit 另記真正原因；`_is_case_member` 改用布林 `row_access.visible`（不丟例外、不記 audit）

## 1.0.0 — 2026-09-26
- 模組化（M01-PLAN §3-8 ②）：自 `routers/quotations.py`、`case_action_items.py`、`case_extra_expenses.py`、`completion_notes.py`、`material_orders.py` 搬入 `modules/case/api/`；`helpers/quotations.py`、`quote_terms.py`、`recognition.py`、`case_deadlines.py`、`case_stage_tasks.py` 與 `completion_pdf.py` 搬入 `modules/case/`（PLAYBOOK §B）；由載入器掛載（路由順序同搬遷前）
- 選單：「報價單」「案件管理」「案件執行看板」「簽核佇列」「簽核歷史」自 L1 `core/menu_l1.json` 移進本模組 `module.json` 的 pages[].menu
- 前置（其他包，已在本分支之下）：稅額純函式下沉 L1（T）、`norm_at`／`steps_to_tiers`（§3-2）、`case.summary`／`case.locations`（§3-4）、`case.recognition`（§3-6）、`approval.*`（§3-7）、CA-O4（§3-8 ①：L1 不 import M01、pdf_gen 不寫 quotations）
- 提供者仍在 import 時登記（載入器 import 本套件即登記）；改成 ModuleSpec 宣告是 ③（CA-O3）
