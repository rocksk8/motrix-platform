# 階段 C 設計：頁面進模組資料夾、選單由登錄表產生

> 狀態：草案（B，2026-09-26 00:03 起草），待主持裁示 §7 的決策點。對應 ROADMAP 階段 C、PLAYBOOK §A 第 6 階段。
> 完成條件（PLAYBOOK §A）：**關閉模組後選單消失、頁面回 404**。

## 1. 現況（2026-09-26 盤點，wip/b-hardcap）

| 項目 | 現況 | 位置 |
|---|---|---|
| 頁面提供 | `app.mount("/", StaticFiles(FRONTEND_DIR, html=True))`；URL 一律 `/pages/x.html`；**伺服器不檢查頁面權限**，也不看模組狀態 ⇒ 關閉的模組頁面照樣 200 | `backend/main.py:715` |
| 頁面守門 | 只在前端：`auth-guard.js` 看 session，`sidebar.js` `_deniedPages` 顯示「無權限」 | `frontend/static/` |
| 選單 | 寫死在 `sidebar.js` `buildSidebar()`（9 組、`sec()`／`ni()`、圖示字典 `ic`、排序＝程式碼順序）；權限用 `computeFlags()` 對 `/api/auth/me` 的 `modules` | `sidebar.js:476-805` |
| 模組停用 | 事後隱藏：`_hideUnavailableModulePages()` 打 `GET /api/system/modules/unavailable-pages`，來源是 module.json `pages`（目前只有 tender_radar 宣告） | `sidebar.js:1153`、`routers/system.py:761` |
| registry | `ModuleSpec` 沒有 pages／menu；loader 不掛靜態路徑；`CORE-SPEC.md:51` 規格裡的 `pages[].menu` 沒有程式使用 | `core/registry.py:26`、`core/loader.py:67` |
| 頁面數 | 56（含 index）：L1 21、M01 8、M02 1、M03 4、M04 3、M05 3、M06 2、M07 3、M08 6、M10 3、M11 1、M12 1 | `docs/platform/modules.json` |
| 相對路徑 | 頁面內 `../static/` 297、`../css/` 52、`../js/` 16 | `frontend/pages/*.html` |
| 寫死 `/pages/` | `sidebar.js:83,88`、`auth-guard.js`、`notif.js`；後端 `routers/auth.py:493`、`helpers/email_notify.py`（寄出的信裡的連結）；前端約 40 處字串 | — |
| e2e | 約 173 處 `.../pages/x.html`，92 檔，無共用 helper | `backend/tests`、`modules/*/tests` |
| 讀原始碼的測試 | 68 檔用 `ROOT/"frontend"/"pages"/x.html` 做靜態斷言，各自拼路徑 | — |
| 工具／守門 | `dep_scan`（`page:` 單位名＝相對 frontend 路徑）、`test_map`、`product_select`、`module_update`、`product_drill`、`verify_package`、G4 changelog 守門、`test_module_boundaries` | `tools/platform/`、`backend/tests/platform/` |

## 2. 核心決定：**實體搬家，URL 不變**

頁面檔搬到 `backend/modules/<key>/pages/x.html`，**對外 URL 仍是 `/pages/x.html`**。

理由（每一條都是「換 URL」要付的代價）：
- 已寄出的 email 連結（`email_notify.py`）指向 `/pages/…`，換 URL 會讓歷史信件失效，而這是正式機客戶手上的東西。
- 頁面內 365 處 `../static`／`../css`／`../js` 相對路徑依賴「在 /pages/ 底下一層」；URL 不變 ⇒ 一處都不用改。
- `sidebar.js`／`auth-guard.js`／`notif.js` 以 `'/pages/'` 判斷目錄深度 ⇒ 不用改。
- 173 處 e2e 與書籤不用改。

搬家只改「檔案在哪」，不改「怎麼被找到」。

## 3. 頁面提供：`core.pages`（L1，新增）

```
GET /pages/{name}.html
  name 屬於 L1（仍在 frontend/pages/）            ⇒ 照舊檔案回應
  name 屬於已啟用模組（registry 的 page map）       ⇒ 回應 modules/<key>/pages/<name>.html
  name 屬於已安裝但停用／未授權的模組               ⇒ 404
  都不是                                          ⇒ 404
```

- loader 在載入每個模組時收集 `module.json` `pages[].path` ⇒ `registry.page_map: {檔名: (模組key, 絕對路徑)}`；**同名衝突（兩個模組或模組與 L1 撞名）⇒ 啟動失敗**，不靜默覆蓋。
- 路由在 `StaticFiles` mount 之前註冊（mount `/` 會吃掉所有路徑）。快取標頭沿用 main.py:213 的 `no-cache` 規則；`_REFERER_RELAXED_PATHS` 是 URL 比對，不受影響。
- 停用時回 404 而不是 403：與端點行為一致（CORE-SPEC 啟停守門「關閉後，端點回 404」）。
- 頁面的權限檢查**不在這一層加**（現況也沒有；頁面是殼，資料由 API 守門）。要不要加列在 §7 D3。
- 模組頁面用到的專屬 JS（`frontend/js/` 16 支中屬於模組的）一起搬進 `modules/<key>/js/`，URL 同樣不變（`/js/x.js`）。共用的 `static/`、`css/` 留在 frontend。

## 4. 選單：`module.json` 的 `menu` ＋ `GET /api/platform/menu`

**宣告**（每一個頁面自己宣告，模組沒裝就沒有這一項）：

```json
"pages": [
  {"path": "tender-radar.html",
   "menu": {"group": "business", "label": "標案雷達", "icon": "radar", "order": 40,
            "perm": "tender_radar", "badge": null}}
]
```

- `group` 用固定鍵（`main／business／case／supply／device／finance／payroll／mywork／system`），名稱與順序由 L1 的 `core/menu_groups.json` 定義 ⇒ 模組不能自己開新群組（避免選單長歪）；要新群組走 L1 次版號。
- L1 頁面（使用者、組織、稽核…）的選單項寫在 `core/menu_l1.json`，同一個格式。
- 圖示：`sidebar.js` 的 `ic` 字典搬成 `frontend/static/menu-icons.js`，`icon` 只能是字典裡的鍵（守門檢查）。

**產生**：`GET /api/platform/menu` 回傳目前使用者看得到的群組與項目：
`L1 項目 ∪ 已啟用模組的項目` → 依 `perm` 過濾（同 `computeFlags` 的 `has(k)`）→ 依 group 順序、`order` 排序。

**前端**：`buildSidebar()` 改成呼叫這支 API 再交給現有的 `renderMainNav()`（渲染不動）。`_hideUnavailableModulePages()` 與 `_FILE_MODULE` 在切換完成後刪除（資料改由 menu 回應帶 `module`）。

## 5. 轉換順序（每一步都可單獨合回、單獨回退）

| 步 | 內容 | 驗證 |
|---|---|---|
| C1 | `core.pages` 路由＋`registry.page_map`；**頁面還沒搬**，page_map 指向 `frontend/pages/`（tender_radar 先宣告） | 停用 tender_radar ⇒ `/pages/tender-radar.html` 404；啟用 ⇒ 200；撞名 ⇒ 啟動失敗（反向控制） |
| C2 | 路徑解析集中：`core.source_tree.page_file(name)`（依 page_map），測試與工具改用它；dep_scan 的 `page:` 單位名改成**邏輯名**（`page:pages/x.html`，與實體位置無關）⇒ modules.json／test_map 不用跟著搬家改 | 全量；守門：`frontend/pages` 字面值只准出現在 `source_tree`（反向控制：新增一處寫死 ⇒ 紅） |
| C3 | 選單：`menu_groups.json`、`menu_l1.json`、各模組 `pages[].menu`、`/api/platform/menu`；**新舊並行**：`sidebar.js` 仍用舊選單 | **對等守門**：以超級管理員與每一種單一模組權限，比對 API 產生的選單與舊 `buildSidebar()` 的項目（href、label、群組、順序）完全一致 |
| C4 | `sidebar.js` 切到 API；刪 `_hideUnavailableModulePages`／`_FILE_MODULE` | e2e：停用模組 ⇒ 選單項消失、頁面 404（PLAYBOOK §A 完成條件）；所有會開頁的 e2e（〈頁面結構改動的 e2e 範圍〉） |
| C5 | 逐模組實體搬家（依 PLAYBOOK §B 的模組順序，搬一個合一個）：`git mv` 頁面與專屬 JS，module.json `pages` 補齊 | 該模組的 e2e＋tests/platform；`product_select`／`module_update` 的包內路徑改為模組資料夾（見 §6） |

C1、C2 不影響使用者畫面；C3 只加不改；C4 是唯一改變前端行為的一步。

## 6. 對既有工具與守門的影響

| 對象 | 改法 |
|---|---|
| `product_select` | 移除模組＝刪整個 `modules/<key>/`，頁面自動跟著走；`frontend/pages/<path>` 的刪除邏輯在該模組搬完後刪掉（過渡期兩邊都查） |
| `module_update`（P7） | 模組包本來就打包 `modules/<key>/`；lock 的 pages 雜湊改讀 page_map；過渡期頁面在 frontend 的仍照現行 |
| G4 changelog 守門 | 頁面在模組資料夾內 ⇒ 自然屬於「模組程式檔」；`frontend/pages/<path>` 的額外規則在全部搬完後刪除 |
| G2 模組包檔案 | 新增：`pages[].path` 必須在 `modules/<key>/pages/` 或（過渡期）`frontend/pages/` 存在；`menu.icon` 必須在字典內；`menu.group` 必須在 `menu_groups.json` |
| 模組邊界守門 | 新增：模組頁面不可以引用別的模組的 `js/`（同 L2 import 規則；共用的東西下沉到 `static/`） |
| `verify_package` | 誘餌路徑 `frontend/pages/index.html` 是 L1 頁面，不受影響 |
| 68 個讀原始碼的測試 | C2 改用 `page_file()`；機械式替換，一次一個模組 |

## 7. 待裁示

| # | 問題 | 推薦 |
|---|---|---|
| D1 | URL 維持 `/pages/x.html`（本文）或改 `/m/<key>/x.html` | **維持**：換 URL 會讓已寄出的信件連結失效，而收益只有「看得出屬於哪個模組」，這個資訊 page_map 已經有 |
| D2 | 停用模組的頁面回 404 或導向「模組未啟用」說明頁 | **404**（與端點一致、守門好寫）；前端 `auth-guard` 可以在 404 時顯示友善訊息 |
| D3 | 頁面 URL 要不要加伺服器端權限檢查 | **本階段不加**：頁面是殼、資料由 API 守門；加了要處理未登入導向 login 的流程，另開一項 |
| D4 | 選單群組是否允許模組自訂 | **不允許**（固定鍵＋L1 定義），自訂選單屬於 CUSTOMIZATION（使用者層），不是模組層 |

## 8. 不在本階段

- 選單的使用者自訂（隱藏、排序、改名）：屬 CUSTOMIZATION-SPEC，建在本階段的 menu API 之上。
- 端點登錄表 `GET /api/platform/endpoints`（ROADMAP 階段 C 第三項）：與頁面無相依，另開一項。
- 行動版（R7）。
