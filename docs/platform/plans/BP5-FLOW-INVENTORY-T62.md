# BP-5 流程狀態機建構器：寫死的簽核／流程程式盤點（第一份，設計之前）

> 日期：2026-10-14　作者：hichan-3e（受 hichan-b4 指派）　基底：`origin/train/t60-int` 1fd62b612　僅讀程式碼、未執行；行號為該基底的行號，改版後會漂移。
> 範圍：每種單據「誰可簽、要不要簽核、退回草稿有沒有紀錄、核准後的回呼」寫在哪裡。**這份是事實清單，不含設計。**

## 0. 先講結論（對設計影響最大的四件事）

1. **「誰可簽」大半已可在系統內調整**：`helpers/tiered_approval.py:55-81` 的 `APPROVAL_DOC_TYPES`（內建 9 類）＋`register_doc_type()`（`:86`，另 5 類由模組登記）；層級存在 `system_settings` 的 `unified_approval_flow` 或 `{doc_type}_approval_flow`（`:112-130`，`approval_flow_scope` 決定走哪把）。BP-5 不必重做「誰可簽」，要做的是把它納入同一個定義／預覽／版本流程。
2. **流程骨架（狀態名稱、轉換、守門）完全寫死在各端點，且高度複製**：完工單、出貨單、請款單、開票申請、承攬商匯款申請五類幾乎逐字相同（草稿→待審核→簽核中→已核准；退回與撤銷核准都回「草稿」）。另有四種變形（報價單、案件支出、傳票、獎金／薪資等）。
3. **只有自訂模組有真的狀態機引擎**（`helpers/custom_modules.py:1416 transition`；`routers/custom_records.py:244`），既有單據沒有。
4. **「退回草稿有沒有紀錄」今天不可選**：各端點各自寫 `signed_log`／`editHistory`／`_audit`，沒有統一的轉換紀錄表（對應 H2 的 UNKNOWN，見 §4）。

## 1. 共用簽核零件（已集中，無 FastAPI 依賴）

| 項目 | 位置 | 備註 |
|---|---|---|
| 簽核單據類型登錄 | `helpers/tiered_approval.py:55-108` | 內建 9：quotation／shipping／invoice_voucher／payment_request／contractor_voucher／extra_expense／completion／voucher／bonus |
| 後來登記的 5 類 | `modules/case/material_approval.py:52`、`material_change.py:90`、`material_payment.py:48`、`modules/payroll/api/payslip_approval.py:30`、`modules/subcontract/api/dispatch_approval.py:26` | 皆呼叫 `register_doc_type` |
| 統一／獨立流程選擇 | `tiered_approval.py:75-77`（預設統一組）、`:112 approval_flow_setting_key`、`:121 resolve_active_flow_setting` | 傳票與獎金刻意不在預設統一組（`:44-71` 註解） |
| 簽核人解析（含部門／處主管） | `:146-368` | `resolve_tier_approvers`、`setting_to_active_tiers` |
| 可否簽核／自簽層連簽／代理 | `:372 active_delegators_for`、`:387 check_approve_permission`、`:418 plan_self_cascade`、`:450 cascade_self_tiers`、`:481 sign_first_pending` | **自簽層：有簽核層時允許簽核人＝申請人**（與架構筆記 §0B.5 一致） |
| 駁回原因／權限 | `:495 require_reject_reason`、`:512 check_reject_permission`、`:532 check_no_tier_self_approval` | |
| 鏈壞掉時的失敗關閉 | `:616 ApprovalChainUnreadable`、`:625 parse_approval_json` | |
| 待簽佇列 | `helpers/approval_queue.py:26 ACTIVE_STATUSES=("待審核","簽核中")`、`routers/approval_queue.py:456 reassign`；覆蓋守門 `tools/check_approval_queue_coverage.py` | 新增狀態名稱會讓佇列看不到 ⇒ 建構器若允許改狀態名，這兩處必須從定義讀 |
| 簽核設定頁 | `routers/system.py`（`approval_flow_scope` 等）、`approval-settings.html` | |

## 2. 逐單據：狀態、轉換端點、守門（file:line）

### 2.1 「標準五件套」（結構相同，逐字複製）
狀態：`草稿 → 待審核 →（簽核中，仍屬同一個 ACTIVE 組）→ 已核准`；`reject` 與 `revoke-approval` 都寫回 `草稿`；`signed-toggle`（客戶回簽）只在 `已核准` 且僅 admin。

| 單據 | 編輯／刪除鎖（僅草稿） | submit | approve | reject | revoke-approval | 核准後的回呼（副作用） |
|---|---|---|---|---|---|---|
| 完工單 `modules/case/api/completion_notes.py` | `:465`、`:514` | `:538`（狀態寫入 `:594`） | `:603`（寫入 `:686`；自簽擋 `:674`） | `:712`（`:741`） | `:754`（已回簽擋 `:777`；`:785`） | 通知申請人＋`_expense_notify.fire_completion_approved`、`notify_module_activity`、`_audit completion.approve` |
| 出貨單 `modules/supply/api/shipping_notes.py` | `:340`、`:366` | `:399`（`:457`） | `:469`（`:590`；序號在庫檢查 `:581`） | `:686`（`:716`） | `:624`（已回簽擋 `:651`；`:672`） | **扣庫存**（approve 內 `stock_items` UPDATE）、背景產 PDF、行事曆推送、通知 |
| 請款單 `modules/arap/api/payment_requests.py` | `:478`、`:566` | `:590`（`:639`） | `:651`（`:733`） | `:801`（`:831`） | `:760`（已匯出擋 `:776`；`:786`） | 背景 PDF、`push_event_for_payment_request`、通知、`_audit` |
| 開票申請 `modules/arap/api/invoice_vouchers.py` | `:473`（刪）；編輯另處 | `:497`（`:546`） | `:558`（`:641`） | `:709`（`:739`） | `:668`（已匯出擋 `:684`；`:694`） | 背景 PDF、行事曆推送、通知、`_audit` |
| 承攬商匯款申請 `modules/subcontract/api/contractor_vouchers.py` | 編輯鎖另處；`void :598` | `:633`（`:683`） | `:695`（`:779`） | `:852`（`:883`） | `:807`（已匯款擋 `:826`；`:836`） | 背景 PDF、通知、`_audit`；另有 `mark-paid`（`:1152` 起，須財務角色、僅已核准） |

共同寫死的守門：自簽處理（`self_block_msg`，各 approve 內）、「系統已設定簽核流程，此單據缺少簽核層資料，請重新送審」（鏈壞掉失敗關閉）、`僅超級管理員可執行此操作`（無 tiers fallback 時只有超管能簽）。

### 2.2 報價單（金額類；**護欄項目寫死**）`modules/case/api/quotations.py`
| 項目 | 位置 |
|---|---|
| 狀態：草稿／待審核／簽核中／已送出／已成案（deal_tag）／已結案 | 散見 `:1377`（僅已送出可…）、`:1439-1447`（待審核／簽核中的編輯拒絕）、`:2006-2010`、`:2102-2153`、`:2571` |
| 送審（status=待審核）：伺服器重算、產生簽核層、孤兒單防護 | `:1573-1700`、`:1807-1865`（`is_new_submission`）；`modules/case/quote_terms.py:164 compute_approval_reasons` |
| 簽核／駁回／最終駁回 | `approve :4989`（寫 `已送出` `:5088`；`簽核中` `:5102`）、`reject :5114`（回草稿 `:5181-5199`）、`reject-final :5206` |
| 撤回送審（待審核／簽核中→草稿） | `:2181-2209` |
| 客戶回簽、解鎖修改 | `signed-toggle :1347`、`case-unlock :2742`、`case-lock :2791` |
| **金額守門（寫死，不可交給建構器）** | `alt_lock.py:56 changed()`（P1 本文比對）、`alt_sign.py:106 check_downstream`（P8→P7→P6→P2）、`:145 clear_signed_selection`、`:172 guard_update`（P4）、`:183 guard_move_out_of_sent`（P3）、`profit_guard.py:306 prepare`、`:401 change_pct` |
| 核准後的回呼 | `after_commit` 清單：下一層通知、背景 PDF、`notify_approved`、`_notify quotation_approved`、`_audit quotation.approve`（`:5030-5119`） |
| 變更單（案件變更簽核） | `approve_case_change :3379`、`reject_case_change :3430`（狀態值為英文 approved／rejected，與其他不同） |
| 銷帳核銷簽核 | `approve-writeoff :4489`、`cancel-writeoff :4460` |

### 2.3 案件額外支出／請購 `modules/case/api/case_extra_expenses.py`
狀態：草稿／待審核／簽核中／**已駁回**（不回草稿）／已核准／**已作廢**。編輯鎖 `:577`（草稿與已駁回可改）、刪除 `:836`；`submit :918`（**無簽核層時自動核准** `:960-973`）；`approve :1006`；`reject :1094`（`已駁回` `:1130`）；`void :859`（僅超管、僅已核准 `:869-882`）；另有「變更申請」子流程 `change-request/submit :1577 / approve :1648 / reject :1738`。付款日限制 `:784-793`（財務角色）。

### 2.4 會計傳票 `modules/accounting/api/vouchers.py`（會計入帳類型，**不在可編輯範圍**）
`submit :652`（寫入 `:713`）、`approve :727`、`send-back :827`（回草稿 `:877`）、`void :906`；`approval_done()` 在 `modules/accounting/voucher.py:569`，被列印／輸出（`vouchers.py:1537`、`voucher_pdf.py:172`）作為「已簽核完成」判定。另有期間關帳／重開（`ledger_periods.py:123-168`、`ledger_closing.py:79-94`）與帳務請求（`ledger_requests.py:100-140`）。

### 2.5 薪資／獎金／派發／材料（較少複製、各有變形）
| 單據 | 位置 | 變形 |
|---|---|---|
| 薪資單 | `modules/payroll/api/payslip_approval.py:121/213/280`；`payslips.py:706 void`、`:868 unsign` | `unsign`（取消簽收） |
| 案件獎金 | `modules/payroll/api/bonus.py:1823 submit / :1878 approve / :1972 reject / :1999 return`；寫入 `:1838`、`:1961`；`已發放` `:2062` | 多「發放」終態與 `return` |
| 獎金更正單 | `modules/payroll/api/bonus_correction.py:257/280/340`；`cancel :209` | |
| 派發（承攬商）／完工驗收 | `modules/subcontract/api/dispatch_approval.py:287-353`（兩段：派發核准、完工核准，各有 withdraw） | 兩階段 |
| 材料核准／變更／付款 | `modules/case/material_approval.py:206-301`、`material_change.py:385-476`、`material_payment.py:355-446` + 路由 `api/material_payments.py:287-399` | 純函式模組（`submit/approve/reject/withdraw`）形式較乾淨 |
| 現金出納匯款覆核 | `modules/arap/api/cashier.py:381 decision` | |
| CRM 開發案刪除／重連報價核准、開發紀錄核准 | `modules/crm/api.py:470/503/665/698/1055` | 兩人核准型小流程 |
| 回收桶刪除核准 | `modules/recyclebin/api.py:130` | |

### 2.6 已有的「可配置」流程（BP-5 的現成基礎）
- 自訂模組狀態機：`helpers/custom_modules.py:1416 transition`；HTTP `routers/custom_records.py:244/267/282`（`approve`／`reject`）；定義審查 `:431/445/466`、`helpers/custom_def_review.py`。含狀態、轉換、分層簽核（層可帶條件公式）、進入狀態通知、事件、`def_version` 凍結。
- 設定治理與雙人核准：`routers/def_pipeline.py`（`:221 approve`、`:260 cancel`）、`routers/settings_center.py:311/341`、`helpers/config_ledger.py`。
- 定義文件庫：`core/definitions.py`（版本、草稿、diff、restore）。

## 3. 「單據要不要簽核」今天怎麼決定（P1／P8 的現況）

- **沒有全域開關**。有簽核層就走簽核；沒有層：完工等「標準五件套」approve 內退到 `僅超級管理員可執行此操作`（`completion_notes.py:661`、`shipping_notes.py:537`、`payment_requests.py:709`、`invoice_vouchers.py:617`、`contractor_vouchers.py:755`）；案件支出 submit 直接自動核准（`case_extra_expenses.py:960-973`）；報價單 submit 沒有層會被視為孤兒（`quotations.py:1700` 起的防護）。**三種「沒有層」的行為不一致**，建構器的「免簽核豁免」要明確定義每種的預設 = 今天的行為。
- 自訂模組：流程沒有簽核狀態時 `_is_unapproved` 回 False（架構筆記 §2.4 已標示：金額／法定類型不得沿用）。

## 4. 還沒查證（UNKNOWN，設計前要補，列為工作項）

1. 簽核歷史（`signed_log`、簽核格、`approval_json`）與 `audit_log` 是否有 DB 層 BEFORE UPDATE／DELETE 觸發器保護（H2 前置，架構筆記 §7.1 U5）。
2. 每個端點退回草稿時究竟寫了哪些紀錄（有的寫 `signed_log`、有的只寫 `_audit`、有的都沒寫）——需要逐端點列表才能設計「留到多細」。
3. 開票申請與承攬商匯款申請的編輯鎖精確行號（編輯端點未在本次關鍵字範圍內命中）。
4. 各 approve 的「核准後回呼」中哪些在交易內、哪些在 `after_commit`（報價單已用 `after_commit`，其他四類未逐一確認）——影響建構器的「回呼」要不要在引擎裡統一成 after-commit 佇列。
5. 單據類型的 `moneyClass`（money／legal／ledger／plain）今天沒有程式內登錄；`APPROVAL_DOC_TYPES` 只有名稱，沒有風險類。**建構器要能判斷「這是金額單據、只能加嚴」需要新增這個登錄（已有 `routers/definitions.py` 的受管 kind 守門可借用型態）。**

## 5. 對設計的直接含意（只列，不展開；設計筆記接著寫）

- 預設定義登記順序（b4 指示）：完工單、出貨單（兩者都屬標準五件套，結構相同 ⇒ 一份「標準五件套」範本即可涵蓋 5 類，逐類只差守門與回呼）。
- 引擎要做的最小集合：狀態表、轉換表（誰可：沿用 `tiered_approval` 的層）、是否需簽核（豁免）、退回紀錄等級、回呼清單（只能引用已註冊動作：通知、PDF、行事曆推送、庫存扣減＝**動作目錄**，而非任意程式）。
- 金額類（報價單、請款單、開票申請、承攬商匯款、傳票、薪資、獎金）：建構器只能加嚴；`alt_lock`／`alt_sign`／`profit_guard`／編輯鎖／重開守門鏈維持寫死。**標準五件套裡有三類屬金額類（請款、開票、匯款），首批只登記完工單與出貨單是對的**（出貨單雖扣庫存，不屬金額守門範圍，但庫存扣減是回呼，要列入動作目錄的『寫入類』）。
- 黃金重放：以第 2 節每條「寫入 / 擋下」行號為測試題清單（含被擋情況與訊息）。
