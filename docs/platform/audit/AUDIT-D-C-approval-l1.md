# 稽核：C 的待簽彙整搬進 L1（wip/c-approval-l1 3897f15b；疊在 c-m01-5 a1e0a45b 上）（D，2026-09-27 12:26）

> 完整稽核（權限類；使用者裁示：待簽彙整搬進 L1）。稽核者 D 沒有寫過任何受稽核的程式碼。
> 內容：`/api/approval-queue` 四支（佇列、角標、詳情、轉簽）從 M01 搬到 L1 `routers/approval_queue.py`，路徑不變；M01 改為 `approval.queue_items`（五種）與 `approval.detail`（四種）的提供者；頁面、選單、前綴歸 L1；`case.summary` 加 `deal_tag`。

## 0. 結論

- **必修 1、建議 1、觀察 4、待驗 1**（真刪 M06，第十二班後由 C 補）。
- 複核 -2（81972141）：**AL-M1、AL-S1、AL-O1、AL-O4 關閉；新必修 AL2-M1、AL2-M2**（§3）；§1 的「④ 角標」一列有更正（§3-4）。

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


## 3. 複核（wip/c-approval-l1-2 81972141，取代 3897f15b）（D，2026-09-27 13:53）

> 主持指定：AL-M1、AL-S1、佇列⇔詳情一致、④ 壞 JSON 題、M05 兩紅處置；並確認「壞 JSON 列出、當成沒有簽核層」是否等於任一 superadmin 可簽。

### 3-1 結論

- **AL-M1、AL-S1、AL-O1、AL-O4 關閉；新必修 2（AL2-M1、AL2-M2）**。

### 3-2 實測

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 相關題（名稱或內容含 approval-queue 的 30 檔） | 389 過 | 成立 |
| AL-M1 | B1「不比對本人」（上一輪存活的 AQ3）⇒ **紅**（`test_case_change_detail_outsider_gets_the_not_found_404`）；B2「selfViewBy 不生效」（AQ4）⇒ **紅**（`…_requester_without_case_access_sees_it`） | **關閉** |
| AL-S1 | B3「守門的 404 照舊帶案件單號」⇒ 紅；B4「提供者自己的 404 訊息不統一」⇒ 紅；B7「audit 原因記錯」⇒ 紅 | **關閉** |
| AL-O3（佇列⇔詳情，主持裁示） | B5「M01 不在也不過濾」⇒ 紅；B6「M01 在也過濾」⇒ 紅。**但 D 探針找到縫** ⇒ AL2-M1 | 部分 |
| AL-O4 | B8「壞 JSON 讓 M01 整類炸掉」⇒ 紅（`test_quotation_with_malformed_approval_json_does_not_break_the_queue`）。D 探針：佇列與角標 200，壞 JSON 的單列出並計入；**詳情 500** ⇒ AL2-M2 | 部分 |
| AL-O1（M05 兩紅） | 真刪 M05（tests/platform＋approval 相關 116 檔）：非 e2e 2192 過、**只剩允許的 5 紅**；e2e 93 過、0 紅 | **關閉** |
| 真刪 M01（同範圍） | 非 e2e 1497 過、648 略過、**只剩允許的 5 紅**；e2e 36 過、0 紅 | 成立 |
| 主持的前提：壞 JSON「列出、當成沒有簽核層」＝任一 superadmin 可簽？ | D 探針（M01 在）：壞 JSON 的報價單在佇列列成 `tiers=[]`、`requestedBy=""`，角標算給每一個 superadmin；**但 superadmin 打 `POST /api/quotations/{no}/approve` ⇒ `JSONDecodeError`（500），狀態仍是待審核**。另外四個核准端點（請款單、開票申請、承攬商匯款、出貨單）同樣是 `json.loads(data_json)` 直接解析 ⇒ 一樣會失敗 | **不成立**：壞 JSON 不會被簽掉（fail-closed，只是 500 很難看）。真正走「任一 superadmin 可簽」的是 **data_json 能解析、但 approval 沒有簽核層**——那是合法的「沒有設定流程」路徑 |

### 3-3 發現

**AL2-M1（必修）　M01 不在時，沒掛案件的單「列出⇔放行」不成立**
- `_openable` 只過濾有 `linkedQuoteNo` 的項目；詳情卻一律以提供者回的 `quoteNo` 做 `guard_case_access`，M01 不在時一律拒絕。
- D 探針（真刪 M01，81972141）：`quote_no=''` 的待簽請款單，superadmin 與 admin **在佇列看得到、點開詳情 404**。簽核人與送審人一致（200）。
- C 的 `test_listed_iff_detail_opens` 只用有掛案件的合成單，沒有涵蓋這種單。
- 修法二擇一（交 C／主持）：
  - ① 佇列在 M01 不在時，對**所有有詳情提供者的**項目都用 `_on_chain` 過濾（不只看 `linkedQuoteNo`）；
  - ② 詳情在 `quoteNo` 為空時不做案件守門、改走該單據自己的規則。
- 補題：逐格一致題加一張 `quote_no` 為空的單。
- 觀察：M01 在時也有同類情況——掛的案件已經不存在（孤兒單）時，admin 看得到、點開 404。舊版相同，非本包造成。

**AL2-M2（必修）　`case.summary` 加 `deal_tag` 帶進 `json_extract`，一張壞 JSON 的報價單就讓整個查詢丟例外**
- 3897f15b 把 `SQL_DEAL_TAG`（`COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')`）加進 `case_summary` 的 SELECT；改動前那支查詢不碰 `data_json`。
- `deal_tag` 欄為空、而 `data_json` 壞掉時，SQLite 丟 `malformed JSON`。
- D 探針：壞 JSON 報價單的**佇列詳情 500**（traceback：`_case_header` → `_case_names` → `case_summary`）。
- 波及範圍：
  - 詳情抬頭；
  - M10 綁定案件（`_CaseAccess.summary`）；
  - 佇列中沒自帶客戶名的項目（會讓整支佇列 500）；
  - a-m06-8 rebase 後的 voucher_link（`quote_nos=None` 一次撈全部），**一張壞單就讓所有人的傳票案件清單 500**。
- 修法：`deal_tag` 只讀欄位，或逐筆在 Python 解析（與 AL-O4 的 `_approval_json_of` 同一個做法）。
- 補題：`case_summary` 在含壞 JSON 列時仍回其他列。
- 這一項讀碼就看得出來：§G5 第 2 列本來就是這一條，D 上一輪沒有對 deal_tag 那一行套用。

### 3-4 更正上一輪的紀錄（保留原句）

- §1 表格「④ 角標」一列原寫：~~「新版列出並對 superadmin 計 1，與佇列一致」~~〔更正：D 上一輪的探針只證明了舊版會 500，新版的輸出沒有實際看，那句是照 C 的申報寫的。C 在 -2 指出 3897f15b 其實是 json_extract 讓 M01 整類消失——C 的指正成立。〈主持人的記憶是負債〉：附和看起來跟查證一樣〕。

### 3-5 給 c-queue-json 的前提（主持要求確認）

- 「跳過＋ERROR」只能套在**解析不了**的單據上。
- **合法的無簽核層單據**（data_json 正常、approval 沒有 tiers）要照舊列給 superadmin：核准端點的 no-tier 分支就是給它們走的，跳過會讓真正要簽的單從佇列消失。
- D 審 c-queue-json 時會驗這一條（兩種單各一張，逐格看佇列、角標、核准）。

### 3-6 D 自己的過程問題

- D 同時跑兩個 `mutate.py`（approval-l1-2 與 O13），兩者共用同一個 basetemp ⇒ B3 那一輪被清掉目錄，出現 191 個 errors。已在 approval 那組跑完後單獨重跑 B3 ⇒ 乾淨的紅。之後同一時間只跑一個 `mutate.py`。
