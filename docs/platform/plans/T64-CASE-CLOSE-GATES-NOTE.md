# T64 切片 4：案件結案閘門組（case close-out gate set）設計筆記

狀態：設計筆記（docs only），基準 `origin/wip/t62-int-c1`（7ae47bbfd）。對應耦合表切片 4、hichan-6c 對帳 #4。
來源（我讀過的程式，行號為該基準）：`modules/case/api/quotations.py` `_CLOSE_DOC_TABLES`、`_close_gate_facts`（:2358）、`_close_gate_opts`（:2420）、`_case_close_gates`（:2427）、`_gates_from_facts`（:2434，**唯一判定**）、`case_close_gates` GET（:2661）、`update_deal_tag`（:2701）、`gate_matrix`（:1236-1288）；`helpers/finance_params.py` `close_gate_options`（:137 起）；`helpers/settings_groups.py` `case_close_gates`（:506 起）；`helpers/email_notify.py` `notify_case_close_blocked`（:1650）；`frontend/js/case-management-close.js`、`case-management-list.js`（:27-31 欄位常數）；`modules/case/api/settlement_api.py`；`FINANCE-FRAMEWORK-INVENTORY-T62.md` §5、§5.1。

## 0. 結論

1. 結案閘門分兩類：**法定鎖死**（收款、單據簽核、精算完結、額外支出待審核：永不可關）與**定義驅動**（進度是否必要、加嚴選項、關卡標籤文字、財務側警示）。
2. 新增的只有三樣，全部預設＝今天的行為：①進度關可設為「選配」（唯一的放寬）；②財務側警示關（新狀態 `warn`，不擋結案）；③關卡標籤／提示文字可自訂（只改顯示，不改判定與擋下理由原句）。
3. 「簽核中的額外支出是否擋結案」建議直接補進基礎行為（收緊、現況與關卡文字「不可停在送審中」不一致），草稿維持選項。
4. 判定仍只在 `_gates_from_facts` 一處；設定在進入前一次讀取（沿用 `_close_gate_opts`）。**不新增第二份判定**。

## 1. 定義驅動 vs 法定鎖死

| 關卡 | key | 類別 | 可調內容 | 不可調 |
|---|---|---|---|---|
| ② 收款 | payment | **LAW-locked** | 只能收緊：無款項期別也算未達成（`require_payment_items`，已有）；標籤文字 | 不可關、不可降級成警示（現金基礎認列與獎金依據；收入認列只認已成案／已結案） |
| ③ 單據 | documents | **LAW-locked** | 只能追加表（只增不減）、標籤文字 | 六張表的 `待審核`／`簽核中` 判定；待簽語意值（BP-5 P2 前不改資料庫值） |
| ④ 精算 | settlement | **LAW-locked（finalized）** | 只能收緊：無精算資料也算未達成（`require_settlement`，已有）；標籤文字 | `settlement.status == 'finalized'` 才算過；結案後案件鎖定，精算停在草稿＝永遠算不完的帳（使用者 2026-09-13 裁示） |
| ⑤ 額外支出 | extraExpense | **LAW-locked（待審核）＋可收緊** | 草稿、簽核中是否也擋（見 §4 Q1）；標籤文字 | 待審核一定擋 |
| ① 進度 | progress | **定義驅動（唯一可放寬）** | `progress_required`（預設 1）：改 0 ＝ 進度關降為 `na`（仍顯示 N/M，不擋）；`require_stages`（已有，收緊） | 改 0 屬放寬 |
| 新 ⑥ 財務側 | ledger | **定義驅動，警示不擋** | `ledger_warn`（預設 0）；標籤文字 | 不提供「擋結案」版本（見 §4 Q3） |

**LAW-locked 的實作方式**：不放進設定表。`_gates_from_facts` 對這四關寫死「blocked 必擋」，設定只能經由 `opts` 的收緊旗標改變 `na→blocked`，沒有任何路徑把 `blocked→ok/na`。測試（§6）斷言這一點。

## 2. 新增設定（群組 `case_close_gates`，主開關 `enabled` 不變）

| 設定 | 型別／預設 | 方向 | 治理分類 | 說明 |
|---|---|---|---|---|
| `progress_required` | int 0/1，預設 1 | 0 ＝ **放寬**（`loosen="down"`） | `risk=ops`；放寬走既有「待生效→第二位最高管理者核准→確認期間」（D-K1） | `enabled != 1` 時視為 1（今天的行為）。讀不到／格式不對 ⇒ 1（最嚴）。與 `require_stages` 互斥：`progress_required=0` 時 `require_stages` 不生效，設定頁驗證器擋同時為真 |
| `ledger_warn` | int 0/1，預設 0 | 1 ＝ 多一個提示（不擋） | `risk=none`（不改任何判定結果；`canClose` 不變）；開關雙向都不屬放寬，**不需**第二位核准 | 需 accounting 提供能力；對方不在 ⇒ 該關不出現（不是 0） |
| `label_<key>`／`hint_<key>` | str，預設＝今天文字 | 顯示 | `risk=none`，不需核准 | 長度上限（標籤 ≤6 字、提示 ≤12 字）；一律走既有 `attr_esc`／`esc`；空字串 ⇒ 用預設，**不是空標籤** |
| `count_unfinished_extra_expenses` | 已有 | 收緊 | 已有 | §4 Q1 若同意，基礎行為先含「簽核中」，此選項只剩「草稿」 |

治理要點：①只有 `progress_required=0` 觸發第二位核准；②標籤與警示都不碰判定，不進核准流程；③所有新設定須註冊在 `settings_groups.py`（`impact_scope`、`question`、`choices` 照 S-C1 既有格式）與 `finance_params.CLOSE_GATE_OPTIONS` 同步，並進 `settings_deploy_baseline.json`。

## 3. 設計細節

**3.1 狀態 `warn`**：`_gates_from_facts` 新增第三種非 ok 狀態。`canClose = not any(blocked)` 與 `_case_close_block_reasons` 都只看 `blocked`，**天然不受影響**（已核對 `update_deal_tag` :2733 與 GET :2692）。需要處理的是所有「把非 blocked 當 ok／na」的消費者：矩陣色階（`list.js` :62-67）、結案前檢查視窗列表、`gate_matrix` 的 `blocked` 計數（:1288 一帶）。前端遇到未知 state 必須有預設樣式（黃色空心），並加測試。

**3.2 財務側警示的資料來源**：總帳是 L2 模組，案件模組不可 import。比照既有 `gl.source_status`（`helpers/gl_status.py`，`registry.providers(...)`）新增一個**批次**能力 `gl.case_unposted(conn, quote_nos) -> {quote_no: 未過帳傳票數}`（accounting 提供；一次查詢，與 `_close_gate_facts` 批次口徑一致，矩陣不得逐件查）。傳票與案件的連結鍵（`source_type`／`source_key` 前綴）我只確認 `gl_posted_warning(..., prefix=True)` 這個前綴查詢存在，**切片實作時要先查實連結鍵格式**，找不到穩定連結就退回 Q3 的「不做」。只計 `status IN ('草稿','待審核','簽核中','已核准')`（`VOUCHER_STATUSES` 去掉 `已過帳`）。文案：「此案尚有 N 張傳票未過帳（請通知會計）」，與 `MESSAGE` 同風格，非阻擋。

**3.3 進度選配**：`progress_required=0` 時，`total>0` 的案件仍算 `done/total` 顯示，狀態 `na`（reason=None）；`stageOverdue` 的矩陣紅燈規則（`list.js` :67）不受影響。`_gateTab` 的 key→分頁對照不變。

**3.4 標籤**：標籤現在散在 `_gates_from_facts`（後端）與 `list.js` :27-31（前端欄位常數）兩處。改法：後端是唯一來源（`gates[*].label/hint`），前端欄位標頭改讀 `gate-matrix` 回應第一列的 label，常數只當離線預設。擋下理由原句（`reason`）**不開放自訂**：它被寫進稽核 `case.close_blocked` 與通知信，改了會讓稽核紀錄前後不一致。

**3.5 精算完結 → 獎金母體／利潤凍結（只列，不動）**：精算完結（`settlement_api.py` :126-160）寫入 `summary.netProfit`、`frozenAt`、editHistory 的凍結快照；`payroll/bonus.py` 取 `settlement.summary.netProfit` 的已存值；獎金母體要求 `deal_tag='已結案'`、收入認列只認已成案／已結案、arap 入帳 `_DEAL_OK`、精算完結需已成案／已結案（:77）。因此「精算 finalized」關是這條鏈的上游，**永不可關**；本切片不改任何一個下游。

## 4. 耦合清單（動這些之前先看）

1. `_gates_from_facts` 的 `opts` 目前是 `{選項: bool}`；加入 `progress_required`（預設 True）、`ledger_warn`、labels 後，**`opts is None`（全關）的快速路徑**要保證輸出與今天逐位元相同（`_close_gate_opts` 的「全關 ⇒ None」捷徑會把放寬選項吃掉；`progress_required=0` 必須讓 opts 非 None）。
2. `finance_params.close_gate_options` 的錯誤處理是「讀不到 ⇒ 全 True」；放寬選項的最嚴值是 `progress_required=1`、`ledger_warn` 不屬嚴格方向（讀不到 ⇒ 0）。不可把兩種方向混在同一個 `strictest` 字典。
3. `gate_matrix`（:1236-1288）、`case_close_gates`、`case-bundle` 首屏、`update_deal_tag` 全走同一組函式；加關卡後 `response_keys_baseline.json`、`golden_case_page_2026_09_24.json`、`route_inventory.json` 要更新。
4. 前端：`list.js` 欄位常數與色階、`close.js` `_gateTab`、`case-management.html` 結案檢查視窗；新 key `ledger` 要補「前往」分頁（建議指到「財務」分頁）。
5. `notify_case_close_blocked`（docstring 仍寫「三項前置條件」）：只通知 `blocked` 的 reasons；`warn` 不寄信。若 Q1 通過，簽核中額外支出的待簽人需要併入 `pendingUsernames`（目前額外支出關永遠是空清單，只有最高管理員收到信）。
6. 稽核 `case.close_blocked`：reasons 內容不變，不可加入 label。
7. BP-5 P2：待簽語意值（`待審核`／`簽核中`）資料庫值不可改；閘門在流程建構器上線前要改成讀語意（既有前置條件，本切片不碰）。
8. `status_display`（S-X2）把 `finalized` 顯示為「已完結／精算完結」：標籤自訂不可與它互相覆寫（兩者作用對象不同：狀態顯示 vs 關卡欄名）。
9. 凍結的歷史：`migrations_frozen/t48_overhead25`、`t52_charity` 以 `settle_status='finalized' or deal_tag='已結案'` 判斷不重算；本切片不得改這兩個字串。
10. 並行車道：T62 S-C1 已在 `wip/t62-int-c1`；切片須從 T62 之後的基準起，且 `quotations.py` 與 `settings_groups.py` 是熱檔，PR 要小、先 rebase 再推。

## 5. 測試計畫（不在本筆記執行）

單元（純計算，不需資料庫）：
- 全關／無 opts ⇒ `_gates_from_facts` 輸出與基準逐位元相同（以 golden 比對五關 dict）。
- 法定鎖死性質：對 `opts` 的所有組合（窮舉 2^n）斷言「②③④⑤在有未達成事實時一律 blocked」；沒有任何組合能讓它們變 ok／na。
- `progress_required=0`：進度未滿 ⇒ `na`；`enabled=0` 時忽略該設定（仍 blocked）；讀不到 ⇒ blocked；與 `require_stages` 互斥驗證。
- `warn` 不影響 `canClose`、不進 `_case_close_block_reasons`、不觸發通知。
- 標籤：逸出（`<`、`"`）、長度、空字串＝預設、不影響 `reason`。
整合：
- `update_deal_tag` 對 `warn` 關有未過帳傳票時仍可結案；對 blocked 仍 400，訊息逐字不變。
- 放寬流程：`progress_required` 1→0 產生待生效變更、第二位核准＋確認期間前不生效、1 直接生效。
- 批次性：矩陣對 N 件案件的 SQL 句數與基準相同（`test_case_gate_batch_2026_09_24.py` 的做法），`gl.case_unposted` 只多一句。
- accounting 模組不在／能力未註冊 ⇒ `ledger` 關不出現、其餘五關不變。
前端：node 直接執行 `list.js`／`close.js` 零件（比照 `test_def_governance_ui` 做法）：`warn` 樣式、標籤來源、`_gateTab('ledger')`。

## 6. 小 PR 切法（每個 PR 預設全關＝今天行為，可獨立合併）

| PR | 內容 | 風險 |
|---|---|---|
| P1 | `_gates_from_facts` 結構整理：opts 型別擴充、`warn` 狀態與前端預設樣式、窮舉鎖死性質測試（無行為變化） | 低 |
| P2 | 標籤／提示設定＋後端為唯一來源＋`list.js` 欄名改讀回應 | 低 |
| P3 | `progress_required`（放寬，走 D-K1 流程）＋與 `require_stages` 互斥驗證 | 中（治理） |
| P4 | 簽核中額外支出併入基礎行為＋待簽人通知（若 Q1 同意）；上線前以唯讀查詢列出受影響的現有案件數 | 中（行為變更，收緊） |
| P5 | `gl.case_unposted` 能力＋`ledger_warn` 關（先查實傳票連結鍵） | 中（跨模組） |

P1→P2 可並行；P3、P4 互不相依；P5 最後。

## 7. 需要使用者決定（每題附建議預設，你可代決）

- **Q1 簽核中（多層簽核簽到一半）的額外支出，要不要擋結案？** 建議：**要擋**（併入基礎行為，P4）。理由：未定案成本，結案後才核准會改已結案案件成本；屬收緊、不需第二位核准；FINANCE §5.1 已建議。代價：目前少數可結案的案件暫時不能結（上線前先給件數）。草稿維持選項，預設不擋。
- **Q2 進度關要不要允許管理者設成選配？** 建議：**允許，預設仍必要**（P3）；放寬走第二位最高管理者核准。若使用者不想增加放寬面，P3 可整個不做，不影響其他切片。
- **Q3 財務側「尚有未過帳傳票」要不要擋結案？** 建議：**只警示不擋**（P5）。理由：總帳引擎在結案後才產生／過帳是正常流程（入帳事件認列只認已成案／已結案），擋結案會形成死鎖；若連結鍵查不到穩定來源則整個不做。
- **Q4 關卡欄名／提示文字是否開放自訂？** 建議：**開放，擋下理由原句不開放**（P2）。理由：欄名純顯示；理由句進稽核與通知信，改動會讓紀錄前後不一致。
- （不需問）收款、單據、精算完結、額外支出待審核四關永不可關：已是使用者既有裁示（結案後鎖案、收入與成本必須先確定）。
