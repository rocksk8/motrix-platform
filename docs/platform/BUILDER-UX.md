# 模組建構器：拖曳式、縮圖化（BUILDER-UX）

> 2026-09-27 B 起草（主持派工，使用者裁示）；主持核准 61d41921（縮圖 8 格方案），補防線主次與焦點驗收兩點。範圍：`frontend/pages/module-builder.html`（B）＋`frontend/static/form-preview.js`（A）＋`custom-records.html` 的預覽掛鉤（A，主持裁示 A 為該掛鉤檔主）。**下一版上**；D7 與這次換版照現行版本走。
> 使用者原話：「在構築的時候就即時預覽，欄位階段就已經有預覽，用拖曳拉 icon 跟文字的頁面直接進去製作表單，流程讓使用者更為簡易」。

## 0. 現況（盤點，e21b099a）

- 已有 6 步：1 基本、2 欄位、3 版面、4 流程（簽核與通知在同一步內）、5 輸出、6 發布；每步 `<section id="mb-step-N">`，導覽 `.mb-step[data-step=N]`。
- 第 2 步**已經**是原生 HTML5 拖曳（`#mb-palette`→`#mb-canvas`，`#mb-props` 屬性面板、↑↓✕ 按鈕）；欄位型別**只**來自 `GET /api/custom-modules/catalog`（text、number、date、select、checkbox、formula、ref），頁面不准有備用清單（既有守門）。
- 第 3 步「表單預覽」只是型別名稱的佔位；執行期表單在 `custom-records.html`（inline Alpine 模板，`formSections(def)`）。
- 既有 e2e（`test_e2e_p8_module_builder`、`test_e2e_p8_gaps`）依賴上述 id／`data-*` 與步驟編號 ⇒ **這次保留所有既有鉤子**（見 §5），換的是版面與操作，不是資料。

## 1. 畫面（第 2 步「欄位」為例）

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 模組：借用登記  [已儲存 ✓]                                             [發布 ▸] │
│ ┌基本┐ ┌欄位┐ ┌版面┐ ┌流程┐ ┌簽核┐ ┌通知┐ ┌輸出┐ ┌發布┐   ← 縮圖導覽（每格一張小圖＋紅點＝有問題）│
│ └────┘ └▀▀▀▀┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘                        │
├───────────────┬──────────────────────────────────┬───────────────────────────┤
│ 欄位工具列     │ 畫布（表單長這樣，照順序）          │ 即時預覽（執行頁本身）       │
│ ┌──────────┐  │ ┌──────────────────────────────┐ │ ┌───────────────────────┐ │
│ │ Aa 文字  │  │ │ ⠿ Aa 品名 *        [必填☑][✕]│ │ │ 品名 *  [__________]  │ │
│ │ 12 數字  │  │ ├──────────────────────────────┤ │ │ 數量    [____]        │ │
│ │ 📅 日期  │  │ │ ⠿ 12 數量          [必填☐][✕]│ │ │ 金額    =數量*單價    │ │
│ │ ☰ 選單  │  │ │   ▾ 更多：代號／預設／公式…    │ │ │ …                     │ │
│ │ ☑ 勾選  │  │ ├──────────────────────────────┤ │ │ （選中的欄位加框）      │ │
│ │ ƒx 公式 │  │ │   ＋ 拖到這裡，或在左邊按 Enter │ │ └───────────────────────┘ │
│ │ ↗ 參照  │  │ └──────────────────────────────┘ │ [表單 | 列表]               │
│ └──────────┘  │                                  │                           │
└───────────────┴──────────────────────────────────┴───────────────────────────┘
```

- 左：**工具列**＝catalog 的每個型別一格（icon＋文字；icon 為 inline SVG，型別對 icon 的對照寫在頁內，catalog 多出沒對照的型別 ⇒ 通用 icon，照樣可用）。
- 中：**畫布**＝欄位卡片，卡片上就地改「標籤」「必填」；「▾ 更多」展開代號、預設值、公式、參照目標、選項、資料分類（沿用 `#mb-f-*` 那組控制項，只是放進選中的卡片裡）。
- 右：**即時預覽**＝A 的 `MotrixFormPreview.render()`（iframe 內就是 `custom-records.html` 的新增表單／列表）；畫布選中哪個欄位，預覽就框起來並捲到那裡。
- 其他步驟同一個三欄骨架：左邊換成該步的「可加入的東西」（狀態、轉換、簽核層、通知對象、輸出區塊），右邊是該步的預覽或縮圖。

## 2. 互動流程

1. 首頁輸入代號 → 開啟（不變）。
2. **欄位**：從工具列拖到畫布（插在放下的位置）或按 Enter 加到最後 → 卡片就地打標籤、勾必填 → 右邊預覽 700 ms 內跟著變（沿用草稿自動存的節流）。
3. **排序**：拖卡片的 ⠿ 把手；鍵盤：卡片聚焦後 `Alt+↑／Alt+↓` 移動、`Delete` 刪除（有確認）、`Enter` 展開「更多」。既有 ↑↓✕ 按鈕保留（e2e 與觸控用）。
4. **縮圖導覽**：8 格（基本、欄位、版面、流程、簽核、通知、輸出、發布）。「流程／簽核／通知」三格都對應既有第 4 步，點下去捲到同一步裡的對應區塊（§5 相容）。縮圖由 A 的 `thumb()` 畫；有驗證問題的步驟縮圖角上一個紅點（沿用 `problems[].path` → `stepOf`）。
5. **發布**：不變（`#mb-publish`、差異、版本、還原）。

鍵盤替代（使用者裁示「拖曳一定要有鍵盤替代」）：工具列每格是 `<button>`（Tab 可到、Enter／Space＝加到最後）；畫布卡片 `tabindex=0`、`role="listitem"`、`aria-grabbed`；移動後以 `aria-live` 念出「數量 移到第 2 個」。

## 3. A／B 介面約定

### 3.1 草稿 JSON（原樣沿用，後端 schema 不動）

```
{ name, icon, menu:{group,order}, permission:'custom.<key>',
  numbering:{prefix, date:'YYYYMMDD'|'YYYYMM'|'', digits:3-8},
  fields:[{key, label, type, dataClass:'T1', required:bool, default?, options?[], formula?, target?}],
  workflow:{initial, states:[{key,label,final?,notify?:{requester?,users?[]},
            approval?:{tiers:[{approvers:[{username,displayName,userId}|{sourceType,departmentId|divisionId}], when?}],
                       on_approved,on_rejected}}],
            transitions:[{key,label,from:str|[str],to,requester_only?}]},
  ui:{form:{groups:[{title,fields:[key]}]}, list:{columns:[key]}},
  output?:{template:{key,version,theme,title:{path,suffix},blocks:[{type,...params}]}} }
```

- 建構器傳給預覽的就是 `def` 本身（深拷貝），不另轉格式。

### 3.2 預覽元件（A，`frontend/static/form-preview.js`，無框架、無 CDN）

- `MotrixFormPreview.render(el, draft, {mode:'form'|'list', highlight:fieldKey})` ⇒ `{update(draft), setHighlight(key), destroy()}`。
- `MotrixFormPreview.thumb(el, draft, {step:'fields'|'layout'|'workflow'|'approval'|'notify'|'output'})`：`workflow／approval／notify／output` 用純函式 inline SVG 從 draft 畫（可單獨測）；`fields／layout` 用縮小的預覽 iframe。
- 做法：`render()` 在 `el` 裡放 `<iframe src="/pages/custom-records.html?preview=1" sandbox="allow-scripts allow-same-origin">`，以 postMessage 傳訊息：
  - 父 → 子：`{type:'motrix-preview', v:1, kind:'draft', draft, mode}`、`{…, kind:'highlight', field}`
  - 子 → 父：`{type:'motrix-preview', v:1, kind:'ready'}`、`{…, kind:'height', px}`
- 未知欄位型別 ⇒ 佔位「此型別尚無預覽」，不丟例外；預覽只讀、不存檔。

### 3.3 預覽模式的約定（主持裁示，A 為 `custom-records.html` 預覽掛鉤檔主，B 不動該檔）

1. postMessage **只接受同源**（`event.origin === location.origin`），而且只收 §3.2 格式的訊息（`type`、`v`、`kind` 對得上）；其他一律忽略。
2. 預覽模式在**程式層面**不打任何 API——讀取與寫入都不打，由**同一個旗標**擋住（不是只把按鈕藏起來）；參照欄的選項顯示空白佔位。
3. 預覽模式只由建構器的 iframe 開啟：iframe 加 `sandbox="allow-scripts allow-same-origin"`（**不給** forms、**不給** top-navigation）；直接開 `?preview=1` 也不會有資料外流（本來就不打 API）。
4. 非預覽模式的行為完全不變：既有 custom-records 的題全過。

⚠️ **防線的主次**（主持 2026-09-27）：sandbox 同時給 `allow-scripts` 與 `allow-same-origin` 時，被框的頁可以自行解除 sandbox——這裡框的是我們自己的頁，**真正的防線是第 2 條（預覽模式在程式層面不打 API）**，sandbox 只是第二道，不可以被當成主要防線。

## 4. 限制

- 後端 schema 盡量不動；要動只准新增（CORE 次版號）。本設計**不需要**動後端。
- 前端不准用 CDN。拖曳用原生 HTML5（repo 裡已有 SortableJS 1.15.3，但 e2e 的 `drag_and_drop` 送的是真的 HTML5 事件，`#mb-canvas` 的原生 drop 必須保留；**不引入**新函式庫）。icon 用 inline SVG，不用圖示字型。
- 不新增 `x-data`＋`x-init` 的頁（`PAGE_POPULATION` 不變）；`_initDone` 守衛保留。
- 欄位型別、輸出區塊等**只**來自 catalog（既有守門），icon 對照缺漏 ⇒ 通用 icon，不是不顯示。

## 5. 相容：保留的鉤子（既有 e2e 照過，不改題）

- `#mb-step-1..6`、`.mb-step[data-step=1..6]`：縮圖導覽的 8 格帶 `data-step`（流程／簽核／通知三格都是 4）＋`data-anchor`；`.mb-step[data-step="4"]` 仍只有一個可點的主格（另兩格用 `data-step-alias`，避免選擇器多抓）。
- `#mb-palette [data-palette-type=…]`（點一下＝加到最後、可拖）、`#mb-canvas`（原生 drop）、`.mb-fc[data-field-index][data-field-key]`（`.is-sel`、`.is-bad`）。
- `#mb-f-key／label／required／default／formula／target`、`#mb-f-formula-problems`：搬進選中卡片的「更多」裡，**id 不變**、選中卡片時一律展開（e2e 直接 fill）。
- 第 3～6 步的所有 id 與 `data-*`（`#mb-add-group`、`#mb-states`、`[data-approval-state]`、`#mb-out-editor`、`#mb-publish`…）照舊。

## 6. 驗收條件

1. 既有 `test_e2e_p8_module_builder`、`test_e2e_p8_gaps`（含 D4：網頁上建自訂模組 → 送審 → 核准 → 匯出）**不改題**照過；`test_alpine_double_init`、catalog-only 守門照過。
2. 新 e2e（B）：
   - 工具列每個 catalog 型別都有 icon＋文字，而且可以拖、也可以 Enter 加入；
   - 鍵盤：Tab 到卡片、`Alt+↓` 移動 ⇒ `fields` 順序改變並存進草稿，驗 DB；`Delete` 經確認刪除；
   - 就地改標籤、必填 ⇒ 草稿 DB 的 `fields[i].label／required`（布林）正確；
   - 即時預覽：加一個欄位 ⇒ 預覽 iframe 內 `[data-field=<key>]` 出現；選中卡片 ⇒ 預覽裡該欄位被框起；
   - 縮圖導覽：8 格都在；流程／簽核／通知三格捲到第 4 步的對應區塊；有問題的步驟有紅點（`data-has-problems`）。
   - **預覽更新不搶焦點、不蓋掉輸入中的值**（主持 2026-09-27；〈先渲染再非同步載入＝競態〉）：在畫布卡片的標籤欄連續打字（中間預覽會重畫），最後焦點仍在該欄、值完整（驗 DOM 與草稿 DB）；A 的 `update()` 不 focus iframe、不重建 iframe、ready 前只留最後一份 draft。
3. 預覽模式（A）：攔截所有 fetch，預覽模式下呼叫次數 **0**；存檔按鈕無效；非同源或格式不對的訊息被忽略；改執行期模板 ⇒ 預覽跟著變；iframe 帶 sandbox 且沒有 forms／top-navigation。
4. 無 CDN、無新函式庫；`frontend/static/form-preview.js` 與改過的頁都在 repo 內；⓪ 自查 §G5 全項未中（#3 色碼用 token、#9 e2e 驗 DOM 與 DB、等終點）。

## 7. 分工與順序

- A：`form-preview.js`（render、thumb）＋`custom-records.html` 預覽掛鉤＋§6-3 的題。
- B：`module-builder.html` 版面與操作（工具列、畫布就地編輯、鍵盤、縮圖導覽、接 A 的預覽）＋§6-1、6-2 的題。
- 介面先定（本檔 §3），兩邊並行；B 在 A 的元件合回前用 `MotrixFormPreview` 不存在時的佔位（顯示「預覽元件尚未載入」），不擋 B 的題。
