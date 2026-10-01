# 承攬商派發的審核機制——設計（第 31 班；2026-10-01；**狀態：已裁示、可開工**）

使用者原話（2026-10-01）：「承攬商派發管理的新增派發，也要有審核機制，目前只有派發然後手動選狀態，沒有審核直接能完結」。基底：包 47db5613。引用格式 `檔:行`＝該 commit 的行號。

## 0. 已裁示（使用者 2026-10-01，經選單；其餘由使用者授權主持定預設）
| # | 項目 | 決定 |
|---|---|---|
| Q1 | 核准流程 | **沿用既有分層簽核**：申請人部門主管→組織鏈→最高管理者；沒設簽核層＝直接核准；不能自己簽自己（`helpers/tiered_approval.py` 既有規則） |
| Q4 | 完工 | **完工也要核准（取較嚴的一種）**：新增第二個簽核階段「完工申請→分層簽核→完結」；另保留驗收人≠建立者（見 §2.6） |
| Q5 | 既有進行中的派發 | **不溯及既往**（舊單 `''`，灰色「舊單」徽章；實質編輯 ⇒ 重新送審） |
| Q6 | 報表 | 草稿與已退回**不計**權責成本；待審核／簽核中**計入並標示**；已核准與舊單計入；**上線時公告數字變動** |
| 預設（授權主持） | 送審者 | 建立者、該報價單的負責人／協作者、admin 以上 |
| 預設 | 核准後編輯 | 實質欄位（承攬商／品項／人員／稅率）⇒ 重新送審；備註、日期、發票欄位免審 |
| 預設 | 取消已核准的派發 | admin 以上＋**必填理由**＋稽核；已有匯款申請者限 superadmin |
| 預設 | 派發單號 | **要**，`DP-YYYYMMDD-NNNN`（同 A2 費用單據的單號作法） |

## 1. 現況（事實）

### 1.1 狀態機與誰能改（`modules/subcontract/api/vendor_contractors.py`）
- 狀態值：`draft／sent／confirmed／pending_acceptance／accepted／completed／cancelled`（`:36-43`）。文件 §5.7 畫的是 草稿→已送出→已確認→待驗收→已驗收→完工，任意非終態→已取消。
- **只有 `PATCH /{id}/accept`（`:1042-1081`）執行狀態機**：`_ACCEPT_ALLOWED_FROM`（`:1037-1040`）＝待驗收只能來自 draft/sent/confirmed、已驗收只能來自待驗收；角色＝admin 以上＋模組 `procurement／case_manage／contractor_list` 任一；已驗收記 `accepted_by／accepted_at`；稽核 `vendor.dispatch.<action>`；通知 `notify_module_activity`（站內活動，不是簽核通知）。
- **`POST` 建立（`:523-562`）與 `PUT` 編輯（`:565-617`）直接把 body 的 `status` 寫進資料庫**（`body.status or 'draft'`，`:549`、`:608`）：沒有白名單、沒有轉換檢查——模型 `DispatchIn.status` 是自由字串（`:66`）。前端「新增派發」Modal 有一個 7 選項的狀態下拉（`case-management.html` 約 3550–3558），文件也寫明「狀態亦可透過 Modal 下拉直接設定（彈性操作，不走 `/accept` endpoint）」（mod-contractor.md §5.7）。
- 權限：建立／編輯／刪除／驗收 ＝ `_require_admin`（`:26-31`，admin／superadmin）＋模組；**沒有任何簽核、沒有「不能自己核自己」**；刪除受「已產生匯款申請就 409」限制（`:620-641`）；編輯同樣受該限制（`:565` 起）。

### 1.2 洞（精確版）
任何 admin 可以：①建立時直接帶 `status:"completed"`（一步到位）；②PUT 把 draft 直接改成 `completed／accepted`（略過待驗收、略過驗收人紀錄 `accepted_by` 為空）；③寫入任意不認得的狀態字串。沒有第二個人看過金額（`items_json`、`personnel_json`、`tax_rate`）。

### 1.3 這個洞往下游會碰到什麼
| 下游 | 規則 | 位置 | 後果 |
|---|---|---|---|
| 匯款申請（付款起點） | 派發必須 `accepted／completed` 才能開申請；一派發一申請 | `contractor_vouchers.py:299` | 申請本身有分層簽核（§5.9）＋出納付款；但**金額來源（派發）沒人審**，申請只是把派發快照凍結 |
| 營運報表／權責成本 | **所有 `status != 'cancelled'` 的派發都計入**（含草稿），日期＝發票日→驗收日→派發日，標暫用 | `case/recognition.py:218`、`analytics/api/reports.py:163` | 未審的派發已經影響成本與精算 `dispatchTotal` |
| 總帳 E（承攬應付） | `status IN ('accepted','completed')` 且有發票日 | `subcontract/gl_events.py:34-37` | 一步 `completed` ＋填發票日 ⇒ 直接入帳草稿 |
| 精算／案件管理承攬商頁 | `grandTotal`（含稅承攬商＋外包人員）排除已取消 | mod-contractor.md §5.7 | 同上 |
所以今天**付款前有一道簽核（匯款申請），但「承諾這筆支出」的那一步沒有**；使用者要的就是補這一道。

## 2. 建議流程

### 2.1 做法：新增「審核狀態」，與既有「作業狀態」分開（建議）
新欄位（migration `subcontract/0003`，只加不改）：`approval_status TEXT NOT NULL DEFAULT ''`（`''`＝舊單，見 §2.5；`待審核／簽核中／已核准／已退回`）、`approval_json TEXT NOT NULL DEFAULT '{}'`（tiers 與歷程，格式同其他單據）、`submitted_by／submitted_at／approved_at` 視需要。**既有 `status`（作業狀態）原封不動**——所有下游讀者（recognition／reports／gl_events／匯款申請／精算）繼續讀 `status`，不必同時改。理由：把「待審核」塞進 `status` 要同時改 5 個以上讀者與前端 7 選項；分開後只需在**寫入口**加一道閘（§2.3）。
替代方案（不建議）：把 `pending_approval／approved` 併進 `status` 機。代價大、回歸面廣；除非使用者要求在同一個下拉看見。

### 2.2 狀態圖（兩段審核）
```
新增派發（作業狀態固定 draft；審核狀態先空白＝草稿）
   │  送審（建立者／案件負責人與協作者／admin+）
   ▼
待審核 ──第一層──▶ 簽核中 ──最後一層──▶ 已核准      ← 第一段：派發審核（承諾這筆支出）
   │                  │
   └──── 退回（任一層）┴──▶ 已退回 ──修改後再送審──▶ 待審核
已核准 → 作業狀態可推進：draft→sent→confirmed→pending_acceptance→accepted（確認驗收，驗收人≠建立者）
accepted ──「申請完工」──▶ 完工待審核 ──分層簽核──▶ 完工已核准＝作業狀態 completed（完結）   ← 第二段：完工審核
              │（退回）└──▶ 完工已退回 ──修正後再申請──▶ 完工待審核（作業狀態維持 accepted）
cancelled：任一非終態；已核准者需理由（見 §0）
```
- **「已核准」之前，作業狀態只能是 `draft`（或 `cancelled`）**；`sent／confirmed／pending_acceptance／accepted` 都要求 `approval_status='已核准'`（或舊單 `''`）。
- **`completed` 只能由「完工審核通過」這個事件設定**（`_set_status` 的內部路徑；任何人不能直接改成 completed）。舊單 `''`：完工同樣要走完工審核（Q4 的「完工也要核准」不因舊單豁免——舊單只是**第一段**免補審）。
- 第二段欄位（同一個 migration）：`completion_status TEXT NOT NULL DEFAULT ''`（`''／待審核／簽核中／已核准／已退回`）、`completion_approval_json TEXT NOT NULL DEFAULT '{}'`、`completion_requested_by／completion_requested_at`；兩段審核各自有 tiers 與歷程，互不覆蓋。
- 簽核流程：重用 `helpers/tiered_approval.py`（`resolve_active_flow_setting`、`setting_to_active_tiers`、`check_approve_permission`、`cascade_self_tiers`、`sign_first_pending`，與匯款申請 `contractor_vouchers.py:448/549` 同一套）。兩段共用同一個流程設定（`register_doc_type('contractor_dispatch','承攬商派發', unified=True)`；可在「簽核設定」頁取消勾選改獨立的 `contractor_dispatch_approval_flow`）；**沒設簽核層＝送審即直接核准**（Q1）。
- **不能自己簽自己**：沿用 `check_no_tier_self_approval`；自簽層（組織鏈上本人就是主管）沿用 `selfApproval` 具名簽核。**同一個派發兩段審核的簽核人可相同**（部門主管兩次都簽是合理的）；職責分離只約束「驗收人≠建立者」。

### 2.3 寫入口的閘（真正的修補）
1. `POST` 建立：忽略 body 的 `status`，一律 `draft` ＋ `approval_status='待審核'` 前先是草稿態（見下「送審」）；使用者仍可存草稿。
2. `PUT` 編輯：**禁止改 `status`**（body 帶 `status` 與現值不同 ⇒ 400「請用操作按鈕」）；`待審核／簽核中` 的派發整筆不可編輯（409，同額外支出）；`已核准` 後的編輯見 §2.4。
3. 新增唯一狀態轉換函式 `_set_status(conn, did, target, user)`，**所有**寫 `contractor_dispatches.status` 的路徑（`/accept`、取消、未來按鈕）都走它；內含：白名單、轉換表（§1.1 的表＋`sent/confirmed` 的推進與 `cancelled`）、審核閘（上面）、稽核。`/accept` 保留（相容），但內部呼叫 `_set_status`。
4. 前端：「新增派發」Modal **拿掉狀態下拉**（狀態只由卡片上的操作按鈕改）；卡片依狀態顯示「送審／撤回／核准／退回／已送出／已確認／待驗收／確認驗收／完工」。
5. 靜態守門 G-D1：掃 `modules/subcontract` 內所有 `UPDATE contractor_dispatches SET ... status` 與 `INSERT ... status`，只准在 `_set_status`（白名單）出現（突變：在別處加一條 → 紅）。

### 2.4 核准後的編輯
分兩類（建議）：
- **實質欄位**（承攬商、`items_json`、`personnel_json`、`tax_rate`、總金額）：核准後要改 ⇒ **重新送審**（`approval_status` 回 `待審核`、作業狀態凍結在目前值、歷程保留「第 N 版」）；已有匯款申請者維持現行 409。
- **非實質欄位**（備註、派發日期、應付款日、發票號碼／日期）：維持現行可編輯（寫稽核）。
替代：用額外支出的「變更申請」模式（提議與原值並存，核准才生效）——實作量較大；若使用者在意「核准前原金額仍生效」才採用。

### 2.5 既有資料（不溯及既往）
- migration 對所有既有列寫 `approval_status=''`（**舊單**），並在稽核留一筆彙總；**不補核准、不補歷程**。
- 舊單行為＝與今天相同（作業狀態可照舊推進），畫面標「舊單（未經審核）」灰色徽章；**不得**用舊單做新規則下的「重新送審」以外的事。
- 舊單被實質編輯 ⇒ 視為新規則適用：要求先送審（與核准後編輯同一條），避免舊單成為繞過新機制的後門。
- 上線前唯讀盤點（正式機）：`SELECT status, COUNT(*) FROM contractor_dispatches GROUP BY status` 與其中「已有匯款申請」的筆數，給使用者看影響面。

### 2.6 完工審核與職責分離（Q4 已裁示：完工也要核准）
- 「確認驗收」（`accepted`）：admin 以上、**操作人≠建立者**、`accepted_by` 必填（修補現行 PUT 路徑可留空）；仍是單人動作（驗收本身是現場確認，不是簽核）。
- 「申請完工」：作業狀態 `accepted` 才可按；操作者＝建立者／案件負責人與協作者／admin 以上；送出後 `completion_status='待審核'`，**作業狀態仍是 `accepted`**，進入第二段分層簽核；全部簽完 ⇒ `_set_status(…, 'completed')`＋寫 `completion_approved_at`。退回（理由必填）⇒ `completion_status='已退回'`、作業狀態維持 `accepted`、可修正後再申請。待完工審核期間，派發的實質欄位凍結（同第一段）。
- 完工的下游效果＝現行 `completed` 的全部效果（精算 `dispatchTotal`、案件頁「外包總成本」標已完工、GL 已是 `accepted／completed` 皆可）——**核准前不會出現「完工」狀態**，因此畫面與報表的「完工」一詞從此代表「經審核的完結」。
- 匯款申請維持「`accepted` 或 `completed` 都可開」（2026-08-20 使用者放寬，不變），**但兩者都要求第一段已核准**（舊單除外）；完工審核**不是**開匯款申請的前置（避免把付款卡在第二段）。→ 實作前向主持確認這一點（預設＝不卡）。

## 3. 簽核佇列、通知、稽核、金額可見
- **佇列提供者**：`approval.queue_items`（subcontract 已提供匯款申請；擴充同一函式或新增第二個提供者）回 `type:"contractor_dispatch"`、`typeLabel:"承攬商派發"`、`quoteNo`（案件）、`docCode`（建議新增派發單號 `DP-YYYYMMDD-NNNN`，用既有 `next_entity_code`）、`subject`（承攬商或「外包人員（點工）」）、`total`（`grandTotal`）、`tiers／currentTier／currentApprovers`、`approveUrl`＝`/api/contractor-dispatches/{id}/approve`、`rejectUrl`、`openUrl`＝`case-management.html?q=…&tab=dispatch`（A2-0 契約欄位，佇列頁不必再改）；`approval.detail`（內容：承攬商、品項、人員與金額、稅率、案件、附件旗標）與 `approval.reassign`（轉簽，沿用 `REASSIGN` 形狀）。
- **完工審核的佇列項目**：`type:"contractor_dispatch_completion"`、`typeLabel:"承攬商派發完工"`，其餘欄位同上（`approveUrl`＝`.../completion/approve`、`rejectUrl`＝`.../completion/reject`；詳情多顯示驗收人／驗收時間）；兩種 type 各自 `approval.detail`／`approval.reassign`。
- **端點**：`POST /api/contractor-dispatches/{id}/submit`、`/approve`、`/reject`（退回，必填理由）、`/withdraw`（撤回待審核）；完工階段 `POST .../completion/request`、`.../completion/approve`、`.../completion/reject`（理由必填）、`.../completion/withdraw`；全部寫稽核（`vendor.dispatch.submit／approve／reject／withdraw`，detail 帶 tier、理由、金額摘要，**不含帳號**）。
- **通知／信件**：`mail_types.register`（owner＝subcontract，A2-0 機制）八種（兩段各四）：`dispatch_submitted／_next_tier／_approved／_returned`、`dispatch_completion_submitted／_next_tier／_approved／_returned`＋個人通知偏好；**信內不放金額**（同費用單據規則）；站內通知 `_notify`。
- **金額可見**：簽核人在佇列看得到金額（同匯款申請的 `_can_see_queue_money`）；其他人沿用現有派發列表規則（模組＋`財務金額可視` 的既有判斷）；佇列詳情不含銀行資料（F2 規則；遮蔽 `bank_mask` 不受影響）。

## 4. 「完結」對成本、精算、付款的影響（確保審核前不付款）
| 面向 | 現行 | 建議 |
|---|---|---|
| 匯款申請 | 作業狀態 `accepted／completed` 即可開 | 加條件：`approval_status='已核准'`（舊單 `''` 照舊）；否則 409「派發尚未核准」。**付款本來就要匯款申請核准＋出納，所以這條讓整條鏈 審核→驗收→申請→出納 無法被跳過** |
| 總帳 E（`gl_events.py:34`） | `accepted/completed`＋發票日 | 加 `approval_status IN ('已核准','')`（舊單不變）；未核准不入帳 |
| 營運報表權責成本（`recognition.py:218`、`reports.py:163`） | 非取消一律計入 | **會改變報表數字（Q6 已裁示）**：草稿與已退回**不計**、待審核／簽核中**計入並標「待審核」**、已核准與舊單正常計入（同額外支出規則）；完工待審核期間仍計入（作業狀態仍是 `accepted`）。**上線時公告**：本月起部分派發不再計入／改標待審核，與上一版報表會有差異；上線前提供「受影響派發數與金額」唯讀清單給使用者 |
| 精算 `dispatchTotal`／案件頁「外包總成本」 | 非取消即加總 | 跟隨報表規則；至少在畫面標「含待審核 N 筆 NT$ X」 |
| 完工 | 任何人改狀態即可 | `completed` 只能由完工審核通過設定（§2.6）；舊單同樣適用 |
| 取消 | 任意非終態可取消 | **已核准後取消＝admin 以上＋必填理由＋稽核；已有匯款申請者限 superadmin**（先處理申請）；未核准者建立者可取消 |

## 5. 測試、守門、e2e、工量
**API／單元**：①寫入口矩陣（建立帶 `status:completed` 被忽略；PUT 改 status 400；PUT 待審核 409）；②狀態轉換表逐格（含非法跳躍 409）；③簽核流程（單層、多層、自簽層、沒設簽核層＝直接核准、退回後重送、撤回）；④核准前 `contractor-vouchers` 409、核准後 201；⑤`gl_events` 未核准不產生事件（正對照：核准後有）；⑥舊單（`''`）行為不變＋實質編輯被要求送審；⑦遷移冪等＋舊列不動；⑧佇列項目形狀契約（`typeLabel／approveUrl／rejectUrl／openUrl`）、詳情不含帳號；⑨信件不含金額；⑩稽核每個動作一筆；⑪**完工審核**：`accepted` 才能申請完工、其他狀態 409；通過前 `completed` 無法由任何路徑設定（PUT／`/accept`／建立帶 status 皆拒）；退回後作業狀態仍 `accepted`；舊單也要走完工審核；驗收人＝建立者 ⇒ 409；兩段審核的 tiers／歷程互不覆蓋；⑫取消：已核准者必填理由、有匯款申請者僅 superadmin；⑬`DP-` 單號序列與唯一；⑭報表：草稿／已退回不計、待審核計入且標示、舊單照舊（兩口徑各一題）。
**守門**：G-D1（只有 `_set_status` 寫狀態；§2.3）；寫入端點稽核守門（既有 `test_write_endpoints_are_audited`）涵蓋新端點；`case_read_scope`（若新端點帶案件號）。
**突變**：移除審核閘、完工審核閘（讓 `/completion/approve` 前即可 completed）、取消不要理由、`_set_status` 白名單放寬、`/accept` 繞過 `_set_status`、匯款申請不檢查核准、`gl_events` 不檢查核准、自簽檢查拿掉。
**e2e（瀏覽器＋截圖）**：新增派發（下拉已無狀態）→ 送審 → 簽核人在簽核佇列核准 → 卡片出現「已送出」按鈕 → 推到「已驗收」（驗收人≠建立者）→ 申請完工 → 簽核人在佇列核准「承攬商派發完工」→ 狀態「完工」→ 開匯款申請成功；反向：未核准時按鈕不存在／API 409；退回→修改→再送→核准；核准後改金額⇒重新送審；舊單徽章。
**工量**：後端（migration、閘、端點、提供者、通知）1 班；前端（Modal 與卡片按鈕、徽章、佇列頁文字）0.5 班；測試＋e2e＋突變 0.5～1 班；合計約 **2.5～3 班**（含完工審核第二段：階段欄位／端點／佇列 type／信件各一組，約 +0.5 班）。層級：subcontract 模組（L2）＋L1 靜態字串（`mail_types` 登記、`register_doc_type`）＋前端頁面 ⇒ **全量班**；不動 L0。

## 6. 問題清單（原 8 題的結果）
1. 誰核准／門檻 ⇒ **已裁示**：沿用統一分層簽核；**不設金額門檻**（本期）。
2. 誰可送審 ⇒ **預設已定**：建立者、案件負責人／協作者、admin 以上。
3. 核准後改金額 ⇒ **預設已定**：實質欄位重新送審；備註／日期／發票免審。
4. 完工要不要審 ⇒ **已裁示：要**（§2.6）。
5. 既有資料 ⇒ **已裁示**：不溯及既往。上線前唯讀盤點（各狀態筆數、其中已有匯款申請者）提供給使用者看。
6. 報表 ⇒ **已裁示**（§4）；上線公告＋受影響清單。
7. 取消已核准派發 ⇒ **預設已定**：admin 以上＋理由＋稽核；有匯款申請限 superadmin。
8. 派發單號 ⇒ **要**，`DP-YYYYMMDD-NNNN`。
**實作前僅剩一個確認（主持）**：匯款申請是否**不**以「完工審核通過」為前置（本設計預設不卡，見 §2.6）。

## 7. 風險與不做
- 風險：①作業狀態分兩層（`status`＋`approval_status`）使用者可能混淆 ⇒ 卡片只顯示一個合併後的人話狀態（例「待審核」「已核准・已送出」）；②報表數字變動（問題 6）；③舊單後門（§2.5 已封）。
- 不做（本期）：依金額分流的複雜規則、跨案件批次送審、派發範本、行動版簽核。

---

# 附錄 A：匯款申請的「款別」與自動計算稅額／比例（使用者 2026-10-01 追加；狀態：**待使用者回答 §A.6**）

使用者答覆：匯款申請可在**派發第一段核准後**即建立（不必等驗收／完工）；匯款有款別 **訂金款／進度款／完工款／驗收款**，系統要**自動計算稅額與比例**。

## A.1 現況（事實）
- **一派發一張匯款申請**：`contractor_payment_vouchers.dispatch_id INTEGER UNIQUE NOT NULL`（`db.py:1570`），建立前還有應用層檢查（`contractor_vouchers.py:300-304`）；`vendor_contractors.py:590/631` 的刪除／編輯守門也以「該派發已有申請」為 409。
- **建立門檻**：派發作業狀態必須 `accepted／completed`（`contractor_vouchers.py:299`；2026-08-20 使用者放寬過一次）。
- **沒有款別、沒有比例、沒有分期**：`VoucherCreateIn` 只有 `dispatch_id`、`payable_date`（`:93-95`）；申請＝派發**全額**的凍結快照（`snapshot_json`：`totalAmount`＝承攬商未稅合計、`taxRate`、`taxAmount`、`totalWithTax`、`personnelTotal`、`grandTotal`，`:326-377`）。
- **稅**：稅額＝`round_half_up(未稅合計, 派發 tax_rate)`（預設 5%），含稅＝未稅＋稅（`:328-330`）；**外包人員金額（`personnel_json`）不計稅**、直接加進 `grandTotal`。沒有扣繳：承攬商匯款不扣繳；個人外包的扣繳／補充保費走**勞報單**（`payroll/api/payslips.py`，`helpers/legal_params.py` 扣繳率與 `round_half_up`／`floor_amount`），匯款單快照只在 personnel 列帶 `payslipNo` 做關聯（`gl_events.py` 的 `linked`）。
- **驗收步驟與欄位已存在**：作業狀態 `pending_acceptance→accepted`，`accepted_by／accepted_at`（`vendor_contractors.py:1042-1081`）。完工審核是 §2.6 新增的第二段。
- **付款**：申請走分層簽核（§5.9）→ 出納「已匯款」（`is_paid／paid_at`、`remit_actual／remit_fee／remit_review` 實付與差額審核，`subcontract/migrations/0001`）。
- **發票**只在**派發**上（`invoice_no／invoice_date／invoice_files_json`），不在申請上。

## A.2 建議模型
**新欄位（`contractor_payment_vouchers`，migration subcontract/0003 的一部分）**：`payment_kind TEXT NOT NULL DEFAULT ''`（`''`＝舊式全額申請；`deposit` 訂金款／`progress` 進度款／`completion` 完工款／`acceptance` 驗收款）、`ratio_pct REAL`（兩位小數，供顯示與驗算）、`amount_pretax REAL`（本期未稅，**權威金額**）、`seq INTEGER`（同派發同款別的第幾期，進度款可多期）、`override_reason TEXT`（超額覆寫理由）。快照照舊（`totalAmount／taxAmount／grandTotal` 改為**本期**的值，另存 `dispatchTotals`＝派發整體未稅／稅／含稅供對照）。
**移除 `dispatch_id UNIQUE`**：SQLite 無法直接 DROP 內嵌 UNIQUE，需**整表重建**（先例：`db.py::_m037_dispatch_vendor_optional`）。新唯一鍵 `(dispatch_id, payment_kind, seq)`。風險與保護：重建前整表備份列、重建後逐欄 hash／筆數比對、冪等、先在正式機資料**複本**演練（PLAYBOOK §E 演練）；所有假設 1:1 的讀者要一併改（見 A.3）。
**計算規則（後端唯一實作，前端只預覽）**：
1. 基數＝**派發承攬商部分的未稅合計**（`total_amount`；個人外包人員部分不在比例內，維持現行走勞報單／或單獨「全額」款別，見問題 4）。
2. 輸入「比例」⇒ `amount_pretax = round_half_up(基數 × 比例/100)`；輸入「金額」⇒ `比例 = amount_pretax / 基數 × 100`（四捨五入到 0.01）。兩者以 **金額為準**存檔，比例只作顯示。
3. 稅額＝`round_half_up(amount_pretax × tax_rate)`（**逐張各自四捨五入**，與廠商逐張開發票一致；派發 `tax_rate` 為準），含稅＝未稅＋稅。
4. **尾款歸零**：同派發最後一期（餘額＝0 的那張）的未稅金額＝基數 − 先前各期合計，避免分期 4 捨 5 入累積差；稅額仍依本張未稅算。
5. **累計上限**：同派發所有**未作廢**申請（含草稿，鎖額度，同發票開立單 §5.9 的作法）的 `amount_pretax` 合計 ≤ 基數；畫面顯示「已申請 X／剩餘 Y（比例 a%／b%）」。超過 ⇒ 409；**superadmin 可覆寫並必填理由**（稽核 `contractor_voucher.over_limit_override`，理由存 `override_reason`）。已作廢／被刪除的草稿釋放額度。
6. 款別唯一性：訂金款、完工款、驗收款各**至多一張有效**（作廢後可重開）；進度款可多期。款別順序**不強制**（見問題 2），但累計上限永遠生效。
7. 比例預設值（選填、可在簽核設定頁改）：訂金 30%、進度 依輸入、驗收 與 完工 合計＝餘額；預設值只是預填，不是規則。

## A.3 款別閘與下游（總帳／稅／付款不重複計）
**建立閘（建議，待 §A.6 問題 2）**：
| 款別 | 建立條件 |
|---|---|
| 訂金款、進度款 | 派發**第一段已核准**（作業狀態可為 draft…accepted 任一；舊單 `''` 亦可）|
| 驗收款 | 作業狀態 ≥ `accepted`（已有驗收人與時間） |
| 完工款 | 作業狀態 `completed`（第二段完工審核通過） |
舊式 `payment_kind=''` 全額申請：沿用現行 `accepted／completed` 門檻（相容）。**任何款別都不可在派發未核准前建立**；付款仍需申請簽核＋出納，**核准前不付款**。
**總帳（`subcontract/gl_events.py`）——不重複計的關鍵**：
- 現行 E04（承攬商發票，依**派發**的單一發票日認列未稅＋估計進項稅額／貸應付，`:34-69`；只收 `accepted／completed` 且有發票日）。**一旦同一派發有款別申請，E04 改以「每張申請」為單位**認列（日期＝該申請自己的發票日，金額＝該申請未稅／估稅／含稅），且該派發**不再**產生派發層級的 E04（以 `payment_kind<>''` 申請存在為準，避免同一筆成本入帳兩次）；舊式（`''`）與沒有申請的派發完全不變。
- E05 付款（`:70-100`）本來就是**每張申請**一筆（借應付＝快照 `grandTotal`，貸銀行＝實付），分期後自然成立；`invoiced` 集合（`:41-43`）改依「該申請（或其派發）有發票日」。
- 發票日／發票號／發票檔：新增**申請層級**欄位（`invoiceNo／invoiceDate`，存快照＋申請列），申請送審前可填；沒填時退回派發層級的值（相容）。進項稅額：估計稅額仍為「本張未稅×稅率」，會計補登實際稅額照舊（`gl_source_annotations` field=input_tax，鍵＝申請單號）。
- **個人外包人員**：不分款別、不計稅、不扣在承攬商比例內；仍由勞報單（E06，含扣繳與補充保費）處理，匯款單快照只做關聯；**不得**同時在承攬商分期與勞報單各認一次（沿用 `linked` 規則）。承攬商本身（公司）不扣繳；若承攬商是**個人**（無統編）需扣繳 ⇒ 問題 5。
- 營運報表／現金口徑（`case/recognition.py:199-209/249`）：以每張申請的 `paid_at` 與實付計，分期天然成立；權責口徑的派發成本（`recognition.py:218`）按派發全額認列的行為**不變**（避免分期改變成本歸月）——只在畫面標「已付款別」。

## A.4 UI（案件管理「承攬商」頁 → 產生匯款申請）
- 表單：款別選擇（4 個）＋「期別」（進度款）＋ 比例 % ⇄ 未稅金額 **雙向即時計算** ＋ 稅額 ＋ 含稅合計；旁邊固定顯示**派發摘要列**：派發未稅／稅／含稅、已申請（含草稿）／剩餘（金額與 %）、各款別已有的申請（單號、狀態、金額）。
- 超過剩餘額度：欄位標紅＋「超過剩餘 NT$ X」；非 superadmin 不可送出；superadmin 出現「覆寫並填理由」。
- 款別不符建立閘 ⇒ 該選項 disabled＋原因（例「驗收款需先完成驗收」）。
- 申請列表與 PDF 顯示款別、比例、本期與累計（`第 N 期／累計 a%`）；簽核佇列項目標題加款別。
- 前端只做預覽；以後端回傳的計算結果為準（有 `POST /api/contractor-vouchers/preview` 唯讀試算端點，吃款別＋比例或金額，回 `{pretax, tax, gross, ratioPct, remainingPretax, remainingPct, errors}`——同一支函式，避免兩套算法）。

## A.5 測試與突變、工量
- **計算單元**：比例⇄金額互換（含 4 捨 5 入邊界：基數 100,001、33.33%、三期尾款歸零 Σ＝基數）；逐張稅 4 捨 5 入；累計上限（含草稿、作廢釋放、超額 409、superadmin 覆寫必填理由）；款別唯一；進度款多期；個人外包不進比例。
- **閘**：每款別 × 派發狀態矩陣（核准前一律 409；驗收款需 accepted；完工款需 completed；舊式全額相容）。
- **遷移**：整表重建冪等、舊列 hash 不變、`UNIQUE` 換成 `(dispatch_id,payment_kind,seq)`、舊 1:1 讀者（recognition、gl_events、刪除／編輯守門、PDF、佇列、出納）逐個改後各一題。
- **總帳**：分期後 E04 以申請為單位且派發層級不重複（正對照：舊式不變）；E05 每期一筆；逐期稅額合計＝各申請稅額和；未開發票日的申請有 notice。
- **突變**：累計上限檢查拿掉、尾款歸零拿掉、E04 派發層級與申請層級同時產生（重複計）、款別閘拿掉、稅額改成整單×稅率後平分、比例以含稅為基數。
- **e2e**：訂金→進度×2→驗收→完工款（含畫面即時計算、超額標紅、superadmin 覆寫），每期簽核＋出納＋總帳草稿，累計＝100%；截圖。
- **工量增量**：遷移與 1:1 讀者改造 0.5 班；計算／預覽端點＋閘 0.5 班；總帳 E04 重構 0.5 班；前端表單與列表 0.5 班；測試／e2e／突變 0.5～1 班 ⇒ **約 +2.5～3 班**（總計派發審核＋款別約 **5～6 班**，建議拆兩班次：審核先上、款別接續）。層級：subcontract L2＋遷移（整表重建）＋前端＋案件 recognition 讀者 ⇒ 全量班；**列車前須用正式機資料複本演練遷移**。

## A.6 需使用者回答（最多 6 題；括號內為建議）
1. **比例的基數**：以派發「承攬商未稅合計」為 100%（建議），稅額逐張依稅率計算？還是以含稅總額為 100%？個人外包人員部分不納入比例（維持勞報單）可以嗎？
2. **各款別何時能開申請**：訂金／進度＝派發第一段核准後；**驗收款＝已驗收（accepted）；完工款＝完工審核通過（completed）**（建議）。款別順序要不要強制（例如不可在訂金前開進度款）？（建議不強制，只靠累計上限）
3. **超額**：同派發各期未稅合計不得超過派發未稅合計；超過只有 superadmin 能覆寫且必填理由（建議）。「已申請」是否包含草稿（建議包含，鎖額度）？
4. **舊式全額申請**：保留（相容，款別留空）？新建申請是否一律必選款別（建議：新建一律必選，舊的留著）？
5. **扣繳**：承攬商本身（公司）不扣繳、個人外包走勞報單，沿用現行規則？承攬商若是**個人**（無統編）需不需要在匯款申請內扣繳（目前系統沒有此功能，會是新增項目，建議本期不做、列第 32 班）。
6. **發票**：每一期（每張申請）各自登錄發票號／日期／檔案（建議），總帳進項稅額估計依每張發票日認列？還是整個派發只有一張發票（現行）？若只有一張，分期付款時成本認列日仍是同一天。
