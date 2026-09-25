# 稽核：A 的獎金三項（通知、送交出納、財務報表）＋U4 扣繳與補充保費＋IP-8／IP-9（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。只審新版（CORE-SPEC 35014aaa）。
> 對象：`wip/a-bonus` `00f331e6`（7 個 commit：`9f660c9c`、`da03a83d`、`b46157ca`、`e8d08eb3`、`a7bc64e6`、`e2b6afbf`、`00f331e6`）。**主持派工時是合回前稽核；D 開工時它已經合回 origin**（`53bcad62..0c009565`，程式碼與 `00f331e6` 相同：D 比對整棵樹，差異只有 rebase 帶進來的 4 個文件檔）⇒ 本份是**合回後稽核**。
> 規格：CORE-SPEC「使用者裁示」獎金分潤（通知、送交出納、財務報表）、U4；INTEGRATION-POINTS IP-7、IP-8、IP-9；R 的 `AUDIT-D-R1-R3-legal.md` D-1（四捨五入）。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached `00f331e6`），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：`BD`＝`backend/helpers/bonus_deductions.py`、`BP`＝`backend/helpers/bonus_payouts.py`、`RB`＝`backend/routers/bonus.py`、`TB`＝`backend/tests/platform/test_bonus_payout_connectors.py`。

## 0. 結論

- 主持點名的三個重點都成立，也都有題目：
  - **捨入**：補充保費用 `Decimal` 的 `ROUND_HALF_UP`（BD:71-74），35,000 → 739（`test_nhi_35000_is_739_not_banker_rounding`），與 R 的 D-1 一致；扣繳稅額元以下捨去。D 突變 A01（改成銀行家捨入）紅。
  - **拒絕撥付時狀態不變**：`mark-paid` 讀取前先 `BEGIN IMMEDIATE`，參數讀不到、欄位不齊、有人沒有投保金額都在 UPDATE 之前丟 409，連線關閉即回滾（RB:2441-2461）。D 突變 A03（讀不到參數就改用預設版）、A07（缺投保金額照發）都紅。
  - **出納頁的「標記已發放」與獎金頁是同一個動作**：`cashier.js:261` 與 `bonus.js:395` 都打 `POST /api/bonus/cases/{單號}/mark-paid`；`test_cashier_queue_mark_paid_is_the_same_action_and_history`。
- U4：參數一律取自 IP-7、依撥付日選版；欄位不齊就拒絕；單據存版本、參數快照與整份 rules（突變 A06、A08 紅）。
- 通知：輪到的簽核人＋代理人，進入待發放時通知出納，名單成員不因在名單上而收到，信裡不放金額（突變 A09 紅）。
- 可見範圍：獎金只給最高管理者與出納，財務看不到（突變 A10 紅）。
- 基準：`TB` 27 passed；連同 `test_bonus_case_vouchers`、`test_bonus_case_api` 共 **68 passed**（10 分鐘，滿載）。D 自做突變 11 項：**10 紅、1 存活**。
- **必修 0 項**。建議 2 項、觀察 3 項。

## 1. 突變（D 自做；每項都用 `git checkout` 還原並核對內容）

突變只跑 `TB`（IP-8／IP-9／U4 的題目都在這一檔）。第一輪連同另外兩檔跑，基準就要 10 分鐘，D 把那一輪停掉（`taskkill /T`，並確認沒有孤兒行程）。停掉時 A01 正在執行，被突變的檔案留在稽核樹上，D 已用 `git checkout` 還原並核對，之後才重跑這一輪。

| 突變 | 結果 | 轉紅的題 |
|---|---|---|
| A01 補充保費改成銀行家捨入 | 🔴 | `test_nhi_rounds_half_up`、`test_nhi_35000_is_739_not_banker_rounding` |
| A02 起扣標準改成「≤ 也不扣」 | 🔴 | `test_withholding_threshold_boundary_and_floor` |
| A03 讀不到法規參數就改用預設版 | 🔴 | `test_no_applicable_version_refuses_payout` 等 2 |
| A04 全年累計連未發放的獎金也算進去 | 🟢 **存活** | —（A-S1） |
| A05 門檻不看累計前的金額 | 🔴 | `test_nhi_only_the_part_over_four_times_insured` 等 2 |
| A06 不存整份 rules 快照 | 🔴 | 1 題 |
| A07 缺投保金額照樣發放 | 🔴 | `test_mark_paid_refuses_without_insured_amount` |
| A08 標記已發放不存扣繳快照 | 🔴 | 2 題 |
| A09 不通知代理人 | 🔴 | `test_notify_approver_with_delegate_then_cashier_never_members` |
| A10 財務也看得到獎金 | 🔴 | `test_cashier_queue_mark_paid_is_the_same_action_and_history` |
| A11 傳票不列代收補充保費 | 🔴 | `test_mark_paid_computes_and_books_deductions` |

## 2. 發現

### 建議

- **A-S1　全年累計「只算已發放」沒有題目（突變 A04 存活）**：`ytd_in_motrix`（BD:183-193）以 `status='已發放'` 且發放年度相同為條件。把條件改成「全部都算」（包含待發放、待審核的其他案件），題目照樣綠。原因是題目裡每個人只出現在一張單上。累計決定補充保費的計費基數（投保金額 × 4 之後的部分），算錯就是多扣或少扣。建議補一題：同一人有一張已發放、一張待發放的單，發放第三張時，累計只含已發放的那一張；另外補同一年度、跨年度各一題。
- **A-S2　投保金額與全年累計的設定是「整份讀、改一人、整份寫回」**：`put_insurance_profile`（RB:2520 起）在交易外讀 `payroll_insurance_profiles`，再用 `_set_setting` 整份寫回。兩位最高管理者同時改不同的人，後寫的會蓋掉先寫的。另外，`load_profiles`（BD:156-164）讀到壞掉的 JSON 會回 `{}`：撥付端因此把每個人都列為 missing ⇒ 拒絕撥付（安全）；但這時只要有人在設定頁存一次，就會以 `{}` 為底寫回，**其他人的投保金額全部消失**。與 R 的 S-3 同一類。建議讀改寫包在寫交易裡；讀不懂時拒絕寫入並告警。

### 觀察

- **A-O1　單次上限 1,000 萬套在「計費基數」而不是「給付金額」**：`nhi_base_of`（BD:61-68）算 `min(累計前 + 本次 − max(門檻, 累計前), 上限)`。健保法 §31 I 但書寫的是「單次給付金額逾新臺幣一千萬元之部分……免予扣取」，依條文，應該先把本次給付截到 1,000 萬，再扣掉門檻。例如本次 1,500 萬、累計前 0、門檻 20 萬：
  - 條文的算法 ⇒ 980 萬
  - 程式的算法 ⇒ 1,000 萬（補充保費差 4,220 元）

  只有單次超過 1,000 萬時才會不同，實務上很少見。條文依據見 `AUDIT-D-R1-R3-legal.md` L-9；建議請會計確認後，決定要不要改。
- **A-O2　代扣稅款與代收補充保費預設同一個科目 2252**：`bonus_vouchers.ACCOUNT_SLOTS` 兩者預設都是 2252，各自可以在設定裡改。傳票分兩行、摘要不同，所以借貸平衡、看得出來源。要不要分科目，由會計決定。
- **A-O3　IP-9 的「對方不在時不另加提示」有一個例外**：INTEGRATION-POINTS 已經寫明。M07 曾經安裝、之後被停用而資料還在時，報表會少列那些已發放的獎金，而且畫面上沒有任何提示。這與 IP-1 稽核 X-1「缺席要明說」的精神不同。作者已經列為觀察，D 同意維持觀察，但建議在模組管理頁停用 M07 時，提示「報表將不再列入獎金支出」。

## 3. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| A-S1 | | | |
| A-S2 | | | |
| A-O1～O3 | | | |
