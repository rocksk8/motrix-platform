# 案件 更新紀錄

## (next) — 2026-10-02（wip/t33-remit-s4-a3）：承攬商分頁分期申請的發票欄位；試算顯示防過期
- 案件管理頁「承攬商」分頁：分期匯款申請列顯示該期發票（號碼／日期；未登錄顯示「未登錄發票（尚不認列）」）並可登錄／更正（31-B S4）；產生匯款申請視窗的試算改輸入時作廢在途請求（不會把舊輸入的金額蓋回畫面）、剩餘額度以四捨五入整數元比較（用 `MotrixLegalRound.halfUp`，金額進位守門；da 稽核 S3 兩項）。

## (next) — 2026-10-02（wip/t33-remit-s2b-a3、s3-a3）：案件應付彙總不計作廢的分期匯款申請；承攬商分頁支援分期匯款申請畫面
- 案件詳情的應付彙總（承攬商匯款申請）略過已作廢的分期申請（31-B S2b）；其餘不變。
- 案件管理頁「承攬商」分頁：派發卡片支援多張分期匯款申請（款別／期別／試算／作廢，31-B S3；規格見 subcontract 模組 SPEC RK10）。

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
