# 稽核：A 的 IP-21 attachments.for_document（wip/a-attachments afcfb513；合回前）（D 稽核，2026-09-26 17:34）

> 完整稽核：動到 C 的 subcontract、M06 讀附件的程式、L1 uploads。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`fdddb641`、`1ae7c870`、`afcfb513`。內容：
> - 九類附件來源改由擁有模組提供：M01 案件 6 類（`helpers/case_attachments.py`）、M05 開票申請 1 類（`routers/invoice_vouchers.py`）、M04 派工單與承攬商發票 2 類（`modules/subcontract/attachments.py`）。
> - `voucher_attachments` 不再讀別組的表。
> - 模組不在時，候選清單回 `unavailable`，帶入與列檔回 400 並明說。

## 0. 結論

- **必修 1（待主持裁示）、建議 2、觀察 1**。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 基準：tests/platform＋subcontract 題＋引用附件的 28 檔（`-n 4`） | 1490 過、1 紅（test_map 過期，交列車） |
| 基準：相關 e2e 4 檔（`-n 2`） | 15 過 |
| §B-11：D2 刪 `modules/subcontract`；tests/platform＋38 檔 | 非 e2e：1451 過、25 skip、**5 紅＝允許 2＋產生檔 3**；e2e：12 過、3 skip；不帶旗標的 `--collect-only`：1496 題、無收集錯誤 |
| 主持重點①：M04 不在 | 候選清單有 `unavailable`：「外包工班模組未安裝：派工單、承攬商發票的附件沒有列出」；帶入與列檔回 400：「外包工班模組未安裝，無法帶入…」。突變 AT1、AT2、AT6 都紅 |
| 主持重點②：已帶入的附件不受影響 | 本包沒有這一題，**D 自寫探針驗證**：先帶入報價單回簽檔，再拿掉**全部**的 `attachments.for_document` 提供者 ⇒ 下載 200（15 bytes）、傳票明細照常列出；重新帶入 ⇒ 400「案件模組未安裝，無法帶入報價單回簽檔附件。」 |
| 主持重點③：M06-PLAN §5 b 列的到期 | 見 §3 AT-S1 |
| 主持重點④：附件權限 | 見 §3 AT-M1 |
| voucher_attachments 殘留的 SQL | 只剩 `voucher_attachments`、`vouchers_all`、`voucher_lines`（M06 自己的表） |

## 2. 突變

| # | 突變 | 結果 |
|---|---|---|
| AT1 | 提供者不在時回空清單 | 紅 |
| AT2 | `unavailable_sources` 恆空 | 紅（2） |
| AT3 | 承攬商發票改讀派工單的欄位 | 紅（3） |
| AT4 | 案件編號與索引改從左切 | 存活。**等價突變**：案件編號只含 `-` 不含 `_`，從左或從右切結果相同 |
| AT5 | 案件動態的附件 JSON 壞掉時吞成空清單 | **存活** ⇒ AT-S2 |
| AT6 | 列檔端點不帶 `unavailable` | 紅（e2e） |

## 3. 發現

### 必修（待主持裁示）

**AT-M1　「只有能看到原單據的人才能列出或下載附件」：目前不成立，新契約也做不到**
- 列出候選（`/api/vouchers/line-source-files`）、預覽來源檔、帶入，都只檢查 `_require_voucher_access`：有傳票相關模組就行，不看使用者能不能看那張案件或派工單。
- 這是 JV36／JV28 起就有的狀況，不是本包造成的。
- 但本包新定的 IP-21 契約是 `files(conn, source_type, doc_no)`／`doc_nos_for_case(conn, source_type, quote_no)`，**沒有 user 參數**，擁有模組就算要擋也沒有依據。之後再補參數，等於改 L1 契約。
- 兩條路，請主持裁示：
  - (a) 裁定「傳票模組權限就足以看所有來源附件」（會計需要），寫進 IP-21，本項結案。
  - (b) 契約現在就加 `user`，由各提供者用自己的可見性判斷（M01 用 row_access `case`）。
- D 建議 (b)：現在加是新增參數，之後加是改契約。

### 建議

**AT-S1　M06-PLAN §5 的 b 列：這包已經達成，但計畫表沒有更新，而它的到期守門還不存在**
- `test_accounting_foreign_reads.py` 還沒寫，計畫在 M06 搬遷時才建，所以目前沒有東西會「觸發」。
- 本包已經把 b 列列出的讀表全部拿掉（見 §1 殘留 SQL），b 列實質上已到期。
- 建議在本包或下一班把 §5 的 b 列劃掉並寫上 SHA，否則之後照表建守門時，基線會多出一筆已經不存在的讀取。依計畫寫的「檔已不讀那張表 ⇒ 紅」，到時會觸發，但那是事後才發現。

**AT-S2　案件動態（`case_update`）的附件 JSON 壞掉時被吞成空清單，沒有題驗**
- `test_l1_side_providers_refuse_to_swallow_broken_json` 只參數化 `case`／`arap` 走 `files_from_json_column` 的那幾類。
- `case_update` 迴圈與 `_case_record`（payment_item、material 類）的壞 JSON 路徑沒有題。
- 建議各補一筆合成壞資料。

### 觀察

- **AT-O1**：AT4 是等價突變；如果之後案件編號允許 `_`，右切是唯一正確的做法，現有題會照綠。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| AT-M1 | 修正（主持裁示 (b)，`wip/a-attachments-2`）：IP-21 契約加 `user`；三個提供者都以 L1 `helpers.case_access.case_documents_readable`（同各單據清單：`case_access_allowed(..., allow_module="case_manage")`）判斷，看不到 ⇒ `AttachmentNotVisible`；M06 列清單不列、帶入／預覽 403。反向控制：同樣有 finance、看不到案件的人列不出、預覽不到、帶不進；每個提供者對看不到的人丟例外。突變 AT2-M1～M6 皆紅 | 46f0e804 | |
| AT-S1 | 修正：M06-PLAN §5 b 列劃掉並加〔更正〕（已到期，建守門時不列） | 46f0e804 | |
| AT-S2 | 修正：補案件動態與 caseRecord 三類的壞 JSON 題；AT5 轉紅 | 46f0e804 | |
| AT-O1 | 同意（等價突變，右切是案件編號允許 `_` 時唯一正確的做法），不改 | — | |

## 4. 複核：wip/a-attachments-2 46f0e804（取代 afcfb513；D 18:18）

- 修法（主持裁示 (b)）：
  - 契約四支方法都加 `user`。
  - 各提供者用 L1 新增的 `helpers.case_access.case_documents_readable(conn, quote_no, user)` 判斷：看不到就 `AttachmentNotVisible`；列清單時不列，帶入與預覽回 403。
  - M06-PLAN §5 的 b 列已劃掉並加〔更正〕。
- 基準：attachments、subcontract、voucher 附件、jv36、jv24、l1 snapshot、generated_maps，96 過。

| 突變 | 結果 |
|---|---|
| V1 `case_documents_readable` 恆真 | 紅（3） |
| V2 派工單提供者 `files()` 不查權限 | 紅 |
| V3 開票申請提供者 `files()` 不查權限 | **存活**（58 過） |
| V4 案件動態壞 JSON 吞成空（AT-S2） | 紅（`test_case_update_broken_json_is_said_not_swallowed`） |
| V5 案件提供者 `files()` 不查權限 | 紅（2） |

**主持重點「`case_documents_readable` 與 case.access 的判準一致」**
- 對 case.access 本身而言一致：兩者都是 `case_access_allowed(conn, q, user, allow_module="case_manage")`，也就是 row_access `case`／owner，或持有 case_manage 模組；M01 不在 ⇒ False。
- **但它和各類原單據自己的讀取規則不一致**：

| 來源類型 | 原單據自己的讀取規則 | `case_documents_readable` | 差異 |
|---|---|---|---|
| quotation_signed／case_update／payment_item／material* | `guard_case_access(allow_module="case_manage")` | 同 | 一致 |
| **extra_expense** | `case_extra_expenses._guard_case` ＝ `row_access.require("case", …)`，**不放行 case_manage** | 放行 case_manage | **較寬** |
| **invoice_voucher** | 案件層＋**金額層**（`can_see_financial` 或本單簽核人；`invoice_vouchers.py:60-80`） | 沒有金額層 | **較寬** |
| contractor_dispatch／invoice | 只檢查模組（procurement／case_manage／contractor_list），沒有每案檢查 | 每案 | 較嚴（安全的方向；派工清單本身沒有每案 IDOR 守門屬既有狀況，另列觀察） |

- **D 實測（探針，不提交）**：「d_other」持有 case_manage＋finance，是 sales、非擁有者。
  - `GET /api/quotations/MQ-DPROBE-1/extra-expenses` ⇒ **403**
  - `GET /api/vouchers/line-source-files?source_type=case&ref=MQ-DPROBE-1` ⇒ **200，列出 `extra_expense` 的附件**
  - 也就是說，原單據頁看不到的附件，經傳票看得到。

⇒ **AT-M1 未關**，改列 **AT-M1b**：
1. 每一類要用「那張原單據自己的讀取規則」：額外支出用 row_access `case` 的 owner；開票申請加金額層。最直接的做法是由各提供者呼叫自己模組的守門，而不是共用一個 L1 函式；若要保留 L1 函式，就得讓它依類型取不同規則。
2. 補一題：開票申請提供者 `files()` 對看不到的人要拒絕（V3 要轉紅）。
3. 探針的情境（case_manage＋finance、非擁有者 ⇒ extra_expense 不列）納入正式題。

**AT-S1 關閉**（M06-PLAN §5 b 列已劃掉並寫〔更正〕）。**AT-S2 關閉**（V4 紅）。
**A 回覆（2026-09-26 18:38，`wip/a-attachments-3` 9973d10b）**：
1. 每一類改用原單據端點的同一支判斷函式（不共用寬鬆判準）：extra_expense ⇒ L1 `case_owner_readable`（`case_extra_expenses._guard_case` 改呼叫它）；invoice_voucher ⇒ `invoice_vouchers._voucher_readable`（`_guard_voucher` 改呼叫它，拒絕訊息照舊）；`doc_nos_for_case` 逐張過濾。
2. V3 轉紅：`test_invoice_voucher_attachments_keep_the_amount_layer`（engineer＋case_manage＋finance：自己端點 403 ⇒ 不列、`files()` 拒絕；持 financial_view 的正對照放行）。
3. 探針入正式題：`test_extra_expense_attachments_are_not_wider_than_the_extra_expense_pages`（sales＋case_manage＋finance 非擁有者：自己端點 403 ⇒ 經傳票不列、預覽不到、帶入 403；admin 正對照）。
- 突變 5/5 紅（V3、開票列單號不過濾、少金額層、額外支出退回 `case_documents_readable`、擁有者規則放行 case_manage）。M04 派工單維持每案判準（較嚴，AT-O2 另案）。

- 觀察 **AT-O2**：`/api/contractor-dispatches?quote_no=` 與 `/{did}` 只檢查模組、沒有每案檢查（既有狀況，與本包無關）；可列舉的 id 會形成 IDOR。

## 5. 複核：wip/a-attachments-3 9973d10b（AT-M1b；D 18:44）

- 修法：
  - 額外支出改用 L1 新增的 `case_owner_readable`（row_access `case`／owner，不放行模組），與 `case_extra_expenses._guard_case` 共用。
  - 開票申請抽出 `_voucher_readable`（案件層＋金額層），與 `_guard_voucher` 共用；`doc_nos_for_case` 逐張過濾。

| 主持的問題 | D 的驗證 | 結果 |
|---|---|---|
| ① 探針情境現在 403 或不列 | 同一支探針（case_manage＋finance、非擁有者） | 經傳票列出的來源**已經沒有 `extra_expense`** ⇒ 成立 |
| ② 原單據端點的拒絕行為沒變 | `row_access.require` 的預設 scope 就是 `"owner"` ⇒ `case_owner_readable` 與原本的判準相同；引用額外支出或開票申請端點的 37 檔＋A 的新題 | 409 過；突變 W1「開票不看金額層」、W2「擁有者規則放行 case_manage」都紅 |
| ③ 還有沒有第三類比原單據寬 | 逐類比對原單據端點，並擴充探針 | **有，見下** |

**AT-M1c（必修）　存在報價單上的四類附件，判準仍然比原單據寬**
- quotation_signed、payment_item、material、material_invoice 都存在 `quotations`（`signed_files_json`、`data_json` 的 caseRecord）。
  - 原單據端點是 `GET /api/quotations/{q}`：`row_access.require("case", user, row, scope="read")`，也就是擁有者、協作者、admin+、**cashier**，**不放行 case_manage**。
  - 附件提供者仍用 `case_documents_readable`，也就是放行 case_manage。
- 只有 case_update 的原單據端點（`list_case_updates`）真的是 `_guard_case(allow_module="case_manage")`，這一類一致。
- **D 實測**：
  - 非擁有者 case_manage＋finance：`GET /api/quotations/MQ-DPROBE-1` ⇒ **403**；經傳票 ⇒ **200，列出 `quotation_signed`**。**較寬**。
  - 反方向：cashier 帳號：`GET /api/quotations/…` ⇒ **200**；經傳票 ⇒ 200 但**一筆都不列**。**較嚴**：傳票權限正是 cashier／finance，出納看得到案件的回簽檔，卻帶不進傳票。
- 修法：這四類改用案件頁本身的讀取規則，也就是 row_access `case`／scope="read"，比照 AT-M1b 的做法抽成一支函式，與 `get_quotation` 共用。補上兩種情境的正式題：case_manage 非擁有者不列，cashier 要列。
- 若主持認為帶入案件附件應該放行 case_manage，那就改的是「案件頁的讀取規則」，不是只放寬附件，需要另外裁示。
