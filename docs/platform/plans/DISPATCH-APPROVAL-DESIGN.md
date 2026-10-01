# 承攬商派發的審核機制——設計（第 31 班；2026-10-01 草擬，唯讀分析，未跑測試）

使用者原話（2026-10-01）：「承攬商派發管理的新增派發，也要有審核機制，目前只有派發然後手動選狀態，沒有審核直接能完結」。基底：包 47db5613。引用格式 `檔:行`＝該 commit 的行號。

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

### 2.2 狀態圖
```
新增派發（作業狀態固定 draft；審核狀態 ''→ 見下）
   │  送審（創建人，admin+）
   ▼
待審核 ──第一層簽核──▶ 簽核中 ──最後一層──▶ 已核准
   │                      │
   └──── 退回（任一層）───┴──▶ 已退回 ──修改後再送審──▶ 待審核
已核准 → 作業狀態才可往下：draft→sent→confirmed→pending_acceptance→accepted→completed（cancelled 任一非終態）
```
- **「已核准」之前，作業狀態只能是 `draft`（或 `cancelled`）**；`sent／confirmed／pending_acceptance／accepted／completed` 都要求 `approval_status='已核准'`（或舊單 `''`，見 §2.5）。
- 簽核流程：重用 `helpers/tiered_approval.py`（`resolve_active_flow_setting`、`setting_to_active_tiers`、`check_approve_permission`、`cascade_self_tiers`、`sign_first_pending`，與匯款申請 `contractor_vouchers.py:448/549` 同一套）。**預設鏈＝申請人部門主管→（組織鏈）→最高管理者**（沿用 `includeSubmitterManagerTier` 內建層；既有規則：沒設簽核層＝直接核准，對照額外支出）。流程設定 key：預設併入統一流程（`register_doc_type('contractor_dispatch','承攬商派發', unified=True)`），可在「簽核設定」頁取消勾選改獨立的 `contractor_dispatch_approval_flow`（與發票開立簽核單相同做法，§5.9）。
- **不能自己簽自己**：依 tiered_approval 既有規則（`check_no_tier_self_approval`）；自簽層（組織鏈上本人就是主管）沿用 `selfApproval` 具名簽核。

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

### 2.6 完工／驗收要不要也審？
**建議不新增第二套簽核**，改用**職責分離**：`accepted`（確認驗收）與 `completed` 要求操作人**不是建立者**且為 admin 以上（現行只要 admin）；驗收人紀錄 `accepted_by` 必填（現在 PUT 路徑可為空）。若使用者要求完工也走簽核，可把同一套 tiers 再開一個「完工審核」階段（`completion_approval_json`），工量 +0.5 班——列為問題 4。

## 3. 簽核佇列、通知、稽核、金額可見
- **佇列提供者**：`approval.queue_items`（subcontract 已提供匯款申請；擴充同一函式或新增第二個提供者）回 `type:"contractor_dispatch"`、`typeLabel:"承攬商派發"`、`quoteNo`（案件）、`docCode`（建議新增派發單號 `DP-YYYYMMDD-NNNN`，用既有 `next_entity_code`）、`subject`（承攬商或「外包人員（點工）」）、`total`（`grandTotal`）、`tiers／currentTier／currentApprovers`、`approveUrl`＝`/api/contractor-dispatches/{id}/approve`、`rejectUrl`、`openUrl`＝`case-management.html?q=…&tab=dispatch`（A2-0 契約欄位，佇列頁不必再改）；`approval.detail`（內容：承攬商、品項、人員與金額、稅率、案件、附件旗標）與 `approval.reassign`（轉簽，沿用 `REASSIGN` 形狀）。
- **端點**：`POST /api/contractor-dispatches/{id}/submit`、`/approve`、`/reject`（退回，必填理由）、`/withdraw`（撤回待審核）；全部寫稽核（`vendor.dispatch.submit／approve／reject／withdraw`，detail 帶 tier、理由、金額摘要，**不含帳號**）。
- **通知／信件**：`mail_types.register`（owner＝subcontract，A2-0 機制）四種：`dispatch_submitted／_next_tier／_approved／_returned`＋個人通知偏好；**信內不放金額**（同費用單據規則）；站內通知 `_notify`。
- **金額可見**：簽核人在佇列看得到金額（同匯款申請的 `_can_see_queue_money`）；其他人沿用現有派發列表規則（模組＋`財務金額可視` 的既有判斷）；佇列詳情不含銀行資料（F2 規則；遮蔽 `bank_mask` 不受影響）。

## 4. 「完結」對成本、精算、付款的影響（確保審核前不付款）
| 面向 | 現行 | 建議 |
|---|---|---|
| 匯款申請 | 作業狀態 `accepted／completed` 即可開 | 加條件：`approval_status='已核准'`（舊單 `''` 照舊）；否則 409「派發尚未核准」。**付款本來就要匯款申請核准＋出納，所以這條讓整條鏈 審核→驗收→申請→出納 無法被跳過** |
| 總帳 E（`gl_events.py:34`） | `accepted/completed`＋發票日 | 加 `approval_status IN ('已核准','')`（舊單不變）；未核准不入帳 |
| 營運報表權責成本（`recognition.py:218`、`reports.py:163`） | 非取消一律計入 | **會改變報表數字**（需使用者裁示）：建議比照額外支出——草稿與已退回不計、待審核／簽核中計入並標「待審核」、已核准正常；舊單照舊。若使用者要保守：本期維持現行（只改上面兩條），報表另期處理 |
| 精算 `dispatchTotal`／案件頁「外包總成本」 | 非取消即加總 | 跟隨報表規則；至少在畫面標「含待審核 N 筆 NT$ X」 |
| 取消 | 任意非終態可取消 | 已核准且已有匯款申請者不可取消（先處理申請）；取消寫稽核＋理由 |

## 5. 測試、守門、e2e、工量
**API／單元**：①寫入口矩陣（建立帶 `status:completed` 被忽略；PUT 改 status 400；PUT 待審核 409）；②狀態轉換表逐格（含非法跳躍 409）；③簽核流程（單層、多層、自簽層、沒設簽核層＝直接核准、退回後重送、撤回）；④核准前 `contractor-vouchers` 409、核准後 201；⑤`gl_events` 未核准不產生事件（正對照：核准後有）；⑥舊單（`''`）行為不變＋實質編輯被要求送審；⑦遷移冪等＋舊列不動；⑧佇列項目形狀契約（`typeLabel／approveUrl／rejectUrl／openUrl`）、詳情不含帳號；⑨信件不含金額；⑩稽核每個動作一筆。
**守門**：G-D1（只有 `_set_status` 寫狀態；§2.3）；寫入端點稽核守門（既有 `test_write_endpoints_are_audited`）涵蓋新端點；`case_read_scope`（若新端點帶案件號）。
**突變**：移除審核閘、`_set_status` 白名單放寬、`/accept` 繞過 `_set_status`、匯款申請不檢查核准、`gl_events` 不檢查核准、自簽檢查拿掉。
**e2e（瀏覽器＋截圖）**：新增派發（下拉已無狀態）→ 送審 → 簽核人在簽核佇列核准 → 卡片出現「已送出」按鈕 → 推到「完工」→ 開匯款申請成功；反向：未核准時按鈕不存在／API 409；退回→修改→再送→核准；核准後改金額⇒重新送審；舊單徽章。
**工量**：後端（migration、閘、端點、提供者、通知）1 班；前端（Modal 與卡片按鈕、徽章、佇列頁文字）0.5 班；測試＋e2e＋突變 0.5～1 班；合計約 **2～2.5 班**。層級：subcontract 模組（L2）＋L1 靜態字串（`mail_types` 登記、`register_doc_type`）＋前端頁面 ⇒ **全量班**；不動 L0。

## 6. 待使用者裁示（編號）
1. **誰核准**：沿用統一流程（申請人部門主管→最高管理者）？還是獨立流程（例如只要採購主管／最高管理者）？是否要「金額門檻」（小額免審、大額才審）？門檻金額與單位（派發總額含稅？）。
2. **誰可以送審／建立**：維持 admin 以上＋模組？
3. **核准後改金額**：重新送審（建議）還是用「變更申請」（原金額在核准前仍生效）？非實質欄位（備註、日期、發票）可否免審？
4. **完工／驗收要不要也審核**：建議只做職責分離（驗收人≠建立者）；是否要完工也走一次簽核？
5. **既有資料**：舊單（`''`）是否一律維持現狀（建議），還是上線時要求「進行中的」補送審？盤點數字上線前提供。
6. **報表**：待審核／草稿的派發要不要計入權責成本（建議待審核計入並標示、草稿與退回不計；會讓部分月份數字變動）？本期要不要動報表，還是只閘付款與總帳？
7. **取消**：已核准的派發誰可以取消（admin？只有 superadmin？），要不要理由？
8. 派發單號 `DP-…` 要不要（簽核佇列與信件需要一個人看得懂的識別）？

## 7. 風險與不做
- 風險：①作業狀態分兩層（`status`＋`approval_status`）使用者可能混淆 ⇒ 卡片只顯示一個合併後的人話狀態（例「待審核」「已核准・已送出」）；②報表數字變動（問題 6）；③舊單後門（§2.5 已封）。
- 不做（本期）：依金額分流的複雜規則、跨案件批次送審、派發範本、行動版簽核。
