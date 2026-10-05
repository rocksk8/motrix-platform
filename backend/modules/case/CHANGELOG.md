# 案件 更新紀錄

## 1.0.144 — 2026-10-05（wip/t42-planned-pay-date）：行事曆事件不含金額；稽核 T41 S1～S5 修正
- **行事曆事件不含任何金額**（使用者 2026-10-05 裁示：公司行事曆看得到的人不一定有財務金額可視）：`receipt_calendar.py` 的「收款登錄」「應收到期提醒」與 `payable_calendar.py` 的「付款待辦」，標題與說明都不再放應收／實收／手續費／金額，只留案號、客戶、專案、款項名稱、日期、入帳帳戶、登錄人（付款待辦另有單號、名目、受款人、付款條件）。**第 41 班（case 1.0.141）出貨的版本說明裡有金額**；三種事件預設關閉，開著的公司之後新建／更新的事件即不含金額，已建立的舊事件說明不回頭改。事件簽章同步改為（日期、款項名稱、入帳帳戶），金額／百分比／備註變動不再觸發推送。
- `payable_reminders.py`：`payable_due_soon`／`payable_due_today` 的預設群組在有「財務」群組時用它（`to_group`），否則維持只走 `finance_recipients()`（收件設定頁覆寫才與其他財務信一致）。
- S1 信件／畫面文字與註解的「請款待付款」→「待付款申請」（`expense_notify.py` 出納待撥款信、`payable_reminders.py` 提醒信等）。
- S4 `receipt_calendar.py`：到期／收款事件的簽章納入應收金額、款項名稱（改了這些，事件說明也會更新）；檔頭記載限制——事件種類打開前就存在的款項不回補、案件層欄位（客戶／專案名）改了不回頭更新既有事件。

## 1.0.143 — 2026-10-05（wip/t42-planned-pay-date）：預定付款日＋提醒信＋行事曆「付款待辦」（疊在 t41 之上）
- **case migration v7**：`case_extra_expenses.planned_pay_date TEXT NOT NULL DEFAULT ''`（`0007_planned_pay_date.py`；只新增欄位、冪等、舊列維持空；回滾程式碼不必動資料）。選填、不是實際付款日；付款後保留當歷史。
- API：`ExtraExpenseIn.plannedPayDate`（建立／編輯；編輯沒送＝保留原值、`''`＝清除；格式不合 400）；`PATCH …/extra-expenses/{id}/dates` 可補登／改期（任何狀態，但已付款後 409；權限同既有日期補登：填寫人、管理員、出納）；列表與 IP-100 `payables.pending` 的項目多 `plannedPayDate`。
- 請款頁（一般＋定義表單）多「預定付款日（選填）」；出納「請款待付款」清單多一欄（可直接改期、已逾期／3 天內標示）。
- `payable_reminders.py`：預定付款日前 3 天（`payable_due_soon`）與當天（`payable_due_today`）寄信；只對已核准、未付款、未作廢、要出納付款的類型；名義日（預定日、預定日−3 天）落在週六日就提前到前一個工作日寄（週一至週五；國定假日未納入，見 `payable_reminders.is_working_day`），兩封折到同一天只寄「今日到期」一封；guard key 以（案件, 種類, 預定日, 寄信日）冪等（改日期重發、過期 key 自動清）；信內不放金額。收件人經單一入口 `finance_recipients(conn)`——**暫時的本地樁**（財務角色＋最高管理者；TODO：換成 wip/t42-finance-role 的 helper）。每日檢查由 `case_deadlines.run_daily_checks` 呼叫。
- `payable_calendar.py`：行事曆「付款待辦」（L1 `payable_due`，預設關）跟著現況走——核准／改預定日／清空／作廢／付款日被更正，commit 後同步 upsert 或 delete；出納付款（M05）以 IP-100 的 `來源:key` 直接收回，不讀本模組的表。
- 測試：`tests/test_payable_planned_pay_date_2026_10_05.py`（migration 冪等、API、IP-100 欄位、行事曆跟現況走、3 天前／當天／冪等／退訂／無日期略過／收件人權限、guard 清理）。

## 1.0.142 — 2026-10-05（wip/quick2-wording，併入 t41）：出納來源名稱「案件支出申請」
- `payables.py` `SOURCE_LABEL` 「案件額外支出（請款）」→「案件支出申請」（出納待付款列的來源）。只改畫面文字；客戶「請款單」（M05 應收）不動。

## 1.0.141 — 2026-10-05（wip/t41-calendar-receipts）：行事曆「收款登錄」「應收到期提醒」
- 新增 `receipt_calendar.py`：比對款項期別（`caseRecord.payment.items[]`）寫入前後的 `received`／`receivedAt`／`actualAmount`／`feeAmount`／`bankAccountName`／`expectedReceiptDate`，產生行事曆事件的 upsert／delete；沒變就不開背景執行緒、不打 Google。事件以（種類、案號::期別 id）為唯一識別，沒有 id 的舊期別不推。
- 三條寫入路徑在 commit 之後推（不在寫鎖內）：`update_case_record`（整包存）、`mark_payment`（出納標記收款）、`_apply_case_change_request`（半解鎖審核通過重播：`case_record_update`／`payment_mark`，由 `approve_case_change` 在放鎖後推；排進佇列時不推）。
- 兩種事件預設關（L1 `EVENT_TYPES`，見 core CHANGELOG (next)）；標題不含金額，金額只在說明（應收、實收、手續費）。「付款待辦」（`payable_due`）本班不做：待付款清單沒有「預計付款日」欄位（主持裁示 A）。
- 測試：`tests/test_receipt_calendar_2026_10_05.py`（差異判斷 8 題、三條寫入路徑、開關關閉零流量、孤兒／手動刪除、推送失敗不影響存檔）。

## (next) — 2026-10-05（wip/t42-finance-role）：財務角色
- 財務／出納權限改由「財務」角色決定（admin／sales 直通拿掉）：額外支出列／金額可見與付款日登錄、標記收款與整包存款項鎖、更換發票號碼、收款帳戶查詢、稅額沖銷申請與取消、財務彙總清單、叫料發票日、取消已核准叫料單、叫料匯款申請撤回／作廢、叫料編輯閘（`can_edit_orders` 去掉 admin 直通）——一律 `has_finance_access`／`has_cashier_access`（僅 `finance` 角色與 superadmin）；出納／獎金通知收件人改走 `finance_usernames`；前端 `canFinanceRole()`。簽核人／申請人例外不變；一般管理（`_can_modify`、案件列範圍）不動。測試：`tests/test_finance_role_2026_10_05.py`。

## 1.0.140 — 2026-10-05（wip/quick-pr-wording）：請款頁文字改為「支出申請」
- 選單「新增請款」→「新增支出申請」；`payment-request.html` 標題「支出申請」、分頁「新增申請」「我的申請」、區塊「申請類型」、說明文字同步。只改畫面文字（含 `<title>`），資料與流程不動；簽核佇列徽章、簽核設定單據名稱、申請頁類型下拉的「案件額外支出」→「案件支出申請」（`routers/approval_queue.py`、`helpers/tiered_approval.py` 標籤同步；內部代碼 `extra_expense` 與表名不動）；「額外支出變更」→「支出申請變更」（佇列標題＋變更申請的通知／信件文字）。其餘「請款」字樣（出納、審核佇列、請款類型編輯頁等）本次不改。
- 測試：`tests/test_e2e_payreq_2026_09_27.py` 選單文字斷言同步。

## 1.0.139 — 2026-10-05（wip/t40-fe-05）：精算頁稅基標籤對齊伺服器鍵名（純前端）
- 稅基標籤的取值改用伺服器 `taxBasis` 的鍵名（`itemEstimate`／`purchase`／`remitFee`／`customExpense`，其餘同名），伺服器有值就顯示它的 `label`，沒有才退回頁面常數；不改伺服器鍵、不改任何金額。測試：`tests/test_e2e_settlement_tax_labels_2026_10_05.py`（逐鍵覆蓋）。

## 1.0.138 — 2026-10-05（wip/t40-case-be）：精算端點拆檔、完結要已成案、稅基標示（階段 0）、稽核 T39 修正
- **純搬移（零行為變更）**：`GET／PUT /api/quotations/{quote_no}/settlement` 與 `SettlementIn` 自 `api/quotations.py` 逐字搬到新檔 `api/settlement_api.py`（路由路徑、函式名、驗證相依不變；router 在 `quotations` 之後立即註冊）。守門 `tests/test_route_table_golden_2026_10_05.py`：整個應用的 OpenAPI 路由表與搬移前逐位相同、精算網址仍先被精算端點匹配。
- **完結要求報價單已成案**：`PUT /settlement` 的 `status=finalized` 在報價單 `deal_tag` 不是「已成案」或「已結案」時回 409「這張報價單還沒成案…」（已結案＝管理員重新開啟後再完結）；草稿存檔與重新開啟不受影響。
- **進項稅階段 0（只標示，不改任何金額）**：`settlement-actuals` 新增 `taxBasis`（品項估計＝含稅×1.05、採購單／材料申請＝含稅最終金額、額外支出＝未拆稅、承攬商＝未稅＋人員、匯款手續費／自訂支出＝實付）；結案報表 PDF 的成本分項旁加稅基說明行（`SETTLEMENT_ROWS` 標籤不動）；守門題釘住 `ESTIMATE_RATE == 1.05`。
- **稽核 T39**：S-1 PDF 差額說明改為「原始預估已扣報價預留間接成本 R（實際只計單據）；其中未被實際成本抵用 Y；其他 Z」（Y＝clamp(R − max(原始直接毛利 − 實際毛利, 0), 0, R)；Z＝淨利差額 − Y；與營運報表同一規則）；S-2 `original_side()` 對舊虧損報價存的負 `charityDonation` 也下限 0（預留隨之重算，原始淨利不變）。伺服器 `schemaVersion` 判斷為 `>= 2`（契約），頁面請對齊。
- **稽核 T40 S-1**：結案報表品項「實際成本」欄與精算後端同一條規則——`schemaVersion >= 2` 時數字（含 0）印出、null／沒有＝「未填寫」；舊存檔 0＝「未填寫」不變。
- 測試：`tests/test_settlement_t40_be_2026_10_05.py`。

## 1.0.137 — 2026-10-05（wip/t40-fe-05）：精算成本品項顯示真的 0、精算頁標示各來源稅基、首頁財務面板隨 financeVisible、稅基標籤對齊伺服器鍵名（純前端，不改任何數字）
- `case-management.html`（案件→精算摘要）與 `reports.html`（結案精算明細）的「成本品項」依 `settlement.schemaVersion`：≥2 時 `actualTotalCost` 為數字（含 0）＝有填，顯示 `NT$ 0`，`null`／空才顯示「未填寫」／「—」；舊存檔（沒有標記）0 仍視為未填，顯示不變。不改任何公式與後端。
- **增修**：`schemaVersion` 一律以 `Number(sv) >= 2` 判斷（與伺服器同規則）；案件頁／報表的公益金：≥0 顯示「− 金額」，舊的凍結負值顯示帶號金額（不再有「− −50」）。
- **稅基標示（VAT 階段 0）**：精算頁每個成本來源標稅基——品項估計「含稅 ×1.05（假設不可扣抵）」、手填依稅別、採購單／材料申請「含稅」、額外支出「未分稅」、承攬商派發「未稅（＋外包人員）」、匯款手續費／自訂「實付金額」；總結加一行口徑說明與 ⓘ（原始總成本未稅、原始毛利另扣進項稅 5%、精算後品項含稅）。只加文字，不改任何金額；伺服器之後回 `taxBasis` 時以它為準。測試：`tests/test_e2e_settlement_tax_labels_2026_10_05.py`。
- 測試：`tests/test_settlement_item_cost_display_2026_10_05.py`（node 載入分檔，兩種顯示＋舊存檔不變）。

## 1.0.136 — 2026-10-04（wip/t39-case-be）：公益金下限 0、實際成本 0 是真的 0（schemaVersion 2）
- **公益金下限 0**：毛利為負時 `charityDonation = 0`（不再算出負的公益金）；完結重算比對、`fill_downstream`、報價原始側 `origCharity`（報價 `tot` 沒有該欄時伺服器算）同一條。毛利 ≥ 0 與已凍結的完結 summary 完全不變（不改寫）。舊頁面對毛利為負的案件送負的公益金 ⇒ 完結 409（要用新頁面）。
- **精算存檔頂層 `schemaVersion`（整數；沒有＝1＝舊存檔）**：`PUT /settlement` 驗證（非 ≥1 整數 ⇒ 422）、原樣存檔、`settlement-actuals` 回傳 `schemaVersion`。**v2：品項 `actualTotalCost` 是數字（含 0）＝已填、null／沒有／空字串＝沒填（用估計）**；沒有標記的舊存檔維持「0＝沒填」。套用在 `compute`（`actual.source` manual／estimate）、完結比對、凍結讀取。
- **原始側資訊列「報價預留間接成本」**（使用者裁示 a）：`original_side()` 新增 `origIndirectReserve`＝報價 `tot.totalIndirect` − `origAdminCost` − `origCharity`（報價沒有 `totalIndirect` ⇒ 0），完結時與其他原始側鍵一樣由伺服器覆蓋並隨 summary 凍結；結案報表 PDF 的「原始預估」欄多一列、差額橫幅多一行拆解（只在該鍵 > 0 時出現，舊完結案輸出逐位元不變）。**不改任何淨利／獎金基數／實際側金額。**
- 測試：`tests/test_settlement_t39_be_2026_10_04.py`。

## 1.0.135 — 2026-10-05（wip/t39-fe-05）：公益金下限（虧損案以 0 計）、實際成本 0＝真的 0、報價預留間接成本資訊列（前端）
- **公益金不為負**：精算頁（實際側與原始側）與報價單表單，毛利為負時公益金以 0 計並顯示「虧損案公益金以 0 計」；已完結的精算照存檔值顯示，不回頭改寫。
- **實際成本 0＝真的 0**：新存檔帶 `schemaVersion: 2`；品項實際成本空白（`null`）＝未填、用估計（來源「估計」），填 0＝實際為 0（來源「手填」、毛利＝報價），輸入框有預設單價提示與「清除」鈕可回到未填；舊存檔（沒有標記）0 仍視為未填，載入後數字與舊版一致，重新存檔才升級。
- **報價預留間接成本**：總結「扣管理費／公益後」區塊的原始欄多一列資訊列（報價單淨利已扣的間接成本預算＝間接合計 − 管銷 − 公益），實際欄寫「以單據為準（已含於實際總成本）」，最終淨利列的差額欄說明「其中報價預留間接成本 X」，讓原始欄加得起來、不再出現假的多賺；已完結讀存檔的 `origIndirectReserve`（舊案沒有＝不顯示）。
- 只動 `frontend/pages/settlement.html`、`quotation-form.html` 與 e2e；後端對應（`schemaVersion`、公益金下限）由後端分支處理。測試：`tests/test_e2e_settlement_zero_and_loss_2026_10_05.py`。

## 1.0.134 — 2026-10-04（wip/t38-case-be）：精算後端強化（完結覆蓋、樂觀鎖、負數採購、派發併入列、歷程快照）
- **完結時下游欄位一律以伺服器值覆蓋**（`fill_downstream`）：過去只補「沒送的」，容差內的偏差照存；現在 `dispatchTotal／remitFeeTotal／customExpenseTotal／totalActualCost／毛利／管理費／公益金／淨利／利潤率／quotedPretax` 一律寫伺服器重算值。`summary` 缺 `itemActualTotal`（或沒有 summary）⇒ 不再照存（可偽造），改由伺服器重建所有計算欄位（非計算欄位保留）。選此而非 422：不擋任何合法呼叫端、結果由伺服器決定。
- **`PUT /settlement` 樂觀鎖**：`SettlementIn.expectedUpdatedAt`（選填）與報價單 `updated_at` 不同 ⇒ 409 不存檔；`GET /settlement` 回 `updatedAt`；舊頁面不帶欄位不受影響。**整份報價存檔**（`PUT /api/quotations/{no}`）不再採用 client 的精算本文，一律沿用資料庫的（過期副本不會蓋掉別人剛存的精算）。
- **負數／零和採購列算「有採購」**：`hasPurchase` 改為「有採購單／材料申請／額外支出／派發列」而非 `purchased>0`；退款列（負數）、正負相抵為 0 的列在「採用」時一樣取代估計。
- **派發被品項吸收時的分項列**：完結 summary 新增 `dispatchAbsorbedTotal`（隨 summary 凍結；舊案沒有＝0）；結案報表 PDF 與獎金分潤 PDF 精算表在 >0 時多一行「已併入品項」，讓分項加總＝實際總成本（`SETTLEMENT_ROWS` 11 列與標籤不動）。
- **編輯歷程**：完結紀錄附快照（`netProfit／totalActualCost／dispatchBasis／frozenAt`）；同一人連續的精算草稿存檔合併成一筆、精算草稿紀錄最多留 50 筆（完結／重新開啟理由不合併不丟）。`settlement-actuals` 新增 `orphanItems`（存檔裡有、報價單已刪的品項，唯讀）。
- **稽核 AUDIT-T38 修正**：①（H-1，既有高風險）`POST /api/quotations` 新建時丟掉用戶端帶的 `settlement` 並強制 `dealTag=''`——原本可直接建出已結案／已完結／淨利 99,999,999 的報價單；整份報價存檔（PUT）本來就不能改成案狀態與精算本文（有題鎖定）。②（S-1）完結時「原始側」欄位（`quotedTotal／origTotalCost／origDirectProfit／origMarginPct／origAdminCost／origCharity／origNetProfit／origNetMarginPct／profitDiff`）也由伺服器依報價單重算。③（S-2）36／37 班完結案只有頁面寫的 `dispatchAbsorbed`：PDF／獎金 PDF／`_freeze` 讀取時 fallback（唯讀，不改寫資料）。④（S-4）完結成功的回應多帶 `summary`（伺服器覆蓋後凍結的版本）。
- 測試：`tests/test_settlement_t38_be_2026_10_04.py`。

## 1.0.133 — 2026-10-04（wip/t38-fe-05）：精算頁前端第 38 班（樂觀鎖與未存編輯保護、完結採用伺服器 summary、失敗訊息不誤導、無障礙、版面、品項刪除提示）
- **只動 `frontend/pages/settlement.html` 與 e2e**：存檔帶 `expectedUpdatedAt`，409 ⇒ 衝突橫幅＋「重新載入」並停用存檔／完結，絕不悄悄覆蓋；完結／重新開啟成功才改本頁狀態，失敗（403／422／409／500）本頁維持原狀並重新取得伺服器狀態（純網路錯誤除外）；失敗訊息一律中文、錯誤停 10 秒且 `role=alert`／`aria-live=assertive`；載入失敗顯示中文橫幅（404 與「不存在」同句，不顯示後端原文）。
- 「存檔有、報價單已無」的品項唯讀清單（`orphanItems`）；`hasPurchase` 與後端同規則（有採購列即取代估計，含相抵為 0／負數）。
- 無障礙：實際數量／單位成本／稅別／備註／來源標籤的 `aria-label`（含品項名），圖表群組有文字說明（`aria-describedby`），「前往」鈕可聚焦且有 `aria-label`。
- 版面：1250px 以下摘要列不 sticky（避免折成多列遮住內容）；列印固定 5 欄單列。不改任何公式。測試：`tests/test_e2e_settlement_t38_fe_2026_10_04.py`。

## 1.0.132 — 2026-10-04（wip/t37b-settle-layout-fe）：精算頁版面置中、摘要卡不被裁切（純前端）
- **只動 `frontend/pages/settlement.html`**：頁面內容改為置中容器（最大寬 1400px、左右對稱）；頁首摘要卡改為自動換欄（`auto-fit`），字級隨寬度縮放，「毛利／毛利比」「最終淨利／淨利比」的金額與比例窄時自動換行，不再被右側裁掉。不改任何公式、後端與存檔欄位。
- 測試：`tests/test_e2e_settlement_layout_2026_10_04.py`（1280／1440／1920／420 寬度：摘要卡文字無裁切、容器左右邊界對稱）。

## 1.0.131 — 2026-10-04（wip/t36-dispatch-offset-fe）：精算頁管理視角（純前端；總結列標籤對齊獎金 PDF）
- **只動 `frontend/pages/settlement.html`（前端）與 e2e，後端與公式不變**：頁首摘要列、需處理清單、完結前檢查（未對應只警示；對帳差額≠0 才停用完結鈕）、品項毛利／毛利比／單件毛利、賺賠總表（含「未對應項目」與「折扣／調整」列與兩條對帳）、扣費前後對照、三張 inline SVG 圖、稽核頁尾、列印版面。
- 品項毛利＝報價單品項金額 − 實際成本；總成本取畫面 summary（與後端 `totalActualCost` 同一規則，派發被品項吸收的部分不重複計入）。門檻與政策集中在頁面 `STL_CONFIG`。
- 總結區塊的列標籤與獎金分潤 PDF 的 `SETTLEMENT_ROWS` 逐字一致（真實毛利率、管銷分攤（10%）、公益捐款（1%）、真實淨利率…），原有說明改放副標。
- 送出 `actualSource`（手填／歷史未建系統／人力標籤，後端已支援）。測試：`tests/test_e2e_settlement_dispatch_offset_2026_10_04.py`。

## 1.0.130 — 2026-10-04（wip/t36-dispatch-offset-be）：承攬商派發可回推報價單品項
- **offsets 新增 `kind: "dispatch"`（`ref`＝`contractor_dispatches.id`）**：派發單整張歸單一品項，規則與材料申請相同（規格 `DISPATCH-OFFSET-SPEC.md`）。`compute()` 新增 `unassigned.dispatches[]`、`items[].dispatch`、`totals.dispatchUnassignedTotal／dispatchAssignedTotal／dispatchAbsorbedTotal`；`dispatchTotal` 語意不變（未對應＋已對應＝dispatchTotal）。金額＝未稅承攬費＋外包人員（稅額只顯示）。
- 規則 A 併入：採用時品項實際＝材料申請＋採購單＋派發的合計取代估計，`totalActualCost` 扣掉被吸收的派發（不重複計入）；不採用時對應／取消對應不改總成本。`sources`／`purchasedTotal`／`pendingTotal` 不含派發（舊案逐位相同）。
- `validate_offsets` 認 dispatch（須在目前未對應清單、品項存在、單一去處；舊存檔原樣列放行）；完結比對與補齊 `dispatchAssignedTotal／dispatchUnassignedTotal`，隨 summary 凍結（舊完結案沒有這兩鍵＝已對應 0）。
- 品項選填欄位 `actualSource`（`manual`／`legacy`／`labor`，沒有＝manual）：顯示用標記，存檔／凍結原樣保留、`compute()` 的 items 回傳；值域外 422；不進任何金額或完結比對。
- `settlement_actuals.dispatch_rows()` 為派發列單一來源，`case_extras().dispatch` 合計改由它產生（輸出不變）。測試：`tests/test_settlement_dispatch_offset_2026_10_04.py`。

## 1.0.129 — 2026-10-04（wip/t35c-settle-assigned）：重新開啟理由的可見範圍
- **重新開啟理由只給有財務檢視的人看（0c 稽核）**：理由是自由文字，沒有財務檢視（`money_visible()` 為否）的帳號從單筆案件 GET、`/versions`、`/case-bundle` 拿到的編輯歷程只留誰／何時／事件，不含理由；沿用 CM13 遮蔽（`helpers/financial_mask.py` 新增 `strip_history_reasons`，由 `mask_quotation_data` 與 `/versions` 呼叫）。案件清單的「最近一次修改」本來就不帶理由。稽核紀錄 `audit_log` 的 detail 仍帶理由，由 `audit_log` 模組權限把關。
- 重新開啟對話框加一行「原因僅財務人員可見」。README 補：對舊口徑已完結案「重新開啟再完結」會轉成新口徑（淨利基數 +0.99×承攬商稅額，已發放的獎金不重算）。
- 測試：`tests/test_case_reopen_reason_visibility_2026_10_04.py`（掃出 OpenAPI 裡路徑帶案件單號的**每一支 GET**，無財務檢視帳號都不可拿到理由；有財務檢視者仍看得到；修改前 3 支端點外洩、紅燈）。

## 1.0.128 — 2026-10-04（wip/t35c-settle-assigned）：結案報表 PDF 的承攬商稅額說明
- **結案報表 PDF：新完結案多一行承攬商稅額說明（使用者裁示）**：「損益分析」的實際成本精算表在「承攬商派發成本」下加一行「承攬商：未稅 X／稅額 Y（進項稅額，不計成本）」，只在新完結案（`summary.dispatchBasis`＝`pretax`）出現；舊完結案印出的 HTML 與改版前逐位元組相同（已用改版前的函式逐份比對：舊口徑、空 summary、無標記三種）。新增 `tests/test_pdf_closing_dispatch_tax_2026_10_04.py`（repo 第一份結案報表 PDF 文字測試）。

## 1.0.127 — 2026-10-04（wip/t35c-settle-assigned）：完結被擋的訊息改為中性
- 測試補強（0c 稽核 (d)）：自訂模組支出非 0 的完結 fixture（誠實完結要過；偽造 0 並讓其他欄位一致仍被擋，已用拿掉檢查的反向控制驗證）。README 的『已知限制』改為『護欄』說明。
- **完結被擋的訊息改為中性（0c 稽核 (c)）**：409 前綴由固定的「採購單、材料申請或額外支出在你編輯期間有變動」改為「完結前系統重算的數字與畫面不一致（資料在你編輯期間有變動，或精算頁版本過舊）——請重新整理精算頁再完結」，因為不符的可能是承攬商或利潤欄位；後面的差異欄位清單不變。

## 1.0.126 — 2026-10-04（wip/t35c-settle-assigned）：已完結精算再存要有理由並重新比對
- **對已完結的精算再存要有理由且重新比對（使用者裁示；0c 稽核 (a)(b)）**：`PUT /api/quotations/{no}/settlement` 對已完結的案件（超級管理員的重新開啟路徑）一律要非空白理由（≤500 字，否則 422）；理由寫進編輯歷程（`reason`、`from: finalized`）與稽核紀錄 `quotation.settlement`。再存成「完結」時跑和第一次完結相同的後端重算比對（F1）並補蓋 `dispatchBasis`；舊口徑頁面送的含稅數字會被擋（409），要先重新開啟再完結。已凍結的舊案讀取不重驗、不改寫。
- 精算頁「重新開啟」改為對話框，必填理由（沒填不送出，畫面與存檔維持完結；後端拒絕時畫面不停在草稿假象）。
- 取代 33-A5 的前提：測試 `test_settlement_finalize_recheck…::test_resaving_an_already_finalized_settlement_…` 改為「要理由、也會比對」。

## 1.0.125 — 2026-10-03（wip/t35c-settle-assigned）：0c 稽核修正（完結口徑、已對應列深色對比）
- **精算頁完結口徑（0c M2）**：真實頁面完結改用新口徑（未稅）；e2e 改為「草稿→在瀏覽器按完結→讀存檔 summary」，並與營運報表權責口徑逐位比對（先前的『新完結』測試寫的是合成 summary，沒走真實頁面，所以沒抓到）。
- **已對應列深色模式（0c M1）**：本頁深色是整頁 invert，已對應列改用淺色字面值（反轉後為深底淺字），完結後唯讀下拉的灰字也加深；新增深／淺色、草稿／完結四種畫面的對比量測（≥4.5:1）。
- 已知限制（0c 稽核、不阻擋）：已完結案件的直接 PUT 不驗證也不蓋口徑標記（之後會被讀成舊口徑）；409 訊息前綴固定寫採購／材料變動；自訂模組支出非 0 的完結 fixture 未涵蓋——詳見 `README.md`「精算完結的已知限制」。
- **使用者可見的說明（0c S1）**：已完結的舊精算畫面有 1 處表頭文字變更與 2 行說明（舊口徑含稅、與完結時存的數字相同，屬刻意）；營運報表的毛利跨案件合計會混入舊口徑（含稅）與新口徑（未稅）完結的案件，屬設計、不另標示。

## 1.0.124 — 2026-10-03（wip/t35c-settle-assigned）：完結精算全欄位後端重算（F1，AUDIT-0C S7）
- **完結時後端用同一個 `compute()` 重算全部下游欄位**（承攬商、匯款手續費、自訂支出、總成本、毛利、管理費、公益金、淨利、毛利率、報價稅前收入），超出進位誤差回 409「請重新整理」且不存檔；原本只比品項／額外支出／採購類三塊，偽造 summary（0c S7 探針：dispatchTotal=0、netProfit=888888）可完結並凍結，而營運報表毛利直接讀 netProfit。
- 沒送的欄位不拒絕，存檔前由伺服器補上重算值並蓋 `dispatchBasis`；只在「非完結→完結」轉換時比對，舊完結案不重寫、讀取時不重驗。
- 精算頁修正：完結送出時狀態先變 finalized 導致誤判成舊口徑（含稅），頁面自己的完結 payload 會被擋；新增 `_finalizing` 旗標，成功後寫入 `_frozenSummary`。

## 1.0.123 — 2026-10-03（wip/t35c-settle-assigned）：精算稅基 B——承攬商成本改為未稅＋外包人員
- **稅基 B（使用者 2026-10-03「承攬商的部分稅金也跟正式做同步，避免有 5% 金額爭議」；對帳依據 AUDIT-0C S2）**：精算的承攬商成本改為「未稅承攬費＋外包人員」（營運報表權責口徑／總帳 E04 同一口徑）；承攬商稅額是進項稅額（總帳記 1268 資產），不是成本，只並列為資訊。範例（未稅 10,000、5%、人員 2,000）：計入成本 12,500 → 12,000，總實際成本 −500，毛利 +500、淨利 +495（公益金 1% 隨毛利）。
  - 端點（只加不減）：`totals.dispatchTotal` **意義改變**（未稅＋人員）、`dispatchReport` 保留（同值）、新增 `dispatchGrandTotal`（含稅，舊值）、`dispatchTax`、`dispatchBasis='pretax'`；`costExtras.dispatch` 保留 `grandTotal`／`report`，新增 `tax`。恆等式 grandTotal ＝ report ＋ tax，測試對帳 `recognition.dispatch_entries(accrual)` 與總帳 E04 未稅／進項稅額。
  - 頁面：精算頁「三、承攬商派發成本」顯示計入成本（未稅）與稅額欄，小計下方一行「未稅 X ＋ 外包人員 Y ＝ 計入成本 Z；承攬商稅額 T（進項稅額，不計成本）；含稅合計 G」；草稿第一次以新口徑打開有一行說明（可「知道了」，不彈窗）。案件頁派發分頁的「外包總成本」同口徑並註明稅額。
  - **舊完結案不改寫、不重驗**：存檔 summary 沒有 `dispatchBasis`＝含稅口徑，頁面照存檔數字顯示並加中性說明；新完結案帶 `dispatchBasis='pretax'`。三處「過期」比對（精算頁、案件頁財務分頁、營運報表 `staleSettlementCount`）口徑對口徑，舊案不會因口徑切換而誤報。
  - **獎金影響（財務／人資請注意）**：`payroll/bonus.py` 原樣帶出存檔的 summary，新完結案的淨利基數因此比舊口徑高「承攬商稅額×0.99」（例：承攬商稅額 500 ⇒ 基數 +495）；已完結的舊案不變。獎金程式本身未改，測試釘住「用存檔淨利」。
  - 消費者盤點見本班報告；承攬商派發單／匯款單自己的總額（`remit_create`／`contractor_vouchers` 的 dispatchTotal、派發表單的「派發總成本」）是單據金額，不屬於精算口徑，**不改**。

## 1.0.122 — 2026-10-03（wip/t35c-settle-assigned）：精算頁二之一已對應清單、已對應列顯示修正
- 修正（使用者截圖：「已經被帶入了，但額外支出還有顯示不對應，已採用也未消失」）：報價品項的 id 是**數字**時，二之一下拉的 `:selected="it.id === u.itemId"` 是 number === string ⇒ false，已對應的列一律顯示「（不對應，計入額外支出）」，但品項列的「額外支出 NT$…」與 API 都證明已對應。改用 String 比對。**金額沒有重複計算**（assigned 的額外支出在對應當下就離開額外支出合計；採用只改 adoptSystem 並重算該品項實際成本）；這是顯示問題，沒有改任何數字語意。
- 新增：二之一分成「未對應」與「已對應」兩張表。已對應表列出類型、品名＋說明、已對應到哪個品項（#號碼＋名稱）、金額；沖銷對應的列可「改對應／取消對應」，材料申請連結到品項的列唯讀（「由材料申請連結」）；品項未採用時照實標「該品項未採用：這筆金額目前不計入實際成本」（規則 D8 不變）。已對應列淺綠底＋文字徽章「已對應」＋圖例（用共用 tone 令牌，深色主題自動換色；不只靠顏色）。
- 新增（唯讀、加性欄位，同一個財務閘門）：`settlement-actuals` 的未對應／已對應材料列帶 `notes`（備註），額外支出列帶 `note`／`qty`／`unit`；頁面在品名下顯示「備註：…」「附註：…」，數量不是 1 時才顯示。非財務角色仍是 403，拿不到任何新欄位。材料申請本身沒有「規格」欄位（規格寫在品名裡）；採購單連到品項的列是自動歸屬、不在二之一。
- 重複對應：伺服器早有守門（同一 ref 兩個去處 422、已連品項的材料申請不在未對應清單 422）；新增測試釘住數字 itemId、預覽重複（第二個去處被忽略、總額不變）、混型 ref 重複、舊 offset 遇到後來才連結的列只算一次。儲存格式不變（offsets 仍是 kind／ref／itemId 三個字串鍵）。
- 測試：e2e 6 題（數字 id 紅燈對照、已對應表／徽章／色差／圖例、守恆＋儲存格式、取消／改對應、未採用提示、字串 id 回歸）＋後端 7 題；稅基 B：後端 6 題＋報表過期 5 題＋e2e 4 題，既有 3 題（cost_extras ×2、精算 e2e ×1）改成新口徑。

## 1.0.121 — 2026-10-03（wip/t35-settle-ui）：精算頁未對應清單帶品名、案件頁分頁列加精算入口
- 精算頁二之一「未對應品項的材料申請與額外支出」：材料列顯示品名＋數量單位、額外支出列顯示單號｜類別｜說明。後端只加欄位（`recognition.extra_entries` 列加 `description`；`material_money_rows` 加 `quantity`／`unit`，數量解析遇髒資料回 None 不丟錯；`settlement_actuals` 帶出），金額與規則不動。
- 案件頁分頁列在「額外支出」右邊加「精算 ▶」連結（`.cm-tab-link`，權限同精算頁）；財務分頁內舊連結保留。


## 1.0.120 — 2026-10-04（wip/t34-m2-maskfix-d7）：材料申請變更申請的金額可見度（da 稽核 must-fix）
- 修正：沒有財務檢視權、但有案件存取的帳號，打變更申請的三支讀取端點（單筆清單、案件層清單、變更提案預覽）會看到採購單行金額。現在差異裡涵蓋採購單行的新舊值、提案與原內容的涵蓋行、`uncoveredLines`、提案問題訊息中的已付金額一律遮蔽（金額欄位整項隱藏、行金額去掉）；財務檢視者不受影響。
- 修正：核准套用寫進審核歷程與稽核的差異摘要，金額欄位只寫「已變更」，不再帶單價／小計數字。測試：以「有案件存取、無財務檢視」的帳號打三支端點，斷言整個回應不含 amount／unitPrice／totalPrice 與其數值（反向控制：拿掉遮蔽即紅）；另測歷程與稽核文字。


## 1.0.119 — wip/t34-m1-coverage-c7：「從採購單帶入」依報價品項分組（34-M1 UI，E4）
- 新唯讀端點 `GET /api/quotations/{no}/material-coverage`：涵蓋分組（一個報價品項一組、內容＝該品項**全部已核准**採購單行的涵蓋快照；額外採購以採購單為單位各一組；審核中的採購單行不併入、只計 `pendingLines`；已有活的材料申請 ⇒ `existing`）。內容與送審的涵蓋檢查（`material_submit_check`）同一個函式，畫面不做金額運算；金額看不到財務檢視者不給單價／小計。
- 案件頁「從採購單明細帶入」改成帶「一品項一列」（數量／金額合計），已有申請的品項標「請用變更申請」且不能勾；涵蓋採購單的列：單價欄唯讀、小計固定（涵蓋行金額合計）、數量只能往下調（單價隨數量換算）。
- 測試：`test_material_coverage_view_2026_10_04.py`（4）、`test_e2e_material_coverage_import_2026_10_04.py`；`test_e2e_material_link`／`po_ui`／洩漏探針改成分組語意。
## 1.0.118 — 2026-10-03（wip/t34-m2final2-d7：33-M2c 材料申請變更申請，畫面與出貨連動接線；稽核寫入改在同一交易；出貨連動真提供者測試；modules.json 登記 mchange.js）
- 案件管理頁財務分頁新增「材料申請變更」面板（`case-management-mchange.js`）：選已核准的材料申請 → 查看差異（數量、小計、涵蓋採購單行；金額由已核准採購單決定）→ 填原因建立 → 修改／送審／撤回；簽核人在面板或簽核佇列核可／退回。核准前原材料申請內容照常有效；看不到財務檢視者金額顯示「金額已遮蔽」。沒有「有審核單」的材料申請時不發任何請求、不留 DOM。
- 新端點 `GET /api/quotations/{q}/material-changes`（案件所有變更申請）。變更申請的「不得低於已出貨＋占用量」接出貨連動（登記表 `shipping.material_shipped_qty`／`shipping.material_shipped`，保留＋已出貨；草稿出貨單不算）；沒有提供者時：出貨模組（supply）已載入＝拒絕（`shipped_unavailable`，fail closed）、沒有出貨模組＝只警告。提案數量不得超過涵蓋採購單行的數量合計（單位一致時，`quantity_exceeds_coverage`）。
- 修正：變更申請的稽核寫入函式改名 `_audit_row`（與 helpers 的另開連線寫入的 `_audit` 區隔；一直是用呼叫端的連線、同一交易寫入，commit 時一起落地），守門 `test_write_lock_deadlock_guard` 不再誤報；測試補「commit 後另一條連線讀得到每個動作的稽核」。

## 1.0.117 — wip/t34-ship-link-c7：材料申請的出貨連動（34-S3，案件側）
- `GET /api/quotations/{no}/material-order-approvals` 回應多一個頂層鍵 `shipping`：`{itemId: {appliedQty, arrivedQty, reserved, shipped, notes[]}}`（已到料或有出貨連動的材料申請；只經 M03 提供者 `shipping.material_shipped`，不讀 `shipping_notes`；提供者不在＝0）。材料申請卡片顯示「已申請／已到料／已出貨（占用中）」與出貨單號。
- 取消材料申請（`POST …/cancel`）：有活的出貨連結（占用中或已出貨）⇒ 409 並列出貨單號；退回／草稿的出貨單不擋；出貨提供者出錯 ⇒ 擋（fail closed）。
- 測試：`modules/supply/tests/test_material_ship_case_view_2026_10_03.py`（5）、`test_e2e_shipping_material_link_2026_10_03.py::test_material_card_shows_…`。


## 1.0.116 — 2026-10-04（wip/t34-m2-wire2-2e）：變更申請數量不得高於涵蓋量；送審內容必須涵蓋全部已核准採購單行（da 稽核）
- `change_proposal` 新增 `quantity_exceeds_coverage`：數量只能往下調，不得超過已核准採購單行涵蓋的數量（單位不同＝品項報價量）；否則一張變更就能把可出貨量灌大。
- `material_submit_check`（強制採購單路徑）新增 `content_not_cover_snapshot`：申請內容要涵蓋該品項**全部**已核准的採購單行——小計＝行金額合計（不可改）、數量只能往下調；只帶一行的申請（同品項多行採購單時）會被擋並提示正確內容（N2）。既有測試 `test_material_po_required` 的材料金額改成與採購單行一致（100×2）。
- 影響 UI：c7 的「從採購單帶入」要以**品項**為單位帶入全部行的內容（一個品項一列），否則第二個採購單行會被 `item_request_exists` 擋下。

## 1.0.115 — 2026-10-04（wip/t34-m2-wire-2e）：材料申請送審接上涵蓋快照、一品項一筆與調整單（34-M2 接線）
- `material_submit_check`（強制採購單路徑 `po_required`）新增：`item_request_exists`（同品項已有活的材料申請，訊息帶單號，提示追加請走變更申請；保留 `po_line_taken`）、`poSnapshot`（送審當下該品項所有已核准採購單行的涵蓋快照，存在審核列 `approval_json.linkSnapshot`）、`no_coverage`、調整單 `adjustOf`（原申請已全額付款才可；只涵蓋尚未被占用的採購單行，快照帶 `adjustOf`）。舊路徑（非強制）逐位不變。
- `material_coverage.snapshot_lines`：讀涵蓋快照時 `snapshot.poSnapshot`（變更申請核准後 d7 套用時改寫）優先於送審時的 `linkSnapshot.poSnapshot`。6 題接線測試。

## 1.0.114 — 2026-10-03（wip/t34-settlement-extras-2e）：精算端點納入承攬商派發、匯款手續費、自訂模組支出（34）
- `settlement-actuals` 新增 `costExtras` 與 `totals.dispatchTotal／dispatchReport／remitFeeTotal／customExpenseTotal／totalActualCost`：口徑與精算頁現行算法逐位相同（使用者裁示 A：歷史精算不變）——派發＝承攬商含稅合計＋外包人員（`dispatch.row` 的 grandTotal；排除已取消、草稿、已退回）；手續費＝額外支出手續費（已登錄付款、未作廢）＋承攬商匯款手續費；自訂模組支出＝`custom_finance.case_finance`。另輸出 `dispatchReport`（未稅承攬費＋人員，營運報表／總帳 `dispatch_entries` 口徑，供漂移守門）；兩者差異＝承攬費的 5% 稅，含稅或未稅由使用者決定（列第 35 班問題），這裡只並列。已完結精算的這幾個鍵取存檔 summary 的凍結值。`extraTotal` 語意不變（仍只含額外支出）。精算頁改取這些值（派發小計、匯款手續費、自訂模組支出；端點不可用時退回原本各打一支的舊路徑），金額與原本逐位相同；新增 e2e 對照頁面成本彙總與端點 totals。完結重算比對（D10）不含這三類（頁面端因無權限可能少打其中一支端點）。

## 1.0.113 — 2026-10-03（wip/t34-settlement-nits-2e）：精算——完結容差、凍結分法、POST 預覽（第 33 班稽核 nits）
- 完結重算的進位容差只套在「品項實際成本」（每品項 ±1 元）；額外支出、採購類總額、未採用採購只留 1 元防浮點（原本一併放寬成品項數）。
- 已完結精算的 `settlement-actuals`：`totals.materialUnassignedTotal` 取存檔 summary 的同名鍵、`extraTotal` 扣掉它與手續費、自訂模組支出，分法與完結前的即時值一致（舊完結案沒有這鍵＝0，合計不變）。
- 新增 `POST /api/quotations/{no}/settlement-actuals/preview`（沖銷對應放請求本文；上百筆不受網址長度限制），精算頁預覽改用它；`GET ?offsets=` 保留相容。

## 1.0.112 — 2026-10-03（wip/t34-ship-case-2e）：出貨單連動——可出貨材料提供者（34-S1 case 側）
- 新增提供者 `("material.shippable", "case")`（`modules/case/material_shippable.py`）：回傳已核准且已做到貨確認的材料申請 `[{materialItemId, docCode, name, unit, quoteItemId, appliedQty, arrivedQty, status}]`，供出貨單（supply）經 registry 取用、不互相 import。唯讀；`arrivedQty` 預設整筆到貨（E5），有選填欄位 `received_qty` 時取 `min(實收, 已核准量)`（欄位與到貨 API 的 `receivedQty` 後補）。契約與逐點答覆：SHIPPING-MATERIAL-LINK-CONTRACT-S1.md §8。

## 1.0.111 — 2026-10-03（wip/t33-m2b-d7：33-M2b 材料申請變更申請，端點、簽核整合與守門調整；重疊於 platform 1184efb0）
- 端點：`GET /api/quotations/{q}/material-orders/{item}/changes`、`GET …/change-proposal`（預覽）、`POST …/changes`（建立；body 只收 `reason／quantity／notes`，金額與涵蓋行由已核准採購單決定）、`POST /api/quotations/{q}/material-changes/{id}/revise|submit|approve|reject|withdraw`。看不到財務檢視者不給金額。核准最後一層 ⇒ 同一交易內套用，套不了回 409 且什麼都不改。
- 簽核整合：登記簽核單據類型 `material_change`（材料申請變更，預設跟統一流程）、簽核佇列與詳情（差異表：數量／單價／小計／涵蓋採購單行／備註 原→新）、站內通知與四種信件（送審／輪到您／核准／退回，信內不放金額）、稽核動作 `material_changes.*`。
- 守門：強制採購單之後建立的已核准材料申請，直接改內容被拒（`use_change_request`，訊息指向變更申請）；舊單與 grandfather 單維持「改了回草稿」。提案內容來自案件側 `material_coverage.change_proposal`，尚未上線時建立／預覽回 501。已核准後直接改內容改為被拒之後，舊測試（連結變動、匯款申請凍結）改依新規則斷言，並保留 grandfather 單舊行為的覆蓋；佇列提供者以字面值 `material_change` 通過佇列覆蓋守門。

## 1.0.110 — 2026-10-03（wip/t33-m2a-d7：33-M2a 材料申請變更申請，狀態機層）
- 新增覆核表 `case_material_changes`（migration 0006；單號 `MC-YYYYMMDD-NNNN`；部分唯一索引：一筆材料申請同時最多一張進行中的變更）與 `modules/case/material_change.py`：建立／修改／送審／核准／退回／撤回、驗證（數量／小計／已付鎖 `paid_in_full`、`below_paid`／不得低於已申請匯款額度／出貨下限提供者）、同一交易內原子套用（核准前原版本完全不動；核准後內容、審核列版本＋1、`content_hash`、涵蓋快照一併切換，已確認到貨不重置）。
- 本版**沒有端點、沒有畫面、不登記簽核單據類型**（屬 M2b）；舊單／規則上線前建立的單不走變更申請（`use_direct_edit`）。

## 1.0.109 — 2026-10-03（wip/t33-d7lock-d7-r2）：已全額付款的材料申請不可改金額（D7）
- 守門：已付總額（舊單歷史已付＋所有付款明細）≥ 小計的材料申請，數量／單價／小計不可修改（`paid_in_full`，訊息「已全額付款，金額不能修改；要調整請另開一筆材料申請…」）；其他欄位照舊；新小計低於已付由既有驗證擋下。新增 `material_payment.paid_so_far`。

## 1.0.108 — 2026-10-03（wip/t34-m2-coverage-2e）：材料申請涵蓋快照與變更提案（34-M2，唯讀新檔；尚未接線）
- 新增 `modules/case/material_coverage.py`（只讀）：`approved_po_lines`／`coverage_snapshot`（涵蓋該品項所有已核准採購單行的快照 `poSnapshot`，金額＝行合計，數量依單位規則；`only_untaken` 去掉已被占用的行）、`item_request_exists`（草稿／待審核／簽核中／已核准的活申請占用品項；`adjust_of` 且原申請已全額付款時不占用）、`taken_lines`、`paid_in_full`、`adjust_check`（D7 調整單條件）、`change_proposal(conn, quote_no, item_id, proposed=None)` ⇒ `{itemId, before, after, diff:[{field,old,new,money}], uncoveredLines, problems}`。problems：`not_found／use_direct_edit／not_approved／no_coverage／coverage_shrinks／bad_quantity／unknown_field／paid_in_full／below_paid／no_change`。
- 還沒有任何呼叫者（簽核與畫面由 d7／c7 接）；不改現有行為。

## 1.0.107 — 2026-10-03（wip/t33-settlement-a5b-2e）：精算頁手填實際成本 0 ＝沒填、完結失敗提示延長（c7 二審）
- 精算頁摘要把手填實際成本 0／空視為沒填、用估計（與重新載入存檔、後端 `manual_actual` 同一規則）：同一次編輯中清成 0 再完結不再被 409「頁面少一筆估計」。新增 e2e（輸入 0 ⇒ 摘要用估計 ⇒ 完結成功；移除修正即紅）。
- 完結被拒的提示（含伺服器說明，約 100 字）顯示 10 秒（原 3.5 秒）。

## 1.0.106 — 2026-10-03（wip/t33-po-off-c7、wip/t33-m1-ui-c7-r2）：33-M1 強制採購單（案件側 UI 上線）
- 材料申請新增只能從「已核准的採購單明細」帶入（E1／E2）：移除「＋ 新增項目」與「從報價單品項帶入」；審核中的採購單明細列出但不能勾；送審前提示「需先申請請購單，再申請採購單…」；已全額付款的列數量／單價反灰並說明。
- `material_approval.PO_REQUIRED` 預設 `True`（先前一版預設關；運維要回退舊流程設成 False）。
- `PO_REQUIRED_FROM` 改 `2026-10-04`：上線日（10-03）前在舊畫面建立的草稿都算規則前建立（grandfather），不會被擋送審（da 建議）。
- 回退開關題 `test_material_po_default_off_2026_10_03.py` 保留（明確設 False 驗舊流程）；預設值題在 `test_material_po_default_2026_10_03.py`。
- 測試：`test_material_po_default_2026_10_03.py`（預設值、預設強制、關閉時舊流程）；畫面 e2e `test_e2e_material_po_ui_2026_10_03.py`；`test_e2e_material_link`／`orders`／`approval`／`unsent` 改走採購單帶入（移除 `_po_rule_off`）。

## 1.0.105 — 2026-10-03（wip/t33-m1-ui-c7）：材料申請畫面改為只能從已核准採購單帶入〔train_number：1.0.104 → 1.0.105〕
- 案件管理頁材料申請：移除「＋新增項目」與報價品項入口，新增只能從已核准採購單的明細帶入；審核中的採購單明細列出但不可勾；送審前顯示提示；已全額付款的項目數量與單價反灰不可改。
- 本版程式與畫面已就緒，強制採購單規則的開關維持預設關閉（開啟時另行說明）。

## 1.0.104 — 2026-10-03（wip/t33-fix-31b-a3）：分期匯款視窗欄位補上已存欄位標記〔train_number：1.0.103 → 1.0.104〕
- 案件管理頁分期匯款申請視窗的輸入欄補上 `data-saved-field` 標記，供畫面守門判斷哪些欄位會被存檔；畫面與行為不變。

## 1.0.103 — 2026-10-03（wip/t33-settlement-a5-2e）：完結失敗時顯示伺服器訊息（c7 獨立審查）〔train_number：1.0.102 → 1.0.103〕
- 精算頁完結被拒（例如 409「完結前系統重算的成本與畫面不一致…請重新整理」）時，提示訊息帶出伺服器說明，不再只顯示「完結失敗」；並關閉確認視窗。

## 1.0.101 — 2026-10-03（wip/t33-grandfather-flag-d7）：舊單送審後被退回，重送不再被「需先申請請購單」擋住
- 修正：舊單（grandfathered）以有簽核層的流程送審時，重建審核內容把「舊單不適用強制採購單」標記丟掉；退回後重送、或核准後修改再送，會被當成上線後的新單擋下。現在送審保留該標記（測試補退回重送；反向控制：拿掉修正即紅）。

## 1.0.100 — 2026-10-03（wip/t33-po-off-c7）：33-M1 強制採購單出貨預設改關
- `material_approval.PO_REQUIRED` 預設 `False`：材料申請流程與第 32 包逐位相同（可手動新增、不必採購單即可送審）；規則本身與「補對應」仍在、設成 True 即強制。M1 案件側 UI 上線的 commit 再把預設翻成 True。
- 測試：`test_material_po_default_off_2026_10_03.py`（預設值、預設關時手動新增可存可送審、設 True 同操作被擋）；`test_material_po_required_2026_10_03.py` 明確設 True。

## 1.0.99 — 2026-10-03（wip/t33-settlement-a5-2e）：完結重算只在「非完結 → 完結」轉換時比對（da 覆審）
- 已完結的精算超級管理員再存（例如只改備註）不再跑完結重算——凍結快照本來就不隨之後的單據變動；草稿重開後再完結仍照常比對。

## 1.0.98 — 2026-10-02（wip/t33-remit-s4-a3）：承攬商分頁分期申請的發票欄位；試算顯示防過期
- 案件管理頁「承攬商」分頁：分期匯款申請列顯示該期發票（號碼／日期；未登錄顯示「未登錄發票（尚不認列）」）並可登錄／更正（31-B S4）；產生匯款申請視窗的試算改輸入時作廢在途請求（不會把舊輸入的金額蓋回畫面）、剩餘額度以四捨五入整數元比較（用 `MotrixLegalRound.halfUp`，金額進位守門；da 稽核 S3 兩項）。

## 1.0.97 — 2026-10-02（wip/t33-remit-s2b-a3、s3-a3）：案件應付彙總不計作廢的分期匯款申請；承攬商分頁支援分期匯款申請畫面
- 案件詳情的應付彙總（承攬商匯款申請）略過已作廢的分期申請（31-B S2b）；其餘不變。
- 案件管理頁「承攬商」分頁：派發卡片支援多張分期匯款申請（款別／期別／試算／作廢，31-B S3；規格見 subcontract 模組 SPEC RK10）。

## 1.0.96 — 2026-10-03（wip/t33-settlement-a5-2e）：完結精算後端重算比對（33-A5，D10）
- `PUT /api/quotations/{no}/settlement` 在 `status=finalized` 時用同一來源（`settlement_actuals.compute`，以請求本文的品項／offsets 計算、不套凍結）重算，與頁面送上的 `summary` 比對：品項實際成本、品項未採用採購（新規則恆 0）、額外支出（扣掉頁面加的手續費與自訂模組支出，含未對應材料申請）、採購類總額（頁面有送才比）；差異超過進位誤差（每品項 ±1 元）⇒ 409 並說明差異、不存檔，頁面需重新整理。只在「非完結 → 完結」的轉換時比對（已完結的再存是凍結快照，不重算）；草稿不比對；summary 沒有 `itemActualTotal`（非精算頁的呼叫）無從比對、放行。

## 1.0.95 — 2026-10-03（wip/t33-settlement-b1-2e）：精算頁改接後端單一來源（33-B1）
- 精算頁（`settlement.html`）載入改打 `GET settlement-actuals`：品項「採購」＝採購單連結金額＋材料申請（連品項或沖銷對應）＋沖銷的額外支出；規則 A——有採購的品項**預設採用**（實際取代估計）；取消採用＝回手填值、採購金額不另加（D8，只在彙總區警示「採購金額未採用」）。已存草稿以存的 `adoptSystem` 為準（缺鍵＝不採用，歷史相容）。
- 新區塊「二之一、未對應品項的材料申請與額外支出」：每筆可選一個報價品項（寫進 `settlement.offsets`，不改原單據；預覽用 `?offsets=`，不存檔），取消＝選回「不對應」；未對應的材料申請併入「額外支出」顯示行（含未對應材料申請）。
- 已完結：額外支出／手續費／自訂模組支出取完結當下凍結的 `summary`；`summary` 新增 `purchasedTotal`、`materialUnassignedTotal`（鍵名其餘不動，報表／獎金／PDF 照讀）。端點失敗或無財務檢視 ⇒ 退回 32-S5 舊路徑。
- `GET settlement-actuals` 新增選填 `offsets`（JSON，預覽）；完結凍結的 `extraTotal` 扣掉頁面加的手續費與自訂模組支出，與端點同義。更新 e2e `test_e2e_pr_po_item_link`（預設採用）、新增 `test_e2e_settlement_actuals`。

## 1.0.94 — 2026-10-03（wip/t33-settlement-a3-2e）：精算漂移守門＋歷史語料對照（33-A3，只加測試）
- `test_settlement_actuals_conservation`：10 個情境（採購單連品項／額外支出、材料申請連／不連採購單／無品項、狀態矩陣、$0 與舊單、品項被刪、待審核採購單、offsets 搬家、現金口徑）逐一斷言精算 `purchasedTotal`＝營運報表＝總帳 E11＋E12（扣待審核）；任何一邊改規則而另一邊沒跟即紅。
- `test_settlement_actuals_legacy_parity`：逐字照搬 `calcSummary()` 的參考實作對照語料（預設估計、含稅三種手填、額外支出各狀態、第 32 班前草稿缺 `adoptSystem`、缺說明／缺 id 舊品項、完結凍結）；`itemActualTotal`／`extraTotal` 逐位相同。
- 存檔實際成本＝0（正式機 13 個品項／6 張報價單真實存在）：與今天頁面載入存檔的 `si.actualTotalCost || oi.actualTotalCost` 同語意——0、空字串、null 視為沒填 ⇒ 用估計（`settlement_actuals.manual_actual`；da A3 S1）。頁面只讀 `actualTotalCost`，`actualQty`／`actualUnitCost` 為 0 不影響已存的總額；語料新增 0／空／null／0.0 與數量、單價為 0 的案例。0 元實際成本是否算缺陷：列第 34 班待裁示。

## 1.0.93 — 2026-10-02（wip/t33-settlement-a4-2e）：精算沖銷驗證（33-A4）＋A2 稽核修正（da S1–S3）
- `PUT /api/quotations/{no}/settlement` 對 `settlement.offsets` 驗證（422、不存檔）：kind 合法、品項必須在報價單內（缺 id／說明的舊品項不可當去處）、同一 (kind, ref) 只能一個去處、ref 必須在目前未對應清單；上次存檔原樣未改的列放行（材料申請事後取消不卡舊草稿）。完結後僅超級管理員可改（沿用）。
- `settlement-actuals`：已完結精算回凍結快照（`frozen`、品項金額取存檔 `actualTotalCost`、三個總額取存檔 `summary`，現算值放 `live`），不隨完結後核准的採購單漂移（S1）；舊存檔品項沒有 `adoptSystem` 鍵＝不採用（歷史相容，與今天頁面同；`legacySave`），品項沒存過＝採用（S2）；缺 id／說明的舊品項以暫時鍵納入並標 `unkeyed`＋警示，估計照算（S3）。唯讀計數 SQL：docs/platform/plans/SETTLEMENT-ACTUALS-PROBE.sql。

## 1.0.92 — 2026-10-02 21:08（wip/t33-settlement-a2-2e）：完結精算實際金額端點（33-A2）
- 新增 `GET /api/quotations/{no}/settlement-actuals`（案件可見＋財務檢視，否則 403／404）：`settlement_actuals.compute(conn, quote_no, offsets=None, unadopted="ignore")`，規則 A（有實際採購 ⇒ 實際取代該品項估計）、三態 adopt、沖銷（offsets）、未對應清單、sources／totals；金額與營運報表同源（`recognition.material_money_rows`、`extra_entries(quote_no=)`）。8 題測試。

## 1.0.91 — 2026-10-02 20:25（wip/t33-settlement-2e）：材料申請逐筆判定抽成共用原語（33-A1，行為零變化）
- `recognition.material_money_rows(conn, department_id=None, quote_no=None)`：每筆材料申請一列（審核狀態、`cost_state`、是否連到有效採購單、`noPo`、`total`），**不分口徑**；`material_entries`（營運報表／總帳 E12／E12b）改成它的投影，輸出與抽出前逐筆相同（測試把抽出前的實作凍結為參考、對 9 種情境的權責與現金口徑整份比對）。完結精算的後端端點（33-A2）將使用同一原語，三處金額不會漂。`_case_rows` 加選填 `quote_no`。

## 1.0.90 — 2026-10-03（wip/t33-m1-d7：33-M1 守門側，強制採購單）
- 新申請必須帶採購單連結（`po_required`，E1：後端面；沒有 `poDocCode` 的新列被拒、不留列、不建草稿）；`material_submit_check(po_required=…)`：送審必須連到「已核准」的採購單（三句提示：沒有／尚未通過／已退回或作廢），待審核／簽核中不算（E2）。
- 不溯及既往：舊單（沒有審核列）、規則上線前建立（`MA.PO_REQUIRED_FROM`）、舊單被編輯而建的審核列（`grandfathered`）不受約束，可「補對應」——只增連結鍵、不重簽、狀態不變，審核歷程與稽核各記一筆；有付款紀錄／匯款申請者不可補。
- 付款互斥（E3）用 2e 的 `_has_valid_po_link`（有效連結才擋）；`MA.PO_REQUIRED` 可由測試關閉。

## 1.0.89 — 2026-10-02 19:08（wip/t33-material-link-fix-2e）：連結失效後可開匯款申請（第 32 包探針）
- `material_payment.create`：「已對應採購單不能另開匯款申請」改看**有效**連結（`purchase_items._link_check`），不再只看 `poDocCode` 有沒有填。採購單作廢／退回後連結失效、金額回到材料申請時，這筆不再被卡住（既不能走採購單請款、又不能匯款）；連結有效時照舊 409。

## 1.0.88 — 2026-10-02（wip/t33-link-guard-d7）
- 守門：已有付款紀錄的材料申請，經 case-record 整包存檔也不可新增／改連採購單（`bad_link`「已有付款紀錄，不可對應採購單」）；`link_validator` 對 has_payment 放行（既有連結存回）後，這條擋在守門自己做，與專屬端點同規則。

## 1.0.87 — 2026-10-02（c7 第32包稽核 M-1）：出納差額審核表的手續費與付款日補回
- 修正：材料申請匯款在出納「差額審核」項目（`/api/cashier/remit-reviews`）的 `fee`、`paidAt` 兩欄被一段行內註解吞掉而為空（表格手續費／付款日空白，「手續費偏高」的覆核看不到手續費金額）；註解移到行首、補回兩欄，測試斷言兩欄有值。

## 1.0.86 — 2026-10-02（wip/t32-wording-d7）：報價單表單 V3.16（階段標籤改字）
- 報價單表單（`quotation-form.html`）案件進度的階段標籤「叫料出貨」改稱「材料申請出貨」（只改顯示文字）；表單版本 V3.15 → V3.16。

## 1.0.85 — 2026-10-02（wip/t32-s4a-2e：c7 預審修正＋e2e 修正）材料申請連結的狀態重置與付款歷史
- 修正：材料申請連結前端 `ml*` 狀態在切換案件時重置（`_reset_mlink`，加入核心的案件範圍重置清單；`moApprovals`／`moPay` 一併重置），打開匯入面板的回應加請求代號與案件檢查（晚到或被取代的回應丟棄）。
- 修正（金額）：有付款歷史的材料申請不再被當成「已連採購單」略過（現金基礎不再漏掉已付的錢）；對已有付款的單「新增」連結，儲存時回 400（已存在的連結重存仍可）。
- 內部：連結狀態端點改名 `GET /api/quotations/{no}/material-link-status`（原網址含 `/material-orders` 子字串，造成開案件的請求計數重複）；簽核佇列標籤一次呼叫內同案件只查一次。

## 1.0.84 — 2026-10-02 11:41（fix/t32-dispatch-s1-2e）：案件頁派發卡片「舊單已修改」警示（S-1）
- 承攬商分頁：舊單被實質修改後，卡片顯示「舊單已修改」徽章（滑過顯示修改時間），存檔當下提示「內容未經審核、成本與總帳照舊計入」。

## 1.0.83 — 2026-10-02（wip/t32-fixes-d7）〔train_number：1.0.78 → 1.0.83〕
- 收款人個資告知 **fail-closed**：告知紀錄寫入失敗 ⇒ 匯款申請不留（503＋稽核 `create_rolled_back`）；沒有（或讀不到）告知紀錄的申請不能送審（409）。
- 材料申請匯款：單筆手續費 > NT$ 500 ⇒ 該筆付款明細進「差額審核」（與多付同一條覆核路徑，原因欄顯示「手續費偏高」）；手續費不可大於實付。**只管材料申請匯款**，其他請款來源沒有此規則。
- 出納 `payee-bank`：材料申請的完整帳號只給最高管理者與出納（有 `cashier` 模組且角色不是 admin）；一般管理員只看遮罩（稽核註記「遮罩」）。

## 1.0.82 — 2026-10-02（wip/t32-seam-d7：材料申請連結接縫，接 32-S4）〔train_number：1.0.77 → 1.0.82〕
- `quoteItemId`／`poDocCode`／`poLine` 列為實質欄位（核准後改連結 ⇒ 回草稿重送審；`overPlanReason` 是說明，不算）；`poLine` 一律轉整數（專屬端點與 case-record 整包存檔同）。
- 儲存時連結檢查：`material_guard.LINK_VALIDATOR`（預設 None，由 `api/material_approvals.py` 掛上 `purchase_items.link_validator`）；無效連結 ⇒ 該列（或該次變更）被拒，code `bad_link`，不留殘列、不建草稿。
- 送審時 `purchase_items.material_submit_check`：問題 ⇒ 400（含 `po_line_taken`、超出計畫量須填原因）；判定快照寫進 `approval_json.linkSnapshot`；簽核詳情追加「採購單連結」「超出計畫」兩欄。
- 已對應採購單的材料申請不能開匯款申請（409；按鈕隱藏）；有匯款申請時不能改連結（沿用 `has_payments`）。

## 1.0.81 — 2026-10-02 15:29（wip/t32-s4a-2e）：對齊 d7 的「尚未送審」狀態列
- 併入 `wip/t32-unsent-d7`：移除 S4d 自己的草稿徽章（`ml-draft-*`），「尚未送審」以 d7 的狀態列為唯一來源；預設分頁（已核准／舊單／尚未送審）與各分頁筆數 chip 維持。
## 1.0.80 — 2026-10-02 14:20（wip/t32-s4a-2e）：材料申請連結前端（32-S4d）＋改用「材料申請」用字
- 前端 `js/case-management-mlink.js`（新檔，獨立於 31-C 區塊）：「從報價單品項帶入」（已申請完成、剩餘 0 者不列，數量預設剩餘量）、「從採購單明細帶入」（只列尚未被有效連結用掉者）、頁籤（已核准／舊單〔預設〕、審核中、草稿與退回、已取消、全部；未儲存的新列每個頁籤都顯示）、徽章「該材料申請未申請採購單」（讀後端判定；舊單與 $0 不標）、超出計畫量原因欄。
- `MaterialOrder` 存檔模型加選填 `quoteItemId`／`poDocCode`／`poLine`／`overPlanReason`；空值不寫入（沒用連結的舊單形狀不變）。前端載入與存檔原樣帶回這四鍵（整份覆寫端點）。
- S4 新增的使用者可見字串改照 `MATERIAL-REQUEST-WORDING.md`：`NO_PO_TEXT`＝「該材料申請未申請採購單」；送審檢查訊息、無案件訊息同改。鍵名不動。
- 材料申請的佇列提供者（`material_approvals.queue_items`）帶 `tags`：未申請採購單者加一個 warn 標註（`purchase_items.queue_tags`）。瀏覽器 e2e（32-S4e）：帶入扣量→超計畫原因→標註出現／消失／失效回來→佇列卡片標註。
- 修正（c7 預審）：(1) 切換案件重設 mlink 狀態、`_reset_exec` 一併清 `moApprovals`／`moPay`；(2) `mlOpen` 回應加請求代號與案件檢查（晚到的別案回應丟掉）；(3) **金額**：已有付款紀錄（已付金額 > 0 或狀態非 pending）的材料申請不視為連到採購單（`_link_check` 回 `has_payment`），已付的錢不再因事後連結而從現金口徑消失；`PATCH …/material-orders` 對已有付款紀錄的列**新增**採購單連結回 400（既有連結原樣存回不受影響）；(4) `queue_tags` 佇列一次呼叫同案件只查一次（傳入快取）。
- 修正（e2e 階段回報）：連結判定端點改名 `GET /api/quotations/{案件}/material-link-status`（原路徑含 `/material-orders`，與「開案件不打材料申請端點」契約測試的子字串比對撞名）；切換案件時重設 mlink 的畫面狀態（`_reset_mlink`，core 的重設清單加 `mlink`）。
- 預設分頁＝「已核准／舊單／尚未送審」（草稿帶「尚未送審」徽章，未進報表／總帳、不佔額度、不在簽核佇列）；其餘分頁：審核中、已退回、已取消、全部，各分頁 chip 顯示筆數。送審檢查加 `po_line_taken`：一個採購單行只能對應一筆活的（非草稿／已退回／已取消）材料申請。
- 簽核佇列項目加 `tags: []`（`helpers/approval_queue.base_item`；前端卡片畫出，tone `warn`／`info`）。

## 1.0.79 — 2026-10-02 13:49（wip/t32-s4a-2e）：連到採購單的叫料不重複計金額＋「未申請採購單」備註（32-S4c）
- `recognition.material_entries`（營運報表來源與總帳 E12／E12b 共用）：叫料列帶**有效 `poDocCode`**（同案件、待審核／簽核中／已核准的採購單，列序／品項對得上）⇒ **權責與現金都略過其金額**——那筆採購的金額由採購單負責（品項實際成本／額外支出），一筆採購只算一次；連結失效（採購單作廢／駁回）⇒ 叫料金額自動回來。每筆叫料來源列新增 `noPo`（`material_link_status` 為 none：沒有連結或連結失效）；舊單與 $0 不標。沒有連結資料的歷史叫料金額與以前相同。

## 1.0.78 — 2026-10-02 11:44（wip/t32-s4a-2e）：叫料連結送審檢查接縫與唯讀端點（32-S4b）
- 新增接縫函式 `purchase_items.material_submit_check`（叫料送審時驗：報價品項存在、`poDocCode` 有效、累計上限與超出原因〔裁示 Q2：超出必填〕，回 `snapshot` 供寫進 `approval_json`）與 `material_detail_fields`（核准詳情追加「採購單連結」「超出計畫」）；31-C 的守門／送審路徑由 d7 接線（`MG.LINK_VALIDATOR`）。
- 新增唯讀端點（案件可見，金額只給有財務檢視者）：`GET /api/quotations/{案件}/material-po-lines`（「從採購單帶入」清單：待審核／簽核中／已核准採購單中尚未被有效連結的叫料用掉的明細列）、`GET /api/quotations/{案件}/material-orders/link-status`（每列叫料的連結判定：linked／none／exempt，含失效註記）；`case_read_scope.json` 登記為 row_access。

## 1.0.77 — 2026-10-02 11:42（wip/t32-s4a-2e）：叫料連結判定與已訂量口徑（32-S4a）
- 新增 `purchase_items.material_link_status(order, po_rows, legacy=)`（叫料與採購單連結的**唯一判定函式**：linked／none／exempt；$0 與舊單不標；固定文字「該叫料未申請採購單」，連結失效補註）與 `material_ordered`（叫料對報價品項已訂量的貢獻：舊單、已核准、待審核、簽核中計入，草稿／已退回／已取消不計，連到有效採購單者只算一次）。`usage()`／`picker()`／`overplan()` 新增選填 `extra_ordered`：`GET …/purchase-items` 的剩餘量與送審上限檢查把未連採購單的叫料算進已訂量（同一口徑、同一份數字）。尚未掛到叫料守門（`MG.LINK_VALIDATOR` 接縫與 UI 在 S4b／S4d）。

## 1.0.76 — 2026-10-02（wip/t32-unsent-d7：材料申請「尚未送審」）
- 新增的材料申請不再先存成正式記錄：新增列與草稿一律顯示「尚未送審」（不計入報表／額度，不出現在簽核佇列）；舊單、已退回、待審核、已核准標示不變。
- 每個尚未送審／已退回的列都有「送審」：一鍵＝先儲存再送審；儲存被守門拒絕（例如缺供應商）就不送審、不留殘列。保留手動「儲存」；**不**自動存草稿。
- 案件頁「材料申請總額」不含尚未送審的項目，並顯示「不含尚未送審 N 項」。
- 有未儲存的材料申請時，離頁（beforeunload）與站內切換案件都會提示；`sidebar.js` 新增 `window.motrixDirtyProbe` 掛鉤，讓「任一請求成功就清離頁警告」不會清掉案件頁未存的材料申請（其他頁不受影響）。
- 測試：新增 e2e `test_e2e_material_unsent`（新增→填寫→尚未送審→重整不留→手動存草稿→一鍵送審→待審核；負向：佇列、缺供應商不留殘列）。

## 1.0.75 — 2026-10-02（wip/t32-wording-d7：叫料→材料申請改字）
- 使用者可見字串「叫料」一律改稱「材料申請」（case）：程式內部 key（material_order、materialOrders…）不變；只改畫面、通知、稽核顯示與報表字樣。；「已叫料」旗標顯示改「已申購」；旗標被擋的提示改為「需先申請請購單，再申請採購單；採購單通過後，才能對應這筆材料申請。」／「這筆材料申請還沒核准。」；新案件預設階段「叫料出貨」改「材料申請出貨」；新增全站掃描守門 test_wording_material_request。閘門邏輯不變。

## 1.0.74 — 叫料匯款金額改四捨五入（half-up）
- 修正：叫料匯款申請的實付／手續費／差額／已付與剩餘的計算，原用 Python `round()`（銀行家捨入：0.145→0.14、2.675→2.67），改成與全系統一致的 half-up（0.145→0.15、2.675→2.68）；新增 `material_payment.r2`（Decimal ROUND_HALF_UP），出納提供者與 API 同用。叫料列「已付」欄位唯讀，前端回送原值不再四捨五入（避免被誤判為已付欄位被改）。

## 1.0.73 — 第 31 包整合：簽核佇列的叫料付款單據類型改字面值
- 內部：叫料付款的簽核佇列提供者改用字面值 `"material_payment"`（原用常數 `MP.DOC_TYPE`，佇列涵蓋守門以靜態字面值掃描，某些順序下紅）；行為不變，無使用者可見改動。

## 1.0.72 — 2026-10-02（wip/t31-material-fix-d7：31-C 守門修正＋收款人個資告知）
- 守門修正（第 31 包 not_e2e 階段紅）：`approve()` 兩處改明列關鍵字（不用 `**`）；叫料程式不再用 `json_extract`（新增 `material_approval.case_row()`、`material_guard._load_old` 在 Python 逐筆解析；成交標籤欄位優先、空時退回 `data_json.dealTag`）；`material_order`／`material_payment` 登記進簽核套用範圍（預設跟統一流程）與簽核佇列覆蓋對照；`test_module_migrations` 期望 case 遷移 `[1..5]`。
- **收款人個資告知**（使用者裁示 A，2026-10-02）：供應商可能是自然人，叫料匯款申請上的收款戶名與銀行帳號屬個資。新增告知對象 `material_payee`（`docs/platform/pii_forms.json`）：開匯款申請必須勾選「已告知收款人」（伺服器強制，否則 400、不建立）；建立時伺服器記錄告知（時間與人員，`privacy_notice_acks` 設定鍵 `material_payment:<單號>`）並寫稽核 `material_payment.privacy_notice_ack`；`GET /api/material-payments/{id}/privacy-notice`（讀）、`POST …/privacy-notice/ack`（補記，冪等）。
- e2e：叫料審核／匯款 e2e 的資料庫輪詢改用 `page.wait_for_timeout`（不用 `time.sleep`，避免 sync Playwright 卡住頁面請求）。

## 1.0.71 — 2026-10-02 09:35（wip/t32-prpo-s1-2e）：連到的品項後來被刪 ⇒ 該列回到額外支出（32-S3 缺口修正）
- 修正（金額靜默短計）：採購單明細連到的報價品項後來不在報價內（被刪／改版）時，該列原本仍被當品項成本（清單 `itemLinkedAmount`、報表來源料件桶、E11 item 維度），而精算與挑選器只列現有品項 ⇒ 該列金額從精算總成本消失。現在這種列在清單、營運報表來源、E11 一律回到一般額外支出（金額與科目不變、不帶 item 維度）；守恆：`extraOnlyAmount` ＋ 各品項系統帶入金額 ＝ `totalAmount`（新增 `purchase_items.live_item_ids`／`load_live_item_ids`，`linked_split` 加選填 `live`）。

## 1.0.70 — wip/t31-material-d7（31-C：叫料審核；S1–S4：核心、端點、寫入閘、報表／總帳閘）
- **疊加審核表** `case_material_approvals`（migration 0004，只加不改、冪等）：叫料（`caseRecord.materialOrders[]`）以 (quote_no, item_id) 疊加審核狀態；**沒有疊加列＝舊單**（不溯及既往，行為與今天相同）。
- **審核狀態機** `modules/case/material_approval.py`：草稿／待審核／簽核中／已核准／已退回（＋終態已取消）；重用分層簽核原語（申請人部門主管→組織鏈→最高管理者；沒設簽核層＝送審即核准；不能自簽）；核准後實質欄位（品名、數量、單位、單價、小計、供應商）變更 ⇒ 回草稿重送審；**到貨確認不簽核**，只記日期＋確認人＋時間。單號 `MO-YYYYMMDD-NNNN`（與 A2 費用單據同格式）。簽核單據類型 `material_order`（叫料）已登記。
- **端點**：`POST /api/quotations/{no}/material-orders/{itemId}/submit|approve|reject|withdraw|cancel|receive`、`DELETE …/receive`、`GET /api/quotations/{no}/material-order-approvals`；寫入先 commit 再通知；稽核 `material_orders.submit／approve／reject／withdraw／cancel／receive／receive_undo`；簽核佇列提供者與詳情（`approval.queue_items`／`approval.detail`）、通知信四種（信內不放金額）。
- **寫入閘（關掉 `case-record` 後門）** `modules/case/material_guard.py`：叫料列與物流旗標的**所有**寫入路徑（專屬 PATCH、`PATCH /case-record`、報價單整份存檔／建立、已結案變更核准套用）都過閘，且寫入漏斗 `save_quotation_json` 內另有同一個閘作後盾（冪等）。**只拒有問題的項目，其餘照存**，回應 `rejected[]`（itemId／field／code／message）。規則：新列建審核單；既有列實質變更依審核狀態處理（舊單→草稿、已核准→草稿、審核中／已取消 ⇒ 拒）；刪除只限舊單／草稿／已退回；誰能新增／修改叫料列沿用專屬端點（admin 以上或 `project_manage`＋財務檢視）；**物流旗標 `ordered`／`arrived` 由 false→true 必須連結（`orderItemId`）一張已核准的叫料單，`arrived` 另要已記錄到貨確認**，被拒時連帶 `devices` 序號維持原值（不讓序號在沒核准時認領庫存）；$0 叫料單走同一流程。已付欄位只能經匯款申請寫入（`PAID_VIA_REMITTANCE_ONLY=True`，見下方匯款切片）。
- **營運報表／總帳**：權責口徑草稿、已退回、已取消的叫料**不計**；待審核／簽核中**計入並標「待審核」**；已核准與舊單照舊；現金口徑付出去的錢照計（只標待審核）。總帳 E12 只有已核准與舊單入帳，審核中的不入帳並在 notice 說明。**上線時報表數字可能變動（舊單被實質編輯後回草稿者不再計入權責成本），需公告。**
- 設計：docs/platform/plans/MATERIAL-ORDER-APPROVAL-DESIGN.md。

### 31-C 匯款切片（叫料匯款申請；migration 0005）
- **每張叫料單可開多張匯款申請**（表 `case_material_payments`，`UNIQUE(quote_no,item_id,seq)`，單號 `MP-YYYYMMDD-NNNN`，無款別），**每張各自走分層簽核**（簽核單據類型 `material_payment`＝叫料匯款）→ 核准 → 出納。端點：`POST /api/quotations/{no}/material-orders/{itemId}/payments`、`PATCH /api/material-payments/{id}`、`POST /api/material-payments/{id}/submit|approve|reject|withdraw|void`、`GET /api/quotations/{no}/material-payments`、`GET /api/material-suppliers`（供應商選單，只回 id／code／name，需能編輯叫料）。稽核 `material_payment.create／update／submit／auto_approve／approve／reject／withdraw／void`；通知信四種（`material_payment_*`，信內不放金額與帳戶）；簽核佇列提供者與詳情。
- **跨申請累計上限**：同一叫料單所有未作廢、未退回申請（含草稿與待審核，**鎖額度**）的金額合計 ≤ 小計（舊單再扣已登記的歷史已付）；超過 ⇒ 409，superadmin 可帶 `overCapReason` 覆寫；作廢／退回釋出額度。**$0 叫料單不能開申請**；叫料單要已核准（**舊單例外**，不溯及既往）；供應商必填（叫料單 `supplierId` 或申請時選）；**收款帳戶（戶名、帳號）填在申請上**，存申請的 `snapshot_json`——屬個資 F2：一般備份拿掉、完整列只進個資資料夾（`archive._F2_FIELDS['模組-case-case_material_payments']`），不進佇列詳情與信件，畫面只給末四碼。
- **出納不用改**：沿用既有名稱空間 `("payables.pending","case_material")`（每張申請一列，`amount`＝剩餘應付，可**分次付款**，未結清留在待付款）、`("remit.reviews","case_material")`（多付＝實付超過剩餘 ⇒ 該筆待審核，核可保留、退回＝刪除該筆明細；登錄人不能自審）、`("expense.entries","remit_fee_case_material")`（手續費列報表支出）。每次付款一列付款明細（`case_material_payment_lines`：日期、實付、手續費、差額審核、付款方式／科目）。
- **叫料單的 `paidStatus／paidAmount／paidDate` 變成明細合計的投影**，唯一寫入點 `material_payment.sync_order_paid`；`PAID_VIA_REMITTANCE_ONLY` 翻成 **True**：**上線後不再有「登記已付」**（舊單與新單一律只能經匯款申請；已付的歷史資料不動，舊單歷史已付在第一張申請時凍結並計入額度）。已有匯款申請的叫料單不可改實質欄位／刪除／取消（先作廢申請；已有付款明細者不可作廢）。
- **新建的叫料單必填供應商**（`materialOrders[].supplierId`，寫入閘 `supplier_required`；舊單不溯及既往，開匯款申請時再選）；案件頁叫料列新增供應商下拉（選單來自 `GET /api/material-suppliers`）；**已付款狀態在畫面上改為唯讀**（顯示付款明細合計），要付款請在叫料列下方「匯款申請」開單。
- **報表／總帳**：有匯款申請的叫料單，現金口徑與總帳 E12b 改讀**付款明細**（一筆明細一列；日期＝該筆付款日、金額＝該筆實付；E12b `source_key`＝`案件::itemId::明細id`；手續費列 FEE 借方；多付未核可的暫不產生分錄並在 notice 說明）；沒有申請的舊單維持讀 JSON。

## 1.0.69 — 2026-10-02 09:14（wip/t32-prpo-s1-2e）：請款頁重按沿用草稿（32-S5 追補）
- 新增請款（有類型表單）：同一次操作內送審被擋（例如採購單缺超出原因）後再按，沿用已建立的草稿（PATCH 它、附件只傳一次），不再多建一份單據；換案件或類型時重置。

## 1.0.68 — 2026-10-02 07:07（wip/t32-prpo-s1-2e）：請款頁品項挑選器＋精算頁採用採購單連結金額（32-S5）
- 新增請款（請購單／採購單、有案件）：「從案件品項帶入」——列出報價品項（計畫量／已請購／已採購／剩餘可採購），勾選後帶入明細（數量＝剩餘量、單價＝計畫單位成本，可改）；明細數量超出計畫時畫面標「超出報價計畫量 N」並提供「超出原因」欄（採購單送審必填，由伺服器檢查；請購單只提示）。無案件或其他類型：完全不變。
- 精算頁：連到品項的採購單金額不再算額外支出——額外支出合計改讀 `extraOnlyAmount`（拿不到品項金額、例如沒有財務檢視時維持讀 `totalAmount`，不讓錢消失）；每個品項顯示「採購單 NT$ X」與「採用／取消採用」：採用＝該品項實際成本＝採購單金額（含稅最終金額，不再 ×1.05／÷1.05；完結後凍結），**未採用的採購單金額仍計入實際總成本**（摘要列「採購單（品項尚未採用）」）。沒有連結列的歷史案件：金額與以前逐位相同（e2e 以歷史案件證明）。

## 1.0.67 — 2026-10-02 04:56（wip/t32-prpo-s1-2e）：連到案件品項的採購單明細＝品項實際成本（32-S3，Q1）
- 採購單明細連到案件品項（`itemId`）的列，在三處**各只算一次、金額守恆**：①額外支出清單 `GET …/extra-expenses` 新增 `itemLinkedAmount`（連結列金額）與 `extraOnlyAmount`（真正的額外支出）、每列 `linkedAmount`；**`totalAmount`／`totalPending` 過渡期仍含連結列**（精算頁改版時才改讀 `extraOnlyAmount`＋品項系統帶入，兩邊一起切，避免漏算／重複）；②營運報表來源 `recognition.extra_entries`：連結列獨立成列（帶 `itemId`／`linkedItem`／`bucket`），落「料件」支出桶（`ITEM_COST_BUCKET`），不再是「其他」；③總帳 E11：連結列另成借方行並帶 `dims={"item": 品項id}`——**金額、角色（專案成本）、類別都不變**，沒有 itemId 的單據逐行與以前相同。請購單永遠不計成本；作廢／駁回不計；待審核清單與報表照計（標待定）、總帳只收已核准；核准後的變更申請以新明細為準。`GET …/purchase-items` 每個品項多 `actualAmount`（已認列的採購單連結列金額；看不到財務金額者不回）。

## 1.0.66 — 2026-10-02 04:45（wip/t32-prpo-s1-2e）：請購/採購單明細連案件品項——驗證與累計上限（32-S2）
- 新增（S2）：請購單／採購單**明細列可帶 `itemId`（報價品項）**：只准有案件的請購單／採購單；品項必須在報價內、數量＞0；伺服器依報價寫入 `itemQtyPlan`／`itemCostPlan` 快照（前端送的不採用）。累計上限：已採購（核准＋送審中的採購單列）＋本單 ＞ 計畫量 ⇒ 超計畫；**採購單送審（含已核准後的變更申請送審）必須在該列填 `overPlanReason`，否則 400（狀態不變）；請購單只警示**（建立／更新回應帶 `overPlan` 清單）；超出量由伺服器寫入 `overPlanQty`。草稿不佔量、駁回／作廢釋放；送審在寫鎖內驗。採購單 `data.fromPr` 必須是同案件、已核准的請購單。沒有 `itemId` 的明細與以前完全相同（保留鍵 `itemId`／`itemQtyPlan`／`itemCostPlan`／`overPlanReason`／`overPlanQty` 不可由未連結的列攜帶）。

## 1.0.65 — 2026-10-02 04:33（wip/t32-prpo-s1-2e）：額外支出合計對齊營運報表規則＋請購/採購品項挑選器（32-S1）
- ⚠️ 行為變更（使用者裁示 2026-10-02，Q6）：`GET /api/quotations/{案件}/extra-expenses` 的 `totalAmount`／`totalPending` 只計待審核／簽核中／已核准、且類型要進金流（kind='' 或採購單／差旅／零用金）——**請購單、草稿、已駁回不再計入**（與營運報表 `extra_entries` 同一條規則；原本只排除作廢與被遮蔽的列，精算的額外支出因此比報表多）；新增 `uncountedAmount`（沒計入的金額，資訊用）。精算頁、案件頁額外支出分頁的合計隨之變。
- 新增：`modules/case/purchase_items.py`（品項計畫量、已請購／已採購量、剩餘量、超計畫判定；純函式）與 `GET /api/quotations/{案件}/purchase-items`（請購單／採購單「從案件品項帶入」挑選器；看不到財務金額者不回 `planUnitCost`；無案件 400）。明細列的 `itemId` 驗證與上限見 S2。

## 1.0.64 — 2026-10-02 00:59（fix/t31-build-2e）：案件頁承攬商卡片字級
- 派發卡片的「舊單」徽章與單號字級由 10px 改 11px（案件頁字級下限）。

## 1.0.63 — 2026-10-01（暫用號，列車取號；wip/t31-builder-b-c7：稽核補洞）
- `set_extra_expense_dates` 文件對齊（第 29 班稽核 O2）：出納也要看得到該案（`_guard_case`），沒有案件讀權的出納得 404；行為不變。補測試 `test_expense_visibility_gaps_2026_10_01.py`（`_caseless_visible` 對未知使用者 fail-closed、舊版額外支出附件對無案件權限者隱藏）。

## 1.0.62 — 2026-10-01 23:40（wip/t31-dispatch-approval-2e）：派發審核對應計成本與案件頁的影響（31-A）
- 應計承攬商成本（`recognition.dispatch_entries`）：派發審核狀態為草稿／已退回者不計入；待審核／簽核中計入並帶 `approvalPending`；已核准與舊單照舊。
- 案件頁承攬商分頁：拿掉新增視窗的狀態下拉（狀態只由卡片按鈕改）；卡片依狀態顯示送審／撤回送審／已送出／已確認／申請完工／撤回完工申請／取消；狀態顯示合併人話（派發審核中、完工審核中…）、舊單徽章；外包總成本與精算頁（`settlement.html`）的派發合計與營運報表同一規則，並標「含待審核 N 筆」。

## 1.0.61 — 2026-10-01（fix/t29-w1／fix/t29-w3：建包全量關卡）
- 案件頁「全部附件」頁籤的兩處寫死色碼改用語意 token；`quotation-form.html` FORM_VERSION V3.14→V3.15（客戶回簽單區塊）；模組目錄 `file_center` 登記；未核可橫幅守門改登記 `doc_render.render_document`。產品行為不變。

## 1.0.60 — 2026-10-01（wip/w1-quote-signed-back：客戶回簽單上傳）
- 報價單「客戶回簽單」（使用者：「報價單成案要能上傳客戶報價回簽單」）：沿用既有 `POST/DELETE /api/quotations/{no}/signed-files`（`quotations.signed_files_json`，不新增表／migration），補規則——
  - **狀態閘**：報價單完成簽核（狀態「已送出」）之後才能上傳（成案前客戶剛簽回、成案、已結案、成案撤回都可傳；草稿／待審核／簽核中／已退回／已作廢 ⇒ 400「…已送出之後才能上傳…」並寫稽核 `quotation.upload_signed_files_denied`）。
  - **權限**：能讀該報價單的人（業務、協作者 `assigned_user_ids`、admin+）可傳可看；外人與唯讀角色 ⇒ 404（看不到＝不存在）。
  - ⚠️ **行為變更（刪除收緊）**：原本任何看得到報價單的人都能刪；現在**上傳者本人或 admin+**（舊檔沒有 `uploaderUsername` ⇒ 只有 admin+）；清單裡沒有該 id ⇒ 404；檔案路徑不在這張報價單自己的資料夾（資料被竄改）⇒ 409 且不碰磁碟；被擋寫稽核 `quotation.delete_signed_file_denied`。
  - 每個新檔記錄上傳者帳號（`uploaderUsername`）與時間；上傳稽核內含檔名（不含伺服器路徑）。
  - **案件管理頁**「案件資訊」分頁最上方新增「客戶回簽單」區塊（列出／預覽／上傳／刪除；上傳鈕只在可上傳時出現）；**報價單表單**每檔顯示上傳者與時間、刪除鈕只給有權的人、案件進度旁新增選填的「客戶回簽單 ＋上傳」入口（不影響標記成案）。
  - 檔案中心（P3）既有的 `quotation_signed` 類別沿用同一可見性；不是結案條件。

## 1.0.59 — 2026-10-01（wip/w1-a2-4：A2-7 費用單據的通知信與單據輸出）
- 通知信（`expense_notify.py`；信件類型 `owner="case"`，自動併入個人通知偏好）：`expense_form_submitted／next_tier／approved／returned／payout_pending／paid`。送審→當層簽核人；下一層→新一層簽核人；核准→申請人（需付款的類型另寄出納「待撥款」）；退回→申請人（含原因）；出納登錄付款→申請人。**信內不放金額**；`kind=''` 的舊額外支出一律不寄；寄信失敗只記 log、不影響簽核／付款。掛點：`case_extra_expenses.py` 的 submit（含無簽核層的自動核准）／approve／reject 與 `payables.mark_paid`。
- 單據輸出：`GET /api/quotations/{quote_no}/extra-expenses/{id}/document?format=html|pdf`（無案件用 `-`）。版型取自單據釘住的定義版本的 `output.template`（`def_version=0` ⇒ 目前生效版），走 L1 `render_document`（公司抬頭／簽核欄／未核可每頁紅色標示）；可見性＝建立者、簽核鏈成員、admin／superadmin、出納／財務，看不到回 404；`kind=''` 回 404。
- 附件目錄 P3：`_CaseCatalog` 加 `search`／`count`（權限沿用各類 `_READ_RULE`／完工單 `case_documents_readable`）；案件管理頁新增「全部附件」頁籤（檔案中心在才出現，呼叫 `/api/filehub/search` 固定本案件，點檔用共用預覽元件）。

## 1.0.58 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2-w2b：推翻已付款限最高管理員、總帳備註）〔train_number：1.0.57 → 1.0.58〕
- 使用者裁示（「admin 給主管等級而已」）：**清除或更改已登錄的付款日**（＝推翻已付款、退回待付款）原本 admin 與 superadmin 皆可，現在**只限 superadmin**（admin／出納 ⇒ 403；第一次登錄付款日不變：出納或 admin 仍可）；稽核專用動作 `extra_expense.paid_date_override` 不變。作廢（已是 superadmin 專屬）的 409 訊息同步改指向最高管理員。下游效應（R1）：沒有 UI 入口會清付款日（只有 API）；出納頁與營運報表不變。
- 總帳事件備註：費用單據（kind≠''）的「來源金額未拆稅」備註不再說「以全額列專案成本」，改為依費用類別對應科目／預設費用科目；舊版列與叫料的備註不變。

## 1.0.57 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2-w2b：費用類別清單為空時不擋送審）〔train_number：1.0.56 → 1.0.57〕
- 使用者裁示 A：`expense.categories` 提供者在、但**沒有任何啟用類別**（公司尚未設定）⇒ 送審不驗證類別（不寫 `categoryCode`／`categoryName`），總帳以既有 `category_unmapped` 備註落到預設科目；一旦有 ≥1 個啟用類別，立刻恢復嚴格驗證（不在清單 ⇒ 400、狀態不變）。原本整合後的全新環境所有費用單據都送不出去（清單空 ⇒ 每個類別都「不是啟用中」）。下游效應（R1）：營運報表／出納不變；總帳未設類別的單據走預設科目並有備註。

## 1.0.56 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2-w2b：單據釘住類型定義版本）〔train_number：1.0.55 → 1.0.56〕
- 費用單據（kind≠''）在**建立**與**送審**當下把目前生效的類型定義版本寫進 `def_version`（`expense_forms.current_def_version` → W1 `helpers.expense_types.get_type`；W1 模組不在或沒發布過 ⇒ 0＝程式預設）；之後定義改版、編輯草稿、變更申請、讀取都不動它——已送審的單據輸出／驗證仍依自己的版本，不被改定義牽動（W1 A2-7 回報：不釘則列印依「目前」定義）。舊版列（kind=''）不查定義、維持 0。下游效應（R1）：營運報表／總帳／出納不讀此欄，不變。

## 1.0.55 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2-w2b：A2 S2 稽核摘要與精算守門）〔train_number：1.0.54 → 1.0.55〕
- 稽核：費用單據的 `extra_expense.*` 稽核 detail 帶單據摘要（類型、單號、金額、明細列數、歸屬部門、收款人類型、幣別；核准帶層級、駁回／作廢帶理由、修改帶前值）——**不含**收款人姓名／銀行／帳號／其餘明細列內容與 data（稽核標題文字沿用單據說明，既有作法）；舊版列（kind=''）只多一個金額。
- 案件額外支出清單新增 `maskedCount`（對本人遮蔽金額的列數，不含已作廢）；精算頁（settlement.html）據此：> 0 ⇒ 顯示警告並**停用「儲存草稿」「完結精算」**（否則金額被遮蔽的費用單據不會進 `totalAmount`，殘缺的額外支出總額會被寫進精算、再被營運報表與獎金讀走）。
- 收款人銀行帳號 `payee_account` 列入 F2 個資備份（L1 `archive._F2_FIELDS`，見 core CHANGELOG (next)）：一般每日 JSON 不再含該欄，完整列只進個資資料夾。
- 下游效應（R1）：營運報表／總帳／出納金額不變；只影響精算存檔的可操作性（金額被遮蔽者不能存）與備份內容（少一欄帳號）。

## 1.0.54 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2-w2b：A2 S1 作廢路徑）〔train_number：1.0.53 → 1.0.54〕
- 新增 `POST /api/quotations/{案件|-}/extra-expenses/{id}/void`（含按鈕，同一片）：**僅 superadmin**、僅「已核准且尚未付款」、理由必填；狀態改「已作廢」並記 `void_reason／voided_by／voided_at`、清掉待核准的變更申請（待核准附件一併丟棄）、通知申請人、稽核 `extra_expense.void`（detail 帶理由與金額）。已付款的列回 409（先由管理員更正付款日退回待付款再作廢）；作廢後不可再編輯／刪除／送審／變更申請／改日期發票／動附件（409）。
- 排除（列照列、不計入）：案件額外支出清單合計與 `pendingCount`、案件財務總覽 `settlementExtras.total`（項目帶 `voided`）、`case_extra_expenses()` 逐筆彙總、案件清單的待審計數、出納待付款／已付款、營運報表認列、總帳 E11／E11b 來源、簽核佇列（狀態白名單本來就不含）。申請人「我的請款」與稽核照列（標已作廢）。前端：案件額外支出頁加「作廢」鈕（僅 superadmin、已核准未付款列）、已作廢標示與理由、財務總覽明細標「已作廢（不計入）」。
- 下游效應（R1）：總帳**不另寫反向分錄**——E11／E11b 只對 status='已核准' 產生，來源消失後引擎自動作廢草稿傳票或對已過帳傳票產生借貸對調的反向草稿（`ledger/engine.py::_orphans`；accounting 測試用真提供者＋真 API 驗證，含反向控制）。營運報表支出總額因此少該筆（預期）。

## 1.0.53 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2：A2-6 營運報表逐類別列＋詳情修正）〔train_number：1.0.52 → 1.0.53〕
- 營運報表（`recognition.extra_entries`）：費用單據（kind≠''）依費用類別**逐類**一筆，帶 `departmentId`（費用歸屬單位）、`kind`、`docCode`；現金口徑實付≠應付另加「付款差額」列（合計＝實付）；明細對不上金額 ⇒ 退回一列。舊版列（kind=''）一列一筆、不帶新鍵，行為不變。下游效應（R1）：營運報表支出總額不變（仍為 total_cost／現金口徑實付），只是結構（類別、部門）可看；部門篩選對無案件列改看 `departmentId` 由 W3 接。
- 修正：簽核詳情（`detail_extra_expense`）變更申請的「改後單價／小計」原本讀 snake_case 鍵（`unit_cost`／`total_cost`）而永遠是空的、待核准附件（`addFiles`）也列不出來；改讀提議真正的鍵（`unitCost`／`totalCost`／`addFiles`），費用單據另顯示明細列數與收款人前後對照。加測試。

## 1.0.52 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2：A2-5 費用單據金額遮蔽）〔train_number：1.0.51 → 1.0.52〕
- 使用者最終裁示：費用單據（kind≠''）的金額只給申請人（建立者／data.applicant）、本單簽核人（含變更申請簽核鏈與代理）、出納／財務、管理員以上；其他人只看到狀態。案件額外支出清單對這類列回遮蔽列（`masked: true`；金額、明細、資料、說明、類別、收款人銀行、付款資訊、附件一律清掉，只留單號／類型／狀態／日期），合計只算看得到金額的列；案件財務總覽 `settlementExtras` 同樣遮蔽。簽核佇列與出納待付款本來就只給簽核人／出納（測試確認不外洩）。舊版列（kind=''）規則不變。下游效應（R1）：營運報表／總帳不受影響（讀 `total_cost`，不經這些回應）。

## 1.0.51 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2：A2-4 費用類別與總帳事件行）〔train_number：1.0.50 → 1.0.51〕
- 費用單據送審（含已核准後的變更申請送審）：明細每列的費用類別必須是 `expense.categories`（accounting，IP-108 草案）的**啟用中**代碼或名稱，否則 400、狀態不變（草稿可放任何類別；提供者不在 ⇒ 不驗證）；通過的列寫入 `categoryCode`（代碼）＋`categoryName`（顯示快照），並由 `gl.category_account` 寫入唯讀 `accountCode` 快照（只供顯示，過帳時總帳由事件行的類別重新解；解不出 ⇒ 空字串）。
- 總帳事件（`gl_events.py`）：費用單據（kind≠''）E11 依費用類別**逐類**借方（行上 `category`＝代碼；有案件 COST_PROJECT、無案件 EXP_OTHER），貸 AP 合計；E11b 付款貸方腿依 `pay_method`（零用金 PETTY、其餘 BANK），出納另選付款科目時行上帶 `account_code`。舊版列（kind=''）分錄**不變**（單一借方 COST_PROJECT、貸 BANK）。下游效應（R1）：營運報表只讀 `total_cost`，不變；總帳 E11／E11b 的行拆分與貸方腿是這次的變動，引擎端由 W4 接。

## 1.0.50 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2：W4 稽核低風險）〔train_number：1.0.49 → 1.0.50〕
- 舊版額外支出附件資料夾的路徑存取（`_CasePathAccess`，`extra_expense_legacy`）改為逐筆解析 `files_json`、比對**完整路徑**（原本是子字串比對：名稱是已列出檔案前綴的檔案也會被放行，僅限同案使用者；並避免含非 ASCII 檔名的 JSON 逸出造成比對失敗）。加測試：未列出的前綴同名檔 ⇒ 不可讀。

## 1.0.49 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2：A2-3 出納付款段）〔train_number：1.0.48 → 1.0.49〕
- IP-100 `case` 提供者：`mark_paid` 寫入 `pay_method／pay_account_code／pay_terms／remit_date／paid_by`；採購單匯款日＋付款條件必填、零用金付款方式必填、請購單不可付款（409）；新增 `payee_info`（收款人資料，給出納專用端點）；待付款項目加 kind／docCode／payee／遮罩銀行。下游效應（R1）：營運報表現金口徑與出納金額不變；總帳 E11b 貸方腿由 W4 讀 `pay_method`。

## 1.0.48 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2：費用單據 A2 前兩段）〔train_number：1.0.47 → 1.0.48〕
- migration 0003（`0003_expense_forms.py`）：`case_extra_expenses` 一次加齊通用欄位（kind／doc_code／data_json／lines_json／def_version／department_id／payee_*／pay_terms／remit_date／pay_method／pay_account_code／paid_by／pretax／tax／currency／void_*）；只新增欄位與索引、冪等、舊列維持原值（kind=''）。
- 無案件單據：哨兵路徑段 `/api/quotations/-/extra-expenses/...`（`-`＝`quote_no=''`；17 支端點共用同一個 `_qn()`）。建立需管理員以上或 `expense_forms` 權限；逐列可見＝建立者／本單簽核鏈成員（含代理）／admin／出納／財務（看不到＝404，不用 `case_owner_readable`）；稽核 target 改為 `case_extra_expense`＋單據 id（不留空 target_id）；「我的請款」列得出自己的無案件列。有案件的舊路徑行為不變。下游效應（R1）：營運報表／總帳／出納對無案件列的處理另由後續切片接（本段只開路徑與守門，不改金流計算）。
- 第二段（W1 契約 §7）：新增 `modules/case/expense_forms.py`（類型 purchase_req／purchase_order／travel／petty_cash、單號 `{PR|PO|TE|PC}-YYYYMMDD-NNNN`、明細金額後端重算、data 合併、未知鍵保留、`payable_sql`）；新欄位帶進建立／編輯（類型建立後不可改）／讀出／已核准後的變更申請（前後值進歷史）／簽核詳情／簽核佇列（無案件項目帶 `caseless`、`typeLabel`、核准／駁回網址）／出納待付款項目。請購單核准後不進出納、營運報表支出、總帳（E11）。舊版列（kind=''）行為不變；舊版變更申請不動新欄位。下游效應（R1）：營運報表與總帳只讀 `total_cost`（＝Σ 明細，整數 TWD）。

## 1.0.47 — 2026-10-01（暫用號，列車取號；wip/w3-dept-dim）〔train_number：1.0.46 → 1.0.47〕
- `recognition.extra_entries` 每筆多選填鍵 `departmentId`（讀 `case_extra_expenses.department_id`；欄位尚未建立 ⇒ 值為 None，不影響舊資料庫）。營運報表用它歸屬無案件支出的部門。

## 1.0.46 — 2026-10-01（暫用號，列車取號；fix/login-approval-popup：簽過的待簽核通知標已讀）
- 報價單核准（只標自己那筆）、退回修改、拒絕結案（標整張單）時，對應的 `approval_request` 通知列標已讀（`helpers.audit._mark_notifications_read`）；原本永遠未讀，造成登入橫幅每次再跳（使用者 2026-10-01 回報）。其他簽核流程（出貨／匯款／發票開立／承攬商憑證／完工單）同樣缺這一步，列為後續。

## 1.0.45 — 2026-10-01（暫用號，列車取號；wip/w3-local-date-2）
- 報價表單 FORM_VERSION V3.14（本地日期：報價日期預設值與送審時間改用 static/motrix-date.js）；測試沙盒載入 motrix-date.js。只動前端與測試，後端行為不變。

## 1.0.44 — 2026-10-01（暫用號，列車取號；wip/w2-legacy-extra-files：額外支出舊版附件資料夾）
- 正式機實測：8 筆額外支出的附件仍在 DB v75 之前的舊資料夾 `quotation_settlement_extra/{案件}_{舊索引}/`（v75 只搬 metadata、沒搬檔案）；路徑綁單據上線後 `attachments.catalog` 的 `open()` 只認 `case_extra_expense/{案件}_{id}` ⇒ 這些舊檔會 404。
- 修法：舊資料夾**只綁案件**（鍵 `{案件}_{數字}` 的案件編號＝該列的 quote_no；舊索引不是現在的列 id，不比）。別案的路徑、別種資料夾、沒有索引尾巴的鍵照舊 404。`uploads.path_access` 同步認領舊資料夾：該案某筆額外支出的 `files_json` 真的列了這個路徑才放行。下游效應（R1）：只影響附件開檔與預覽，不影響營運報表／總帳／出納。

## 1.0.43 — 2026-10-01（暫用號，列車取號；wip/w3-local-date）
- 本地日期（使用者 2026-10-01：凌晨建的單日期變前一天）：報價單預設報價日期、案件管理頁（動態／階段／外包／出貨／額外支出）的「今天」改用本地日期；送審 requestedAt 改存本地時間；佇列送審日／PDF 申請日改經 `_local_date_of`（舊的 UTC 字串換成本地日期，只改顯示）。

## 1.0.42 — 2026-10-01（wip/w1-unapproved-wm）
- 完工單未核准預覽／PDF：改用共用的每頁標示（fixed 大斜角紅色浮水印＋每頁頂端紅條＋頁尾單號頁碼，舊灰色浮水印隱藏）；報價單預覽／PDF 同（`_build_quote_html`，浮水印字樣「報價單預覽稿・尚未正式生效」）。已核准輸出不變。

## 1.0.41 — 2026-09-30（wip/w1-t27fix2）
- 完工單退回／撤銷核准：原因改在狀態與權限檢查之後才驗（已回簽不可撤銷的 409 不再被 400 蓋掉）。

## 1.0.40 — 2026-09-30（暫用號，列車取號；wip/w3-t27fix2）
- 匯出 PDF 姊妹的歸屬區改用常數 `_EXPORT_AREA`（不寫 module 等號字串字面量：test_module_keys_consistency 的後端掃描器會把它當權限 key）；只動寫法，行為與稽核內容不變。

## 1.0.39 — 2026-09-30（暫用號，列車取號；wip/w2-glwarn-doc：提示要說得出是哪一筆（W1 複核））
- 已入帳提示 `glWarning` 帶單號與項目：「此筆（MQ-…／款項）已入總帳…」（`_gl_doc`；L1 訊息本文不動）。

## 1.0.38 — 2026-09-30（暫用號，列車取號；wip/w2-money-guards：金流寫入連動修補（MONEY-FLOWS §9 L5/L11/L12））
- L12：更換**已登錄**的發票號碼（`mark_payment`／案件紀錄整包存）要 admin 以上或出納／財務，並寫稽核 `payment.invoice_no_change`（第一次登錄不變）；L11：已付款的額外支出經變更申請改金額 ⇒ 實付≠新應付時設 `remit_review='pending'`，強制重走出納的差額審核（下游：報表現金標差額待審核、總帳 E11b 待審核期間不產生）。

## 1.0.37 — 2026-09-30（暫用號，列車取號；wip/w2-open-bind：附件開檔路徑綁單據（安全審查 W3））
- `attachments.py`：`_CaseCatalog.open` 要求檔案路徑在該單據自己的資料夾底下（`_path_bound_to_doc`）；`api/quotations.py`：案件紀錄 PATCH／PUT／POST 只保留資料庫已有的 `files`／`invoiceFiles`（`_strip_foreign_file_entries`，前端夾帶的新路徑一律丟掉；R1 下游效應：只影響附件顯示與開檔，不影響報表／總帳／出納）。

## 1.0.36 — 2026-09-30（暫用號，列車取號；wip/w3-export-pdf）
- 匯出規則（使用者 2026-09-30）：案件批次匯出加 PDF 姊妹（`POST /api/case-batch/export/pdf`），每次匯出寫稽核。

## 1.0.35 — 2026-09-30（暫用號，列車取號；wip/w2-gl-warn：已入帳來源的修改提示（MONEY-FLOWS §9 L3））
- 改動／取消已入總帳的收款、更換發票號碼時，回應帶 `glWarning`（非阻擋）：案件紀錄整包存與 `mark_payment`；前端 toast／出納頁行內提示「此筆已入總帳：修改後下次引擎執行會產生沖轉草稿」。

## 1.0.34 — 2026-09-30（暫用號，列車取號；wip/w1-xss）
- 完工單 PDF：區域 `esc()` 補跳脫引號（共用 `helpers.doc_template.esc_quotes`；W3 #2 再查）。

## 1.0.33 — 2026-09-30（暫用號，列車取號；wip/w1-pdf-unapproved）
- 完工單預覽視窗高度包 `--fz`（字級放大不超出視窗）。

## 1.0.32 — 2026-09-30（暫用號，列車取號；wip/w1-pdf-unapproved＋退回原因必填）
- 完工單 PDF／預覽：未核准時加紅色「未核可・僅供預覽」橫幅（共用 `helpers.doc_template.unapproved_banner`）；已核准輸出不變。（另含退回原因必填，見下）
- 退回（報價單 reject／reject-final、完工單）與完工單撤銷核准一律要填原因；完工單 `pdf-download` 放行本單簽核人／申請人，`export?mode=preview` 不計次，案件頁完工單預覽改為視窗並可「退回修改」。

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
