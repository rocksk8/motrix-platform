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
| `plain` | 完工單、材料核准／變更、派發、案件支出（無付款部分）、自訂模組 | 完整（狀態、轉換、豁免、回呼、編輯鎖），但受 §14.5 的相依警示約束 |
| `stock` | **出貨單**（核准會在同一交易內把庫存序號改為已出貨；04 審查 10-14，PM 暫定） | 可調狀態名稱／顏色／誰可簽／編輯鎖；**不可關閉簽核**；**所有回呼只能保留**（可加、不可拿掉） |
| `money` | 報價單、請款單、開票申請、承攬商匯款申請、薪資單、獎金、獎金更正、案件額外支出（含付款） | 只能加嚴；不可豁免簽核（豁免僅可由政策 P8 走放寬流程，且 H2 不可關） |
| `ledger` | 傳票、關帳、帳務請求 | 不在範圍，建構器看不到 |

（出貨單原先列 plain，04 審查指出核准動庫存，改列 `stock`。）
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

## 12. 需要使用者決定（只列不可逆／影響範圍者；**PM 暫定答覆 10-14，使用者尚未確認：不得在正式機開啟 builder_workflow**）

1. **D-W1**：`money` 類在第一期是否完全唯讀（建議：是）。**暫定：是。**
2. **D-W2**：「關閉簽核」對 `plain` 類是否允許（與 D-K1 同類：放寬要第二位核准＋確認期間）。**暫定：允許，但屬放寬；預設定義不變。** 細化（04 審查）：`stock`（出貨單）不可關；完工單關簽核要在比較器的理由與介面帶出相依警示（§14.5）。
3. **D-W3**：新表 `workflow_transitions`（DDL＋觸發器）。**暫定：不授權；`log` 等級映射到既有 `audit_log`（見 §14 的限制）。**
4. **D-W4**：「無簽核層」今天三種不一致行為是否在預設定義中保留各自行為。**暫定：保留，黃金重放以現況為準。** 延伸（04 審查）：`revoke-approval` 今天只要 `_require_admin`＋狀態已核准＋未回簽＋有原因——**任何 admin 都能撤銷別人的核准**（不限當層簽核人）。**暫定：原樣釘住**（預設定義 `revoke.who = admin`，黃金重放有一題 `test_known_gap_any_admin_can_revoke_an_approval`），**列為已知缺口，不在 BP-5 修**；收緊需另案並讓使用者知情。
5. 三項盤點 UNKNOWN 已於 P0 查完（§14）；其結論改變了 §8 的 H2 做法。

## 13. 靜態檢查清單（實作前）

- 守門：`doc_class` 未分類測試；`ACTIVE_STATUSES` 與待簽佇列覆蓋守門改讀語意標籤後仍綠。
- OFF 狀態：端點不呼叫引擎、頁面不多請求、`route_inventory`／`response_keys` 不變（由 46 重建的基準以旗標關為準）。
- 不改 `layout-editor.js`；不碰 `modules/case` 的金額守門檔（`alt_lock`／`alt_sign`／`profit_guard`）。

## 14. P0 查證結果（三項 UNKNOWN；讀程式得出，未執行）

### 14.1 資料庫觸發器
- **有** BEFORE UPDATE／DELETE 保護的：`config_changes`、`config_change_events`、`permission_changes`（`core/migrations.py:482-558`）、獎金編修紀錄與傳票編修紀錄（`db.py:4634-4661`）、法定科目（`db.py:4362-4371`）。
- **沒有**：`audit_log`（`db.py:589`）。而且它**會被改、會被刪**：保留期清理 `archive.py:1670 DELETE FROM audit_log WHERE at < ?`；失敗嘗試的累加計數 `helpers/audit.py:375,414 UPDATE audit_log SET detail`；遷移 `core/migrations.py:406`。
- **簽核軌跡不在 `audit_log`**：每張單據的簽核資料（各層誰簽、何時）存在該單據 `data_json["approval"]`（獎金類另有 `approval_json` 欄）；`signed_log` 欄是『客戶回簽』紀錄，不是簽核歷史（更正盤點的措辭）。單據列本身沒有觸發器。

### 14.2 退回草稿時各端點留了什麼
- 完工單、出貨單、請款單、開票申請、承攬商匯款申請、報價單退回：**`d.pop("approval")` 把整份簽核軌跡從單據刪掉**（`completion_notes.py:739,782`；`shipping_notes.py:657,714`；`payment_requests.py:783,829`；`invoice_vouchers.py:691,737`；`contractor_vouchers.py:833,881`；`quotations.py:5182`），獎金與獎金更正清成 `approval_json='{}'`（`bonus.py:1961`、`bonus_correction.py:358`）。**之後唯一的證據是 `_audit` 寫的那一筆**（動作、人、單號、原因 `{"note":…}`；出貨單撤銷另帶 `stockReturned`）。
- `_audit` 的特性：在 `conn.commit()`／`conn.close()` **之後**才呼叫、用另一條連線、內部包 try/except（`helpers/audit.py:285-`）。⇒ **不與狀態變更同交易**：提交後、稽核前當機＝狀態已改而無紀錄；稽核失敗也不會讓退回失敗。
- 被擋的嘗試：另有 `_audit_failure`（`helpers/audit.py:333`，只記方法／路由／單號／狀態碼／原因碼，同人同路由 60 秒限流）— 這是 H2『被拒嘗試』的現成一半，但沒有『從→到』欄位。
- 結論：今天**所有類型**退回草稿都是『清掉軌跡＋一筆盡力而為的稽核』。`returnLog` 的 `basic|full` 兩檔在不新增資料表的前提下只能這樣映射：`basic`＝維持現狀（一筆 `<doc>.reject`／`.revoke_approval`，帶原因）；`full`＝同一筆稽核的 `detail` 另帶**被清掉的簽核軌跡快照**（各層簽核人與時間）。**限制要告知使用者**：`audit_log` 可被保留期清理刪除、不是不可改；因此本期的 `log` 等級不構成 H2 的『不可改』保證——金額類的不可改保證仍需 D-W3（現在不授權）。
- 對 §8 的修正：『第一期沿用各端點現有紀錄』成立；但**進入 `workflow` 引擎後仍不得關閉這一筆稽核**（最低等級＝今天的行為；`none` 選項只有 plain 類才給，且屬放寬）。

### 14.3 核准後回呼在交易內或交易後
以出貨單 `shipping_notes.py:469-624` 為準，其餘四類形式相同：
- **交易內**（同一個 `commit` 之前）：狀態寫入、簽核資料寫入、**庫存扣減**（`stock_items` UPDATE，`:590-596`）。序號不在庫在寫入之前檢查，失敗＝409，不改任何東西。
- **commit 之後**：背景 PDF（`spawn_bg_thread(_generate_*_pdf)`）、行事曆推送、通知、`notify_*`、`_audit`。這些各自失敗不影響核准結果。
- 報價單已用 `after_commit` 清單明文化（`quotations.py:5030-5119`）；其餘四類是直接內嵌呼叫，順序相同。
- 設計含意：動作目錄的 `write` 類＝交易內、失敗關閉；`notify|render|push`＝commit 之後、失敗不回滾——與 §5 一致，**不需要改引擎設計**。要注意：『commit 後才 `_audit`』使 `_audit` 也屬 commit 之後的一員，不能被當成交易內的證據。

### 14.4 P0 交付物（本分支）
| 項目 | 位置 |
|---|---|
| 單據風險類登錄 `DOC_CLASS`／`doc_class()`／`register_doc_type(…, doc_class="money")`（目前沒有任何執行期讀取者） | `backend/helpers/tiered_approval.py` |
| 守門測試（14 類全數分類；plain 只有完工單與出貨單；漏分類會紅；登記失敗不留半登記；突變正對照）— **已實際執行、5 題全綠** | `backend/tests/test_workflow_doc_class_2026_10_14.py` |
| 完工單／出貨單黃金重放（編輯鎖、被擋的轉換與訊息、退回需原因且清簽核資料、核准／撤銷來回、無簽核層行為釘住、突變正對照）— **寫好未跑**（需資料庫與機器空閒） | `backend/tests/test_workflow_golden_replay_2026_10_14.py` |

### 14.5 相依關係（`workflow_grammar.DEPENDENCIES`；04 審查更正：案件結案閘門**確實**讀完工單與出貨單）
| 單據 | 相依 | 位置 | 意義 |
|---|---|---|---|
| 完工單 | `completion_counted_statuses` | `modules/case/completion_sync.py:23` | 已完工數統計依**資料庫狀態值**『待審核／簽核中／已核准』 |
| 完工單、出貨單 | `case_close_gate` | `modules/case/api/quotations.py:2230-2283`（`_CLOSE_DOC_TABLES` 含完工單與出貨單；`_close_gate_facts` 以 `status IN ('待審核','簽核中')` 加簽核 JSON 判定還有單據在簽） | 閘門讀的是**資料庫狀態值**，不是『核准』這個事實：待簽語意的狀態若換了資料庫值，就逃過閘門、案件可被結案。關閉簽核＝單據永遠不進入待簽，閘門也少一道人工確認（放寬，比較理由會帶出） |
| 完工單、出貨單 | `pending_queue` | `helpers/approval_queue.py:26 ACTIVE_STATUSES`；`quotations.py` 待簽佇列 SQL（約 :4850、:4886） | 待簽佇列同樣寫死『待審核／簽核中』 |
| 出貨單 | `stock_flip` | `shipping_notes.py` approve（同一交易 UPDATE `stock_items`） | 核准動庫存，撤銷歸還 |
**P2 的前置條件（先於任何公司版本生效）**：①狀態新增 `dbValue` 欄位，**待簽語意的狀態必須對應既有資料庫值**（『待審核』『簽核中』），改名只改顯示名稱；②結案閘門（`_close_gate_facts`）與待簽佇列（`approval_queue.ACTIVE_STATUSES` 與 `quotations.py` 的佇列 SQL）改成讀『語意』而不是寫死字串；③完成前，工作流程引擎不得接上端點。
比較器：關閉簽核（放寬）時，理由清單附上該單據的相依警示；預覽介面要把它們顯示在紅色橫幅裡。（本節前一版寫『t60 基底查不到』是我的錯，已更正。）

### 14.6 04 審查後新增的文法規則（P1 已實作並有測試）
- **簽核層明講角色** `tierRole`：`step`（中間層簽完，留在待簽）／`final`（最後一層簽完才進 approved）／`return`（簽核人退回，回草稿）。`who=tier` 必須宣告，其他轉換不可有；簽核層轉換的**所有**來源都必須是待簽語意；只有 `final` 可以進 approved（不可由第一層簽核就核准）。
- **未知欄位一律拒絕**（本體、狀態、轉換、approval、exemption、editLock 各層），比較器對未知欄位也視為放寬。
- **官方用語保護**：非 approved 語意的狀態名稱不可含『核准／批准／核可／已簽核／簽核完成／審核通過』；已核准語意的狀態改名＝放寬（受管），其他狀態改名維持中性。
- **編輯鎖只能是草稿語意的狀態**（簽核後改內容＝H3 破功）。
- **豁免編號必須在 P8 豁免登記表內**：登記表第一期不存在（`EXEMPTION_REGISTER` 空集合）⇒ **第一期任何公司版本都不能關閉簽核**；P2 以帳本登記取代。
- **stock 類**：進入 approved 的每條轉換（來源皆非 approved）必須帶 `stock_deduct` 與守門 `serials_in_stock`；離開 approved 的每條轉換必須帶 `stock_return`；來源不可混含 approved 與其他狀態；`stock_deduct` 的『只能進入』檢查加上『來源沒有 approved』。
- **`effective()` 與發布用同一個驗證器**（含不可拿掉的回呼與 stock 規則）；已發布的壞版本不會生效。注意：讀設定失敗時會連管理者已收緊的版本一起退回內建版——這是目前接受的取捨（內建版＝今天的行為，不會比今天更鬆）。
- **內建 v1 對齊端點**：submit 帶 `notify_first_tier`＋`notify_org_chain` 且 log=basic（端點寫 `<doc>.submit` 稽核）；signed_toggle 帶 `notify_module_activity` 且 log=basic（端點寫 `<doc>.sign/unsign` 稽核）；出貨單 approve 保留 `material_link_check`（核准時再檢查一次）。字面值對照端點原始碼的測試已擴充。

## 15. P1 交付（本分支；純函式測試已實際執行，需要資料庫的黃金重放仍未跑）
| 項目 | 位置 | 狀態 |
|---|---|---|
| 文法／驗證器／靜態分析／比較器／守門與動作目錄／相依宣告 | `backend/helpers/workflow_grammar.py` | 純函式，69 題（含風險類 5 題）已跑全綠（含突變正對照） |
| 內建 v1（完工單、出貨單） | `backend/helpers/workflow_defaults.py` | 通過同一份驗證器；字面值對照端點原始碼的題已跑 |
| 定義種類 `workflow` 的懶登記、旗標、`effective()` 影子 | `backend/helpers/workflow_defs.py` | **沒有任何端點或路由呼叫**；`ensure_registered()` 無呼叫端 ⇒ `/api/definition-kinds` 與今天相同 |
| `def_pipeline` 接線 | `ACTIVE_KINDS` 加 `workflow`、`COMPARATORS['workflow']` | 只多一項；kind 未登記前不會被走到 |
| 單據風險類 `stock` | `helpers/tiered_approval.py`（`DOC_CLASS`：出貨單→stock） | 守門測試 5 題已跑全綠 |
| 旗標 `builder_workflow.enabled` | **設定群組在第一期刻意不登記** | 避免設定中心出現一個『開了也沒作用』的開關、避免動設定基準檔與 API 回應；登記時機＝第一個會呼叫引擎的路由（P2）。`flag_on()` 對未登記群組回 False |
OFF 位元組相同：沒有新路由、沒有新設定群組、沒有端點改動；`def_pipeline` 只多兩個字典項；`tiered_approval` 只多一張登錄表與一個函式。
**沒做、留給 P2**：影響預覽（`impact_of_workflow`）與預覽雜湊、`enforce_workflow`、路由與前端、端點接 shim、狀態 `dbValue` 欄位、進行中單據的映射。
