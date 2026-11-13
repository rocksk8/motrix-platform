# 共用元件規格：設定矩陣＋批次列（SettingsMatrix）

狀態：設計草案 r1（hichan-4）。LINE 事件矩陣（hichan-6，`feat/line-events-matrix` @ c9ca919b4）是第一個使用者；設定中心與各設定頁共用同一套，不每頁各寫一套。
實作時：`frontend/static/settings-matrix.js`＋`settings-matrix.css`（核心），各頁只提供「欄定義＋資料＋動作」。禁止再往 `notification-settings.html` 等大頁面塞新元件。

## 0. 先講目標（使用者 2026-11-13：「介面辨識度跟選擇都很難懂；每個項目都做」）

每一個設定項目，使用者掃一眼就要知道四件事：**它叫什麼（白話）→ 現在是什麼值、從哪來 → 改了會怎樣 → 能不能一次改很多**。
矩陣與批次解決「項目太多、逐項操作」；白話名稱、說明、來源、標籤解決「看不懂」。兩者同一個元件、同一份規格。

## 1. 元件清單

| # | 元件 | 作用 | 備註 |
|---|---|---|---|
| C1 | `SmTable`／`SmGroup`／`SmRow` | 依群組分段、可收合的列；欄由頁面宣告 | 桌面＝表格，≤ 900px＝C9 卡片 |
| C2 | `SmToolbar` | 搜尋＋篩選晶片＋群組下拉＋展開／收合全部 | 黏在頂端；搜尋時自動展開有結果的群組 |
| C3 | `SmBatchBar` | 選取後固定在畫面下方：動作按鈕＋預設組合＋取消選取 | 只對「可批次」的列起作用（§4） |
| C4 | `SmConfirm` | 批次套用前的確認視窗 | 顯示：筆數、被排除的項目與原因、前後差異、（有的話）估算影響 |
| C5 | `SmUndoToast` | 套用後 6 秒內可「復原」 | 復原＝回寫前一個值（§5） |
| C6 | `SmHelp`（「?」） | 每列一個，點開四段說明 | 內容來自 `settings_help.json`（§6），不寫死在 HTML |
| C7 | `SmSource` | 顯示「目前生效值」與來源徽章 | 公司設定／個人偏好／系統預設／等待生效 |
| C8 | `SmDiff`（「與預設不同」） | 列標記＋篩選條件＋逐列「還原成預設」 | 用 `isDefault`／`defaultText`（已有） |
| C9 | `SmCards` | 手機卡片版（≤ 900px） | 每列一張卡，批次列固定在下方，觸控目標 ≥ 40px |
| C10 | `SmCell` 註冊表 | 欄內控制項的型別 | 見 §3 |

## 2. 每一列固定要有（PM 規則 5）

```
[☐] 中文名稱（白話，粗體）  ?   [標籤…]        目前值（控制項）   來源徽章   與預設不同●
    小字代碼（等寬字，灰）  一句說明（影響什麼、預設值是什麼）
```

1. **中文名稱**：白話，一句話看懂（`label`）；問句式在展開／手機卡片顯示（`question`）。
2. **小字代碼**：`key`（`group.field`），灰色等寬小字；給客服與開發者對話用，不當主要辨識。**不是**把代碼當名稱。
3. **標籤**（可多個；顏色固定）：
   - 🔴「影響大」：`risk ∈ {money, legal, security}`，或 `requires_pending`，或 `loosen`（放寬方向）。
   - 🟠「需外部設定」：要先到外部服務／伺服器做事才有用（Google Cloud OAuth、SMTP 帳號、LINE token、S3、Edge 路徑…）。目前登錄表沒有這個欄位 ⇒ 見 §7 新增 `needs_external`（頁面層宣告即可，不改核心）。
   - 🔵「影響別人」：改了會影響其他使用者的畫面或通知（權限、簽核人、收件人）。
   - ⚪「進階」：`advanced`，預設收在「進階」區。
   - 🟣「個人」：個人偏好，只影響自己。
4. **與預設不同**：值 ≠ 預設時，列左側一條色帶＋小圓點「●與預設不同」；工具列有同名篩選；列尾「還原成預設」（高風險欄位走單項流程，不進批次還原）。
5. **一句說明**：必含「影響什麼」與「預設值」。例：「超過這個金額的報價單要送審。預設 100,000 元。」不放代碼、不放工程用語（UX-PRINCIPLES §6.5 禁用清單）。
6. **選項型欄位**：每個選項顯示「白話標籤＋後果一句」（`choices` 的第三項 `impact`，已是必填）；不顯示整數代碼。

## 3. 欄型別（`SmCell` 註冊表）

頁面以宣告式欄定義使用元件，不寫 DOM：

```js
SettingsMatrix.mount(el, {
  rows,            // 見 §3.1
  groups,          // [{id,label,help?}]
  columns: [       // 每欄一個 cell 型別
    {id:'on',   title:'開關',   cell:'switch'},
    {id:'who',  title:'收件對象', cell:'select', options:[...]},
    {id:'roles',title:'角色',   cell:'chips', ...},     // LINE 稿的 6 角色格
    {id:'val',  title:'值',     cell:'value'},           // 依 type 自動：開關／數字／選項／文字
  ],
  filters: ['all','changed','external','heavy', ...],     // 內建＋頁面自訂
  batch:   { eligible(row){…}, actions:[…], presets:[…] },
  save:    async (changes, ctx) => {…},                  // 頁面提供：呼叫既有 API
});
```

內建 cell：`switch`（開／關）、`check`（單格勾選）、`select`（下拉）、`chips`（多格晶片，LINE 角色格）、`number`（含單位、範圍、步進）、`text`、`value`（依欄位 `type`／`choices` 自動挑上述之一）、`readonly`、`custom(fn)`（頁面自訂，例如 LINE 人員挑選、權限的「繼承來源」格）。
LINE 版的「角色格兩種顏色」「人員挑選」＝`chips`／`custom`，**不進核心**。

### 3.1 列資料契約

```json
{ "id": "quote_approval.threshold_amount",
  "group": "quote_approval",
  "label": "報價單送審金額門檻",
  "code": "quote_approval.threshold_amount",
  "question": "報價單超過多少錢要送審？",
  "oneLine": "超過這個金額的報價單要送審。預設 100,000 元。",
  "type": "int", "unit": "元", "min": 0, "max": null,
  "value": 150000, "valueText": "150,000 元",
  "default": 100000, "defaultText": "100,000 元", "isDefault": false,
  "recommendedText": "100,000 元",
  "source": { "kind": "company", "by": "王經理", "at": "2026-10-20", "reason": "…" },
  "risk": "money", "tags": ["heavy"],
  "pending": null,
  "choices": [{"value":1,"label":"…","impact":"…"}],
  "helpId": "quote_approval.threshold_amount" }
```

來源對照（`source.kind`）：`default`（值＝預設，從未改過）／`company`（公司設定，有最後修改人與時間）／`personal`（個人偏好）／`pending`（等待生效，顯示何時生效、誰要核准）／`legacy`（來自舊儲存位置，唯讀提示）。現有 `field_views` 已有 `value／valueText／isDefault／defaultText／recommendedText／banner／choiceBanners`；新增 `source`（見 §7）。

## 4. 批次規則（PM 規則 2、3；本節是硬規則，守門要驗）

**可批次（eligible）＝ `risk == "none"`  且  非 `requires_pending`  且  非 `loosen`  且  無待生效項  且  非 `sensitive` 群組**。

- 設定中心目前 183 欄中 `risk=none` 共 63 欄；其中仍須逐一排除 `requires_pending`／`loosen`（實作時以程式判定，不以人工清單）。
- 不可批次的列：核取方塊灰掉（tooltip 寫原因：「影響大，要逐項設定」「要等 N 天才生效，要逐項設定」…）；群組標題的全選／全開全關**自動略過**這些列，並在 C4 確認視窗列出「已略過 N 項：原因」。
- **批次絕不繞過 change_control**：不可批次的列不會被批次改到；使用者要改，走該欄位自己的流程（儲存原因、確認期間、雙人核准）。批次寫入一律走既有 `settings_registry.publish()`（它自己會 `_split` 成待生效／立即／放寬），**不另開旁路寫入**。
- 同一群組內的批次＝對 `POST /api/settings-center/groups/{group}` 一次送多欄（`publish` 在群組內已是原子）；跨群組批次＝逐群組各送一次，**中途失敗要明講「已套用 X 項、未套用 Y 項」並提供復原已套用的部分**（不假裝原子）。若要真原子需新端點（§7 選配，預設不做）。
- 批次要填「變更原因」（現有 API 必填 `reason`）：C4 確認視窗內一個欄位，預設帶「批次調整（N 項）」，可改。

預設組合（preset）：只是前端把一組值展開成欄位值；若是設定中心的既有預設組（`GET /api/settings-center/profiles`、`/profiles/{name}/apply`）則直接沿用。**預設組合同樣只套用到可批次的欄位**；含不可批次欄位的組，確認視窗要明講略過哪些。

## 5. 套用前確認＋6 秒復原

1. 勾選 → 批次列出現 → 選動作 → **C4 確認視窗**：「將變更 N 項、略過 M 項」→ 可展開每項「現在 → 之後」（用 `valueText`）→ 有影響估算的欄位顯示估算（`impact_fn`／`live_impact`，沿用）→ 填原因 → [套用] [取消]。
2. 套用成功 → **C5 吐司**「已套用 N 項　[復原]」停留 6 秒。復原＝對同一批欄位回寫「套用前的值」（前端在套用時保存），同樣走 `publish`、原因註明「復原批次」。
3. 復原的限制：只復原可批次欄位（本來就只有它們）；若 6 秒內該欄位被別人改過（版本號變了）→ 復原失敗並說明，不覆蓋別人的修改。
4. 單項修改不出確認視窗（直接改、保留現有儲存流程），但出現同樣的 6 秒復原吐司。危險欄位（影響大）維持現有「確認句型＋原因」流程，**不套 6 秒復原**（避免誤以為能撤回已進入等待期的變更；它們有自己的「取消待生效」）。

## 6. 「?」說明：`settings_help.json`

位置（建議）：`backend/core/settings_help.json`，經 `GET /api/settings-center/help?ids=…` 取（可批次取、可被瀏覽器快取）。**每項四段**：

```json
{ "quote_approval.threshold_amount": {
    "what":      "這是什麼：報價單金額超過這個數字，就要先送主管簽核才能寄給客戶。",
    "when":      "什麼時候要改：公司報價規模變大、或主管想多看幾張單的時候。",
    "impact":    "改了會影響什麼：之後新送出的報價單；已送出的不受影響。調低會讓更多單進簽核。",
    "recommend": "建議值：100,000 元（小型工程公司常見）。" } }
```

- 命名空間：`<群組>.<欄位>`（設定中心）、`mail.<信件類型>`、`line.<事件>`、`perm.<權限鍵>`、`page.<頁面>`（整頁的「這頁在做什麼」）。
- **後備**：沒有條目時，由登錄表自動組出（what←`help`、impact←`impact`、recommend←`recommended`＋`recommendedText`，`when` 缺就不顯示該段）——所以 183 欄不必一次寫完才上線；但「`when`」是新內容，要補。
- 守門（實作時）：JSON 條目的 key 必須對得上實際欄位（防殘留）；四段都不得出現禁用詞（UX-PRINCIPLES §6.5）；`recommend` 必須與登錄表 `recommended` 一致（防兩處不同步）。

## 7. 需要的 API／後端（越小越好）

| 項目 | 內容 | 必要性 |
|---|---|---|
| `source` 欄位 | `field_views` 回應每欄加 `source:{kind,by,at,reason}`（由 `config_ledger` 最後一筆＋是否預設＋有無 pending 推得） | 必要（C7） |
| `needs_external` 標籤 | 頁面層宣告（欄位 key 清單），或 `SettingDef` 加選填 `external=""`（一句話：需要先做什麼） | 必要（標籤） |
| `GET …/help` | 讀 `settings_help.json`，含後備組裝 | 必要（C6） |
| 批次 | 群組內：沿用 `POST /groups/{g}`；跨群組：前端逐群組送 | 不需新端點 |
| 批次預覽 | 沿用 `POST /groups/{g}/preview`（已回 `plan` 分類：待生效／立即／放寬） | 沿用 |
| 真原子跨群組批次 | `POST /api/settings-center/batch`（先驗證全部、同一把鎖寫入） | 選配，**預設不做**（風險＝動核心寫入路徑） |
| 通知矩陣（信件／LINE／權限） | 各自既有 API；LINE 的批次端點照 h6 稿（`/api/settings/line-notify/events/batch`） | 各頁自己的 |

## 8. 篩選晶片（內建）

`全部`、`與預設不同`、`需外部設定`、`影響大`、`影響別人`、`進階`；頁面可加自己的（LINE 的「已開啟／發給整份名單」）。搜尋範圍：中文名稱、小字代碼、說明、群組名、選項標籤（不比內部整數代碼）。篩選與搜尋狀態保存在 `sessionStorage`（try/catch 包起來，讀不到就預設）。

## 9. 無障礙、手機、效能、測試

- 鍵盤：列可用方向鍵移動、空白鍵勾選、Shift 連選；開關與晶片用 `role="switch"`／`aria-pressed`；吐司 `aria-live="polite"`；對話框焦點圈住、Esc 關閉。
- 手機（≤ 900px）：卡片版；批次列固定下方、按鈕 ≥ 40px；不得有橫向捲動（e2e 驗）。
- 效能：列數 ≤ 200 直接渲染；超過用「依群組延遲渲染」（群組展開才建 DOM）。70 事件／183 欄／42 信件都在範圍內。
- 測試（實作階段）：元件契約測試（eligible 判定表驅動：每種 risk／pending／loosen 組合）；e2e 遵守 e2e lint（動作後先等再讀；Alpine `x-show` 用 `wait_for(state=…)`）；守門：每個接入頁的 `rows` 都必須帶 `code`／`label`／`oneLine`、可批次判定不得被頁面覆寫成更寬鬆。

## 10. 與 hichan-6（LINE 稿）的協調

- LINE 稿的以下部分上收進共用核心：工具列（搜尋＋篩選晶片＋群組下拉＋展開收合）、群組標題列（全選＋全開全關）、批次列、確認視窗、6 秒復原吐司、手機卡片骨架、`.sw` 開關與 `.rc` 格子樣式（改成 CSS 變數 token）。
- 留在 LINE 頁的：角色格的雙色語意、人員挑選視窗、用量條與推估、預設組合三個（只發給我／最高管理者／照 Email 收件人）、`/events/batch` 端點。
- 需 h6 確認的 3 點：(1) 願意改用 `SettingsMatrix.mount` 宣告式介面（先出核心，LINE 當第一個接入）；(2) 樣式 token 對齊本規格 §2 的標籤配色；(3)「新開啟事件的預設對象」那類行為差異留在 LINE 頁，不進核心。
