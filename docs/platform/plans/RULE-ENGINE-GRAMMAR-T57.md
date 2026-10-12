# 規則引擎文法 v1：欄位目錄上的宣告式條件規則（僅文件，未跑任何測試）

> **r2（1d／2b 對 r1 `a035abe0b` 與脊柱 E-b 的審閱）**：①**衝突修正（主要）**：脊柱的執行期失敗＝功能停用／群組隱藏（對『設定』fail-closed、對『行為』fail-open）。若規則評估被 `spine.feature_enabled` 擋住，一次驗證小故障就會**靜默關掉已發布的 `block`＋`fail_closed` 保護型規則＝繞過**。r2 規定：**功能狀態（`open／planned／hidden`）只用於編輯器可見性、新發布與顯示；已發布的 `fail_closed` 阻擋規則只要『規則引擎本身健康』就照常評估**；『引擎不健康』是本文 §6.4 自己的路徑（不是脊柱降級）。見新增的 §6.5。②重用脊柱掛鉤：`alert_rule` 為**受管 kind**（`register_kind_gate`）、規則發布／評估前問 `spine.surface_status`、`rule.degraded` 稽核去重沿用 `audit_spine_failures` 的簽名法、健康徽章共用 `spine.register_health_source`、`{"setting": …}` 指到 planned／hidden 群組的規則發布一律 422（不說 hidden）（§6.5）。③U3 改為採 `loosen="both"`（§8、§13）。④快取鍵加『設定群組戳記』（§6.1-4）。

> 日期：2026-10-13　作者：hichan-5e（T57）　狀態：r1，待非作者稽核（0d）。回應 `PLATFORM-BUILDER-ARCHITECTURE-T57.md`（98）的 **UNKNOWN U1『精確的規則文法』**。
> 對齊：98 `PLATFORM-BUILDER-ARCHITECTURE` §3.1／§3.2／§3.4／§3.4b（三態、`mode`／`on_failure`、K01 方向、長度先限制再解析）；0d `USER-DEFINED-LOGIC-THREAT-MODEL.md` §1（規則引擎）、§5（欄位目錄與衍生操作）；`FIELD-CATALOG-SEED-T57.md` r3（目錄欄位、§5.0 衍生操作唯一規則、§5.7 付款衍生事實、§6.2 `alert_rule` 介面）。
> 已讀並**實測**的程式：`backend/helpers/formula.py`（366 行）。§9 列出『要改什麼』，每個結論都附我實跑的結果。**本文不改任何安全底線。**

## 0. 結論（先看）

1. **規則的儲存形式是 JSON『條件樹』，不是文字運算式。** 圖形編輯器直接產生樹；後端驗證樹、編譯成評估計畫。理由：①沒有文字就沒有解析器攻擊面（無 `ast.parse`、無跳脫、無注入）；②節點數、深度、型別在驗證時就能精確計算；③每個節點可附白話標籤給編輯器與稽核；④三態語意（§3）在樹上是明確的節點屬性，而不是藏在 Python 的 `and/or/not` 行為裡。
2. **只有一種『文字』存在：算術葉 `expr`**（例：`price - cost`、`days_between(updated_at, $today)`），其文法是 `formula.py` 的**子集**（§5），由**同一個 `formula.check()` 白名單走訪器**驗證，加上規則專用的上限（§7）。**不是第二套文法。** 規則引擎自己的**求值**不沿用 `formula.evaluate()`（理由：它用浮點、`not None` 為真、`and/or` 回傳運算元值、`check` 每次重新解析——見 §9 的實測），而是以同一個走訪器產生**編譯後的 Decimal 三態求值器**。
3. **三態（Kleene）是核心**：條件的值是 `TRUE／FALSE／UNKNOWN`（缺值＝UNKNOWN）；另有第四種**『不適用』**（輸入欄位對檢視者**不可見**）——它**不是**UNKNOWN，而是『整條規則對此人不存在』（無輸出、無痕跡）。兩者必須分開，否則缺值會被誤當成隱藏、隱藏會被誤當成缺值而洩漏。
4. **兩種輸出、全是顯示或攔截，沒有寫入**：`mark`（徽章、列樣式、紅字）與 `block`（攔截一個**已註冊的動作**並顯示固定訊息）。規則**不能**寫欄位、改狀態、通知、呼叫其他 API（通知是註冊動作，威脅模型 §8，本期不開）。
5. **『除非 X 否則擋』與『若 Y 則擋』是兩種不同的節點**（`block.unless`／`block.if`），三態下**不等價**（§4）；驗證器登記每個運算子的 `UNKNOWN` 行為並有測試。
6. **K01 是一條規則**（§8）：`direct_margin_pct lt {設定: 門檻}`；放寬／收緊方向**由運算子決定**（`lt`／`le`：調低＝放寬；`gt`／`ge`：調高＝放寬；其他運算子或未知＝一律視為放寬），不寫死『調高＝放寬』。
7. **上限寫死、管理者只能調小**：JSON 8 KB、節點 200、深度 8、`expr` 200 字、每表面 50 條、每條規則評估 20 ms、每批次總預算；超限＝**可見的降級**（§7、§6）。
8. **保護型阻擋規則**（引用了執行者看不到的欄位）只能是 `protective` 規則：**在伺服器端以真實資料評估、輸出固定中性訊息、不帶任何欄位值**，且只在**動作當下**評估（不進清單、不批次）、只限 money／legal 單據、建立與放寬都走高影響流程（§6.3）。洩漏的是『被擋了』這 1 bit，這是**已知且被接受的殘餘**，需 0d／使用者確認（§11 U5）。
9. **8 條範例規則**取自今天寫死的 11 處警示（§10），其中 A1／A10 需要先把 `lifecycle` 與『停留天數』搬成後端 `computed` 欄位（目錄 U4）。**每條範例都有『與今天逐位相同』的黃金比對。**
10. **工量（估）**：文法與驗證器 1.0＋編譯求值器（Decimal 三態）1.25＋批次評估／快取／預算 1.0＋失效模式與 break-glass 0.75＋K01／範例遷移 1.0＋測試（含正對照）1.5＝**約 6.5 pd**（不含編輯器 UI；UI 在 98 的 BP-2）。**估計，未原型驗證。**

## 1. 規則定義的形狀（`alert_rule` kind v1；定義文件庫的新 kind）

```json
{
  "kind": "alert_rule",
  "key": "quote_low_margin_crit",
  "scope": "company",
  "body": {
    "version": 1,
    "label": "毛利偏低（嚴重）",
    "surface": "module:case.quotation_list",
    "mode": "mark",
    "severity": "crit",
    "on_failure": "degrade_loud",
    "applies": {"state_in": null},
    "when": { "cmp": {"op": "lt", "left": {"field": "direct_margin_pct"}, "right": {"setting": "profit.margin_crit_pct"}} },
    "then": { "badge": [ {"t": "text", "v": "毛利偏低 "}, {"f": "direct_margin_pct", "fmt": "pct1"} ],
              "tone": "crit", "target": "cell:direct_margin_pct" }
  }
}
```

| 鍵 | 必填 | 說明 |
|---|---|---|
| `version` | ✔ | 文法版本（本文＝1）；未知版本＝驗證失敗，**不載入、不猜**（威脅模型 §7 的回滾原則） |
| `label` | ✔ | 白話名稱（純文字；顯示用 `textContent`） |
| `surface` | ✔ | 目錄表面鍵（`module:<模組>.<表面>`，≤30 字表面）；規則只能引用**該表面目錄中 `ops.ruleUsable=true`** 的欄位 |
| `mode` | ✔ | `mark`｜`block`（API 從第一天帶，98 §3.4b） |
| `severity` | ✔ | `info`｜`warn`｜`crit`；`block` 恆為 `crit` |
| `on_failure` | ✔ | `degrade_loud`｜`fail_closed`（§6.4）；引擎預設 `degrade_loud`；金額／法定類型上建立 `block` 時**必須由作者明確選**（介面預選 `fail_closed`） |
| `applies` | 選填 | 套用範圍：`state_in`（單據狀態語意標籤清單，例：僅草稿與待審核）、`doc_type`；不寫＝全部 |
| `when` | ✔ | 條件樹（§2） |
| `then` | `mark` 必填 | 標記輸出（§5.1） |
| `block` | `block` 必填 | 攔截輸出（§5.2）；與 `when` 的關係見 §4 |
| `protective` | 選填 | 保護型阻擋（§6.3）；預設 false |

驗證器拒絕**任何未知鍵**（拼錯的鍵不得靜默忽略——與 `customization` 同規矩）。

## 2. 條件樹

### 2.1 節點

| 節點 | 形狀 | 子節點數 | 值 |
|---|---|---|---|
| `all` | `{"all": [c1, c2, …]}` | 2～16 | Kleene AND |
| `any` | `{"any": [c1, c2, …]}` | 2～16 | Kleene OR |
| `not` | `{"not": c}` | 1 | Kleene NOT |
| `cmp` | `{"cmp": {"op": …, "left": 運算元, "right": 運算元}}` | 葉 | 比較（§3） |
| `between` | `{"between": {"value": 運算元, "lo": 運算元, "hi": 運算元}}` | 葉 | 含兩端：`lo ≤ value ≤ hi` |
| `in` | `{"in": {"value": 運算元, "set": [常數…]}}` | 葉 | 集合成員（`set` 最多 32 個常數，皆須與 `value` 同型） |
| `is_null` / `not_null` | `{"is_null": 運算元}` | 葉 | **永遠是 TRUE／FALSE，從不 UNKNOWN**（唯一能『看見』缺值的節點） |
| `is_true` / `not_true` | `{"is_true": c}`／`{"not_true": c}` | 1 | 把 UNKNOWN 收斂成兩態：`is_true(c)` ＝ c 為 TRUE；`not_true(c)` ＝ c 為 FALSE **或** UNKNOWN（§4 的 `unless` 用它） |

### 2.2 運算元（`left`／`right`／`value`／`lo`／`hi`）

| 運算元 | 形狀 | 說明 |
|---|---|---|
| 欄位 | `{"field": "direct_margin_pct"}` | 必須是目錄欄位 id、`ops.ruleUsable`、且該表面可用；驗證時記錄為規則的**輸入欄位集合**（§6.1 per-viewer 評估用） |
| 常數 | `{"const": 20}`／`{"const": "草稿"}`／`{"const": true}` | 數字以**十進位字串或整數**儲存（`{"const": "20.5"}` 亦可）→ 評估時一律 `Decimal`，不經浮點 |
| 設定引用 | `{"setting": "profit.margin_crit_pct"}` | 引用**設定中心**登錄的欄位（唯讀、型別為 number／percent／int）；讓門檻仍由設定登錄表的風險類、確認期間、帳本管理（§8）。引用不存在或型別不符＝驗證失敗 |
| 情境常數 | `{"ctx": "today"}` | 伺服器提供的**唯一**情境值：`today`（本地日期 `YYYY-MM-DD`，沿用 `MotrixDate` 的時區規則；**同一批次內固定**，確保可重現）。**沒有 `now`、沒有 `user`、沒有任何其他情境**（`user` 會讓規則依人而異，違反『輸出只依資料與檢視者可見性』的簡單性；需要時另案） |
| 算術 | `{"expr": "price - cost"}` | §5 的受限運算式；只能引用目錄欄位 id（與 `ctx`，以 `$today` 寫入） |

型別系統：`number／money／percent／count`（皆為 `Decimal`）、`date`（ISO 字串）、`text`、`enum`（以代碼比較）、`bool`。**不做隱含轉型**：`cmp` 兩側型別必須相同（數字族彼此相容）；日期只能與日期比較；文字只能 `eq／ne／in`（區分大小寫、不 trim，除非欄位的 `format` 已正規化）。型別不符＝驗證失敗，不是執行期的 UNKNOWN。

## 3. 三態語意（逐運算子固定；驗證器登記並有測試）

### 3.1 值與傳遞
- 欄位值缺（`None`、空字串視為缺；`0`、`false` **不是**缺）→ 該運算元為 **NULL**。
- 任何**含 NULL 運算元**的 `cmp`／`between`／`in` ⇒ **UNKNOWN**（沒有例外；`NULL == NULL` 也是 UNKNOWN）。`is_null`／`not_null` 是唯一例外（兩態）。
- `expr` 內任何 NULL 運算元（含被 `coalesce` 之外的函式）⇒ 結果 NULL（空值傳遞，與 `formula.py` 的『空值不等於 0』一致）；除以 0 ⇒ NULL 並**不**算失效（§6.4）。
- Kleene 真值表（`T`／`F`／`U`）：

| AND | T | F | U |
|---|---|---|---|
| **T** | T | F | U |
| **F** | F | F | F |
| **U** | U | F | U |

| OR | T | F | U |
|---|---|---|---|
| **T** | T | T | T |
| **F** | T | F | U |
| **U** | T | U | U |

`NOT T = F`、`NOT F = T`、`NOT U = U`。`all` 是 n 元 AND、`any` 是 n 元 OR（短路求值**只可優化、不可改變結果**；測試：短路與全評估結果相同）。

### 3.2 各運算子的 UNKNOWN 行為（固定表）

| 運算子 | 條件 | 結果 |
|---|---|---|
| `lt／le／gt／ge／eq／ne` | 任一側 NULL | **U** |
| `between` | `value`、`lo`、`hi` 任一 NULL | **U**（即使 `value > hi` 已足以為 F，也先看 NULL：**保守為 U**——避免依賴求值順序；測試鎖定） |
| `in` | `value` NULL | **U**；`set` 內不允許 NULL 常數 |
| `is_null`／`not_null` | — | T／F（兩態） |
| `is_true(c)` | c 為 U | **F** |
| `not_true(c)` | c 為 U | **T** |
| `all／any／not` | 見真值表 | |

### 3.3 輸出端如何看待 U
- `mark`：`when` 為 **T** 才標記；**F 與 U 都不標記**（98 §3.4b：標記型 `unknown` ＝不標記）。
- `block.if`（『若 Y 則擋』）：Y 為 **T** 才擋；F 與 U 不擋。
- `block.unless`（『除非 X 否則擋』）：X 為 **T** 才放行；**F 與 U 都擋**（缺值視為不滿足 X）。
- 這兩種在 UNKNOWN 下**刻意不對稱**——見 §4 的陷阱與測試。

## 4. 『除非 X 否則擋』vs『若 Y 則擋』

```json
"block": { "unless": { "cmp": {"op":"ge","left":{"field":"item_margin"},"right":{"const":"0.3"}} },
           "blocks": "transition:submit", "message": [ {"t":"text","v":"有品項毛利率低於 30%，需主管核准後才能送出"} ] }
```
```json
"block": { "if": { "cmp": {"op":"lt","left":{"field":"item_margin"},"right":{"const":"0.3"}} }, ... }
```
- `unless X`＝『X 不為真就擋』＝等價於 `if not_true(X)`；`if Y`＝『Y 為真才擋』。
- **陷阱**：`if not(X)` **不等於** `unless X`——當 X 為 U（缺成本）時，`not(U)=U` ⇒ `if` 不擋，而 `unless` 擋。**驗證器不禁止兩種寫法，但編輯器介面只提供『除非…否則擋』與『若…則擋』兩個明確選項**（不讓人手寫 `not`），白話文字都帶一句說明：『欄位沒填時，「除非」會擋、「若」不會擋』。
- 預設推薦：保護性規則（金額、法定）用 `unless`（缺值＝不放行，fail-safe）；提醒性規則用 `mark`。
- 測試（含正對照）：①真值表三個值 × 兩種節點的 6 格；②『把 `unless X` 換成 `if not(X)`，缺值案例測試必須紅』（突變證明兩者不等價且測試抓得到）。

## 5. 允許的函式與輸出

### 5.1 `expr` 的文法（`formula.py` 的子集；同一個白名單走訪器）

- **允許**：數字常數、`$今天` 以外的欄位 id（目錄欄位）、`+ - * /`、一元負號、括號、函式呼叫；**`$today`** 代表情境常數 `today`（編輯器顯示為『今天』）。
- **函式（封閉清單，v1）**：

| 函式 | 引數 | 傳回 | NULL 行為 |
|---|---|---|---|
| `abs(x)` | 1 個數字 | 數字 | NULL ⇒ NULL |
| `min(a, b, …)`、`max(a, b, …)` | ≥2 個數字 | 數字 | 任一 NULL ⇒ NULL |
| `round(x[, n])` | 數字、0～4 位 | 數字 | 以 `legal_params.round_half_up` 的四捨五入（與 `formula.py` 現況一致）；NULL ⇒ NULL |
| `coalesce(a, b, …)` | ≥2 | 第一個非 NULL | **唯一能把 NULL 變成值的函式**（例：`coalesce(freight, 0)`） |
| `days_between(起, 迄)` | 兩個日期 | 整數 | 沿用 `formula.py` 規則：不含起算日、只看前 10 碼、任一邊 NULL ⇒ NULL、格式錯＝驗證/求值失敗（§6.4 算失效） |

- **刻意不開**（v1）：`if`（條件分支用條件樹的 `all／any`，不在算術裡做）、`sum／total／avg／count`（明細表彙總：清單類規則不開；表單層級若要『品項毛利最低值』另案以目錄的 `computed` 欄位提供，例如 `min_item_margin`，**由程式算、規則只引用**）、字串函式、日期加減（用 `days_between` 與比較代替）、`now`、任何外部查詢。
- **字串**：`expr` 不接受字串運算（文字比較用 `cmp`／`in`）；`formula.py` 允許的字串常數與 `+` 串接在規則 profile 下**禁用**。
- `expr` 長度 ≤ **200 字**（`formula.py` 現行上限 500，規則 profile 降為 200；驗證在 `ast.parse` **之前**，已是 `formula._parse` 的順序）。
- 輸入欄位集合＝`formula.references()` ∩ 目錄；算術結果型別：全部 `Decimal`；結果型別在驗證時推導（數字／日期差＝數字），與 `cmp` 另一側的型別檢查合併。

### 5.2 `mark` 輸出（`then`）

| 鍵 | 說明 |
|---|---|
| `badge` | **分段陣列**（不是範本字串）：`{"t":"text","v":"…"}` 純文字段、`{"f":"欄位id","fmt":"格式化器"}` 欄位值段。**沒有大括號範本、沒有解析**；欄位段只能引用**檢視者可見**且 `ops.tooltip`/顯示許可的欄位（§6.1）；格式化器取自具名格式化器登錄（`pct1`、`money_ntd`、`date10`…）。文字段 ≤ 40 字、整個 badge ≤ 6 段。輸出一律當**純文字**（前端 `textContent`、PDF／Excel 跳脫） |
| `tone` | `info`／`warn`／`crit`（沿用既有色階語彙，由目錄 `tone` 登錄映射到 CSS 類；管理者不寫顏色碼） |
| `target` | `row`｜`cell:<欄位id>`（該欄必須在表面上且對檢視者可見；否則此標記對該人不輸出） |
| `text_red` | 選填布林：把 `target` 儲存格文字標紅（對應今天的『紅字』）；本質是 `tone=crit` 的樣式 |

### 5.3 `block` 輸出

| 鍵 | 說明 |
|---|---|
| `if`／`unless` | 二選一的條件（§4）；內含條件樹 |
| `blocks` | **已註冊動作的代號**（`save`、`transition:<名稱>`、`export:<範本>`…），來自**動作登錄表**（程式提供；與按鈕／選單的動作登錄表是同一份，FIELD-CATALOG §6.3）；未知＝驗證失敗。只能**攔截**，不能代為執行 |
| `message` | 同 `badge` 的分段陣列（固定中性文字＋可見欄位段）；`protective` 規則**只允許純文字段**（§6.3） |

規則對資料與狀態**零寫入**：評估前後資料庫 `total_changes` 不變（測試）。

## 6. 評估：per-viewer、批次、失效

### 6.1 輸入＝檢視者看得到的欄位（威脅模型 §1 / FIELD-CATALOG §5.0）
1. 編譯時算出規則的**輸入欄位集合** `I(rule)`（`when` 內所有欄位＋`expr` 引用＋`then.badge`／`message` 的欄位段）。
2. 對檢視者 `v`：`I(rule)` 中**任何一個欄位 `v` 不可見**（目錄 `visibility`＋表面門檻 AND，FIELD-CATALOG §5.5）⇒ 這條規則對 `v` 的狀態是 **不適用**：不評估、不輸出、不寫任何痕跡、不回『被隱藏』、不計入任何筆數（連 0 都不回）。這**不是 UNKNOWN**。
3. 不適用判定發生在**伺服器**；前端（表單即時評估）只拿到伺服器給的『可評估規則清單』，不可見欄位的值本來就不在回應中。
4. **快取與批次**：以（規則版本，檢視者的**可見欄位集合雜湊**，`today`，**規則引用到的各設定群組的『群組戳記』**）為鍵（r2：設定讀取有 15 秒快取與待生效疊加，只用規則版本會讓門檻過期；戳記＝`settings_registry.group_stamp(group)`＝該群組最新版本＋下一筆待生效的生效時間，由 2b 提供）；列表一次掃描、規則先編譯成評估計畫（每條規則一個閉包樹），每列只跑計畫。**正對照**：admin 先載入含 cost 衍生標記的列表，engineer 接著載入同一列表，不得見到任何由 cost 衍生的標記（98 §3.4b）。
5. **衍生欄位**的可見性＝輸入欄位可見性的交集（FIELD-CATALOG §5.0 末列），故『由成本衍生的欄位』對無成本權限者不適用，規則自動不適用。

### 6.2 付款衍生事實不可作規則輸入
`recv_overdue`、`missing_invoice`、`overdue` 等（FIELD-CATALOG §5.7）`ruleUsable=false`：驗證器拒絕引用（`rule_input_forbidden`）。要『應收逾期』的規則，必須用 `expectedReceiptDate`（目錄欄位，`isMoney=false`）與 `received` 組成，並且**只在 `case_page_readable` 的檢視者適用**（不新增金額旁路）。

### 6.3 保護型阻擋（`protective`）
問題：一條『成本相關的阻擋規則』對**看不到成本**的業務也必須生效（否則業務能送出低毛利單，規則形同虛設），但 6.1 的『不適用』會讓它對業務失效。解法與限制：
- `protective: true` 的 `block` 規則**在伺服器端以『系統檢視者』評估**（可讀真實資料），**只在動作當下**（`save`／`transition`）評估，**不進清單、不批次、不在表單即時評估**。
- 訊息必須是**純文字固定訊息**（無欄位段、無數值、無門檻、不點名哪個欄位）；回應只含規則 `label`（作者寫的中性文字）與 `blocks` 的動作代號。
- 只允許 `mode=block`、單據風險類 `money／legal`，**建立／修改／停用皆屬高影響**（紅色橫幅＋影響範圍＋第二位最高管理者核准＋確認期間；放寬＝停用或調鬆門檻）。
- **已知殘餘**：被擋本身洩漏 1 bit（『這張單的成本相關條件不滿足』）。緩解：①不進清單（無法掃描全部單據）；②每使用者每規則的嘗試速率上限；③稽核每次被擋的動作（誰、哪條規則、哪張單；不記值）；④訊息中性。**是否接受此殘餘由使用者／0d 裁示**（§11 U5）。

### 6.4 失效與降級（98 §3.4b 的落地）
- **失效＝逾時、超預算、評估器例外、`days_between` 格式錯**；**缺值不是失效**（走 UNKNOWN）；除以 0＝該 `expr` 為 NULL（不是失效，**但**登記一次 `rule.div_zero` 計數供儀表）。
- `on_failure = degrade_loud`（預設）：該規則對該次評估視為『不適用』，**同時**：規則橫幅（編輯器可見）、管理員警示（系統中心健康卡）、稽核 `rule.degraded`（去重）；**絕不影響單據存取或儲存**。
- `on_failure = fail_closed`：`block` 規則失效 ⇒ **攔截動作**，訊息點名該規則（『規則「X」目前無法判斷，已先攔下，請聯絡管理員』）。`mark` 規則的 `fail_closed` 無意義＝驗證失敗。
- **引擎不健康（r2）**：這是**規則引擎自己的**狀態，不是脊柱的功能降級。定義＝評估器連續失效率超過門檻、編譯器載入失敗、或資料庫定義無法讀取。處置：①已發布的 `fail_closed` 阻擋規則**維持攔截**（訊息點名『規則引擎目前無法判斷，已先攔下』）；②`degrade_loud` 規則與 `mark` 規則大聲降級；③**絕不**因脊柱的 `feature_enabled=False` 或 `group_status≠open` 而停止評估已發布的 `fail_closed` 規則（§6.5）。
- **break-glass**：`fail_closed` 規則故障時，最高管理者可把**該單一規則**切成 `degrade_loud` 或停用（寫稽核；自動到期或事後第二位核准複核）；`DEFAULTS_ONLY` 模式也解除。
- 金額／法定單據上建立 `block` 時 `on_failure` **必須作者明確選擇**（介面預選 `fail_closed`，選擇寫入變更帳本）。

### 6.5 與脊柱（E-b）的接點與『不可被脊柱降級繞過』（r2）

1. **評估不以 `spine.feature_enabled` 為閘**（衝突修正）：功能狀態用於①編輯器是否列出該表面的規則、②**新發布**是否允許（`planned` 灰色、`hidden` 404／不顯示）、③顯示（徽章）。**已發布的 `block`＋`fail_closed` 規則的評估，在規則引擎健康時一律進行**——與『設定被脊柱隱藏』解耦。測試：把規則所屬功能翻成 `planned`／`hidden`／驗證失敗，已發布的 `fail_closed` 阻擋規則**仍然攔截**（正對照：把評估掛在 `feature_enabled` 上，測試必須紅）；`mark` 與 `degrade_loud` 規則在功能非 open 時**不顯示**（顯示屬功能狀態）但不影響儲存。
2. **引擎層守門（比照 `settings_registry.publish()` 先問脊柱）**：規則的**發布與還原**最前面問 `spine.surface_status(surface)`（目錄 `features[].catalog.surfaces` 繼承功能狀態；2b 提供，約 0.2 pd）；非 `open` ⇒ 發布失敗（`planned`→409『這項功能還在開發中』、`hidden`→404）。**評估端不問**（見 1）。
3. **`alert_rule` 必須是受管 kind**：定義文件庫的通用草稿／發布路由若能直接處理 `alert_rule`，就繞過本文的高影響管線（§6.3）。做法：在 `routers/definitions.py` 的受管 kind 清單登記，並用 2b 提供的 `register_kind_gate(kind, fn)` 讓**列表／讀取**路由也服從 `hidden=404／planned=409`（否則 `GET /api/definitions/alert_rule` 會洩漏 hidden 表面的規則——2b 自己在 r3 被 0d 退過的同一個洞）。路由表守門：每個 kind 要嘛在受管清單、要嘛在明列的低風險直發清單（98 §3.9）。
4. **稽核去重**：`rule.degraded` 沿用 `audit_spine_failures` 的簽名法——`sig = sha1(規則 key + 問題清單)`，以 `json_extract(detail,'$.sig')` 去重（同一失效不重複洪水）；detail 不含欄位值。
5. **健康徽章共用**：系統中心 `system.hub_badge` 每張卡只允許一個提供者。規則降級**不另註冊提供者**，改用 2b 的 `spine.register_health_source(name, fn)` 與脊柱失敗合併成同一個徽章（『N 項功能登錄未通過驗證／N 條規則降級』）；不在 `settings-center` 卡上註冊第二個提供者。
6. **驗證器掛鉤**：規則驗證器以 `spine.register_validator(name, fn, covers=(…))` 登記；除本文的文法檢查外，額外規則：`{"setting": …}` 指向 `planned／hidden` 群組 ⇒ 發布 **422（通用訊息『這個設定目前無法使用』，絕不說 hidden）**。
7. **誰提供什麼（2b 估）**：`register_kind_gate`（~0.25 pd）、`spine.register_health_source`、`spine.surface_status`（~0.2 pd）、`loosen="both"`（~0.1 pd）、`settings_registry.group_stamp`——在 E-b 出貨後插入；本文不重複實作，只引用其介面。

## 7. 上限（寫死上界；管理者只能調小）

| 項 | 上界 | 超過時 |
|---|---|---|
| 規則定義 JSON 大小 | 8 KB（**在 `json.loads` 之前**檢查位元組數） | 驗證失敗 |
| 樹節點數 | 200 | 驗證失敗 |
| 樹深度 | 8（`formula.MAX_DEPTH` 的 30 在規則 profile 降為 8） | 驗證失敗 |
| `expr` 長度／AST 節點／深度 | 200 字／60 節點／6 層 | 驗證失敗（`ast.parse` 之前先檢字數） |
| `in.set` 元素 | 32 | 驗證失敗 |
| 每表面規則數 | 50 | 發布失敗 |
| 單條規則單次評估 | 20 ms 與 **節點評估次數**上限（deterministic 的 tick 計數，避免只靠牆鐘不可重現） | 失效（§6.4） |
| 單次批次（一頁清單）總預算 | 例：頁大小 × 規則數 × 平均節點的上界（由 tick 總量限制）＋ 150 ms 牆鐘 | 該批次降級：未評估完的規則整批『不適用』並大聲降級 |
| `badge`／`message` | 段數 ≤ 6、文字段 ≤ 40 字 | 驗證失敗 |

實際預設值（20 ms 等）放設定中心『規則』群組（`impact` 說明：只影響效能與降級時機），**管理者只能往更嚴調**；上界在程式內寫死。

## 8. K01（利潤警示）表達為規則；放寬方向由運算子決定

今天的行為（`static/margin-tone.js`）：`pct < 30` ⇒ danger、`pct < 40` ⇒ warning、其餘 success；`null／空字串／0 ⇒ danger`（註解：沿用舊行內算式）。

```json
[
 {"key":"k01_margin_crit","body":{"version":1,"label":"毛利偏低（危險）","surface":"module:case.quotation_list","mode":"mark","severity":"crit","on_failure":"degrade_loud",
   "when":{"any":[ {"is_null":{"field":"direct_margin_pct"}},
                   {"cmp":{"op":"lt","left":{"field":"direct_margin_pct"},"right":{"setting":"profit.margin_crit_pct"}}} ]},
   "then":{"badge":[],"tone":"crit","target":"cell:direct_margin_pct"}}},
 {"key":"k01_margin_warn","body":{"version":1,"label":"毛利偏低（警示）","surface":"module:case.quotation_list","mode":"mark","severity":"warn","on_failure":"degrade_loud",
   "when":{"all":[ {"not_null":{"field":"direct_margin_pct"}},
                   {"cmp":{"op":"lt","left":{"field":"direct_margin_pct"},"right":{"setting":"profit.margin_warn_pct"}}},
                   {"cmp":{"op":"ge","left":{"field":"direct_margin_pct"},"right":{"setting":"profit.margin_crit_pct"}}} ]},
   "then":{"badge":[],"tone":"warn","target":"cell:direct_margin_pct"}}}
]
```
- 預設設定值：`margin_crit_pct = 30`、`margin_warn_pct = 40`（＝今天）。**黃金比對**：對 `null`、`0`、`29.9`、`30`、`39.9`、`40`、`-5` 逐值與 `MotrixMargin.tone` 輸出一致（`is_null` 分支對應今天『缺值＝danger』的行為——這是**舊行為的忠實轉錄**，不是三態的 UNKNOWN 不標記；規則自己用 `is_null` 明確寫出，故不與 §3.3 衝突）。
- **已知的預期差異（黃金比對需明列）**：今天看不到金額的人（遮蔽者）清單裡 `direct_margin_pct` 是 `null`，`MotrixMargin.style(null)` 會把那格『—』上 danger 色（`null < 30` 在 JS 為真）；改成規則後，欄位對遮蔽者**不可見 ⇒ 規則不適用 ⇒ 不上色**。這是§6.1 的預期行為（也消除了『紅色破折號』洩漏『這欄有值且低』以外的雜訊），黃金比對的『遮蔽者』案例應標為**已知差異**而不是回歸。另：鍵完全不存在（`undefined`）今天為 success、規則下為 UNKNOWN ⇒ 不標記，兩者一致。
- **方向表（驗證器依規則的比較運算子推導，不靠設定自己宣告）**：

| 規則裡引用該設定的運算子 | 調高設定 | 調低設定 |
|---|---|---|
| `lt`／`le`（『低於 X 就警示』） | **收緊**（更多警示，即時生效） | **放寬**（走放寬流程） |
| `gt`／`ge`（『高於 X 就警示』） | **放寬** | **收緊** |
| `eq`／`ne`／`between`／`in` 或其他／未知 | **放寬**（任何變動都走放寬流程） | **放寬** |

- **（r2）實作機制**：設定登錄新增 `loosen="both"`（任何數值變動＝放寬、走確認期與雙人核准）。規則發布管線依上表推導：只被 `lt/le` 引用 ⇒ 該設定維持 `loosen="down"`；只被 `gt/ge` 引用 ⇒ `"up"`；多方向或其他運算子 ⇒ `"both"`。
- **同一設定被多條規則以不同方向引用**（例：`margin_crit_pct` 同時出現在 `lt` 與 `ge`——上例 warn 規則就用 `ge`）：設定登錄的方向分類取**較嚴者＝兩個方向都視為放寬**，即任何變更都走確認期（保守）。這與今天 `SettingDef.loosen` 是**單一靜態方向**不同——需要設定登錄新增『方向由引用規則推導』（§11 U3）。
- **正對照測試**：①`lt`→調高門檻＝收緊（即時）；②把規則運算子改成 `gt`，方向必須翻轉；③『把方向互換』的突變使測試變紅；④未知運算子＝放寬。

## 9. `helpers/formula.py` 要改什麼（已實測）

**實測結果（Python 3.11.15，本分支）**：
- `evaluate("not x", {"x": None}) == True`；`evaluate("not (x < 5)", {"x": None}) == True`（因為 `x < 5` 回 `None`、`not None` 為真）→ **不是三態**：用在 `block.if not(...)` 會把『缺值』誤判為『條件成立』。
- `evaluate("x < 5 or y == 1", …)` 的 `and/or` **回傳運算元的值**（Python 語意），不是布林。
- `evaluate("0.1 + 0.2", {}) == 0.30000000000000004` → **浮點**；威脅模型 §1 要求 `Decimal/Fraction`。
- `check(...)` 與 `evaluate(...)` 各自 `ast.parse` 一次（`evaluate` 內先 `check` 再 `_parse`）⇒ 批次評估成本 ×2，且**每次求值都重新解析**。
- 已具備、**不必改**：`MAX_LENGTH = 500`（在 `ast.parse` 之前檢查，順序正確）、`MAX_DEPTH = 30`（`check` 走訪）、巢狀括號 190 層可通過（括號不產生 AST 節點）、`\x00` 回傳 `FormulaError` 而非例外、`-`×400 與 `not `×120 被深度檢查擋下、`**`／屬性／索引／lambda 等被走訪器拒絕、`if` 關鍵字改名技巧。

**要改（規則專用，不影響自訂模組既有行為）**
1. **規則 profile**：`check(expr, fields=…, profile="rule")`——`FUNCTIONS` 收斂為 §5.1 清單（拿掉 `if/sum/total/avg/count`）、禁字串常數與字串 `+`、`MAX_LENGTH=200`、`MAX_DEPTH=6`、新增 **AST 節點上限 60**（目前**只有深度、沒有節點數**上限）。預設 profile 仍是現行值（自訂模組不變）。
2. **編譯一次、求值多次**：新增 `compile_rule(expr, fields, profile) -> Callable[[dict, Tick], Decimal|None]`（一次解析、閉包樹），不經 `evaluate()` 的重解析；`Tick` 提供節點評估計數與牆鐘預算（§7）。
3. **Decimal 運算**：規則求值器內部所有數字轉 `Decimal`（輸入欄位值先 `Decimal(str(v))`，布林排除）；除法用有限精度 `Decimal` context（28 位）並對除以 0 回 NULL。`round` 沿用 `legal_params.round_half_up`。**不改 `formula.evaluate` 對浮點的既有行為**（自訂模組公式依賴它，改動是行為變更）。
4. **三態求值在條件樹層做**（§3），`expr` 只負責算術與函式，因此**不需要**把 `and/or/not` 的三態塞進 `formula.py`——`expr` profile 禁用 `and/or/not/比較`（比較在 `cmp` 節點）。
5. **`$today` 情境常數**：`Name` 節點 `today`（保留字，與 `true/false/null` 同層）解析為 `ctx.today`；`days_between` 的日期輸入沿用現行規則（`_ISO_DAY`、前 10 碼）。
6. **`references()`** 回傳需排除保留字（`today`），已排除 `true/false/null`；加 `today`。
7. **錯誤位置**：沿用 `FormulaError.pos`，樹驗證器回傳 `{"path": "when.all[1].cmp.right", "message": …}`（JSON 路徑）給編輯器標示。
8. 抽出走訪器共用常數（`_BIN`、`_CMP`），讓 profile 以參數選擇，**不複製一份走訪器**（避免兩套白名單分叉；守門：測試斷言 rule profile 的允許集合 ⊆ 預設集合）。
- 工量（含於 §0-10）：①②③⑤⑥⑦⑧ 約 1.0 pd；樹驗證器與求值器另計。

## 10. 八條範例規則（取自今天寫死的 11 處；FIELD-CATALOG §2.3）

| # | 來源（今天） | 規則（摘要） | 備註／前置 |
|---|---|---|---|
| R1 | A3 毛利率標色（`margin-tone.js` 30／40）— 兩條 | §8 的 `k01_margin_crit`／`k01_margin_warn` | 黃金：7 個邊界值逐值與 `MotrixMargin.tone` 一致 |
| R2 | A2 有效天數 >30 紅字『需審核』 | `valid_days gt 30` ⇒ `mark`／`crit`／`badge:[文字「需審核」]`／`target: cell:valid_days` | 與簽核原因 `compute_approval_reasons` 同源：**顯示可資料化，簽核判定仍是程式**；`valid_days` 缺值＝不標（今天 `q.valid_days > 30` 對 undefined 為 false，一致） |
| R3 | A1 草稿停留 | `lifecycle in [draft]` AND `days_between(updated_at, $today) gt 30` ⇒ `crit`；`gt 7` 且 `le 30` ⇒ `warn`（兩條） | **前置**：`lifecycle`（草稿／送審…）目前是前端 `lifecycleOf(q)`（`derived_ui`）；必須先在目錄搬成後端 `computed` 欄位，否則不得作規則輸入（FIELD-CATALOG U4） |
| R4 | A1/A10 送審停留 | `lifecycle in [review]` AND `days_between(updated_at, $today) ge 4` ⇒ `crit`；`ge 2` 且 `lt 4` ⇒ `warn` | 同上；與簽核佇列『同一組門檻』（程式註解自述）→ 共用同一個設定引用 |
| R5 | A5 營業利益率 <12 紅、<20 黃 | `net_margin_pct lt {setting: net_margin_crit}`（預設 12）⇒ crit；`lt 20` 且 `ge 12` ⇒ warn | `TARGET_MARGIN_PCT = 12` 在 `helpers/profit_rules.py`／`profit-rules.js` 兩處；成為設定後兩處都讀設定（單一來源） |
| R6 | A9 專案毛利提醒 | `project_margin_pct lt {setting: project_margin.warn_pct}` AND `{setting} gt 0` ⇒ warn | 已有設定 `project_margin.warn_pct`（預設 0＝不提醒）；**『設定>0 才生效』用 `cmp gt 0` 表達**（設定引用可作 `left`）|
| R7 | A8 應收預定日已過 | `received eq false` AND `expectedReceiptDate lt $today`（`expr` 不需要；日期 `cmp` 與 `ctx`）⇒ warn／`target: row` | 輸入皆非金額欄；只對 `finance_access` 且 `case_page_readable` 者適用；**不得**使用 `recv_overdue`（§6.2） |
| R8 | A11 稅率 <5 需核准 | `tax_rate lt 5` AND `not_true(approval_status eq "approved")` ⇒ warn／`target: cell:tax_rate` | `approval_status` 需為目錄欄位（今天 `q.approval?.status === 'approved'` 在前端）；〔待核：法定稅別單的顯示條件是否另有 `taxType` 分支〕 |

每條都有**黃金比對**：對一組固定樣本單據，規則輸出（有無標記、tone）與今天前端函式輸出**逐筆相同**；不同＝遷移紅燈（98 §5-2）。

## 11. 測試計畫（每項都有正對照）

| # | 測試 | 正對照（必須紅的突變） |
|---|---|---|
| T1 | **文法拒絕清單**：`__import__`、屬性、下標、lambda、f-string、`{{ }}`、`${ }`、字串運算、`**`、未知函式、`if/sum/total/avg/count`（規則 profile）、超長、深度 +1、節點 61、JSON 8 KB+1、未知 JSON 鍵、未知節點 → 全部驗證失敗 | 把其中一個加進白名單 ⇒ 必須紅 |
| T2 | **三態真值表**：AND／OR／NOT 的 27 格；各運算子 NULL ⇒ U；`is_null`／`not_null` 兩態；`is_true`／`not_true`；`between` 保守 U | 把 `NOT U` 改成 T ⇒ 紅；把 `between` 改成短路 ⇒ 紅 |
| T3 | **`unless` vs `if not`**：缺值案例兩者結果相反（擋／不擋） | 把 `unless` 實作成 `if not` ⇒ 紅 |
| T4 | **Kleene 定律的性質測試**（De Morgan、交換、結合、雙重否定在 U 上的行為）隨機產生樹，與參考實作（三值查表）逐值比對 | 換成 Python 的 `and/or/not` ⇒ 紅 |
| T5 | **短路等價**：短路與全評估結果相同 | 讓短路改變結果 ⇒ 紅 |
| T6 | **Decimal 精確**：`0.1 + 0.2 eq 0.3` ⇒ T；`round` 平手遠離零；專案毛利進位後比較（顯示值與規則一致） | 換浮點 ⇒ 紅 |
| T7 | **預算**：最大節點／最大深度規則集、百萬列模擬 ⇒ 延遲有上限、超限降級不拋 500；tick 計數可重現 | 移除預算 ⇒ 逾時而紅 |
| T8 | **失效模式**：逾時／例外 ⇒ `degrade_loud`：不影響存檔、有警示與稽核；`fail_closed` ⇒ 存檔被拒且訊息點名該規則；break-glass 生效並有稽核；缺值**不**觸發降級 | 把缺值當失效 ⇒ 紅 |
| T9 | **per-viewer 不洩漏**：5 角色×全部範例規則；engineer／無成本權限者的回應**位元組**中不得出現由成本衍生的標記、rule id、label、筆數；admin 先載入再換 engineer（快取鍵） | 把快取鍵拿掉可見集合 ⇒ 紅；把成本欄標成 sales 可見 ⇒ 紅 |
| T10 | **不適用≠UNKNOWN**：隱藏輸入的規則不評估；缺值輸入的規則走 U；兩者回應不同 | 把隱藏當 U ⇒ 紅 |
| T11 | **保護型阻擋**：低毛利單對無成本權限的業務送出被擋；訊息不含任何數值／欄位名；不出現在清單；嘗試速率上限；稽核 | 讓訊息夾帶門檻 ⇒ 紅；讓它進清單批次 ⇒ 紅 |
| T12 | **零寫入**：評估前後 `total_changes` 不變；規則不能呼叫通知／API | 加一個寫入 ⇒ 紅 |
| T13 | **篡改**：規則 JSON 被直接改庫（超大小、未知鍵、未知版本、引用不存在欄位） ⇒ 載入時重新驗證、失敗＝**不載入並大聲警示**、其他規則照常 | 略過載入時驗證 ⇒ 紅 |
| T14 | **八條範例黃金**（§10）逐筆與今天前端輸出一致；K01 七個邊界值 | 改門檻 1 ⇒ 紅 |
| T15 | **K01 方向**（§8）四項 | 方向互換 ⇒ 紅 |
| T16 | **靜態守門**：評估器模組不得 import `eval/exec/compile/importlib/subprocess/os.system`；規則 profile 允許集合 ⊆ 預設集合（不分叉） | 加一個 `eval` ⇒ 紅 |
| T17 | **輸出純文字**：`badge`／`message` 含 `<img onerror>` ⇒ 前端以 `textContent` 渲染、PDF／Excel 跳脫；前端禁用 `innerHTML` 於使用者定義字串的靜態掃描 | 加一處 `innerHTML` ⇒ 紅 |
| T18 | **目錄一致**：規則引用 `ruleUsable=false` 或 `derived_ui` 欄位（含 §6.2 付款衍生事實）⇒ 驗證失敗 | 放行一個 ⇒ 紅 |
| T19 | **定義治理**：規則改動只能發布新版、單據凍結版本、放寬走高影響管線（門檻調鬆、停用保護規則） | 允許就地改 ⇒ 紅 |

## 12. 與 98 r16 §3.4b、0d 威脅模型 §1／§5 的對齊對照

| 98 §3.4b／§3.1／§3.2 | 本文 |
|---|---|
| 宣告式、無程式碼、動作目錄有限 | §0-1／§5.3（`blocks` 取動作登錄表）、T1、T16 |
| 規則輸出只有標記／阻擋；通知不是規則輸出 | §0-4、§5 |
| 標記結果是每位檢視者的；快取鍵含可見欄位集合 | §6.1、T9 |
| 失效模式 `mode`／`on_failure`、缺值不是失效、預設 `degrade_loud`、金額阻擋由作者明選、break-glass | §1 表、§6.4、T8 |
| 三態：標記 U＝不標；`除非 X`：U ⇒ 擋；`若 Y`：U ⇒ 不擋；每運算子 U 行為登記 | §3.2／§3.3／§4、T2／T3 |
| 長度先限制再解析；規則／簽核條件／浮水印共用一份驗證器 | §5.1／§7、§9-8；**共用驗證器**＝同一個走訪器 + profile（簽核條件與浮水印占位另用不同 profile，但允許集合 ⊆ 預設集合） |
| K01 方向由運算子決定 | §8、T15 |
| 威脅模型 §1：純函式、無迴圈、白名單函式、Decimal/Fraction | §5.1／§9-3 |
| 威脅模型 §1：以執行者角色求值、看不到的欄位不評估且不回訊號 | §6.1、T9／T10 |
| 威脅模型 §1：評估預算、節點／深度／逾時、超過＝未命中並稽核 | §7、§6.4 |
| 威脅模型 §1：輸出型別固定；阻擋只能更嚴；放寬走流程 | §5、§6.3、T19 |
| 威脅模型 §1：`live_impact`（顯示會影響多少既有單據，唯讀預覽） | 發布前試跑（98 §3.5）；本文未另設計，介面：`dry_run(rule, last_n)` 回命中數與（有權限者可見的）樣本 |
| 威脅模型 §5：所有讀取衍生操作先與可見欄位取交集；對不可見欄位的請求 ⇒ 400 | FIELD-CATALOG §5.0；規則對不可見欄位『不適用』而不是 400（規則是定義不是請求；**定義作者引用自己看不到的欄位 ⇒ 發布時 422**，§6.1 之外的另一道門） |

## 13. 未知事項（逐項；★＝影響排程）

| # | 未知／決定 | 影響 | 建議／需誰 |
|---|---|---|---|
| ★U1 | 條件樹 JSON vs 文字運算式作為**儲存形式** | 編輯器、驗證器、攻擊面 | 本文建議樹（§0-1）；需 98／0d 確認；`expr` 葉是否值得保留（可降為只許 `field/const/setting/ctx`，把算術全部放進目錄 `computed` 欄位——更保守但每個新算術都要程式登記） |
| U2 | `ctx.today` 的時區與『同一批次固定』的實作 | 午夜附近的清單一致性 | 沿用 `MotrixDate`／伺服器本地日期；批次開始時取一次 |
| ~~★U3~~ 已有解法（2b） | 設定登錄的 `loosen` 是 `"up"｜"down"` 靜態單向；§8 需要多規則多方向取較嚴 | — | **採 `loosen="both"`**（任何數值變動都視為放寬，約 0.1 pd，2b 在 `_split／plan／banner_of` 內加）；規則發布管線把『被規則引用的門檻』的 `loosen` 設/驗為 `both`（多方向或未知運算子時）；單一明確方向（只被 `lt/le` 引用）可維持 `down`。註：設定登錄型別只有 `int／float／bool／str`（沒有 percent／money 型別；百分比用 `float`＋`unit`）、`choices` 必須整數代碼（E-f）、鍵是 `<群組>.<欄位>` 扁平欄位——§2.2 的 `{"setting": …}` 型別檢查以此為準 |
| U4 | `lifecycle`、`approval_status` 等 `derived_ui` 欄位搬後端 | R3／R4／R8 無法在前置完成前遷移 | FIELD-CATALOG U4 同一件事；先遷 R1／R2／R5／R6／R7 |
| ★U5 | 保護型阻擋的 1 bit 殘餘是否接受 | 沒有它，業務可繞過成本相關阻擋；有它，洩漏『被擋了』 | 建議接受＋§6.3 緩解；**需使用者與 0d 裁示**；備案：保護型阻擋只允許引用『檢視者可見』欄位（等於放棄保護成本相關條件） |
| U6 | 條件樹是否允許跨表面引用（例：案件頁規則引用報價單欄位） | 欄位可見性有兩道門（表面門檻 AND 欄位） | v1 不允許；規則只能引用**同一表面**目錄 |
| U7 | `block` 規則與簽核引擎的關係（『低毛利須主管核准』） | 阻擋≠要求核准；後者是簽核政策 | v1 `block` 只攔截並顯示訊息；『要求核准』屬簽核政策（t55），不在規則內（FIELD-CATALOG U12） |
| U8 | 同一欄位多條規則的排序／衝突（兩條都標 tone） | 顯示一致性 | 以 `severity` 取最高；同層以規則 key 排序；文字訊息並列（上限 3 則，其餘『還有 N 項』） |
| U9 | 規則 label／badge 文字的在地化與長度 | 純顯示 | 不做在地化；長度 ≤40 |
| U10 | 工量 6.5 pd 未經原型驗證 | ±30% | 先做 T1／T2／T6 三組測試驅動的最小核心（0.5 pd）驗證三態與 Decimal 的實作成本 |
| U11 | 表單層級（`save` 前）的即時評估要不要有前端孿生 | 與專案毛利% 同做法（前後端共用黃金向量） | 需要；工量併入 BP-2 的編輯器，不在本文 6.5 pd |

## 14. 來源
- 程式：`backend/helpers/formula.py`（全檔；§9 的實測數字為本分支 Python 3.11.15 實跑）、`frontend/static/margin-tone.js`（K01 色階與缺值行為）、`frontend/pages/quotations.html`（`agingOf`、有效天數『需審核』）、`quotation-form.html`（品項『需審核』、營業利益率色階）、`backend/helpers/profit_rules.py`（`TARGET_MARGIN_PCT`）、`backend/modules/arap/api/cashier.py`（`overdue`）、`backend/modules/case/api/quotations.py`（`_CASE_RECV_OVERDUE_SQL`）。
- 文件：`PLATFORM-BUILDER-ARCHITECTURE-T57.md` §3.1／§3.2／§3.4／§3.4b／§3.5／§4；`USER-DEFINED-LOGIC-THREAT-MODEL.md` §1、§5；`FIELD-CATALOG-SEED-T57.md` r3 §2.3、§5.0、§5.5、§5.7、§6.2、§6.3。
