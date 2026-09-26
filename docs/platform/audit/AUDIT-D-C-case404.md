# 稽核：C 的 case404——看不到＝不存在（wip/c-case404 f743662b；疊在 ② 上）（D，2026-09-27 00:24）

> 完整稽核（權限類）。稽核者 D 沒有寫過任何受稽核的程式碼。
> 內容：L1 `helpers/case_access.py` 新增 `deny_case`／`require_case`。逐案被拒與查無都回同一個 404、訊息逐字相同（`case_not_found_message`），audit `case.access_denied` 記真正原因（denied／not_found）；M01 的 13 處單筆讀寫改走它們；守門 `test_case404.py`。

## 0. 結論

- **必修 1、建議 1、待驗 1**。

## 1. 主持重點

| # | D 的驗證 | 結果 |
|---|---|---|
| 403→404 的替換有沒有誤換到模組權限的 403 | 列出產品碼被替換掉的每一行：全是 `row_access.require("case", …)`（13 處）、`HTTPException(403, CASE_ACCESS.deny_message)`，以及案件層的「無權限存取這筆資料」；`require_any_module`／`user_has_module` 一處都沒動。題目 `test_module_permission_403_is_untouched`（沒有出納模組打出納端點仍是 403）也在 | 成立 |
| 行為 | 突變 CZ1「被拒回 403」、CZ2「被拒訊息不同」、CZ3「audit 不記真正原因」⇒ 3/3 紅 | 成立 |
| 403 守門的反向控制 | `test_rc_the_scanner_catches_each_form` 涵蓋 3 種寫法：`row_access.require("case")`、`HTTPException(403, deny_message)`、`if not case_access_allowed(...)`→403。D 另測其他寫法，見 CR-S1 | 部分 |
| AT6-O1 界線：守門不是靠排除清單變綠 | 掃描器唯一的例外是定義處 `helpers/case_access.py` 本身，**沒有任何排除清單**；傳票路徑本來就沒有案件層的 403 | 成立 |
| 附件 -6「整案看不到⇒404」合回後的一致性 | 依主持指示記為**待驗**：兩條路的訊息都是「報價單 X 不存在」（附件 -6 用自己的 `CASE_NOT_FOUND`，本包用 `case_not_found_message`），合回後應改成共用同一支 | 待驗 |

## 2. 發現

**CR-M1（必修）　C 的「47 檔改前後同一組」選題之外，還有 3 處 403 斷言沒有改（主持已知 1 處，另外 2 處）**
- D 把 repo 裡**所有含 403 斷言**的測試檔都跑一遍（125 檔非 e2e＋1 個 e2e 檔，f743662b）：1487 過、**3 紅**。這 3 題在 cefc5ecd（本包之前）都過：
  - `tests/platform/test_approval_providers.py::test_detail_keeps_m01_access_and_money_rules_for_provider_types`（主持說的那 1 處，C 會以 fast-forward 修）
  - `tests/test_approval_queue_detail_authz_2026_09_14.py::test_outsider_cannot_open_queue_detail`（`assert 404 == 403`，訊息「外人看得到送審內容」）
  - `tests/test_case_approver_single_rule_2026_09_25.py::test_extra_expense_approver_opens_queue_detail_and_sees_money`
- 產品行為是對的（簽核佇列詳情的逐案拒絕改成 404），是題目的期望沒有跟著改。
- 列車現在只跑選題，這 2 題不在選題裡就會一路帶到全量才紅。請一併改成 404，並把選題的依據從「改前後同一組」改成「全 repo 含 403 斷言的檔」。

**CR-S1（建議）　掃描器只認得三種寫法**
- D 用 `per_case_403` 直接測沙盒：
  - `if not row_access.visible('case', …): raise HTTPException(403)` ⇒ **漏**
  - `if not case_page_readable(...)`（或 case_owner_readable、case_documents_readable）`: raise HTTPException(403)` ⇒ **漏**
  - 狀態碼用常數 `FORBID = 403` ⇒ **漏**
  - `row_access.require(K, …)`（K 是變數）⇒ **漏**
  - alias 的 `ra.require("case", …)` 抓得到。
- 真實程式目前 **0 處**有這些寫法，所以列建議。但「用 L1 的判定函式判斷，然後回 403」是之後最自然會出現的寫法，建議至少把 L1 的四個判定函式加進掃描。

- 觀察：`test_denied_and_missing_look_the_same` 只參數化 2 個端點；13 處轉換的一致性主要靠靜態掃描與 `deny_case` 集中保證。
