# 稽核：C 的待簽彙整搬進 L1（wip/c-approval-l1 3897f15b；疊在 c-m01-5 a1e0a45b 上）（D，2026-09-27 12:26）

> 完整稽核（權限類；使用者裁示：待簽彙整搬進 L1）。稽核者 D 沒有寫過任何受稽核的程式碼。
> 內容：`/api/approval-queue` 四支（佇列、角標、詳情、轉簽）從 M01 搬到 L1 `routers/approval_queue.py`，路徑不變；M01 改為 `approval.queue_items`（五種）與 `approval.detail`（四種）的提供者；頁面、選單、前綴歸 L1；`case.summary` 加 `deal_tag`。

## 0. 結論

- **必修 1、建議 1、觀察 4、待驗 1**（真刪 M06，第十二班後由 C 補）。

## 1. 實測

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 路徑不變 | M01 在時 `/openapi.json`（方法＋路徑）：a1e0a45b **566 ⇔ 3897f15b 566，逐條相同**；四支 approval-queue 都在 | 成立 |
| **行為等價**（D 自寫探針，新舊兩棵樹同一份種子） | 7 種身分（superadmin、admin、只是簽核人的 viewer、業務、外人、送審的案件管理者、engineer＋case_manage）×（佇列、角標、報價單／完工單／已結案變更的詳情、兩種查無）：**輸出 1074 行逐格相同**。輸出本身有實質差異（外人 404、簽核人 200、案件管理者金額遮蔽、申請人看自己的變更），不是空洞的綠 | 成立 |
| ① 詳情守門 | 本單簽核人放行，否則 `guard_case_access`（c-case404 的 404）；四種 M01 提供者的 `approvalRaw` 與舊版逐一相同（case_change 仍是 None ⇒ 不走簽核人放行）。突變 AQ1「簽核人不放行」⇒ 紅；AQ2「不守門」⇒ 紅 | 成立 |
| ① M01 不在時（真實 M05 單據） | 真刪 M01 樹種一張待簽請款單：簽核人看得到佇列、詳情 200、抬頭只有單號；外人 404；**非簽核人的 superadmin 也 404**（符合裁示）；送審人本人 200——`is_document_approver` 本來就含 requestedBy，既有規則 | 成立 |
| **② selfViewBy** | 突變 AQ3「不比對是不是本人」、AQ4「selfViewBy 不生效」⇒ **兩個都存活**（相關 30 檔 380 題全綠）。AQ3 下外人打已結案變更詳情 ⇒ **200，並看到客戶、案名、成交標籤** | **不成立 ⇒ AL-M1** |
| ③ SYSTEM 呼叫 case.summary | 佇列：先以 SYSTEM 補名稱，再做可見性過濾，被濾掉的項目不外流；詳情：守門之後才取抬頭。突變 AQ5「改用本人身分」⇒ 紅（26） | 成立 |
| ④ 角標 | 舊版遇到簽核 JSON 壞掉的報價單時，`json_extract` 丟 `malformed JSON`，**整支端點 500**（D 探針在 a1e0a45b 重現）；新版列出並對 superadmin 計 1，與佇列一致。突變 AQ6 ⇒ 紅 | 成立（是改善） |
| 佇列可見性、金額遮蔽 | AQ7「佇列不過濾」⇒ 紅；AQ8「金額不遮」⇒ 紅 | 成立 |
| 轉簽權限沒有放寬 | 與舊版逐行相同，`require_superadmin=True`；AQ9 拿掉 ⇒ 紅 | 成立 |
| `deal_tag` 與 a-m06-8 的交會 | a-m06-8（b33aab7d）的 voucher_link 路徑回的是 `{k for k in SUMMARY_LINK_FIELDS}`，`cols` 多選 deal_tag 也不會外流；`test_case_summary_purpose` 斷言 `set(r) == {quote_no, customer_name, project_name}` ⇒ rebase 若把 deal_tag 解進 wide 的回傳會紅 | 成立（rebase 要逐 hunk） |
| 真刪 M01（tests/platform＋名稱或內容含 approval 的 116 檔） | 非 e2e：1493 過、647 略過、**5 紅＝§B-11 允許**；e2e：36 過、0 紅 | 成立 |
| 真刪 M05（同範圍） | 非 e2e：允許 5 紅＋**2 紅**（analytics `test_accrual_income_…`、`test_case_attachments_scope[invoice_voucher]`）；e2e 0 紅。這 2 紅在基底 a1e0a45b 拿掉 M05 時同樣紅 ⇒ 不是本包造成（AL-O1） | 成立 |
| 真刪 M06 | 待驗（主持指示：第十二班合回後由 C 補） | 待驗 |

## 2. 發現

**AL-M1（必修）　`selfViewBy`（申請人本人免每案守門）兩個方向都沒有題鎖住**
- L1 的規則是 `if not (d.get("selfViewBy") and d["selfViewBy"] == user["username"]): guard`。現在任何提供者宣告 `selfViewBy`，L1 就照做。
- 突變驗證：
  - AQ3 把「是不是本人」的比對拿掉 ⇒ 任何人拿到已結案變更的編號都能看詳情（IDOR，D 以探針證明：外人 200，看得到客戶、案名、成交標籤），**380 題全綠**；
  - AQ4 讓它失效 ⇒ 沒有案件權限的申請人看不到自己的申請，也全綠。
- 補兩題，都要用**沒有案件權限**的人才分得出來：
  - ① 外人打已結案變更詳情 ⇒ 404（與查無同訊息）；
  - ② 沒有案件權限的申請人本人 ⇒ 200。
- 建議順便在 docstring 寫明 `selfViewBy` 是誰可以宣告的（目前只有 M01 的 case_change）。

**AL-S1（建議，既有問題，非本包造成）　詳情的「查無」與「看不到」訊息不同**
- 外人打詳情：
  - 查無回「報價單不存在」「完工單不存在」（提供者回 None 時 L1 的訊息，或提供者自己的訊息）；
  - 看不到回「報價單 MQ-X 不存在」。
- 兩者分得出來 ⇒ 可列舉單號；用完工單號去打，還會洩漏它掛在哪一張報價單上。
- 新舊兩版相同（等價探針的一部分），但違反 c-case404「看不到＝不存在、訊息逐字相同」的原則。端點現在歸 L1，建議由 L1 統一：提供者回 None 與守門拒絕都用 `case_not_found_message`，而且不帶關聯單號。

**觀察**
- **AL-O1**：真刪 M05 時的 2 紅在基底就存在，是 M05 缺席時題目沒有處置（與 M4-M3 同類，屬於 M05 的反向控制範圍）。
- **AL-O2**：`modules/arap/api/payment_requests.py::queue_detail` 的 docstring 仍寫「權限、案件抬頭、金額遮蔽在 M01」，現在在 L1。
- **AL-O3**：M01 不在時，superadmin 在佇列看得到別人的待簽（可見性 admin+ 全看），點開詳情卻是 404（守門 fail-closed，符合裁示）。這是裁示的直接後果，是否要在畫面上說明，交主持。
- **AL-O4**：④ 的新行為本身**沒有題**：壞 JSON 的報價單佇列列出、角標對 superadmin 計 1、而且不 500。
  - D 查過：repo 裡壞 JSON 的題只有轉簽（`test_unreadable_chain_is_refused` 等）。
  - AQ6 會紅，是因為它連正常的「沒有簽核層」單據也一起排除了，不是壞 JSON。
  - 建議補一題，把舊版會 500 的那條路鎖住。
