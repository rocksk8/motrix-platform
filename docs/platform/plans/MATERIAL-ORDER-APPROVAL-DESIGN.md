# 叫料管控的審核機制——設計（第 31 班；2026-10-01 草擬，唯讀分析，**未跑任何測試**）

使用者原話（2026-10-01）：「叫料管控也需要審核跟派工一樣」。基底：包 47db5613。引用格式 `檔:行`＝該 commit 的行號。
對照文件：`origin/wip/dispatch-approval-2e:docs/platform/plans/DISPATCH-APPROVAL-DESIGN.md`（承攬商派發；下稱「派發設計」）。
標記：**【已讀】**＝讀過程式；**【推論】**＝由程式推得、沒執行；**【問】**＝需要使用者裁示（§6）。

> **先講最重要的一件事：「叫料」在系統裡是兩份互不相連的資料。** 不先決定審核的對象是哪一份（或兩份），設計無從談起（§6 問 1）。

## 0. 兩份「叫料」資料（事實）

| | 叫料管控（物流追蹤）`caseRecord.materials[]` | 叫料（財務應付）`caseRecord.materialOrders[]` |
|---|---|---|
| 畫面 | 案件管理 →「執行進度」→ **「叫料管控」**子頁（`case-management.html:813`、區塊 `:1034`） | 案件管理 →「財務」→ `#fin-material-orders`（`case-management.html:2323`）；文件 `docs/quick/mod-inventory.md §7.20` 講的是這份 |
| 欄位 | `name／model／qty／unit／ordered／arrived／supplier／expectedDate／devices[]（SN、MAC）／files／invoiceFiles／note` | `itemId／itemName／quantity／unit／unitPrice／totalPrice／paidStatus(pending/partial/paid)／paidAmount／paidDate／invoiceDate／notes` |
| 金額 | **沒有任何金額欄位**（`voucher_summary.py:219-221` 自己寫「物流追蹤不是支出記錄」） | 有；單價／小計／已付金額受 CM13 金額遮蔽 |
| 「狀態」 | 待叫料 → 已叫料（`ordered`）→ 已到料（`arrived`）：**兩個布林**（`case-management.html` 約 `:1060-1070` 的標籤；`dashboard.py:695` 把它們折成 pending／ordered／arrived） | `paidStatus` 三值＋`invoiceDate`；**沒有「已叫／已到貨」狀態** |
| 兩者的關聯 | **無**（沒有任何共同鍵；`materials[].id`＝時間戳，`materialOrders[].itemId`＝UUID） | 同左 |
| 下游 | 到料後可產生 `devices[]`（序號）→ 案件存檔時 `_sync_device_stock` **認領庫存序號**（`quotations.py:2472`）；首頁／採購頁的叫料進度（`dashboard.py:694`）；執行報告 PDF（`pdf_gen.py:2915`）；附件（`attachments.py:50-51`） | 營運報表成本（權責＝小計，歸月＝發票日否則付款日；現金＝已付金額，`recognition.py:276-296`）；總帳 E12 應付／E12b 付款（`case/gl_events.py:100-125`） |

結論：**「叫料管控」這個畫面名稱指第一份（物流）；「叫料」文件／財務指第二份（金額）**。派發的審核是「承諾支出」的那一步，落在金額上 ⇒ 真正對應的是第二份；但使用者說的「管控」又指第一份。建議的處理見 §3.0。

## 1. 現況：狀態機、誰能改、洞（**【已讀】**）

### 1.1 叫料（財務）`materialOrders[]`
- **沒有狀態機**，只有 `paidStatus` 與一個驗證函式。整份清單**整包覆蓋**。
- 唯一專屬寫入口 `PATCH /api/quotations/{no}/material-orders`（`modules/case/api/material_orders.py:58`）：
  - 權限：admin 以上**或**模組 `project_manage`（`:102`）＋有財務檢視（`:104`，CM13）；已結案 400（`:111`）；驗證只有「小計＝數量×單價」「paidStatus 與已付金額／日期一致」（`:116-133`）。**沒有任何簽核、沒有「已叫料／已到貨」概念；`paidStatus` 可由送出者直接設成 `paid`**（`:128-133` 只驗內部一致）。稽核 `material_orders.update`（`:153`）。
  - 另有 `PATCH …/{item_id}/invoice-date`（`:166-203`）：只登發票日，admin／專案經理／出納／財務，任何案件狀態（含已結案）都可登；**發票日決定權責歸月與 E12 的日期**。
- **第二個寫入口（真正的洞）：`PATCH /api/quotations/{no}/case-record`**（`quotations.py:2750`）。它**整包取代 `caseRecord`**（只保留 `stages`；`:2909-2913`）。呼叫者只要是「案件成員」（業務、協作者、案件角色、階段負責人）或管理員（`_is_case_member`，`:427`）：
  - 這支端點**對 `materialOrders` 完全沒有驗證**——不檢查小計、不檢查 paidStatus 一致性、不檢查已結案（已結案走半解鎖審核 `_gate_case_edit`，`:2888`，但那是整個案件的閘，不是叫料的）。
  - 也就是：**任何案件成員（不需 `project_manage`、不需 admin）都能新增叫料列、改單價／小計、把 `paidStatus` 設成 `paid` 並填已付金額與日期**；金額遮蔽帳號則由 `restore_case_record`（`financial_mask.py:142`）以資料庫現值覆蓋 `materialOrders`（所以只有「看得到金額」的成員能蓋掉）。目前畫面刻意不走這條（`mod-inventory.md §7.20`：「存檔刻意不併進 `saveCase()`」），但 **API 是通的**，這是「畫面沒入口≠沒洞」。
  - 第三個入口：`PUT /api/quotations/{no}`（整份報價單存檔；`quotations.py:1671`；草稿階段才可存，`_LOCKED`）與 `POST` 建立（`:1471`）都會寫 `data_json.caseRecord`，同理未驗 `materialOrders`。
- 結論（洞的精確版）：**今天可以不經任何第二個人，把叫料建立出來、標成已付、填發票日，並立刻進營運報表成本與總帳 E12／E12b 草稿**；而且這條路徑**不限於 `project_manage` 持有者**。

### 1.2 叫料管控（物流）`materials[]`
- 沒有專屬端點：**增刪、`ordered`、`arrived`、供應商、預計到貨日、序號全部隨 `PATCH /case-record` 一起存**（同上，案件成員即可）。
- 附件（到貨憑證、發票）有專屬上傳端點，**「任何登入使用者皆可」**（`quotations.py:4035` 註解；`:3062-3081` 寫入）——到貨證據誰都能附。
- **到料（`arrived`）不是純標記**：到料後前端展開 `devices[]`（SN／MAC，`onMaterialArrived`）；案件存檔時 `_sync_device_stock`（`quotations.py:2472`）對序號 diff，**認領／釋放庫存序號**（經 IP-19 `stock.serial`，與存檔同一交易）。⇒ **到貨登載會在沒有任何審核下動到庫存序號的狀態**（序號對得上才動；找不到就略過、不擋存檔）。
- 沒有金額，所以**不直接進成本／應付**；但「已叫料」是對外採購的事實，目前零控管。

### 1.3 下游（誰在讀、會被未審資料影響）
| 下游 | 規則 | 位置 | 後果 |
|---|---|---|---|
| 營運報表／權責成本 | 所有 `materialOrders` 小計計入，日期＝發票日，否則付款日（標「暫用」） | `recognition.py:276-296` | 未審的叫料直接進成本 |
| 營運報表／現金 | `paidStatus≠pending` 且有付款日 ⇒ 計 `paidAmount` | `recognition.py:281-288` | 同上 |
| 總帳 E12／E12b | 所有 entries 都產生事件（需日期） | `case/gl_events.py:100-125` | 未審叫料入帳草稿 |
| 付款 | **沒有付款流程**：`paidStatus` 是登記，不是出納付款；E12b 直接由它產生 | 同上 | 與派發不同：派發付款要走匯款申請（分層簽核＋出納），叫料**沒有**這道 |
| 庫存 | `materials[].devices[].sn` → `stock.serial` 認領 | `quotations.py:2472` | 見 1.2 |
| 首頁／採購頁叫料進度 | 讀 `materials[].ordered/arrived` | `dashboard.py:694` | 未核准的「叫料中」會被當真 |

### 1.4 與派發的差異（為什麼不能照抄）
- 派發有**獨立資料表與狀態機**（`contractor_dispatches.status`＋`/accept`）；叫料是 `data_json` 裡的**陣列、無狀態機、整包覆蓋**。
- 派發的付款有「匯款申請」這道天然閘；叫料**沒有**——這使「付款前審核」不夠，**建立當下的審核**更關鍵，而且「已付」登記本身就是洞（§3.4）。
- 叫料沒有單據編號、沒有佇列提供者、沒有信件類型（派發設計要新建的東西，這裡全要新建）。

## 2. 「完成」對叫料是什麼（回答要點 2）
派發的完成＝驗收→完工；叫料沒有對應狀態。依資料推得三個候選的「完成」節點（**【推論】**；使用者要選 **【問 3】**）：
1. **到料（`arrived`）**：物流上「叫的料到了」；會觸發設備序號登載與庫存認領（1.2）。**最像派發的「驗收」**。
2. **已付（`paidStatus=paid`）**：財務上結清；目前無付款流程。
3. **發票日登錄（`invoiceDate`）**：權責認列的日期來源（決定成本歸月與 E12 日期）。
**審核前已被動到的東西**：成本（建立當下就計入）、總帳草稿（E12 見 1.3）、庫存序號（到料登載後存檔當下，若序號對得上）、應付／付款登記（`paidStatus`）——**四項都在沒有審核下發生**。

## 3. 建議流程（**【建議】**，仿派發，差異處標明）

### 3.0 審核的對象——建議：以「叫料單（金額列）」為審核單位，物流旗標跟著它
- **建議**：審核單位＝`materialOrders[]` 的一列（金額承諾，對應派發的「新增派發」）。`materials[]` 的 `ordered`／`arrived` 旗標**不單獨審核**，而是**受閘**：沒有核准的叫料單，不得把對應料件標「已叫料」（見 3.3）。
- 需要把兩份資料**關起來**：在 `materials[]` 項目加選填 `orderItemId`（指向 `materialOrders[].itemId`）；沒關聯的物流項目維持現狀（不審，無金額）。**【問 1、2】**
- 替代（不建議）：只審物流 `materials[]`（沒有金額 ⇒ 審核人看不到要核什麼）；或兩份合併成一份（資料遷移大，違反「只增不改」）。

### 3.1 儲存：用「核准疊加表」，不動 `data_json` 的形狀
`materialOrders` 住在 `data_json`，沒有資料表，直接把審核欄位塞進每列有三個問題：①佇列要掃全部案件的 JSON（`json_each`，慢且脆）②整包覆蓋會把審核狀態一起蓋掉 ③沒有單據編號可引用。**建議新增一張薄表**（migration `case/0004`，只加不改）：

```
case_material_approvals(
  quote_no TEXT, item_id TEXT,                 -- 鍵＝(案件, materialOrders.itemId)
  doc_code TEXT UNIQUE,                         -- 叫料單號 MO-YYYYMMDD-NNNN（next_entity_code；與 TE-/PR-/PO-/PC- 同格式）
  stage TEXT,                                   -- 'order'（叫料）／'receipt'（到料）
  status TEXT,                                  -- 草稿／待審核／簽核中／已核准／已退回
  approval_json TEXT, submitted_by, submitted_at, approved_at,
  content_hash TEXT,                            -- 核准當時的實質欄位雜湊（品名、數量、單位、單價、小計、關聯料件）
  version INTEGER, created_at,
  PRIMARY KEY(quote_no, item_id, stage))
```
- **沒有疊加列＝舊單**（自動寬限，不必回填、不必標記遷移）；舊單的畫面標「舊單（未經審核）」灰徽章（同派發 §2.5）。
- 核准時存實質欄位雜湊；之後任何寫入口若使實質欄位與雜湊不符 ⇒ 該單**自動回到「待重新送審」**（見 3.3），這樣即使有人繞過專屬端點也留下痕跡。**【風險】**雜湊的欄位清單要與前端一致（小計用浮點，需正規化）。

### 3.2 狀態圖（兩階段，對應使用者「建立與完成都要審」）
```
新增叫料單（金額列，預設不得標已叫／已到／已付）
  └送審（創建者／負責業務／協作者／admin+）→ 待審核 → 簽核中 → 已核准（叫料核准） ─┐
                │                         └退回（任一層，必填理由）→ 已退回 →（修改後再送）
                │                                                                        ▼
        已核准後才可：標「已叫料」（materials[].ordered）→ 到貨後送「到料審核」（stage=receipt）→ 已核准 → 才可標「已到料」＋ 登載序號／認領庫存 → 才可登記付款／發票日
```
- 階段 1「叫料核准」＝核准這筆**採購承諾**（金額、數量、供應商由審核人看）。
- 階段 2「到料審核」＝確認**實際到貨**（數量、品項、必要時序號與到貨憑證）；通過後 `arrived` 才能被設成真，`devices[]` 序號才會被存檔流程認領庫存。
- 簽核流程：重用 `helpers/tiered_approval.py`（派發設計同）：**申請人部門主管→組織鏈→最高管理者；沒設簽核層＝直接核准；不能自己簽自己**（`check_no_tier_self_approval`）。
- 提交者／取消／文件編號／舊單：全部照派發的使用者決定（§7 對照表）。

### 3.3 寫入口的閘（真正的修補；比派發更重要，因為洞在 `data_json` 整包覆蓋）
1. **新增一支共用驗證 `material_orders_guard(old_list, new_list, user)`**，三個寫入口（`material_orders` PATCH、`case-record` PATCH、`PUT/POST quotations`）**一律呼叫**：
   - 新列（舊清單沒有的 `itemId`）：**強制**為未核准——`paidStatus` 必須 `pending`、已付金額／日期清空（否則 400「請先送審」）。
   - 既有列：實質欄位變更 ⇒ 該單狀態回「待重新送審」並**凍結**（不可標已叫／已付），除非是 admin+ 且帶理由。
   - 非實質欄位（備註、發票日）：可改；**發票日登錄**維持現行權限，但**只有已核准的單才進成本**（見 3.5）。
2. `case-record` PATCH：`materialOrders` 與 `materials[].ordered／arrived／devices` 不再信任 body——**以資料庫現值為準，只接受「閘函式」放行的差異**（比照 `restore_case_record` 對金額的處理方式，已有先例）。
3. **靜態守門 G-M1**：掃 `modules/case` 內所有對 `caseRecord.materialOrders`／`materials` 的寫入，只准經 `material_orders_guard`（突變：在別處加一條直接寫入 ⇒ 紅）。
4. 前端：叫料列新增「送審／撤回／核准狀態徽章」；「已叫料」「已到料」勾選在未核准時 disabled 並顯示原因；付款欄位同。

### 3.4 付款（派發沒有、叫料必須回答）
叫料的「已付」目前是**登記**，沒有出納、沒有付款申請。**【問 4】**：維持登記（只加「已核准才能登記已付」）？還是比照派發改成「付款申請→簽核→出納」（可重用 A2 的採購單／請款流程，見 §3.6）？後者範圍大很多。

### 3.5 報表／總帳（使用者對派發的決定，原樣套用）
| 面向 | 規則 |
|---|---|
| 營運報表成本 | **草稿與已退回不計；待審核／簽核中計入並標「待審核」；已核准正常；舊單（無疊加列）照舊**。位置：`recognition.py:276-296`（權責與現金兩個分支都要改；取疊加表狀態）。 |
| 總帳 E12／E12b | 只在 `已核准` **或舊單**才產生事件（`case/gl_events.py:100-125`）；未核准不入帳；E12b 另需已核准。 |
| 首頁／採購頁叫料進度 | 未核准的不顯示為「叫料中」（`dashboard.py:694` 讀 `ordered` 前先看閘）。 |
| 與總帳差異頁 | 「待審核」差額應能對上報表標示（現有分桶 `unposted`／`residual`；必要時新增一桶，另案）。 |

### 3.6 與 A2 的重疊（**【問 5】**——這可能讓整個設計換方向）
A2 已有「請購單 PR → 採購單 PO」類型的費用單據（`helpers/expense_types.py`、`modules/case/expense_forms.py`；各自有送審、分層簽核、佇列、信件、總帳 E11、營運報表、PDF）。**叫料本質上就是案件採購。** 兩個方向：
- **(X) 沿用現有叫料列＋疊加審核表**（本文 3.1–3.5）：改動小、使用者畫面不變、舊單自然寬限；缺點：又一套審核碼（雖由共用閘分攤，見 §4）。
- **(Y) 叫料改走 A2 的 PR/PO**：一套審核、一套信件與報表；缺點：使用者要換入口、`materials[]` 物流旗標與 PO 如何關聯需另設計、既有叫料資料遷移或並存、工量大（估 3+ 班）。
**建議先做 (X)，不排斥日後 (Y)**；但要使用者決定。

## 4. 共用機制「審核閘」（**【建議，含風險】**；回答要點 3）

**證據：同一套分層簽核邏輯已被手抄約 13 處**（`setting_to_active_tiers`／`sign_first_pending` 在 `case_extra_expenses.py:740/840/1336/1422`、`completion_notes.py:415/508`、`contractor_vouchers.py:450/551`、`shipping_notes.py:365/469`、`invoice_vouchers.py:507/607`、`payment_requests.py:600/699`、`vouchers.py:687`、`bonus.py:1187/2218`、`quotations.py:539/4880`、`custom_modules.py:1281/1388`、`vendor_contractors.py:760`）。派發與叫料是第 14、15 份——這就是該抽共用的時機。

### 4.1 建議形狀：`helpers/approval_gate.py`（L1）＋「受審單位描述」
```
class GateSubject:                       # 每種單據一個，只描述「怎麼讀寫」，不含簽核邏輯
    doc_type            # 已 register_doc_type 的代碼（'contractor_dispatch'／'material_order'）
    label, code_prefix  # 「承攬商派發」DP-／「叫料」MO-
    load(conn, key, lock)            -> row（含 approval 狀態、擁有者、案件、金額摘要）
    save_approval(conn, key, status, approval_json, ...)    # 寫自己的疊加欄位／表
    can_submit(user, row) / can_cancel(user, row)           # 派發與叫料的 submit/cancel 規則（使用者已決定）
    summary(row) -> {subject, total, caseNo, docCode}       # 佇列、稽核、信件用
    on_transition(conn, row, old, new, user)                # 狀態變更後的掛鉤（例：核准後放行作業狀態）
```
提供：`submit／approve／reject／withdraw`（內部用 `tiered_approval` 既有原語：`resolve_active_flow_setting`、`setting_to_active_tiers`、`check_approve_permission`、`cascade_self_tiers`、`sign_first_pending`、`check_no_tier_self_approval`，**不改它們**）、`gate_state(row)`（回 `legacy／draft／pending／approved／returned`，供下游「只算核准或舊單」的統一判斷）、`queue_items(subject, user)`（`approval.queue_items` 提供者的共用實作）、信件類型批次登記（`mail_types.register`，信內不放金額）、稽核動作命名 `<owner>.<doc>.<submit|approve|reject|withdraw>`。
- 配套「**一致性測試台**」：給任何 `GateSubject` 跑同一組情境矩陣（單層／多層／自簽層／沒設簽核層＝直接核准／退回重送／撤回／不能自己簽自己／舊單／重複核准冪等／權限矩陣）。**第三、第四個需求只要寫 Subject＋通過測試台**。

### 4.2 風險（誠實列出）
1. **L1 改動 ⇒ 全量班**（動 `helpers/`＝底層；列車全量＋預演）。派發本來也要全量（subcontract＋mail_types＋前端），多出的是新 L1 檔，**不改既有 L1 檔** ⇒ 對既有行為零影響（加法）。
2. **兩個消費者同班上線**：若同時做、同時改共用抽象，容易互相牽制。建議**先從派發實作抽出**（派發是第一個、已有設計），叫料是第二個使用者；共用檔由派發班落地，叫料班只寫 Subject。**這與派發設計（尚未動工）需要 2e 同意**。
3. **不要一次把既有 13 處遷移進來**——只服務新單據；既有單據保持原樣（遷移是另案、逐個有回歸風險）。
4. **抽象過早**：兩個消費者（派發＝資料表、叫料＝疊加表＋JSON）差異不小；`GateSubject` 的 `load／save_approval` 要夠薄。若兩邊寫完發現沒什麼可共用，退回「共用工具函式（佇列與信件的樣板）」而不是框架。
5. **簽核設定頁**：兩種新單據類型都要 `register_doc_type`（`tiered_approval.py:86`，A2 已示範），預設是否跟統一流程（**【問 6】**）。

## 5. 佇列、信件、稽核、金額可見、測試、工量（回答要點 4、5）

### 5.1 佇列／信件／稽核／金額
- **佇列**：新增 `approval.queue_items` 提供者（owner＝case）：`type:"material_order"`、`typeLabel:"叫料"`（到料階段 `"到料審核"`）、`quoteNo`、`docCode`（MO-…）、`subject`（品名＋案件名）、`total`、`openUrl`＝案件管理頁該叫料列、`approveUrl／rejectUrl`、`rejectField`＝`reason`。`routers/approval_queue.py:_ITEM_TYPE_LABELS`（`:203`）與簽核佇列頁 `docTypeLabel`（`approval-queue.html`）兩邊要同步（守門 `test_approval_labels_match` 會抓）。
- **信件**：`mail_types.register`（owner＝case）四種＋個人通知偏好：`material_submitted／_next_tier／_approved／_returned`；**信內不放金額**；站內通知照舊。
- **稽核**：`material_orders.submit／approve／reject／withdraw／cancel`（detail 帶 tier、理由、品名／單號，**不含帳號與完整金額**）；既有 `material_orders.update` 與 `.invoice_date` 保留。**靜態守門**：寫入端點必有稽核（既有 `tests/test_write_endpoints_are_audited_2026_09_24.py` 涵蓋新端點）。
- **金額可見**：簽核人在佇列看得到金額（共用 `routers/approval_queue.py:302` 的 `_can_see_queue_money`，與憑證流規則一致）；沒有財務檢視的帳號沿用 CM13 遮蔽；佇列詳情不含供應商帳戶資料。**注意**：沒有財務檢視權的案件成員**無法**建立／送審有金額的叫料列（`material_orders.py:104` 已擋，且 `case-record` 路徑要補同樣的拒絕，見 3.3）。

### 5.2 測試／守門／突變（不跑；列計畫）
- **API**：寫入口矩陣（三個入口各自：新列強制未核准、`paidStatus=paid` 被拒、整包覆蓋不能蓋掉審核狀態）；狀態轉換逐格；簽核流程（單層／多層／自簽層／無簽核層／退回重送／撤回）；階段 2（到料）；舊單寬限（無疊加列＝照舊、實質編輯後要求送審）；報表三態（草稿與退回不計、待審核計入並標示、核准正常）；`gl_events` 只對核准或舊單產生 E12／E12b；`_sync_device_stock` 在 `arrived` 未核准時不認領序號。
- **守門**：G-M1（只有 `material_orders_guard` 寫叫料）；`approval_gate` 一致性測試台；`approval labels match`；`case_read_scope`（新端點帶案件號）；頁面路徑／alpine 守門若動到前端。
- **突變（固定守門題，比照 G5）**：拿掉三個入口任一的 guard 呼叫、guard 放行新列帶 `paid`、疊加表不影響報表、`gl_events` 不看核准、雜湊比對拿掉、自簽檢查拿掉；每項需有正向控制。
- **e2e（瀏覽器＋截圖）**：新增叫料（核准前「已叫料」「已付」disabled）→ 送審 → 簽核人在佇列核准 → 標已叫料 → 到料送審 → 核准 → 登載序號；反向：API 直送 `paidStatus=paid` ⇒ 400；退回→修改→再送；核准後改金額 ⇒ 待重新送審；舊單徽章；金額遮蔽帳號行為。
- **工量（粗估，【推論】）**：(X) 方案——後端（migration、`approval_gate`＋`GateSubject`、三入口 guard、提供者、閘到報表／總帳／庫存／首頁）**1.5～2 班**；前端（叫料列徽章與按鈕、物流旗標受閘、佇列文字）**0.5～1 班**；測試＋e2e＋突變＋守門 **1 班**；合計約 **3～4 班**，其中「共用審核閘」若由派發班先落地則叫料班少 ~0.5 班。層級：case 模組（L2）＋L1 `helpers/approval_gate.py`／`mail_types`／`register_doc_type`＋前端 ⇒ **全量班**；不動 L0。(Y) 方案 3+ 班且需另案設計。

## 6. 待使用者裁示（**只列派發決定沒有回答的**）
派發已決定的（不再問）：分層簽核（部門主管→組織鏈→最高管理者；無簽核層＝自動核准；不能自核）；建立與完成兩個步驟都要審；既有進行中資料寬限（舊單徽章、實質編輯後重新送審）；報表（草稿／退回不計、待審核計入並標示）；送審者＝創建者／負責人／協作者／admin 以上；已核准取消＝admin 以上加理由；單號格式。

1. **審核對象是哪一份？** (a)「叫料」金額列 `materialOrders`（建議，§3.0）；(b)「叫料管控」物流 `materials[]`（沒有金額）；(c) 兩份都要，並**把兩份關聯起來**（物流項目指向金額列）。目前兩者互不相連，使用者平常是只用物流那份、還是兩份都填？
2. **要不要強制兩份關聯？** 建議：標「已叫料」之前必須先有一筆已核准的叫料單。使用者是否接受「沒有金額列就不能標已叫料」？（會改變只用物流頁、不填財務頁的人的工作方式。）
3. **叫料的「完成」是哪一步要審？** 候選：到料（`arrived`，建議）、已付、發票日登錄；或「到料」審核後才能登載序號並認領庫存？
4. **付款**：目前「已付」只是登記、沒有出納流程。維持登記（加「已核准才能登記」）？還是改走付款申請＋出納（較大）？
5. **是否改走 A2 的請購單／採購單**（§3.6 方案 Y）？若是，現有叫料畫面如何處理？
6. **簽核設定**：叫料審核預設跟「統一流程」，還是獨立流程？要不要金額門檻（小額免審）與門檻金額？（派發若已有門檻決定可沿用；目前派發設計把門檻列為待問。）
7. **到料審核的審核人**：與叫料核准同一條鏈，還是由「案件執行負責人／倉管」到料確認即可（不走多層）？
8. **沒有財務檢視權的案件成員**今天可經 `case-record` 改叫料（金額遮蔽帳號會被蓋回現值，有財務檢視者不會）。上線後這條一律關閉（建議）；是否有人依賴它？
9. **舊資料盤點**：上線前要不要唯讀盤點正式機現有叫料列數、已付金額總計、涉及案件數，讓使用者看影響面？
10. **叫料單號**：用 `MO-YYYYMMDD-NNNN`？到料審核是否另開單號（建議同號、兩階段）？

## 7. 與派發設計的對照（只列差異）
| 項目 | 派發 | 叫料（本文） |
|---|---|---|
| 資料位置 | 資料表 `contractor_dispatches` | `data_json` 陣列（無表）⇒ 加疊加表 |
| 現有狀態機 | 有（`/accept`） | 無（兩個布林＋`paidStatus`） |
| 洞 | `POST／PUT` 寫 `status` | **`case-record` 整包覆蓋**＋`material-orders` PATCH 可直接標已付 |
| 付款閘 | 有（匯款申請） | **無**（需另決定，問 4） |
| 庫存 | 無 | `arrived`＋序號 ⇒ 認領庫存序號 |
| 舊單 | 欄位 `''` | 無疊加列＝舊單 |
| 共用機制 | 第一個使用者 | 第二個使用者 |

## 8. 不做（本期）
金額門檻分流的複雜規則、跨案件批次送審、叫料範本、行動版簽核、把既有 13 處簽核遷入 `approval_gate`、(Y) 方案的資料遷移。
