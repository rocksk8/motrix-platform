# 共用元件規格：設定矩陣＋批次列（SettingsMatrix）

狀態：設計草案 r2（hichan-4；已納入 PM 2026-11-13 裁示 M1／N2／N3／N4／N5／N6 與 hichan-11 審查）。
LINE 事件矩陣（hichan-6，`feat/line-events-matrix` @ c9ca919b4）是第一個使用者；設定中心與各設定頁共用同一套，不每頁各寫一套。
實作時：核心＝hichan-6 在 `feat/line-events-matrix` 已寫好並有 6 個 e2e 的 `frontend/static/mx-table.js`＋`frontend/css/mx-table.css`，**改名為 `settings-matrix.js`／`settings-matrix.css`，對外 `window.SettingsMatrix`（`MxTable` 留別名）**；本規格的 C6～C8、C10、C11 在它之上加。`h4/index.html` 內的核心只是**示範行為的原型，不進 repo**。各頁只提供「欄定義＋資料＋動作」。禁止再往 `notification-settings.html` 等大頁面塞新元件。

## 0. 目標（使用者 2026-11-13：「介面辨識度跟選擇都很難懂；每個項目都做」）

每個設定項目，使用者掃一眼就要知道四件事：**它叫什麼（白話）→ 現在是什麼值、從哪來 → 改了會怎樣 → 能不能一次改很多**。
矩陣與批次解決「項目太多、逐項操作」；白話名稱、說明、來源、標籤解決「看不懂」。同一個元件、同一份規格。

## 1. 元件清單

| # | 元件 | 作用 | 備註 |
|---|---|---|---|
| C1 | `SmTable`／`SmGroup`／`SmRow` | 依群組分段、可收合的列；欄由頁面宣告 | 桌面＝表格，≤ 900px＝C9 卡片 |
| C2 | `SmToolbar` | 搜尋＋篩選晶片＋群組下拉＋展開／收合全部 | 黏在頂端；搜尋時自動展開有結果的群組 |
| C3 | `SmBatchBar` | 選取後固定在畫面下方：動作＋取消選取 | 只對「可批次」的列起作用（§4） |
| C4 | `SmConfirm` | 批次套用前的確認視窗 | 筆數、被略過的項目與原因、前後差異、影響估算、變更原因 |
| C5 | `SmUndoBatch` | 套用後「復原這一批」 | 版本檢查，不是逐格計時（§5） |
| C6 | `SmHelp`（「?」） | 每列一個，點開四段說明 | 內容由登錄表產生（§6），**不另建說明檔** |
| C7 | `SmSource` | 顯示「目前生效值」與來源 | 公司／預設；**只有真的有個人層的欄位才顯示「個人」**（§2.3） |
| C8 | `SmDiff`（「與預設不同」） | 列標記＋篩選條件＋「重設為預設」 | 用 `isDefault`／`defaultText`（已有） |
| C9 | `SmCards` | 手機卡片版（≤ 900px） | 每列一張卡，批次列固定在下方，觸控目標 ≥ 40px |
| C10 | `SmCell` 註冊表 | 欄內控制項的型別 | §3 |
| C11 | `SmColSelect` | 欄頭勾選（兩軸都是實體的矩陣，如「權限鍵 × 人」） | 用於使用者權限頁 |

## 2. 每一列固定要有

```
[☐] 中文名稱（白話，粗體）  ?   [標籤…]        目前值（控制項）   與預設不同●
    小字代碼（等寬字，灰）  一句說明（影響什麼、預設值是什麼）
    來源：公司設定 · 王經理 10/28 ／ 系統預設
```

### 2.1 名稱、代碼、說明、標籤
1. **中文名稱**（`label`）：白話、一句話看懂；問句（`question`）在展開／手機卡片顯示。
2. **小字代碼**：`key`（`group.field`），灰色等寬小字；給客服與開發者對話用，**不當名稱**。
3. **標籤**（多個；顏色固定）：
   - 🔴「影響大」：`risk ∈ {money, legal, security}`，或 `requires_pending`，或 `loosen`。
   - 🟠「需外部設定」：要先到外部服務／伺服器做事才有用（Google OAuth、SMTP、LINE token、S3、Edge 路徑…）。登錄表目前沒有此欄 ⇒ 見 §7。
   - 🔵「影響別人」：改了會影響其他使用者的畫面、通知或簽核（權限、簽核人、收件人）。
   - ⚪「進階」：`advanced`，收在「進階」區。
   - 🟣「個人」：個人偏好，只影響自己。
4. **與預設不同**：值 ≠ 預設時列左側橘條＋「●與預設不同」；工具列有同名篩選。逐列「重設為預設」；`risk ∈ {security, money, legal}` 或受 change_control 管的欄位不進批次重設，只能逐項（走原流程）。
5. **一句說明**必含「影響什麼」與「預設值」；不放代碼與工程用語（UX-PRINCIPLES §6.5 禁用清單）。
6. **選項型欄位**：每個選項顯示「白話標籤＋後果一句」（`choices` 第三項 `impact`，已是必填）；不顯示整數代碼。

### 2.2 群組的風險標示（PM N5）
群組標題**不另外標高／低風險**（會和欄位層級矛盾）：欄位各自顯示自己的標籤；群組標題只在其中有任一欄屬「影響大」時顯示一個 🔴「內含高風險項目」，點開看是哪幾項。

### 2.3 「目前生效值」與來源（PM N3）
來源徽章只有：**預設**（值＝預設、從沒改過）／**公司**（有最後修改人、時間、原因）／**等待生效**（顯示何時生效、誰要核准）／**舊位置**（來自 legacy 儲存位置，唯讀提示）。
**「個人」徽章只出現在真的有個人設定層的欄位**（目前已知：`login_greeting`、`list_view`／`list_prefs` 清單偏好；個人通知偏好）。其他欄位一律只顯示「公司」或「預設」，不得為了版面一致而假裝有個人層。
`field_views` 已回 `value／valueText／isDefault／defaultText／recommendedText／banner`；新增 `source:{kind,by,at,reason}`（由 `config_ledger` 最後一筆＋是否預設＋有無 pending 推得）。

## 3. 欄型別（`SmCell`）與宣告式用法

```js
SettingsMatrix.mount(el, {
  rows, groups,                       // §3.1
  columns:[{id,title,cell:'switch'|'check'|'select'|'chips'|'number'|'text'|'value'|'readonly'|'custom'}],
  filters:['changed','external','heavy',…],
  batch:{ eligible(row), actions:[…] },    // §4
  save: async (changes, ctx)=>{…},         // 頁面提供：呼叫既有 API（一律走 publish／既有端點）
});
```
`value` 依欄位 `type`／`choices` 自動挑控制項。LINE 的角色格雙色、人員挑選＝`chips`／`custom`，**不進核心**。
**文字類欄位**（`download_name` 的檔名樣板、各種 `*_labels`）不畫勾選格：做成「逐列直接編輯＋即時預覽（顯示實際檔名／畫面長相）」，儲存仍走群組存檔（PM M1）。

### 3.1 列資料契約
```json
{ "id": "quote_approval.threshold_amount", "group": "quote_approval",
  "label": "報價單送審金額門檻", "code": "quote_approval.threshold_amount",
  "question": "報價單超過多少錢要送審？", "oneLine": "超過這個金額的報價單要送審。預設 100,000 元。",
  "type": "int", "unit": "元", "value": 150000, "valueText": "150,000 元",
  "default": 100000, "defaultText": "100,000 元", "isDefault": false, "recommendedText": "100,000 元",
  "source": { "kind": "company", "by": "王經理", "at": "2026-10-20", "reason": "…" },
  "risk": "money", "tags": ["heavy"], "pending": null,
  "help": { "what": "…", "when": "…", "impact": "…", "recommend": "…" } }
```

## 4. 批次規則（PM M1；硬規則，守門要驗）

1. **可批次**：欄位 `risk ∈ {none, ops}`，且非 `requires_pending`、非 `loosen`、無待生效項、非 `sensitive` 群組。`ops` 欄位在確認視窗內另加一行提示；`none` 直接確認即可。
2. **永不進批次**：`risk ∈ {security, money, legal}`，以及一切受 change_control 管的欄位（`requires_pending`／`loosen`）。核取方塊灰掉，tooltip 寫原因；群組標題的全選與批次動作**自動略過**，確認視窗列出「已略過 N 項：原因」。
3. **設定中心的批次只有三種動作**（實測：`risk=none` 的 63 欄中沒有任何 bool，全是 str／int／float，勾選格與全開全關沒有東西可作用）：
   - **套用建議值**（`recommended`）
   - **套用預設組合**（`presets`；沿用 `/api/settings-center/profiles/{name}/apply`、`settings_registry.apply_profile`）
   - **重設為預設值**（逐欄 `default`）
4. **寫入一律走既有路徑**：`settings_registry.publish()`／`apply_profile()`；不另開新的寫入點。`publish` 內部自己會把變更 `_split` 成待生效／立即／放寬，批次無法繞過。
5. 同一群組內＝對 `POST /api/settings-center/groups/{group}` 一次送多欄（群組內原子）；跨群組＝逐群組各送一次，**中途失敗要明講「已套用 X 項、未套用 Y 項」**並提供復原已套用的部分（不假裝原子）。真原子跨群組端點預設不做。
6. 批次要填「變更原因」（現有 API 必填 `reason`）：確認視窗內一個欄位，預設「批次調整（N 項）」。
7. **`eligible()` 可由頁面覆寫**（hichan-6 提出）：設定中心頁用本節的嚴格預設；LINE 事件頁依使用者已裁示「重要（系統告警）可批次關閉，但要第二道警告視窗列出會停止通知的情況」，由伺服器強制 `confirm_critical`。覆寫只能由頁面**自己的**裁示放寬，且守門要列出所有覆寫處（見 §9）。
8. **非設定中心的矩陣頁**（權限、信件收件、個人通知偏好、簽核流程、LINE 事件）的批次動作是各頁自己的領域動作（授予／取消、信件開關、套用流程範本…），但同樣遵守：高敏感／影響大的列不進批次、寫入走該頁既有的驗證與稽核路徑、確認視窗＋復原這一批。

## 5. 確認與「復原這一批」（PM N2）

1. 勾選 → 批次列 → 選動作 → **確認視窗 C4**：「將變更 N 項、略過 M 項」→ 展開每項「現在 → 之後」（`valueText`）→ 影響估算（`impact_fn`／`live_impact`，沿用）→ 變更原因 → [套用][取消]。
2. 套用成功 → 吐司「已套用 N 項　[復原這一批]」（停留 6 秒，避免漏看；但**復原的條件不是計時，是版本**）。
3. **復原這一批＝對涉及的群組做 expected-version 檢查**：套用當下記下每個群組的版本號；復原時若任一群組版本已變（別人改過），**整批拒絕復原**，並顯示「誰、在何時、改了哪一項」，請使用者到「變更紀錄」或手動調整。不覆蓋別人的修改。
4. **不做欄位層級的 6 秒復原**：單項修改直接生效、吐司只說「已更新（要還原請到變更紀錄）」；影響大欄位維持原本的「原因＋確認句型＋等待期／核准」，沒有復原。
5. **後端需求（要先寫成規格才實作）**：`settings_registry.publish(group, values, …, expected_version=None)`——帶了就比對目前版本，不符丟 `SettingConflict(by, at, keys)`；路由 `POST /groups/{g}` 接受 `expectedVersion`，衝突回 409 並帶 `{by, at, keys}`。復原＝以 `expected_version=套用後的版本` 回寫套用前的值（同樣走 publish、原因註明「復原批次」）。非設定中心的頁面比照辦理（各頁既有的版本／更新時間欄位）。

## 6. 「?」說明：從登錄表產生（PM N4，取代原 `settings_help.json`）

**不另建說明檔，只維護一個來源。** 四段由 `SettingDef` 既有欄位產生：

| 說明段 | 來源 |
|---|---|
| 這是什麼 | `question`＋`help` |
| 什麼時候要改 | **新增 `SettingDef.when`**（選填；沒填就不顯示該段，守門逐步要求補齊） |
| 改了會影響什麼 | `impact`（＋風險欄位的 `risk_text`） |
| 建議值 | `recommended`／`recommendedText`（＋選項型各選項的 `impact`） |

- API：`field_views` 回傳每欄 `help:{what,when,impact,recommend}`，前端直接用；不需新端點、不需新檔案。
- 非設定中心的頁面（信件類型、個人權限鍵、LINE 事件、簽核單據類型）：各自的登錄處（`mail_types`、`module_registry`、`line_catalog`、`tiered_approval`）已有 `name／event／impact／action` 等欄位，用同一個「四段 → 欄位」對照函式產生；缺 `when` 的先不顯示。
- 守門（實作時）：四段都不得出現禁用詞；`when` 不得與 `help` 完全相同（防複製貼上）。

## 7. 需要的 API／後端（越小越好）

| 項目 | 內容 | 必要性 |
|---|---|---|
| `source` | `field_views` 加 `source:{kind,by,at,reason}` | 必要（C7） |
| `help` 四段 | `field_views` 加 `help{…}`；`SettingDef` 加選填 `when` | 必要（C6） |
| `needs_external` | `SettingDef` 選填 `external=""`（一句話：要先做什麼）或頁面層宣告 | 必要（標籤） |
| expected-version | `publish(..., expected_version=None)`＋路由 `expectedVersion`＋409 `{by,at,keys}` | 必要（復原這一批） |
| 預設組內容 | 為可批次欄位宣告 `presets`（目前 `profiles()`＝`{}`，0 個）／建議值 | 內容待決（見 INVENTORY §五） |
| 批次 | 群組內沿用 `POST /groups/{g}`；套預設組沿用 `/profiles/{name}/apply` | 不需新端點 |
| 批次預覽 | 沿用 `POST /groups/{g}/preview`（回 `plan` 分類） | 沿用 |
| 各矩陣頁自己的端點 | 信件批次、使用者權限批次、LINE 批次（h6）、個人偏好本人入口、簽核流程複製 | 見 INVENTORY §四 |

## 8. 篩選晶片（內建）
`全部`、`與預設不同`、`需外部設定`、`影響大`、`影響別人`、`進階`；頁面可加自己的（LINE 的「已開啟／發給整份名單」）。搜尋範圍：中文名稱、小字代碼、說明、群組名、選項標籤（不比內部整數代碼）。篩選狀態存 `sessionStorage`（try/catch；讀不到就預設）。

## 9. 無障礙、手機、效能、測試
- 鍵盤：方向鍵移動、空白鍵勾選、Shift 連選；開關／晶片用 `role="switch"`／`aria-pressed`；吐司 `aria-live="polite"`；對話框焦點圈住、Esc 關閉。
- 手機（≤ 900px）：卡片版；批次列固定下方、按鈕 ≥ 40px；無橫向捲動（e2e 驗）。
- 效能：列數 ≤ 200 直接渲染；更多就依群組延遲渲染。
- 測試（實作階段）：`eligible` 判定表驅動（每種 risk／pending／loosen 組合）；復原版本衝突案例；e2e 遵守 e2e lint；守門：接入頁的 `rows` 必帶 `code／label／oneLine`；`eligible()` 的覆寫處必須登記在清單裡（目前只有 LINE 事件頁的「重要」），其餘頁面不得把可批次判定覆寫成更寬鬆。

## 10. 與 hichan-6（LINE 稿）的協調
- 核心＝hichan-6 的 `mx-table.js`（已含 C1 表格／群組／列、C2 工具列、C3 批次列、依序確認視窗、手機卡片、switch／chips／select／html 欄、自訂欄內 `data-mx` 按鈕、單格 `confirm`）；本規格新增 C6 說明、C7 來源、C8 與預設不同、C10 欄註冊表擴充、C11 欄頭選取。
- 留在 LINE 頁：角色格雙色語意、人員挑選、用量條與推估、三個預設組合、`/events/batch` 端點。
- h6 回覆（已採納）：(1) 核心由 `mx-table.js` 演進；(2)「復原這一批」＝批次端點接受選填 `expect`（套用後那幾個鍵的狀態），不符回 409 `{code:'conflict', keys, by, at}`（`by/at` 取自該鍵最後一筆 `settings.line_notify.*` 稽核列），吐司維持 6 秒只為避免漏看；(3) LINE 標籤：「僅 LINE」「LINE 細項」改中性灰（藍色保留給「影響別人」）、「重要」維持原字樣用 🔴、「沒人會收到」是狀態徽章（紅框）而非標籤；(4) `eligible()` 可由頁面覆寫（見 §4-7）。

## 11. 用語表（所有人遵守；mockup 與盤點表一律用這些詞）

**套用樣式**（盤點表「套用樣式」欄只能填）：`矩陣`｜`勾選批次`｜`群組全開全關`｜`搜尋篩選`｜`預設組合`｜`套用前確認＋復原這一批`｜`手機卡片`｜`單項表單`（不需批次的單一選項）｜`逐列編輯＋預覽`（文字類欄位）｜`精靈`。
> 設定中心欄位的「勾選批次」意指「套用建議值／預設組合／重設為預設」三種動作（§4.3），不是勾格切換。

**標籤**：影響大｜需外部設定｜影響別人｜進階｜個人　　**群組標示**：內含高風險項目
**來源**：預設｜公司｜等待生效｜舊位置｜個人（僅限真有個人層）
**篩選**：全部｜與預設不同｜需外部設定｜影響大｜影響別人｜進階
**按鈕**：套用建議值｜套用預設組合｜重設為預設｜套用 N 項｜取消選取｜復原這一批｜展開全部｜收合全部
**確認句型**：「將變更 N 項，略過 M 項。」「已略過（不能批次，請逐項設定）：…」「已套用 N 項」「已復原這一批（N 項）」「無法復原這一批：這幾項在你套用之後被 ○○ 於 ○○ 改過，為了不蓋掉別人的修改，系統拒絕整批復原。」
**不得出現**：欄位代碼當名稱、`true/false`、整數選項代碼、「影子」「閘門」「確認期間」（改寫成「要等 N 天才生效」）等工程用語（UX-PRINCIPLES §6.5）。
