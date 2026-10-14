# BP-5 流程狀態機建構器：設計筆記（第 1 版，僅文件）

> 日期：2026-10-14　作者：hichan-3e（受 hichan-b4 指派）　基底 `origin/train/t60-int` 1fd62b612　**未實作、未執行任何程式。**
> 前置：`BP5-FLOW-INVENTORY-T62.md`（寫死程式盤點，行號出處）；上位文件 `FRAMEWORK-10DAY-ROADMAP-T56.md` §0B.3、`PLATFORM-BUILDER-ARCHITECTURE-T57.md` §2.4／§4。
> 旗標：`builder_workflow.enabled`，預設 0；關閉時所有端點回應與頁面 DOM 與今天逐位元相同（含不得多一次請求）。

## 1. 目標與不做的事

**做**：管理者在系統內、帶即時預覽地調整「非金額單據」的流程：狀態名稱／顏色、誰可簽（沿用既有層）、要不要簽核、退回草稿要不要留紀錄、核准後的回呼（從已註冊動作挑）、各狀態哪些欄位可改。
**不做（寫死，與架構筆記 §4 一致）**：
- 金額守門：`alt_lock`、`alt_sign`（P8→P7→P6→P2 鏈、P4、P3）、`profit_guard`、報價單編輯鎖、重開守門鏈中的金額項。
- 會計入帳類型（傳票）與法定連號；期間關帳。
- 金額單據的「核准後編輯鎖」只能**加嚴**；金額單據不得關閉 H2 紀錄。
- 任意程式碼／運算式。規則只能「作為條件」被引用，不能驅動狀態（沿用 BP-2 規則引擎 `mode: mark` 的結論）。

## 2. 單據風險類（新登錄，前置工作）

盤點 §4-5：目前沒有單據類型的風險類。新增程式內登錄 `doc_class`（**不是使用者可編輯**）：

| class | 單據 | 建構器權限 |
|---|---|---|
| `plain` | 完工單、出貨單*、材料核准／變更、派發、案件支出（無付款部分）、自訂模組 | 完整（狀態、轉換、豁免、回呼、編輯鎖） |
| `money` | 報價單、請款單、開票申請、承攬商匯款申請、薪資單、獎金、獎金更正、案件額外支出（含付款） | 只能加嚴；不可豁免簽核（豁免僅可由政策 P8 走放寬流程，且 H2 不可關） |
| `ledger` | 傳票、關帳、帳務請求 | 不在範圍，建構器看不到 |

\* 出貨單扣庫存＝回呼是寫入類動作，仍列 `plain`，但回呼受 §5 的動作目錄約束。
分類由程式登錄且有守門測試（新增單據類型而未分類 ⇒ 測試紅）；`register_doc_type()` 增加必填 `doc_class`（舊呼叫預設 `money`，即最嚴）。

## 3. 定義格式（kind `workflow`，每單據一份，走既有定義文件庫）

```
{
  "docType": "completion",
  "states": [ {"id":"draft","label":"草稿","tone":"gray","semantic":"draft"},
              {"id":"pending","label":"待審核","semantic":"pending"},
              {"id":"in_approval","label":"簽核中","semantic":"pending"},
              {"id":"approved","label":"已核准","semantic":"approved"} ],
  "transitions": [
    {"id":"submit","from":["draft"],"to":"pending","who":"owner_or_admin","reason":"none","guards":["has_tiers_or_exempt"]},
    {"id":"approve","from":["pending","in_approval"],"to":"approved","who":"tier","reason":"optional","callbacks":["notify_requester","gen_pdf"]},
    {"id":"reject","from":["pending","in_approval"],"to":"draft","who":"tier","reason":"required","log":"full"},
    {"id":"revoke","from":["approved"],"to":"draft","who":"admin","reason":"required","guards":["not_customer_signed"],"log":"full"}
  ],
  "approval": {"required": true, "exemption": null},
  "editLock": {"editableIn":["draft"]},
  "returnLog": "full"
}
```
- **語意標籤**（`draft|pending|approved|closed|void`）是下游守門與佇列認的東西；狀態 id／顯示名稱可改，語意標籤不可刪、`approved` 只能經簽核路徑或記錄在案的豁免進入。`helpers/approval_queue.py:26 ACTIVE_STATUSES` 與 `tools/check_approval_queue_coverage.py` 改為從語意標籤推導（`pending`＝待簽組），否則改名會讓待簽佇列看不到。
- `who`：`owner_or_admin`、`tier`（沿用 `tiered_approval` 的層，**層本身仍在簽核設定頁／既有設定管**，建構器只引用）、`admin`、`superadmin`。不新增角色語法。
- `guards`：從**守門目錄**挑（`not_customer_signed`、`not_exported`、`serials_in_stock`、`has_tiers_or_exempt`…），每個守門是一個已存在的程式函式；建構器只能開關／加嚴，不能新增。目錄項目是盤點 §2.1 各行「擋」的條件逐一抽出。
- `callbacks`：從**動作目錄**挑（§5）。
- `log`／`returnLog`：`none|basic|full`（誰／何時／從→到／原因 / 加上欄位差異）；`money` 類固定 `full` 且不可選。

## 4. 預設定義＝現況（登記順序：完工單 → 出貨單）

- 每個既有單據的現行流程以**內建 v1 唯讀基準**登記（`origin: "builtin"`），沒有公司版本 ⇒ 完全走今天的程式路徑（旗標關或沒有公司版時，端點**不呼叫**流程引擎）。
- **採用 shim 而非重寫**：端點原樣保留，在狀態寫入與守門處改為 `workflow.resolve(doc_type)`；`resolve` 在旗標關／無公司版時回傳內建 v1，且內建 v1 的每一欄與今天的字面值相同（黃金測試保證）。這樣遷移是機械的、可逐單據推進，不會一次改五個端點的交易順序。
- 完工單與出貨單先行的原因：兩者都是「標準五件套」且不屬金額守門；出貨單另帶庫存扣減回呼，是動作目錄的第一個寫入類壓力測試。請款／開票／匯款（金額類）在第一期只登記為**唯讀基準**（可看流程圖與影響，不可改）。

### 黃金重放（先於任何改動）
對每個預設定義，把盤點 §2 每一條「寫入／擋下」行號轉成測試案例（含被擋情況與**訊息字串**），新舊路徑結果逐位元相同。突變正對照：改一個守門的條件，重放必須紅。這些案例**先寫、先在現行程式上綠**，再接 shim。

## 5. 動作目錄（回呼）

回呼只能引用已註冊動作；每個動作有：權限、影響類（`notify|render|push|write`）、是否在交易內、是否冪等。
| 動作 | 現況來源 | 類 | 位置 |
|---|---|---|---|
| `notify_requester`／`notify_next_tier` | 各 approve 的 `_notify`、`notify_*` | notify | after_commit |
| `gen_pdf` | `spawn_bg_thread(_generate_*_pdf…)` | render | after_commit |
| `calendar_push` | `push_event_for_*` | push | after_commit |
| `stock_deduct` | `shipping_notes.py` approve 內 `stock_items` UPDATE | **write** | **交易內**（失敗＝核准失敗） |
| `fire_expense_notify` | `_expense_notify.fire_completion_approved` | notify | after_commit |
**規則**：`write` 類動作不可被移除或延後（移除＝庫存不扣，視為資料完整性破壞），只能由程式定義預設；建構器對 `write` 動作只能「保留」。這點直接由 §8 的靜態分析強制。
「簽核後要不要回傳（回簽）」＝是否啟用 `signed-toggle` 這條轉換（`plain` 類可關；`money` 類不可關）。

## 6. 發布前靜態分析（發布管線的 comparator 與驗證器）

驗證器（錯誤＝不能發布）：
1. 結構：狀態 id 唯一；每個轉換的 from／to 存在；每個語意標籤至少一個狀態；初始狀態唯一。
2. 可達性：所有狀態自初始狀態可達；`approved` 可達；無「只進不出」的非終態（卡死）；無不經 `draft`/`pending` 就能到 `approved` 的路徑，除非有記錄在案的豁免。
3. 簽核要求：`approval.required=true` 時，每條通往 `approved` 的路徑必經 `who:tier` 轉換；`required=false` 時必須有豁免紀錄（帶政策編號）。
4. 分類：`money` 類的任何欄位相對內建 v1 只能更嚴（比較器見 §7）；`ledger` 類不接受。
5. `write` 回呼存在且在交易內；`log` 不低於類別下限。
6. 簽核層可解析：`who:tier` 需要至少一個在職簽核人；找不到時發布失敗並指出轉換（H6）。
7. 環：允許（退回重送是正常環），但「自動轉換」不得成環（本期不提供自動轉換，驗證器先擋）。

**比較器**（`def_pipeline.COMPARATORS['workflow']`，沿用 BP-1 的放寬／收緊分類）：收緊＝加守門、加簽核層、提高 log 等級、縮小 `editableIn`、縮小 `who`；放寬＝其反向、關簽核（豁免）、移除守門、放寬 `who`。**無法比較一律放寬**。放寬 ⇒ 待第二位最高管理者核准＋確認期間；`money` 類的放寬一律拒絕（不是 pending，是直接驗證錯誤）。比較器與 BP-2 同樣附**突變正對照**（方向互換則結果翻面）。

## 7. 進行中的單據（H6）

- 單據在送審時凍結 `def_version`（沿用自訂模組做法；既有單據 `approval_json` 內補寫 `workflowVersion`，**唯讀欄位新增、舊單據視為內建 v1**，不需要回補資料）。進行中的單據**不被追溯改變**：用凍結版本完成它的流程。
- 影響預覽（發布前，沿用 T62 預覽雜湊）顯示：
  - 「若套用到進行中單據，哪些會改變狀態語意」＝被移除／改名的狀態各有幾張（依 `status` 欄位計）；
  - 「誰會被要求簽」＝在途單據（`待審核／簽核中`）依新舊定義的當前層差異，列出將新增／移除的簽核人與張數；
  - 「哪些轉換權限變寬」；
  - 「下游依賴」：被改名的語意標籤被哪些守門引用（`has_tiers_or_exempt`、佇列、PDF 橫幅）。
- 預覽只讀，樣本 200 筆顯示／1000 筆掃描（同 BP-2），**不含金額欄位值**；權限同 BP-2：僅最高管理者。
- 要把進行中單據遷到新版：獨立批次動作（高影響、需核准、逐張寫 H2 紀錄），**本期不做**，只提供「全部沿用舊版直到結案」。缺漏映射 ⇒ 不能發布「改版並遷移」，但可發布「僅新單據生效」。

## 8. H2／H3 配套

- **H2 轉換紀錄**：新表 `workflow_transitions`（僅附加；誰／何時／doc_type／doc_no／從→到／定義版本／原因／結果＝成功|被拒|豁免通過），**BEFORE UPDATE／DELETE 觸發器**。屬 DDL，需 b4 另行決定；本設計不依賴它即可交付第一期（第一期沿用各端點現有 `signed_log`／`_audit`，`log` 等級先只做 `basic|full` 兩檔映射到既有紀錄）。盤點 §4-1、4-2 要先查清。
- **H3 簽核綁內容**：報價單實質已成立（寫死）；其他單據只在盤點確認後才列入，不在第一期。

## 9. 管理者介面（含即時預覽）

沿用 BP-2 的入口手法：**不新增 L1 頁、不改關閉時的選單與 DOM**。在簽核設定頁（`approval-settings.html`）旗標開啟時多一個「流程」分頁；或各單據頁的浮動按鈕（僅最高管理者）。頁面讀旗標沿用 `MotrixPublicFlags`（3c 的公開旗標機制，群組 `builder_workflow` 追加於現有逗號清單末端，需與 3c 協調字串）。
- 左：狀態圖（狀態節點＋轉換箭頭，點選編輯；下拉為主，不給自由文字運算式）。
- 右：**即時預覽**——「這個改動會讓 N 張進行中單據的狀態語意改變、M 張的當前簽核人改變、K 條轉換權限變寬」，附樣本表（單號、現狀態、新狀態、將被要求簽核的人），以及放寬／收緊分類與紅色橫幅（放寬）。
- 沙盒走一次：用「假單據」逐步點擊轉換，顯示每一步誰可、被哪個守門擋（不寫真實單據）。
- 發布走既有治理：預覽雜湊強制（T62）、版本帳本、還原（還原到較寬鬆版本＝放寬）、`enforce_workflow` 與 `_OPT_IN_PREVIEW_KINDS`。
- 不用原生 `confirm()`／`alert()`。

## 10. 治理層重用對照

| 需要 | 重用 | 新增 |
|---|---|---|
| 版本／草稿／diff／還原 | `core/definitions.py`（kind `workflow` 惰性登記，同 `rule_set`） | — |
| 放寬／收緊、待核准、確認期間 | `routers/def_pipeline.py` COMPARATORS／ACTIVE_KINDS | `_cmp_workflow` |
| 預覽雜湊、強制預覽 | `routers/def_governance.py` impact／`_gate`、`_OPT_IN_PREVIEW_KINDS` | `impact_of_workflow`（§7） |
| 旗標 | `settings_registry`（`builder_workflow.enabled`，`risk` 與 `impact_scope`；另 `builder_governance.enforce_workflow`） | 兩個設定 |
| 簽核層 | `helpers/tiered_approval.py` | 不新增層語法 |
| 嚴格設定讀取 | `helpers/settings_strict.strict_value` | — |

## 11. 分期（估；不是承諾）

| 期 | 內容 | 風險 |
|---|---|---|
| P0 | `doc_class` 登錄＋守門測試；盤點 UNKNOWN 補查（觸發器、各端點退回紀錄、回呼交易位置） | 低 |
| P1 | 完工單、出貨單的內建 v1 定義＋**黃金重放先綠**；唯讀流程圖與影響預覽（旗標開才有；無任何寫入） | 低 |
| P2 | 公司版本可發布（plain 類）：狀態改名／顏色、誰可簽、退回 log 等級、編輯鎖；shim 接上完工單 | 中 |
| P3 | 簽核豁免（P8）與回簽開關、動作目錄的回呼編輯；出貨單 | 中高 |
| P4 | 其餘 plain 類；money 類只讀基準 | 中 |

## 12. 需要使用者決定（只列不可逆／影響範圍者）

1. **D-W1**：`money` 類在第一期是否完全唯讀（建議：是）。
2. **D-W2**：「關閉簽核」對 `plain` 類是否允許（P8 已有暫定同意，需使用者確認；與 D-K1 同類：放寬要第二位核准）。
3. **D-W3**：是否授權新表 `workflow_transitions`（DDL＋觸發器）；不授權則 `log` 只能映射既有紀錄，等級受限。
4. **D-W4**：「無簽核層」今天三種不一致行為（僅超管／自動核准／孤兒單）是否在預設定義中保留各自行為（建議：保留，黃金重放以現況為準）。
5. 三項盤點 UNKNOWN 未補完前，不開 P2。

## 13. 靜態檢查清單（實作前）

- 守門：`doc_class` 未分類測試；`ACTIVE_STATUSES` 與待簽佇列覆蓋守門改讀語意標籤後仍綠。
- OFF 狀態：端點不呼叫引擎、頁面不多請求、`route_inventory`／`response_keys` 不變（由 46 重建的基準以旗標關為準）。
- 不改 `layout-editor.js`；不碰 `modules/case` 的金額守門檔（`alt_lock`／`alt_sign`／`profit_guard`）。
