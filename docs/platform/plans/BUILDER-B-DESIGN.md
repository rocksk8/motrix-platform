# 建構器方案 B：自訂模組掛成「既有頁面的頁籤」——設計（第 31 班主軸，2026-10-01 草擬）

承 `BUILDER-ATTACH-EXISTING-MODULE-SPEC.md`（方案 A 已出貨；B 延後）。本檔把 B 收斂成可實作的合約：宣告格式、權限、頁面要改什麼、失效保護、測試與守門、工量。基底 platform `fca93b04`。**不在第 29／30 班。**

## 0. 查證過的現況（決定設計的事實）
- 自訂模組＝資料（`ui_definitions` kind=`custom_module`）；有自己的執行頁 `custom-records.html?key=<模組>`（`&no=<單號>` 直開單據）、自己的權限 `custom.<key>`（`helpers/custom_modules.permission_of`）、可見性唯一一份 `visible_to(mods, user)`（`GET /api/custom-modules` 與 `GET /api/platform/menu` 共用）。
- 選單併入：`core/menu.py::merge_custom`（`menu.group` 同名＝併進群組成一個選單**項目**）。方案 A 已讓「在我的工作選單下找得到」成立。
- **「我的工作」是選單群組，不是一頁**：底下是 `daily-tasks.html`（每日工作事項）、`payment-request.html`（新增請款）、`approval-history.html`（簽核歷史）等獨立頁面（`module.json pages[].menu.group="mywork"`）。所以 B 的掛載對象是**某一頁**，不是群組。
- 內建頁面沒有宣告可嵌入的位置；`core/customization.validate_manifest` 對不認得的鍵一律回問題（loader 不載入該模組）⇒ 新鍵必須先進驗證器。
- 技術可行：同源 iframe 已被允許（`frame-src 'self'`、`frame-ancestors 'self'`、`X-Frame-Options: SAMEORIGIN`，`main.py:645–707`）；記錄列表端點已支援 `?field=&value=` 篩選（`routers/custom_records.py:113`）；登入狀態是同源 localStorage，iframe 內免重新登入。

## 1. 範圍與裁示（建議，待使用者確認）
1. **掛載單位＝頁籤（`kind:"tab"`）**；本期不做「區塊」「按鈕」。
2. **首個掛載頁：`daily-tasks.html`（每日工作事項，我的工作群組）**——該群組唯一已有頁籤列（`.dt-tab-bar`）的頁面，改動最小；其餘頁面（新增請款、簽核歷史、案件管理）照同一樣板後續補，每頁一個宣告＋一個容器。
3. 自訂模組**可同時**有獨立選單項（A）與掛載頁籤（B）；掛載不取代選單，也不複製資料（同一個模組、同一份 `custom_records`）。
4. 每個掛載點最多 8 個頁籤（超過 ⇒ 驗證器拒絕，避免頁籤列爆掉）。

## 2. 宣告格式（內建模組的 `module.json`）
新增頂層選填鍵 `mount_points`（陣列；沒有＝本模組不開放掛載）：
```json
"mount_points": [
  {"key": "daily-tasks", "page": "daily-tasks.html", "kind": "tab",
   "label": "每日工作事項頁籤", "perm": "any", "context": []}
]
```
- `key`：模組內唯一（小寫英數／連字號）；全域識別＝`<模組key>.<key>`（例 `daily_tasks.daily-tasks`）。
- `page`：必須是同一個 module.json `pages[].path`（驗證器比對；同 `customization.pages[].page` 規則）。
- `kind`：本期只有 `"tab"`。
- `label`：給建構器下拉顯示的人話。
- `perm`：該點本身的可見條件，**格式同 `pages[].menu.perm`**（`["k1","k2"]` 任一／`"superadmin"`／`"any"`）。
- `context`：頁面能提供給嵌入模組的上下文鍵（字串陣列，例案件頁 `["case_no"]`；本期首點為 `[]`）。
驗證：`core/customization.validate_manifest` 加入 `mount_points` 的鍵檢查（必填 key/page/kind/label/perm，選填 context；不認得的鍵＝問題；key 重複＝問題；page 不在 pages＝問題；perm 格式錯＝問題）。**L0 契約新增（只加不改）⇒ 核心次版號升版＋L1 介面快照重產**（PLAYBOOK §C-7）。

## 3. 自訂模組的定義（`custom_module` body）
新增選填鍵 `mount`：
```json
"mount": {"point": "daily_tasks.daily-tasks", "label": "請款單", "contextField": ""}
```
- `point`：`<模組key>.<key>`。`label`＝頁籤文字（沒寫＝模組名稱）。`contextField`：該點有 `context` 時，指定哪個欄位接收上下文值（例 `case_no` → 表單欄 `caseNo`）；沒有 context 的點必須留空。
- `helpers/custom_modules.validate_module` 新增檢查：點存在且 kind=tab、**該內建模組目前已載入**（未載入 ⇒ 問題「掛載目標模組不在」，不是靜默略過）、同一點內自訂模組 key 不重複、同點上限 8、`contextField` 必須是本模組的欄位且屬於該點的 `context` 鍵之一。
- 發布時驗證一次；**執行時再驗證一次**（內建模組可能之後被停用或改版移除該點，見 §6）。

## 4. 權限規則（一份函式，兩處共用）
頁籤可見 ＝ **自訂模組可見**（`visible_to`：`custom.<key>` 權限＋`menu.visibleTo` 角色／帳號，superadmin 全部）**∧ 掛載點 `perm` 通過**（`core.menu` 同一份 `_perm_ok`／`visible` 語意；superadmin 一律可）。
- 新函式 `helpers/custom_modules.visible_mounts(conn, user, point)`：唯一實作；`GET /api/platform/mounts` 呼叫它，頁面不自己判斷。
- **隱藏頁籤不是存取控制**：records／meta 端點仍各自驗 `custom.<key>`（既有）；本功能不放寬任何一支。
- 反例必測：有 `custom.<key>` 但不滿足點 perm ⇒ 不顯示；滿足點 perm 但沒有 `custom.<key>` ⇒ 不顯示；`menu.visibleTo` 排除者 ⇒ 不顯示（與選單一致）。

## 5. API 與頁面改動
### 5.1 API（新，唯讀）
- `GET /api/platform/mounts?point=<模組key>.<key>`（登入者）⇒ `{"point": "...", "tabs": [{"key","label","icon","href"}]}`；`href`＝`custom-records.html?key=<K>&embed=1`（有 context 時由頁面端附 `&ctx.<鍵>=<值>`，後端不回帶值的 URL，避免快取／洩漏）。
- 點不存在、或所屬內建模組未載入 ⇒ **404**（缺席不可長得像「沒有頁籤」；頁面本身也不會存在）。點存在但沒有人掛 ⇒ `tabs: []`。
- `GET /api/platform/mount-points`（superadmin，建構器下拉用）⇒ 所有已載入模組宣告的點（key、頁面、label、context 鍵）。

### 5.2 共用元件（新，`static/mount-tabs.js`，L1 前端）
Alpine 元件 `motrixMountTabs(point, getCtx)`：載入 `tabs`、渲染頁籤按鈕＋同源 iframe 面板；切換時才建立 iframe（懶載入）；提供 `ready/error/tabs/active`。iframe 高度由內頁 `postMessage({type:'motrix-embed-height'})` 回報；`message` 只收 `event.origin === location.origin`。API 失敗／空清單 ⇒ **不顯示任何頁籤、頁面照常**（附一行 console warn，不彈窗）。

### 5.3 嵌入模式（`custom-records.html?embed=1`）
隱藏 topbar／側欄、去掉外距、回報高度；`ctx.<鍵>`＝值 ⇒ 新增單據時預填 `contextField`、列表自動帶 `?field=<contextField>&value=<值>` 篩選（既有端點）。`embed=1` 不改任何權限判斷。

### 5.4 內建頁面要改什麼（每個掛載頁一次）
1. `module.json` 加一筆 `mount_points`。
2. 頁面加：一個頁籤按鈕（沿用該頁既有頁籤樣式）＋一個面板容器，帶 `data-mount-point="<模組key>.<key>"`，由 `motrixMountTabs` 驅動；`<script src="../static/mount-tabs.js">`。
3. 把 `static/mount-tabs.js` 登記到 `docs/platform/modules.json` 歸屬（L1 前端），頁面不得自己 fetch `/api/platform/mounts`。
首批：`daily-tasks.html`（約 20 行）。

## 6. 失效保護（缺席要明說、資料不動）
| 情況 | 行為 |
|---|---|
| 內建模組停用／未載入 | 點消失（API 404）、頁面不存在；自訂模組與 `custom_records` 原封不動；建構器列出「掛載目標不在」警示，**不自動刪**也不自動改定義 |
| 之後版本把該點移除 | 啟動檢查與 `validate_module` 列「掛載目標不存在」；自訂模組仍可用（選單／直開）；頁籤不顯示 |
| 自訂模組取消發布／被刪 | 頁籤消失；刪除沿用既有規則（有單據需確認、已入帳拒絕） |
| `/api/platform/mounts` 失敗 | 頁面不出頁籤、其餘功能正常；不報錯彈窗 |
| iframe 載入失敗（逾時 8 秒） | 面板顯示「載入失敗，請從選單開啟：<連結>」 |
| 使用者失去 `custom.<key>` | 頁籤消失（後端過濾）；records 端點本來就擋 |

## 7. 測試與守門
**單元／API**
- `validate_manifest`：缺鍵、不認得的鍵、key 重複、page 不在 pages、perm 格式錯、kind 不是 tab ⇒ 各一題（正對照：合法宣告通過）。
- `validate_module`：目標點不存在、模組未載入、同點重複、超過 8 個、`contextField` 不屬於點的 context ⇒ 各一題。
- 權限矩陣（API）：superadmin／有 `custom.<key>`＋點 perm 通過／只有其一／被 `visibleTo` 排除／未登入 ⇒ 各自預期的 `tabs`；404 情境（點不存在、模組未載入——以 registry 假造）。
**守門（機械）**
- G-M1：每個宣告的 `mount_points[].page` 的 HTML 必含 `data-mount-point="<模組key>.<key>"`；反之 HTML 出現 `data-mount-point` 就必須有宣告（宣告了卻沒畫＝靜默沒有；畫了沒宣告＝建構器看不到）。**先在已知命中的檔案證明掃描器抓得到（正對照）**。
- G-M2：頁面不得直接呼叫 `/api/platform/mounts`（只能經 `mount-tabs.js`）。
- G-M3：L1 介面快照／核心 CHANGELOG（L0 新增）。
**e2e（瀏覽器，含截圖）**：發布一個掛在 `daily_tasks.daily-tasks` 的自訂模組 ⇒ 每日工作事項頁出現頁籤 ⇒ 點選後 iframe 內列表可見 ⇒ 新增一筆單據 ⇒ DB 有列、列表出現；取消發布 ⇒ 重載頁籤消失；無權限帳號看不到頁籤；API 404 時頁面照常。終點狀態驗 DOM＋DB。
**突變**：點 perm 檢查拿掉；`visible_to` 略過；`event.origin` 檢查拿掉；G-M1 對應的 data-mount-point 拿掉 ⇒ 守門紅；`embed=1` 時 contextField 篩選拿掉 ⇒ e2e 紅。

## 8. 工量與出貨
| 項目 | 估計 |
|---|---|
| 驗證器（manifest＋custom_module）＋`visible_mounts`＋兩支 API＋測試 | 0.5 班 |
| `mount-tabs.js`＋`custom-records.html` 嵌入模式＋守門 G-M1／M2 | 0.5 班 |
| 建構器欄位（掛載目標下拉、label、contextField）＋驗證訊息 | 0.5 班 |
| 首批頁面（daily-tasks）＋e2e＋截圖＋突變 | 0.5 班 |
合計約 **2 班**（1 班可出骨架：後端＋守門＋首頁籤、建構器欄位晚一班）。**層級**：L0 新增（customization）＋L1 新增（`mount-tabs.js`、`/api/platform/*`）＋模組小版 ⇒ **全量班**。

## 9. 待使用者裁示
1. 首個掛載頁用 **每日工作事項**（建議）還是別頁（新增請款？案件管理？）。「我的工作」本身是群組、沒有單一頁面。
2. 自訂模組掛頁籤後，要不要**同時保留**獨立選單項（建議保留，A 與 B 並存）。
3. 案件管理頁（需要 `case_no` 上下文）排第二批？（本設計已預留 `context`／`contextField`，首批不用。）
4. 頁籤上限 8 是否合適。

## 10. 不做（本期）
區塊／按鈕掛載；跨頁共用同一自訂模組的多個掛載點（一個自訂模組一個 `mount`）；自訂模組之間互相掛載；iframe 以外的內嵌元件（非同源風險、樣式耦合）。
