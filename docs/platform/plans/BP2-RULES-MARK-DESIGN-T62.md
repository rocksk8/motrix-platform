# BP-2 規則引擎（標記型）設計：條件 → 標紅／提醒，門檻在系統內可改、改前可預覽「現有哪些紀錄會被標示」

> 日期：2026-10-14　作者：hichan-3e（受 hichan-b4 指派）　**僅設計，尚未實作、未跑任何測試。**
> 依據：`FRAMEWORK-10DAY-ROADMAP-T56.md` §0B.3（BP-2）、`PLATFORM-BUILDER-ARCHITECTURE-T57.md` §3.2、§3.4、§3.4b、§3.9／3.9b、`BUILDER-DECISION-PACK-T57.md`（規則失效模式、付款衍生旗標、規則上線順序 P-2），以及 t59–t62 已落地的治理層（版本帳本、差異、影響預覽、預覽雜湊把關、放寬分類＋第二位核准＋確認期間）。
> 範圍：**只做標記型**（`mode=mark`）。阻擋型、通知、寫欄位、改狀態一律不在本班（驗證器直接拒絕）。

## 1. 管理者出貨後能做什麼

1. 在「規則」頁看到某個畫面（例如案件／報價）已有的規則清單：名稱、條件白話、標示顏色、目前狀態、版本、**目前命中幾筆**。
2. 新增或修改一條規則：用下拉選單選「欄位 → 比較方式 → 門檻」＋顏色＋提示文字（不是寫運算式）。
3. **改門檻前先預覽**：畫面即時顯示「若發布，現有紀錄會有幾筆被標示、與目前相比新增幾筆／取消幾筆」，並列出樣本（只列預覽者本來就看得到的紀錄與欄位）。
4. 發布走既有的治理流程：影響預覽 → 預覽雜湊 → 版本帳本／還原；**讓標示變少的變更（放寬）要第二位最高管理者核准＋確認期間，讓標示變多的變更（收緊）即時生效**。
5. 規則故障時**不影響任何人存檔或讀資料**：該條規則暫停、畫面上出現中性提示、管理員看得到警示與稽核（`degrade_loud`）。
6. 例子：利潤警示（K01）——「毛利 < X% 就標紅」，X 在系統內調整。調高 X＝更多警示＝收緊（即時）；調低 X＝放寬（走核准）。

## 2. 旗標與「關＝逐位元不變」

- 設定群組 `builder_rules`，欄位 `enabled`（int 0/1，預設 0）。**不加 `loosen`**（同 `builder_governance.enabled`，整體回退要能即時）。
- 關閉時：規則 API 一律 404、規則頁與標示疊加層不載入、**沒有任何現有畫面的 DOM／回應多出東西**、K01 等今天寫死的警示邏輯**完全不動**（本班不遷移它們，見 §10）。
- 前端不使用 `x-show`／內嵌 `display` 改寫既有節點；疊加層只在旗標開且有已發布規則時，往既有列／欄位加 `data-rule-mark` 與 class（上次 e2e 失敗的就是 x-show 蓋掉 inline `display:flex`）。
- 開啟前提：`builder_governance.enabled=1`（要用版本帳本／預覽雜湊）。

## 3. 資料模型（無 DDL）

- 新定義種類 `rule_set`（以 `core.definitions.register_kind()` 由 helper 登記，與 `expense_types` 同模式；不改 L0）。
- **key＝畫面主題（entity）**，例如 `case`、`quotation`；一個 entity 一份規則集，body：

```json
{"rules": [
  {"id": "low_margin", "name": "低毛利", "enabled": true, "mode": "mark", "on_failure": "degrade_loud",
   "when": {"op": "lt", "field": "quotation.marginPct", "value": 15},
   "mark": {"level": "red", "text": "毛利偏低", "target": "row"}}
]}
```

- 版本、草稿、差異、還原、送審：全部沿用 `ui_definitions`；待核准／確認期間／第二位核准沿用 `def_pipeline` ＋ `config_ledger`（`_submit_pending`）。
- 規則集**不就地改**：只能發布新版；停用＝發布一個 `enabled:false` 的新版（也是一次版本）。

## 4. 規則文法（宣告式，不執行任何程式碼）

```
when := cmp | {"op":"and"|"or","args":[when,…]} | {"op":"not","arg":when}
cmp  := {"op": "lt|le|gt|ge|eq|ne","field": <欄位代號>,"value": <數字|字串|布林>}
      | {"op":"between","field":…,"min":…,"max":…} | {"op":"in","field":…,"values":[…]}
      | {"op":"empty"|"not_empty","field":…}
```

- 沒有運算式字串、沒有函式呼叫、沒有欄位對欄位的算式（v1 只有「欄位 vs 常數」；比例類欄位由欄位目錄提供預先算好的衍生欄位）。
- 驗證器：先檢長度與型別再解析；節點數 ≤ 200、深度 ≤ 8、每個 entity 規則數 ≤ 50、`id` 唯一且 `^[a-z][a-z0-9_]{1,39}$`、提示文字 ≤ 40 字（純文字，輸出一律轉義、不支援占位符）、`level ∈ {red,yellow,info}`、`target ∈ {row,field}`（field 時需 `field` 在目錄且可顯示）。
- `mode` 只接受 `mark`；`on_failure` 只接受 `degrade_loud`（API 與驗證器**已帶這兩個欄位**以便 BP-2 後續開 `block`／`fail_closed`，本班值固定；其他值 ⇒ 驗證不過，訊息「這一版尚未開放」）。
- 與簽核條件、浮水印占位**共用同一份驗證器**的要求（T57 §3.4b）：本班先把驗證器寫成 `helpers/rule_grammar.py` 的獨立模組，簽核條件／浮水印之後只呼叫它，不再另寫第二套。

## 5. 欄位目錄與遮蔽（遮蔽永遠優先）

- 規則只能引用**欄位目錄**裡的欄位。目錄由各模組宣告（資料：`module.json` 的 `rule_fields`，或 helper 登記表），每項帶：`id`、白話名稱、型別（number/text/enum/date/bool）、單位、`internal`／`isMoney`、所需檢視權限（沿用 `quote_money_visible`／`money_visible`／`case_page_readable`）、取值函式。
- **付款衍生旗標（逾期應收、缺發票…）不得進目錄**（決策包 #7、U13）：目錄項若帶 `derived_from_payment: true` 或其取值函式落在付款表 ⇒ 登錄時 ValueError；**靜態守門測試**列舉全目錄，任何此類項目 ⇒ 紅（附故意加入一項的正對照）。
- **標記型 ＝ 每位檢視者的訊號**：評估時，檢視者看不到的欄位不進上下文；規則的條件含該檢視者看不到的任何欄位 ⇒ **對他不評估、不回任何訊號**（不是 false，是「不存在」）。因此無成本權限者不能由「紅／不紅」推得毛利。
- 規則本身的存在也分權限：含 `internal`／`isMoney` 欄位的規則，其名稱與提示文字只對有權限者顯示；規則清單頁只給最高管理者。
- 快取鍵＝（規則集版本，角色，檢視者可見欄位集合的雜湊，紀錄更新戳）。**正對照測試**：admin 先載入（含成本衍生紅字）、engineer 接著載入同一列表，engineer 不得看到任何由成本衍生的標記；把快取鍵拿掉檢視者維度，測試必須紅。

## 6. 評估器（沙箱、純函式、降級要大聲）

- `helpers/rule_engine.py`：`evaluate(rules, ctx, *, limits, now) -> list[Result]`，**純函式**（不碰資料庫、不寫任何東西、不 import `eval/exec/compile/importlib/subprocess/os`；靜態守門掃描）。三態：`true/false/unknown`；缺值＝`unknown`；標記型 `unknown`＝不標記。
- 批次：列表先編譯成評估計畫、單次掃描；單頁上限（預設 200 列）；單次評估時間預算 20 ms／列頁（總預算 300 ms）。
- 失效＝逾時、超預算、評估器例外（缺值不是失效）。失效時：該條規則本次視為未標示；寫一筆稽核 `rules.degraded`（同一規則同一版本 5 分鐘內只記一次，避免灌爆）；回應多一個中性欄位 `degraded:[{ruleId,reason:"timeout|budget|error"}]`（只給最高管理者的請求；一般使用者只看到畫面上的中性提示「部分提醒暫時無法顯示」）；規則頁該規則出現橫幅。**絕不阻擋存取或儲存。**
- 脊柱接點：規則評估**不受功能狀態影響**（T57 §3.9b-1），只有編輯／發布／顯示受功能狀態控制。

## 7. 執行期標示怎麼出現在畫面（讀取側，不改既有路由回應）

- 新唯讀路由（旗標關 ⇒ 404）：`GET /api/rules/marks?entity=case&ids=1,2,3`（≤ 200 個 id）⇒ `{marks:{"<id>":[{ruleId,level,text,target,field?}]}, degraded?}`。伺服器以呼叫者的權限載入這些紀錄的**可見欄位**、跑已發布規則集。
- 既有列表／表單**不改回應**，也不改 DOM 結構：前端 `js/rule-marks.js`（獨立元件，同 `def-governance.js` 模式）在頁面宣告了「規則插槽」（頁面 `data-rules-entity="case"` 與每列 `data-rule-id`）且旗標開時，才抓 marks，加 `data-rule-mark="red"` ＋提示。**插槽宣告由各模組擁有者加到各頁**（每頁一個小 hunk；本班只在 1 頁接線作示範，建議案件列表，見 §11 決定 R2）。
- 提示文字與顏色只來自已發布規則集；沒有任何使用者輸入進 `innerHTML`（用 `textContent`）。

## 8. 管理者介面（規則頁，只給最高管理者）

頁面 `rules-builder.html`（`js/rules-builder.js`；從「系統 → 建構器」進入；旗標關不顯示入口）：

```
┌ 規則：案件 ▾ ────────────────────────────  [新增規則]  [版本帳本] [待核准 2] ┐
│ ● 低毛利        毛利 低於 15%      紅   v3   目前命中 12 筆   [編輯] [停用]   │
│ ● 逾期未結案    結案天數 大於 90   黃   v1   目前命中  4 筆   [編輯] [停用]   │
└────────────────────────────────────────────────────────────────────────────┘
編輯（右側面板）
  名稱 [低毛利]   欄位 [毛利率 ▾]  比較 [低於 ▾]  門檻 [15] %   顏色 (紅)(黃)(灰)
  提示文字 [毛利偏低]（≤40 字）                      ☐ 條件組（且／或）進階
  ── 即時預覽（草稿，尚未發布）──────────────────────────────────────────
  目前已發布：命中 12 筆　→　套用後：命中 19 筆（新增 8、取消 1）　＝ 收緊（立即生效）
  樣本（你看得到的前 10 筆）：ABC-001 毛利 12.5% ｜ …
  [取消]  [儲存草稿]  [預覽並發布…]
```

- **即時預覽**＝`POST /api/rules/preview`（唯讀；旗標關 404）：body＝草稿規則集（或單條規則＋entity）⇒ 對「最近 N 筆（預設 200、上限 1000）紀錄」以**預覽者的權限**評估兩份（已發布 vs 草稿）⇒ `{published:{hits}, draft:{hits}, added, removed, samples:[{id,label,ruleId}], sampled:N, direction:"tighten|loosen|neutral", reasons:[…], previewHash}`；**不寫任何資料**（只留一筆「看過預覽」稽核，同 `definitions.previewed` 機制，雜湊＝草稿戳）。畫面隨輸入去抖 400 ms 重算；失敗顯示白話原因，不顯示舊結果。
- 樣本只列預覽者看得到的紀錄；欄位值只顯示預覽者可見的欄位（成本衍生數字對無權限者不顯示）。這頁只給最高管理者，但仍用同一個遮蔽路徑（不另寫一份）。
- **改門檻快捷**：列表上「15」可就地改 ⇒ 開啟預覽面板，確認後走同一個發布流程（`MotrixDefGovernance.review()` ＋預覽雜湊）。
- 發布結果：收緊＝立即；放寬＝顯示「已送出，待第二位最高管理者核准；生效時間…；原因：…」（沿用 t60 回應形狀 `pending/effectiveAt/reasons`，不說「已發布」）。
- 無原生 `confirm()`／`alert()`；停用／刪除用兩段式內嵌確認。e2e 等待點：`#rb-panel[data-state]`（idle｜previewing｜ready｜published｜pending｜error）。

## 9. 治理層重用（不另造輪子）

| 項目 | 做法 |
|---|---|
| 版本／差異／還原／帳本 | `rule_set` 是一般定義種類，直接用 `/api/def-governance/rule_set/{entity}/…` 與面板 |
| 預覽雜湊把關 | 把 `rule_set` 加進 `_OPT_IN_PREVIEW_KINDS`（設定 `builder_governance.enforce_rule_set`，預設 0）；規則頁一律送雜湊，**上線時建議直接開** |
| 放寬／收緊分類 | `def_pipeline.COMPARATORS["rule_set"]=_cmp_rule_set`（見下）；`ACTIVE_KINDS` 加入；無法比較＝放寬 |
| 第二位核准＋確認期間 | `_submit_pending`（`risk=security`、`approvals_required=1`、確認期間沿用 `confirm_period_days`） |
| 受管 kind | 加進受管 kind 名單：通用 PUT/POST 在旗標開時只能經規則頁的發布入口（沿用 S2 的做法） |
| 稽核 | `definitions.*`、`rules.degraded`、`rules.previewed`（沿用 `definitions.previewed`） |

**`_cmp_rule_set(old, new)`**（逐規則 `id` 對照；方向由比較運算子決定，**不寫死「調高＝放寬」**）：

| 變更 | 分類 |
|---|---|
| 新增規則（enabled） | 收緊 |
| 移除規則、停用規則 | 放寬 |
| `lt/le`：門檻調高；`gt/ge`：門檻調低（標示變多） | 收緊 |
| `lt/le`：門檻調低；`gt/ge`：門檻調高（標示變少） | 放寬 |
| `between` 範圍擴大／縮小、`in` 增加／減少值 | 依「命中集合變大＝收緊」判定 |
| 顏色由 red→yellow/info（醒目度降低） | 放寬；反向＝收緊 |
| 只改名稱／提示文字 | 中性 |
| `and/or/not` 結構改變、運算子改變、欄位改變、無法解析、未知運算子 | **放寬**（保守） |

測試必含：每個方向的正反兩例；**把 `lt`/`gt` 方向互換，測試必須紅**（突變控制，T57 §3.4b 明定）。

## 10. 與現有寫死警示（K01）的關係

- 本班**不遷移、不修改**現有利潤警示。規則引擎是新增的疊加層，「規則只能更嚴、不能移除或繞過任何內建檢查」（T57 §3.10）。
- K01 作為規則實例（預設值＝今天的行為）屬下一個子切片，需先盤點今天寫死的位置與數值（`modules/case/api/quotations.py` 送審 reasons 的低毛利判斷等；**UNKNOWN：精確門檻與觸發條件需先讀程式盤點，不在本設計假設**），並用獨立旗標 `builder_rules.k01_seed` 預設關；開啟後才由規則集接手顯示，原送審 reasons 邏輯仍保留並繼續把關。

## 11. 切片、檔案與工量（估）

| 序 | 切片 | 內容 | 檔案（新增為主） | 估 pd |
|---|---|---|---|---|
| R0 | 文法＋驗證器＋評估器（純函式） | `rule_grammar.py`、`rule_engine.py`、靜態守門、病態規則集測試、三態與突變測試 | `helpers/rule_grammar.py`、`helpers/rule_engine.py` | 3～4 |
| R1 | 欄位目錄＋遮蔽＋定義種類＋設定群組 | 目錄登錄表（拒付款衍生）、`rule_set` 登記、`builder_rules` 設定、per-viewer 上下文 | `helpers/rule_catalog.py`、`helpers/rule_sets.py`、`settings_groups.py` | 3～4 |
| R2 | API：`marks`／`preview` | 旗標關 404；批次；快取鍵含檢視者維度；降級稽核與節流 | `routers/rules.py`（+`main.py`、`modules.json`） | 3～4 |
| R3 | 治理接線 | `_cmp_rule_set`、`ACTIVE_KINDS`、受管 kind、`enforce_rule_set` | `routers/def_pipeline.py`、`definitions.py` | 2～3 |
| R4 | 規則頁＋疊加層 | `rules-builder.html/js`、`rule-marks.js`、示範 1 頁接線（案件列表） | `frontend/…`、案件頁一個小 hunk（擁有者） | 4～6 |
| R5 | 逐角色正反對照＋e2e 腳本 | admin/sales/finance/cashier/engineer/viewer；快取污染；故障降級；break-glass 留給阻擋型 | `tests/` | 2～3 |

合計約 **17～24 pd**（估，不含 K01 實例化與其他頁接線；與路線圖 BP-2 規則引擎 18～30 pd 同量級）。

## 12. 測試計畫（每個守門都要有「故意弄壞」的對照）

1. 旗標關：規則路由全 404；既有列表／表單回應與 DOM 不變（黃金對照）；沒有新增 script 標籤載入到未宣告插槽的頁。
2. 文法：任何不在文法內的輸入拒絕（參數化突變）；長度／節點／深度／規則數上限；`mode=block`、`on_failure=fail_closed` 被拒。
3. 評估器：三態；缺值不標記；病態規則（最大深度／節點、10 萬列模擬）延遲有上限；超時／例外 ⇒ 降級＋稽核＋不影響呼叫端；靜態掃描無 `eval/exec/compile/importlib/subprocess/os.system`。
4. 遮蔽：檢視者看不到條件欄位 ⇒ 不評估、無標記；回應位元組不含來源欄位值；成本衍生標記快取跨角色不外洩（正對照：移除檢視者鍵 ⇒ 紅）；目錄拒絕付款衍生項（正對照：加一項 ⇒ 紅）。
5. 預覽：只讀（資料庫無寫入，除一筆稽核）；新增／取消筆數正確；樣本只含預覽者可見；`previewHash` 與草稿一致；草稿改過再發布 ⇒ 409。
6. 治理：`_cmp_rule_set` 全表；方向互換突變；放寬 ⇒ pending＋第二位核准＋確認期間；收緊 ⇒ 立即；無法比較 ⇒ 放寬。
7. 前端（node 假環境）：規則頁狀態機、預覽去抖與失敗訊息、待核准文字不說「已發布」、疊加層只用 `textContent`、沒有原生對話框。

## 13. 已知缺口與風險

1. 欄位目錄與 3c 的 S5「欄位目錄＋`x_` 自訂欄位」會重疊：**建議 BP-2 的 `rule_catalog` 直接讀同一份欄位目錄**；S5 未落地前，R1 先用自己的小登錄表（`rule_fields`），之後以轉接層合併。**需 46／3c 確認欄位目錄的擁有者與介面**（決定 R1）。
2. 「最近 N 筆」預覽是抽樣，不是全表；畫面明講「依最近 N 筆估算」。大表全掃屬後續（需要背景工作，目前沒有排程器）。
3. 疊加層只接 1 頁；其他頁由各模組擁有者加插槽（每頁一小 hunk＋逐角色測試）。
4. 阻擋型、通知、寫值類輸出完全不在本班；`fail_closed`／break-glass 等到阻擋型與試跑存在時才實作。
5. 沒有真瀏覽器 e2e（只有 node 假環境）；開旗標前至少需一輪真瀏覽器驗證（由主持排）。
6. 精確的現行低毛利判斷（K01）位置與門檻**尚未盤點**（UNKNOWN）。

## 14. 需要決定（附建議預設）

- R1 欄位目錄的擁有者與接口：沿用 3c 的 S5 目錄，還是 BP-2 先自建小登錄表？ 建議：先自建，S5 落地後合併。
- R2 疊加層示範頁選哪一頁？ 建議：案件列表（已有版面引擎登記，且 3c 對該頁最熟）。
- R3 規則集的粒度：一個 entity 一份（建議），或一條規則一份定義？ 建議：一個 entity 一份（版本對照與還原較直覺；缺點是放寬判斷要逐規則）。
- R4 預覽樣本大小：預設最近 200 筆、上限 1000？ 建議：同左。
- R5 提示文字是否允許占位符（例如 `{threshold}`）？ 建議：v1 不允許；文字固定。
- R6 `enforce_rule_set` 上線時是否直接開？ 建議：開（規則頁天生送雜湊）。
