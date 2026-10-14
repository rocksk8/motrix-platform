# T61 S6：動作目錄與使用者自訂按鈕——設計（步驟 1：文件；沒有程式改動）

> 日期：2026-10-14　作者：hichan-3c　基底：`wip/t61-s5-impl-r1`（d70f272de）
> 讀過：`PLATFORM-BUILDER-ARCHITECTURE-T57.md` §2.1 積木 5、§2.3、§2.6、§3.1；`BP1-MENUS-T59.md`（已知缺口 5：「新增按鈕不在本班：沒有動作目錄，允許的動作清單是安全決定」）；`core/customization.py`（`actions`／`menus`／`exports` 的登記格式與驗證）；`core/menu.py`（`visible`／`denied`）；`core/mounts.py`（掛載點宣告的先例）；`helpers/builtin_fields.py`（S5 的做法）。
> D1 暫定（b4）：**第一批只有兩種動作：「開啟既有頁面」與「執行既有匯出」，沒有任何會寫資料的動作。**

## 0. 結論（先看）

1. **按鈕永遠不授權。** 使用者定義的按鈕只是一個「入口」：開頁＝連結（目標頁面自己的登入／模組權限／遮蔽照舊）；匯出＝用**點擊者自己的登入**呼叫該匯出端點（端點自己的權限、遮蔽、稽核照舊）。按鈕能不能被看見，也由「點擊者能不能做目標動作」決定（看不到目標＝不顯示），但**顯示與否不是存取控制**——真正擋人的永遠是目標。
2. **動作目錄＝程式／模組宣告的有限清單，不是使用者輸入。** 開頁的目標只能是「已登記頁面」（模組 `pages[].path` ∪ L1 頁面）；匯出的目標只能是模組在 `module.json` 的 `customization.pages[].exports` **已經登記**的匯出（格式、端點、`perm` 都是現成欄位，`core/customization.py` 已會驗證）。沒有外部網址、沒有查詢字串、沒有任意端點、沒有 POST 以外會寫資料的動作。
3. **放置位置要「登記」**：頁面宣告可放按鈕的**插槽**（例：供應商頁的工具列），使用者只能把按鈕放進插槽、排順序；不能放到頁面上任意位置。
4. **儲存走既有定義文件庫**（新 kind `user_buttons`，用 `register_kind`，不改 L0 的 `core/definitions.py`）：草稿、版本、差異、還原、3e 的待核准與快照都沿用。
5. **預覽有意義**：可「以某角色／某使用者」預覽哪些按鈕會出現（伺服器用真實權限判斷，唯讀、不執行）；草稿即時畫在真實頁面上。
6. **需要核心層裁示的只有一件（可延後）**：把插槽宣告放進 `module.json`（新頂層鍵 `button_slots`，比照 `mount_points`）需要 L0 的驗證器掛鉤。先導可以先把插槽表放在 L1 helper，之後再搬。
7. 工量（估）：設計＋先導一個畫面 **約 8 pd**；每多一個頁面的插槽 0.3～0.5 pd；之後每加一種動作類型是另案（安全決定）。

## 1. 現況盤點（已查證）

| 項目 | 現況 | 證據 |
|---|---|---|
| 已登記的按鈕／選單／匯出 | `module.json` 的 `customization.pages[].actions`（`key,label,endpoint?,perm?`）、`menus`（一組按鈕）、`exports`（`key,label,endpoint,format∈xlsx/csv/pdf,perm?`）；格式與 perm 有驗證器；P9 只能**移動、隱藏、改名**既有的 | `core/customization.py::_validate_page` |
| 實際登記了什麼 | 只有 `tender_radar` 登記了 `actions`／`menus`；**沒有任何模組登記 `exports`** | 掃描所有 `module.json` |
| 可當「既有匯出」的端點 | 有：`GET /api/contractors/export`（xlsx，`@export_logged` 寫稽核、`_require_user(module='contractor_list', superadmin)`，證件號碼遮成末 4 碼）、`/api/cashier/export`、`/api/reports/tax-export`、`/api/shipping-notes/export-history` 等；多數**自己檢查權限並寫稽核** | `modules/*/api/*.py` |
| 頁面存取 | 選單可見性：`core.menu.visible(perm, modules, superadmin)`、`denied()`；頁面自己載入 `auth-guard.js` 並由伺服器檢查頁面對應的模組 | `core/menu.py`、頁面 |
| 側欄改名／換群組 | 已有（BP-1 選單建構器，旗標 `builder_menu`）；**新增按鈕沒有** | `BP1-MENUS-T59.md` §已知缺口 5 |
| 宣告式「掛載點」先例 | `mount_points`（module.json 頂層鍵，自己的驗證器 `core.mounts`，掛進 `validate_manifest`） | `core/customization.py:131` |
| 資料驅動的新定義種類 | `register_kind()`（新增一種定義不必改 L0 檔）；S5 沿用；3e 的管線以 `ACTIVE_KINDS` 名單接管發布／還原 | `core/definitions.py`、`def_pipeline.py` |

## 2. 範圍與硬規則

**第一批動作類型（目錄的全部內容）**
| 類型 | 參數 | 執行 |
|---|---|---|
| `navigate`（開啟頁面） | `page`＝已登記頁面檔名（例 `shipping-export-history.html`） | 瀏覽器導向 `pages/<page>`；不帶查詢字串、不開新分頁以外的任何選項（`target=_blank` 固定關閉） |
| `export`（執行匯出） | `export`＝`<模組>:<匯出 key>`（來自 `module.json` 已登記的 `exports`） | `fetch(端點, {headers: 點擊者的 token})` 取回檔案後下載；參數只有登記的固定值（第一批匯出一律無參數） |

**寫死的限制（不可由設定放寬）**
1. 沒有會寫資料的動作（不呼叫 POST/PUT/PATCH/DELETE；`export` 目標的 HTTP 方法限 `GET`）。
2. 沒有外部網址、`javascript:`、`data:`、任意端點；目標只來自目錄。
3. 按鈕文字：純文字、1～20 字，拒絕 `< > & " ' \` \\` 與控制字元（沿用側欄改名的 `sidebar_label_problem` 規則），一律以 `x-text`／`textContent` 渲染。
4. 每個插槽最多 6 顆、每頁最多 3 個插槽、每個單位（公司）最多 30 顆。
5. 按鈕**不改變**目標的權限與遮蔽；不帶任何額外參數、不傳遞頁面上的資料（第一批沒有「帶入目前單據」）。
6. 旗標 `builder_actions.enabled` 預設關閉；關閉＝頁面逐位元不變（沒有請求、沒有區塊）。

## 3. 動作目錄與插槽的宣告格式

**3.1 匯出目錄（現成格式，模組補登記）** ——不新增格式：

```json
"customization": { "pages": [ { "page": "contractors.html", ...,
  "exports": [ { "key": "roster", "label": "外包名冊", "endpoint": "GET /api/contractors/export", "format": "xlsx", "perm": "contractor_list" } ] } ] }
```
規則：被當作「可被使用者按鈕執行」的匯出，必須是 `GET`、無必填參數、端點自己檢查權限並寫稽核（`@export_logged` 或等價）。登記是**模組擁有者的決定**（程式碼審查項目），使用者不能登記。

**3.2 插槽（新；先導放 L1 helper，之後可搬 module.json）**

```json
"button_slots": [ { "page": "suppliers.html", "key": "toolbar", "label": "工具列", "max": 6 } ]
```
- 頁面用 `<div data-button-slot="toolbar"></div>` 標出位置（守門：宣告的插槽必須在頁面 HTML 出現，反之亦然——比照 `mount_points` 的 G-M1）。
- 先導階段（不動 L0）：插槽表是 `helpers/user_buttons.py` 的程式內常數 `SLOTS = {("supply","suppliers.html"): [("toolbar","工具列")]}`；之後核心層同意再改成 module.json 宣告（驗證器 `core/button_slots.py` 掛進 `validate_manifest`，與 `core/mounts.py` 同型）。

**3.3 可開啟頁面目錄**：模組 `pages[].path` ∪ `core/l1_pages.json`；排除登入頁、公開頁與需要查詢字串才有意義的頁面（`customer-log.html`、`supplier-log.html`…，以 `NAVIGABLE` 反向清單在 helper 內明列，守門測試鎖住）。

## 4. 定義與儲存

- kind：`user_buttons`，key＝`module:<模組鍵>`（與 layout 同鍵風格），scope＝`company`（第一批不做角色層）。
- body：

```json
{ "buttons": [
  { "key": "b1", "slot": "suppliers.html/toolbar", "label": "出貨匯出紀錄",
    "action": { "type": "navigate", "page": "shipping-export-history.html" } },
  { "key": "b2", "slot": "suppliers.html/toolbar", "label": "外包名冊",
    "action": { "type": "export", "export": "subcontract:roster" } }
] }
```
- `key`：`b<序號>`（編輯器自動產生，使用者看不到），發布後不改；刪除＝從清單拿掉（按鈕沒有資料，不需要「停用」）。
- 不認得的鍵＝驗證問題（不靜默丟棄）。順序＝陣列順序（同一插槽內）。

## 5. 驗證器（發布前，`definition_problems`）

按鈕數量上限、`slot` 必須是登記的插槽、`label` 規則、`action.type ∈ {navigate, export}`、`navigate.page` 必須在可開啟頁面目錄且不在排除清單、`export.export` 必須是已登記的匯出且方法為 GET、不得有多餘的鍵（`href`、`url`、`query`、`method`、`params`、`confirm`…一律拒絕）。模組沒載入／頁面被移除 ⇒ 該按鈕在執行期**不出現**（缺席說明列在管理員的編輯器，不炸頁面）。

## 6. 執行期與「點擊時的權限」

**取得按鈕**：`GET /api/user-buttons/{module}/{page}`（登入者）→ 伺服器讀已發布定義，**逐顆用點擊者的權限過濾**：
- `navigate`：目標頁面在點擊者的選單可見性內（`core.menu.denied` 的反面）才回；
- `export`：點擊者的模組／角色滿足該匯出登記的 `perm`（超級管理員另依端點自己的規則）才回；
- 目標模組沒載入／未授權 ⇒ 不回。
回應只含 `{key,label,type,page|exportEndpoint}`，不含其他按鈕的存在。旗標關閉 ⇒ `{enabled:false, buttons:[]}`。

**點擊**：
- `navigate`：瀏覽器導向目標頁；目標頁的 `auth-guard.js`＋伺服器模組檢查照舊。
- `export`：`fetch(登記的端點, Authorization: 點擊者 token)`；端點自己驗證（401/403 ⇒ 顯示伺服器訊息，不重試）、遮蔽、寫稽核；按鈕端**不做任何額外授權決定**。
- 按鈕端沒有自己的稽核（目標已有）；定義的發布／還原記帳本與稽核（既有）。

**反例必測**：按鈕目標點擊者本來進不去／匯不出 ⇒ 不顯示；繞過 UI 直接呼叫匯出端點 ⇒ 端點照樣 403（按鈕沒有放寬任何東西）；偽造的定義（直接打 API 存入）驗證器擋下。

## 7. 放置與 P9 版面引擎

- 第一批：按鈕只能放進登記的插槽，順序＝定義順序；編輯器內調順序。
- 與 P9 的關係：使用者按鈕**不是** `module.json` 的點，P9 看不到它們（與 S5 的自訂欄位同一個限制）。要讓 P9 能隱藏／改名／移動它們（按角色），需要 `core.catalog` 的「動態點提供者」——與 S5、T60-S3 同一個核心層案，**不在第一批**。
- 側欄改名／換群組（BP-1 選單建構器）是另一回事，不受影響。

## 8. 預覽

- **即時預覽**：編輯器的草稿即時畫在真實頁面的插槽裡（`mode='edit'` 標示「預覽（草稿，尚未發布）」），不存任何東西。
- **以角色／使用者預覽**：`POST /api/user-buttons/preview {buttons, user?|role?}`（唯讀、僅超級管理員、旗標關 ⇒ 404）：伺服器對草稿用指定對象的真實權限過濾，回 `{visible:[…], hidden:[{key, reason}]}`（`reason` 白話：「這個角色打不開『…』」）。**不執行任何動作**。
- 發布前要求先看過預覽（沿用 3e 的影響預覽鉤子）。

## 9. 治理（3e 的管線）

- `user_buttons` 加進 `ACTIVE_KINDS`；比較函式：新增／改成 `export` 類按鈕＝**放寬**（多一個資料外送入口，需第二位最高管理者核准）；新增／改成 `navigate`＝中性（只是連結，目標自己擋）；移除任何按鈕＝收緊；改標籤＝中性；無法判斷＝放寬（既有慣例）。
- 版本、差異、還原、快照＝既有定義文件庫；待核准時編輯器如實顯示（S5 的元件已有）。
- 新的**動作類型**（不是新按鈕）屬程式變更，不在使用者能力內：加一種類型＝改驗證器與派發器＋安全審查＋使用者裁示。

## 10. 測試與守門

1. 驗證器逐項反例（每個限制一題）：未知類型、`href/url/query` 鍵、外部網址、`javascript:`、不在目錄的頁面、排除清單頁面、未登記或非 GET 的匯出、標籤含 `<`／引號／過長、超過數量上限、未登記的插槽。正對照：合法定義通過。
2. 逐角色矩陣（admin／sales／finance／cashier／engineer／viewer／superadmin）：按鈕清單只含該角色打得開／匯得出的目標；偽造 token 與未登入 401。
3. **按鈕不放寬**：對每個登記的匯出，用沒有權限的角色直接呼叫端點仍 403（與有沒有按鈕無關）；發布按鈕前後，該角色對目標的存取結果位元相同。
4. XSS：標籤含標記字元被驗證器擋；即使資料庫被直接寫入，渲染用 `x-text`（node 測試把 `<img onerror>` 放進去，確認只是文字）。
5. 旗標關閉：端點回空、頁面不畫插槽內容、不多任何請求以外的東西（node 中性題）；頁面其餘 DOM 不變。
6. 預覽：唯讀（資料庫無任何寫入）、指定對象的權限被真實套用、旗標關 404、非超級管理員 403。
7. 守門：`data-button-slot` 與插槽表一致（兩個方向，正對照）；`NAVIGABLE` 排除清單鎖定；匯出登記必須是 GET 且 `perm` 在模組 `permissions` 內。
8. 治理：export 新增 ⇒ pending；navigate 新增 ⇒ 立即；還原到含 export 的舊版 ⇒ pending。

## 11. 風險

| # | 風險 | 對策 |
|---|---|---|
| R1 | 按鈕成為資料外送／提權入口 | 按鈕不傳任何參數、不授權；匯出端點照舊驗證；`export` 新增需第二人核准；匯出端點本身寫稽核 |
| R2 | 使用者命名誤導（例：把匯出命名「回上頁」） | 標籤純文字＋編輯器固定顯示目標名稱（「→ 執行匯出：外包名冊」）；匯出類按鈕畫面上固定帶下載圖示（管理者無法移除） |
| R3 | 目標被移除／改權限後按鈕失效 | 執行期過濾（不出現）；編輯器列出「目標已不存在」警示，不自動刪 |
| R4 | 匯出檔含個資 | 只能選「模組已登記」的匯出（登記時審查）；匯出端點本身的遮蔽／稽核不變；第一批不登記含完整個資的匯出（外包名冊證件號碼已遮蔽末 4 碼，仍列使用者決定） |
| R5 | 與 P9 的疊加（同一區域兩套擺放） | 插槽專用區，P9 的點不在其中 |
| R6 | 頁面改版刪了插槽容器 | 守門雙向檢查；缺席時按鈕不出現且編輯器警示 |

## 12. 工量（pd，估）

| 項目 | pd |
|---|---|
| `helpers/user_buttons.py`（目錄、插槽表、驗證器、過濾、預覽函式）＋`user_buttons` kind 與路由（`GET`、`preview`） | 3 |
| 前端執行時（插槽渲染、導向／下載）＋編輯器面板（沿用 S5 元件改造，含預覽、兩段式確認、待核准） | 3 |
| 先導一個畫面的接線＋一個匯出的登記 | 1 |
| 測試（驗證器、角色矩陣、不放寬、XSS、node 中性題、治理）＋文件 | 2 |
| 合計（先導） | 約 9 |
| 之後每個頁面的插槽 | 0.3～0.5 |
| 核心層（module.json `button_slots`、P9 動態點）另案 | 約 3～4 |

## 13. 需要使用者決定的事

1. **確認第一批只有「開頁」與「執行匯出」**（D1），且匯出只限模組登記的、無參數的 GET。
2. **誰能建立／發布按鈕**：建議只有最高管理者（與版面、自訂欄位一致）。
3. **`export` 類按鈕新增要不要第二位最高管理者核准**（建議要；`navigate` 不用）。
4. **哪些匯出可以被登記**（建議：第一批只登記外包名冊 xlsx 這類已遮蔽個資、本來就限定模組的匯出；出納匯出、稅務匯出不登記）。
5. **插槽放哪些頁面**（建議先導＝供應商管理頁的工具列）。
6. **插槽宣告要不要升級成 `module.json` 的 `button_slots`**（需 L0 驗證器，與 S5/S3 的核心層案一起決定）。
7. 數量上限（每插槽 6、每頁 3 個插槽、全公司 30）是否合適。

## 14. 步驟 2（先導）建議範圍

供應商管理頁（`suppliers.html`）加一個「工具列」插槽；動作目錄＝可開啟頁面 ∪ 一個登記的匯出（`subcontract:roster`＝`GET /api/contractors/export`，需先在 `modules/subcontract/module.json` 補登記）；旗標 `builder_actions.enabled` 預設關；證明標準同 S5（旗標關閉＝逐位元不變的 node／API 證明、角色矩陣、按鈕不放寬、XSS、治理、編輯器預覽）。
