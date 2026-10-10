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

## 第 46～51 班追加（文件同步 DOCSYNC-T52；細節與版本見 CHANGELOG 1.0.158～1.0.169，第 51 班項目以該班實際上線為準）

**利潤規則（第 48～50 班；設計 `docs/platform/plans/OVERHEAD-25PCT-OPERATING-PROFIT-DESIGN-T48.md`、切換步驟 `OVERHEAD-25PCT-CUTOVER-RUNBOOK-T48.md`）**
- 算式只寫在 `helpers/profit_rules.py`（前端同式 `static/profit-rules.js`，同一份黃金向量 `tests/data/profit_rules_vectors.json`）。**口徑 1（舊）**：管銷分攤＝報價稅前×10%，另計五項間接成本，公益＝max(0, 直接毛利×1%)。**口徑 2（新，`tot.formulaVer=2`）**：管銷分攤＝max(直接毛利, 0)×該單比率%（預設 25，每單可調），**五項間接成本不再計入**（運輸物流／安裝施工／差異項／保固預估／其他費用輸入已自報價單頁移除，費用一律走請款申請），公益不變；營業利益＝直接毛利−管銷−公益（舊稱淨利、稅後淨利；內部鍵 `netProfit`／`netMarginPct` 不改）；營業利益率低於 12% 警示門檻不變。
- 開關：`system_settings.overhead_rule_mode`（`legacy` 預設｜`v2`）、`overhead_default_pct`（預設 25）、`overhead_migration_done`（完成標記；**沒有標記伺服器一律當 legacy**）。切到 v2 只能經離線工具 `backend/tools/overhead_migrate.py recalc --apply --set-mode-v2`（單一交易：重算未精算報價單、寫舊值快照 `tot._legacy`／`overhead_legacy_snapshot`、寫標記與模式）或 `PUT /api/overhead/settings`（要 `confirm=true` 且已有標記）；退回 legacy 會刪標記。回滾順序與程式回滾前提見 Runbook。
- 權限與稽核：`GET /api/overhead/settings` 登入者可讀；`PUT` 與每張單的比率變更**只有最高管理者**（非最高管理者 403，伺服器端把關）；偏離預設比率要警示＋二次確認；稽核 `settings.overhead.update`、`quotation.overhead_pct_change`。`tot.formulaVer`／`overheadPct`／`_legacy`／`_recalc` 戳記**只由伺服器蓋**（用戶端值丟棄；表單存檔不遺失 `_legacy`）。
- **歷史不動**：已精算／已結案（`settle_status=finalized` 或 `deal_tag=已結案`）的存檔、重算與遷移一律略過，數字、標籤與 PDF 與切換前相同；獎金基數＝完結凍結的營業利益。新口徑下伺服器（`profit_guard`）重算品項金額、稅前、稅額與利潤欄位，不信前端送的值；稅率語意不靜默改舊單（零稅率／免稅恆 0、數字稅率照用、缺鍵＝5%；鍵存在但 null／空字串的舊儲存形狀以資料庫存的 `tot.tax` 為準）。
- 標籤依戳記：管銷分攤列「（直接毛利 N%）」／「（報價稅前 10%）」（`pdf_gen.admin_cost_label`、前端 `stlAdminLabel`／`caseSettleAdminLabel`）；「淨利／淨利率」全站改稱「營業利益／營業利益率」，未扣費用前稱「扣費用前（直接毛利）」（會計報表的「稅後淨利」是科目，不改）。修改紀錄欄位名稱新舊並列（舊紀錄仍存「淨利率」）。
- **第 52 班規劃（未上線）**：公益捐款改報價含稅金額×1%（`charityBasis` 戳記、預設 direct），見 `CHARITY-QUOTE-1PCT-DESIGN-T52.md`；上線後本節再補。

**採購單／請購單／出納（第 46～48 班）**
- 簽核佇列詳情依單據類型顯示表單欄位（備註說明、緊急程度…），不再顯示舊版額外支出專用的空欄位；金額類欄位標籤命中遮蔽表者不顯示；出納待付款與「我的申請」標題＝「類型名稱｜品項摘要」，採購單收款人＝廠商、零用金＝支付對象；沒有另存收款人與銀行資料的採購單／零用金**不再退回申請人的員工收款帳戶**（出納頁警示）。
- 採購單表單多「廠商收款帳戶」（銀行／分行／帳號／戶名，選填；帳號去空白與連字號後須 5～20 碼數字，否則 400）。額外支出清單／我的申請／變更申請提議裡的 `payeeAccount` **只給末四碼**，完整帳號只給財務角色與最高管理者，且只經出納『查看收款人銀行資料』（嚴格提供者 `FULL_ACCOUNT_STRICT`：先寫稽核 `cashier.payee_bank_view`，寫不進去 ⇒ 500 且不回帳號，`no-store`）；變更申請／草稿 PATCH 沒帶收款人欄位＝保留原值，把遮罩值原樣送回 ⇒ 400。
- 缺廠商收款帳戶擋付款（預設關）：`system_settings.po_bank_block_since`（缺／空＝關）；只對切換時間點之後建立的採購單（收款人是廠商、銀行名稱或帳號任一為空）擋出納登錄付款與 `PATCH …/dates` 設付款日（409，什麼都不寫）；`GET /api/extra-expenses/po-bank-block`（財務角色／最高管理者）、`PUT`（只有最高管理者，稽核 `settings.po_bank_block.update`）。
- 出納改預定付款日：與登錄付款同時發生 ⇒ 409；日期沒變 ⇒ 不寫、不稽核、不通知。提醒信／站內通知／行事曆規則已搬到 L1 `helpers/payable_due_core.py`（IP-114 `contractor_voucher.planned_changed`）；本模組只留「查案件額外支出＋叫料匯款待付款列」。

**旗標嚴格解析（第 49～50 班）**：請求本文的旗標（`cascade`、`received`、`internal`、階段 `done`、`hasFee`、`enabled` 等）一律經 `helpers.validation.body_flag`／`strict_bool`——只收真布林（含整數 0／1），字串 `"false"`／`"0"`／`""` ⇒ 422 且什麼都不寫。這些旗標以前用真值判斷，字串 `"false"` 會被當成 true。

**其他**：IP-12 `case.access` 新增 `allowed(conn, quote_no, user, allow_module=None)`（不丟例外的可見判斷，供網路規劃書等依案件過濾）；報價人電話／Email 由 `GET /api/users/sales-contact` 帶入（使用者清單對一般人員不再含別人的聯絡方式）；報價單表單 `FORM_VERSION` 現為 V3.19（內容變動必須升版並登記 LEDGER，守門 `test_form_version_bumped`）；案件頁派發卡片的「勞報單」區塊（單號、狀態、受領人，**無金額**；連結／解除只有最高管理者）與「同一人員的勞報單」；承攬商匯款建立視窗可填預定付款日。
**第 51 班（隨列車）**：單據狀態徽章依狀態上色（共用晶片 `.st-chip` 與對照表 `static/status-chip.js`；已核准／已駁回／待審核／已作廢…各自不同色，全走語意 token）；材料卡片『對應材料申請』列出同案件已核准採購單、尚無材料申請的候選，選取＝帶入草稿並連結（仍須選供應商、儲存、送審、核准後才能勾「已申購」；看不到金額的帳號不顯示候選）。

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
- 對**舊口徑（含稅）**的已完結案「重新開啟再完結」會把它轉成新口徑（未稅）：營業利益（舊稱淨利）基數 +0.99×承攬商稅額；已發放的獎金不會被重算。這是刻意的，改之前要知道。
