# 模組建構器：拖曳式、縮圖化（BUILDER-UX）

> 2026-09-27 B 起草（主持派工，使用者裁示）；主持核准 61d41921（縮圖 8 格方案），補防線主次與焦點驗收兩點。範圍：`frontend/pages/module-builder.html`（B）＋`frontend/static/form-preview.js`（A）＋`custom-records.html` 的預覽掛鉤（A，主持裁示 A 為該掛鉤檔主）。**下一版上**；D7 與這次換版照現行版本走。
> 使用者原話：「在構築的時候就即時預覽，欄位階段就已經有預覽，用拖曳拉 icon 跟文字的頁面直接進去製作表單，流程讓使用者更為簡易」。

## 0. 現況（盤點，e21b099a）

- 已有 6 步：1 基本、2 欄位、3 版面、4 流程（簽核與通知在同一步內）、5 輸出、6 發布；每步 `<section id="mb-step-N">`，導覽 `.mb-step[data-step=N]`。
- 第 2 步**已經**是原生 HTML5 拖曳（`#mb-palette`→`#mb-canvas`，`#mb-props` 屬性面板、↑↓✕ 按鈕）；欄位型別**只**來自 `GET /api/custom-modules/catalog`（text、number、date、select、checkbox、formula、ref），頁面不准有備用清單（既有守門）。
- 第 3 步「表單預覽」只是型別名稱的佔位；執行期表單在 `custom-records.html`（inline Alpine 模板，`formSections(def)`）。
- 既有 e2e（`test_e2e_p8_module_builder`、`test_e2e_p8_gaps`）依賴上述 id／`data-*` 與步驟編號 ⇒ **這次保留所有既有鉤子**（見 §5），換的是版面與操作，不是資料。〔更正 2026-09-27 23:05：第二輪（§8）使用者改了操作方式，主持允許改綁著第 3 步的題，逐題寫明原因；D4 驗收的行為照過〕

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
4. **縮圖導覽**：~~8 格（基本、欄位、版面、流程、簽核、通知、輸出、發布）~~〔更正 2026-09-27 23:05（§8）：7 格——基本、表單、流程、簽核、通知、輸出、發布〕。「流程／簽核／通知」三格都對應既有第 4 步，點下去捲到同一步裡的對應區塊（§5 相容）。縮圖由 A 的 `thumb()` 畫；有驗證問題的步驟縮圖角上一個紅點（沿用 `problems[].path` → `stepOf`）。
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

**notif.js 的第一道要另開一頁量**（B，2026-09-28）：預覽頁的第三道先把 `window.fetch` 定成不可寫，notif.js 沒讓位時的包裝只會靜默失敗 ⇒ 在預覽頁上量不出來（D 23:52 突變存活）。改以同源空白頁、不裝第三道、只設旗標載入 notif.js，量 `window.fetch` 有沒有被換掉：`test_e2e_notif_preview_stand_down_2026_09_28`（正對照：不設旗標就會被換掉）。

⚠️ **防線的主次**（主持 2026-09-27）：sandbox 同時給 `allow-scripts` 與 `allow-same-origin` 時，被框的頁可以自行解除 sandbox——這裡框的是我們自己的頁，**真正的防線是第 2 條（預覽模式在程式層面不打 API）**，sandbox 只是第二道，不可以被當成主要防線。

### 3.4 輸出預覽（A，使用者 8866 試用回饋；wip/a-builder-output）

- `MotrixFormPreview.render(el, draft, {mode:'output', key})` ⇒ 同一組 `{update, setHighlight, destroy}`（`setHighlight` 在輸出是 no-op）。可與 `list` 實例同頁並存、各自更新。
- 內容來自既有的只讀端點 `POST /api/custom-modules/{key}/output/preview`（僅超級管理員；不寫庫、不存檔），後端用**正式匯出同一個 renderer**（`render_view`）與同一份版型畫 HTML——預覽沒有自己的一份。
- 邊拖邊看：編到一半的草稿照畫。未完成的欄位（沒有 key、公式空白／錯誤、選單沒有選項、型別不認得…）在輸出裡是「〈名稱〉尚未完成」，清單在回應標頭 `X-Motrix-Preview-Incomplete`，元件顯示在 `.fp-output__note`（`li[data-field]`）。只有連一個欄位都畫不出來、或版型結構錯（未知積木／主題）才 422；422 時保留上一次的畫面並說明原因。任何半成品都不會 500（兜底 422，log／回應不帶草稿內容與 stack）。
- 請求：同一時間一個，途中的草稿只留最後一份；`update` 不重建 iframe、不搶焦點。
- iframe `sandbox="allow-same-origin"`（**不給** scripts）。⚠️ **已知取捨**：正式輸出內建「內容超過 A4 一頁就縮放」的小腳本，在預覽裡不執行 ⇒ **內容超過一頁時，預覽不縮放**（正式輸出／PDF 會縮），其餘相同。理由：同時給 scripts 與 same-origin 等於可以自行解除 sandbox。

## 4. 限制

- 後端 schema 盡量不動；要動只准新增（CORE 次版號）。本設計**不需要**動後端。
- 前端不准用 CDN。拖曳用原生 HTML5（repo 裡已有 SortableJS 1.15.3，但 e2e 的 `drag_and_drop` 送的是真的 HTML5 事件，`#mb-canvas` 的原生 drop 必須保留；**不引入**新函式庫）。icon 用 inline SVG，不用圖示字型。
- 不新增 `x-data`＋`x-init` 的頁（`PAGE_POPULATION` 不變）；`_initDone` 守衛保留。
- 欄位型別、輸出區塊等**只**來自 catalog（既有守門），icon 對照缺漏 ⇒ 通用 icon，不是不顯示。
- `custom-records.html` **不准** `x-html`（含 `x-bind:innerHTML`、`:innerHTML`）：這一頁畫的全是使用者自訂內容（標籤、說明、選項、紀錄值；預覽時是編到一半的草稿）⇒ 一律 `x-text`。守門 `test_custom_records_no_x_html_2026_09_28`（正對照：在真頁面植入三種寫法各一處要亮並指出行號；反向控制：字面相近的不算）。
- JS 端的 HTML 寫入點（`document.write`、`.innerHTML =`、`.outerHTML =`、`insertAdjacentHTML`、`:srcdoc`）只准白名單上審過的那幾處（逐處：種類＋所在方法或元素 id，附理由；上限 5 筆；雙向——新的未登記紅、白名單過期也紅）。守門 `test_custom_records_no_js_html_sink_2026_09_28`（A，稽核 AB42-S1；目前兩筆：`openOutput` 的 document.write、`cr-output-frame` 的 sandbox srcdoc）。〔擴大 2026-09-28（D BS1／BO1）：同一守門也掃 `static/form-preview.js`（白名單三筆：輸出預覽 srcdoc、縮圖 paint／destroy 的 innerHTML）與 `static/custom-layout.js`（0 筆），每檔各自上限 5；寫法加 `setHTMLUnsafe`、`createContextualFragment`。中括號寫法、`Object.assign`、`document` 換行接 `.write` 是已知限制（寫在題目 docstring），由稽核讀碼負責〕

## 5. 相容：保留的鉤子（既有 e2e 照過，不改題）

〔更正 2026-09-27 23:05（§8）：第 3 步拿掉 ⇒ `#mb-step-3`、`[data-assign-field]`、`[data-group-field]` 不再存在；改題清單見 §8-5〕

- `#mb-step-1..6`、`.mb-step[data-step=1..6]`〔更正：沒有 3〕：縮圖導覽的 ~~8~~〔7〕格帶 `data-step`（流程／簽核／通知三格都是 4）＋`data-anchor`；`.mb-step[data-step="4"]` 仍只有一個可點的主格（另兩格用 `data-step-alias`，避免選擇器多抓）。
- `#mb-palette [data-palette-type=…]`（點一下＝加到最後、可拖）、`#mb-canvas`（原生 drop）、`.mb-fc[data-field-index][data-field-key]`（`.is-sel`、`.is-bad`）。
- `#mb-f-key／label／required／default／formula／target`、`#mb-f-formula-problems`：搬進選中卡片的「更多」裡，**id 不變**、選中卡片時一律展開（e2e 直接 fill）。
- 第 3～6 步的所有 id 與 `data-*`（`#mb-add-group`、`#mb-states`、`[data-approval-state]`、`#mb-out-editor`、`#mb-publish`…）照舊。

## 6. 驗收條件

1. 既有 `test_e2e_p8_module_builder`、`test_e2e_p8_gaps`（含 D4：網頁上建自訂模組 → 送審 → 核准 → 匯出）**不改題**照過；`test_alpine_double_init`、catalog-only 守門照過。
2. 新 e2e（B）：
   - 工具列每個 catalog 型別都有 icon＋文字，而且可以拖、也可以 Enter 加入；
   - 鍵盤：Tab 到卡片、`Alt+↓` 移動 ⇒ `fields` 順序改變並存進草稿，驗 DB；`Delete` 經確認刪除；
   - 就地改標籤、必填 ⇒ 草稿 DB 的 `fields[i].label／required`（布林）正確；
   - ~~即時預覽：加一個欄位 ⇒ 預覽 iframe 內 `[data-field=<key>]` 出現；選中卡片 ⇒ 預覽裡該欄位被框起；~~〔更正（§8）：右側不再有表單 iframe；改驗輸出＋列表兩個預覽跟著變、畫布與執行頁一致〕
   - 縮圖導覽：~~8~~〔7，§8〕格都在；流程／簽核／通知三格捲到第 4 步的對應區塊；有問題的步驟有紅點（`data-has-problems`）。
   - **預覽更新不搶焦點、不蓋掉輸入中的值**（主持 2026-09-27；〈先渲染再非同步載入＝競態〉）：在畫布卡片的標籤欄連續打字（中間預覽會重畫），最後焦點仍在該欄、值完整（驗 DOM 與草稿 DB）；A 的 `update()` 不 focus iframe、不重建 iframe、ready 前只留最後一份 draft。
3. 預覽模式（A）：攔截所有 fetch，預覽模式下呼叫次數 **0**；存檔按鈕無效；非同源或格式不對的訊息被忽略；改執行期模板 ⇒ 預覽跟著變；iframe 帶 sandbox 且沒有 forms／top-navigation。
4. 無 CDN、無新函式庫；`frontend/static/form-preview.js` 與改過的頁都在 repo 內；⓪ 自查 §G5 全項未中（#3 色碼用 token、#9 e2e 驗 DOM 與 DB、等終點）。

## 7. 分工與順序

- A：`form-preview.js`（render、thumb）＋`custom-records.html` 預覽掛鉤＋§6-3 的題。
- B：`module-builder.html` 版面與操作（工具列、畫布就地編輯、鍵盤、縮圖導覽、接 A 的預覽）＋§6-1、6-2 的題。
- 介面先定（本檔 §3），兩邊並行；B 在 A 的元件合回前用 `MotrixFormPreview` 不存在時的佔位（顯示「預覽元件尚未載入」），不擋 B 的題。

## 8. 第二輪：同一個畫面直接放（2026-09-27 23:05，使用者 8866 試用；主持核准）

> 使用者原話：「模組建構器，我的意思預覽都在同一個頁面，直接放入，現在是切換欄位版面」。

1. **② 欄位＋③ 版面合成 ② 表單**：中間的畫布**就是表單本身**——區塊＝`ui.form.groups`（可新增、改名、拖曳 ⠿ 或 ↑↓ 排序、刪除；刪有欄位的區塊先確認，欄位回到「其他」），
   欄位從工具列拖進某區塊的某個位置（放在卡片上＝插在它前面；放在區塊空白或標題列＝區塊最後），欄位可以跨區塊拖；點欄位就地展開屬性（`#mb-f-*` 不變），`Esc` 收合。
   規則是 `custom-layout.js` 的純函式：`editorSections`（含空區塊，最後一塊是沒分組的「其他」）、`placeField`（回 `{fields, ui}`；`fields` 依畫布順序重排）、`sectionOrder`、`moveGroupTo`。
   **草稿 JSON 格式不變、後端不動**。
2. **右側同時顯示**輸出預覽（A 的 `mode:'output'`，§3.4）與列表預覽（`mode:'list'`，`<details>` 可收合，下方是列表欄位的勾選與順序）；沒有頁籤切換。
   原本的表單 iframe 預覽拿掉（畫布就是表單）。
3. **縮圖導覽 7 格**：基本、表單、流程、簽核、通知、輸出、發布；內部步驟號 1、2、4、5、6（沒有 3），`ui.*` 的問題標回第 2 步。
4. **鍵盤替代照舊**：`Alt＋↑／↓` 在區塊內移動、到邊界移到相鄰區塊（「其他」也算一塊）；`Enter` 展開、`Esc` 收合、`Delete` 刪除；工具列 Enter／點一下＝加到目前選中欄位所在區塊的最後；
   `aria-live` 念「甲 移到「二」第 1 個」。
5. **防漂移（主持條件）**：畫布不是執行頁本身 ⇒ 欄位外觀用執行頁同一套 class 與標記（`.cr-sec／.cr-grid／.cr-f`、`label>span`＋`.req`、`.cr-fx`、`.cr-help`），
   CSS 從 `custom-records.html` 抽到 `css/custom-form.css` 兩頁共用。一致性題 `test_e2e_builder_form_canvas::test_canvas_sections_and_fields_equal_what_the_runtime_form_draws`：
   同一份草稿，畫布（非空區塊）與執行頁（A 的 `render(mode:'form')` 載入的真頁面）逐項相同——區塊標題與順序、欄位順序、標籤、必填、說明、可讀式子；
   突變：改執行頁的必填星號／說明／可讀式子／「其他」標題、改畫布的說明 ⇒ 都紅。
6. **改題**（逐題理由也寫在題目裡）：
   - `test_e2e_p8_module_builder` 的 D4 驗收：「③ 版面」那段從「切到第 3 步用下拉指派分組」改成「同一畫布＋ 區塊→改名→把設備、數量拖進去」；存下的 `ui` 與原題相同（`_assert_definition_v1` 不改）。
   - `test_e2e_builder_dnd`：導覽 8→7 格、沒有第 3 步；預覽題改成「輸出＋列表兩個預覽跟著畫布變、不重建、不搶焦點」；說明題裡驗表單 iframe 的那段移到一致性題。

## 9. 第三輪：單頁編排（2026-09-30，W1 建構器第三輪 S1）

七格縮圖導覽 → 頂列三頁籤（作業資訊／表單設計／流程設計）＋「發布」抽屜；左元件列（分組、搜尋、預設屬性）、中畫布（編輯｜預覽就地切換）、右屬性面板（屬性｜輸出預覽｜列表預覽）。內部步驟號 1、2、4、5、6 與 `#mb-step-N` 保留，測試走 `tests/_builder_nav.py`（`go_step`、`start_blank`）。

### 9.1 改題清單（舊題對不上新 UI ⇒ 改「怎麼走到」，不改「驗什麼」）

每題都做過反向控制：把該行為在前端弄壞（暫時改、跑完還原），新題必紅。

| 舊題 | 原斷言（驗什麼行為） | 新斷言 | 為什麼仍守同一個行為 | 反向控制（結果） |
|---|---|---|---|---|
| dnd `palette_is_icon_and_text_for_every_catalog_type…` | 元件列＝catalog `fieldTypes` 逐一相同（含順序）；每格有 icon＋文字；Enter 加到最後 | 元件列的**型別集合**＝catalog `fieldTypes` 集合；**每個元件**（不只主元件）都有 icon＋文字；Enter 加到最後（改點 `data-palette-element="date"`） | 行為是「catalog 每個型別都出現在元件列、只來自 catalog」；分組後順序由目錄分組決定，不再等於 fieldTypes 順序（順序不是這題要守的）。集合比對仍會在少一個或多一個型別時紅；icon／文字檢查範圍反而變大 | 讓 `table` 的主元件不出現 ⇒ 紅 |
| dnd `output_and_list_previews_follow_the_canvas…` | 加欄位、改名稱 ⇒ 輸出預覽與列表預覽兩個 iframe **同時**跟著變；改名時焦點不離開輸入框；iframe 不重建 | 改名稱後焦點仍在輸入框（先驗）；切到「輸出預覽」頁籤 ⇒ iframe 內容含最新名稱、列表 iframe 不可見；切到「列表預覽」頁籤 ⇒ 同理；仍不跳頁不開彈窗 | 行為是「預覽跟著畫布的最新內容」；新 UI 預覽只在該頁籤開著時渲染，所以等待點移到切頁籤之後。仍用「最新名稱」（第二次改名的值）當判準，等到的是切換時重算的結果，不是舊值 | `syncPreviews` 直接 return ⇒ 紅 |
| form_canvas `palette_drops_into_a_section…` | 元件列拖到卡片／區塊標題、欄位跨區塊搬、區塊拖曳排序 ⇒ 草稿 DB 的 groups／fields 順序正確 | 斷言不變；只在拖區塊前先把目標區塊標題列捲到畫面中央（固定頂列會蓋住放置點） | 只改操作前置，沒有動任何斷言 | `moveGroupTo` 不生效 ⇒ 紅 |
| p8_module_builder `acceptance_equipment_loan…` | 在瀏覽器建出借用模組（欄位、分組、列表欄、流程）並端到端使用 | 斷言不變；勾「借用人」列表欄前先點「列表預覽」頁籤（勾選框搬到那裡） | 只改操作前置；後面照樣驗列表欄實際出現在執行頁 | 列表欄勾選不寫入 ⇒ 紅 |

另有通則：新型別、範本、屬性面板、預覽切換、明細表欄編輯、金流面板、行動抽屜由新檔 `test_e2e_builder3_singlepage_2026_09_30.py`（7 題）與 `test_e2e_builder3_runtime_2026_09_30.py`（2 題）承接，觀測點都在草稿 DB 落地值或執行頁畫面。

### 9.2 區塊欄數
`ui.form.groups[].columns`（1～4；其他＝自動）。建構器畫布與執行頁共用 `MotrixCustomLayout.gridStyle` 與 `.cr-grid--n`（`--cr-cols`）；窄螢幕一律 1 欄。反向控制：`colsOf` 恒回 0 ⇒ 執行頁欄數題紅。
