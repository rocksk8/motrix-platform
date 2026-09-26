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

- loader 在載入每個模組時收集 `module.json` `pages[].path` ⇒ `registry.page_map: {檔名: (模組key, 絕對路徑)}`；**同名衝突（兩個模組或模組與 L1 撞名）⇒ 啟動失敗**，不靜默覆蓋。〔更正（B，2026-09-26 01:14，主持裁示）：不讓整台起不來（可販售產品）⇒ 比照 STATES-PLATFORM P-LD-07 路由衝突：依 key 排序先到先得，後到的模組**整個**記 failed、不掛（在 mount_modules 之前檢查），記 ERROR，模組管理頁與 D5 看得到原因；實作在 `core.pages.check_and_register`，page_map 不放 registry〕
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

〔更正（B，2026-09-26，C3 實作後定案；**此後不再改**，P1＋P3 依此格式）：上面的範例與三條說明有四處與實作不同，以下為準——
① **沒有 `icon`**：`renderMainNav()`（2026-09-14 側欄改上方下拉）早已不畫圖示，而且舊碼的 `radar`／`vouch`／`acct`／`bonus`／`co` 根本不在 `ic` 字典裡；留著是死資料。
② **`perm` 是清單或兩個固定字串**：`["k1","k2"]`（任一模組權限；最高管理者一律可）／`"superadmin"`／`"any"`——舊碼有 `cRpt || cFi`、`true`、`sa` 三種，單一字串表達不了。
③ **群組定義在 `core/menu_l1.json` 的 `groups`**，沒有另一個 `menu_groups.json`。
④ 其餘欄位：`order`（整數，同群組內排序；標案雷達實際是 20，排在業務開發 10 與地圖 30 之間）、選填 `active`（預設＝該頁本身）、`badge`（徽章元素 id）、`extra_badge`（`{"id","color"}`）。**不認得的欄位 ⇒ `core.menu.validate` 報錯**。
定案範例：`"menu": {"group": "business", "label": "標案雷達", "order": 20, "perm": ["tender_radar"], "badge": "sb-mod-tender-radar"}`〕

**產生**：`GET /api/platform/menu` 回傳目前使用者看得到的群組與項目：
`L1 項目 ∪ 已啟用模組的項目` → 依 `perm` 過濾（同 `computeFlags` 的 `has(k)`）→ 依 group 順序、`order` 排序。

**前端**：`buildSidebar()` 改成呼叫這支 API 再交給現有的 `renderMainNav()`（渲染不動）。`_hideUnavailableModulePages()` 與 `_FILE_MODULE` 在切換完成後刪除（資料改由 menu 回應帶 `module`）。

〔更正（B，2026-09-26，主持裁示）：**不改成打 API 再畫**。舊選單是同步渲染，獎金入口隱藏、未載入模組入口隱藏、`_deniedPages` 無權限提示與大量 e2e 都假設選單已經在畫面上；改成非同步＝〈先渲染再非同步載入〉競態。改為：
- ~~伺服器提供 `/static/sidebar.js` 時在最前面接上 `window.MOTRIX_MENU = {…}`（L1＋已載入模組的宣告，含 `perm`；與使用者無關、每個請求現查模組狀態）；前端用原本的 `has()` 同步過濾後交給 `sec()`／`ni()`，時序不變，HTML 不用改。~~
  〔更正（主持裁示 2026-09-26，選 A；C4 第一個 commit）：P9 的角色版面（側欄點的 hide／move index）跟使用者角色有關，而載入 `<script src=sidebar.js>` 的請求沒有 Bearer token ⇒ 伺服器在注入處算不出角色。改為三點：
  ① **`MOTRIX_MENU` 只放與使用者無關的宣告**（L1＋已載入模組~~＋已發布自訂模組~~的項目，含 `perm`；每個請求現查模組狀態）；首屏照舊同步渲染、權限同步過濾（`has()`），時序不變、HTML 不用改。
     〔更正（B，2026-09-26 12:57，C4 步驟 ② 實作時；主持確認）：**自訂模組與模組狀態不放進 `MOTRIX_MENU`**——`/static/sidebar.js` 不需登入就拿得到，自訂模組名稱是公司資料、模組狀態原本在要登入的 `/api/system/modules/availability`；兩者改在 ② 的 `/api/platform/menu` 階段出現（自訂模組原本就是非同步追加，無退步）。實際內容 `{v, groups, pageModules}`（`routers.platform_menu.menu_declaration`）。
     **主持判定**：`MOTRIX_MENU` 讓未登入的人讀得到「這套安裝有哪些模組」（L1＋已載入模組的標籤與 perm）——**可以接受**：登入頁本身就顯示產品，而這是程式宣告、不是資料。界線是**不含任何來自資料庫的字串**（自訂模組、公司名稱等）；守門 `tests/platform/test_menu_inject.py::test_motrix_menu_contains_no_database_strings`（先寫入哨兵字串並以登入 API 讀回當正對照），反向控制 `test_rc_database_string_leak_would_be_caught`（宣告併入已發布自訂模組 ⇒ 判準要抓到）。〕
  ② **session 取回之後**打 `GET /api/platform/menu`（回「已套角色 layout 的結果」）**再重排一次**；讀失敗 ⇒ 保留宣告版，而且要明說（console 一筆＋側欄 data 屬性），不可以靜默。
  ③ 這是「先渲染、再非同步套用」＝〈先渲染再非同步載入＝競態〉那一型，守三件事：
     - 角色 layout 的 **hide 只是顯示、不是權限**：重排前被點到的項目本來就是使用者有權限的頁面 ⇒ 無害；伺服器端權限不看 layout（附題：hide 不影響伺服器端權限）
     - 側欄 **`data-menu-state`＝`declared`／`layout`／`layout-failed`**，當 e2e 的等待終點
     - 重排以**序號**丟掉較晚回來的舊回應（同 O7）
  另：套用 layout 的 `apply_layout` 與 `GET /api/layout/{module}` 共用同一個 resolve＋`check_layout`（不複製）；U17 裁示前照「整份」resolve。〕
- `GET /api/platform/menu`（伺服器端過濾）保留給其他使用端。
- ~~C4 同時把**已發布的自訂模組**（P8，`custom-modules-nav.js` 以 MutationObserver 在 `#app-mainnav` 追加）納入 `MOTRIX_MENU` 的來源，`custom-modules-nav.js` 退場 ⇒ 選單只有一個來源。~~
  〔更正（B，2026-09-26 12:57，同上）：自訂模組改由 session 之後的 `/api/platform/menu` 帶（依使用者權限過濾，規則與 `/api/custom-modules` 共用），sidebar.js 在套 layout 那一步一起渲染；`custom-modules-nav.js` 照樣退場 ⇒ 選單仍只有一個渲染者。〕
- 時機：C1、C3、P8 前端合回之後；開工時主持通知各視窗凍結 sidebar.js 相關測試直到 C4 合回（約 15 個測試檔以靜態解析讀 `ni()`／`sec()`，要改讀 `core/menu_l1.json`）。C3 的對等守門在 C4 退場。〕

## 5. 轉換順序（每一步都可單獨合回、單獨回退）

| 步 | 內容 | 驗證 |
|---|---|---|
| C1 | `core.pages` 路由＋`registry.page_map`；**頁面還沒搬**，page_map 指向 `frontend/pages/`（tender_radar 先宣告） | 停用 tender_radar ⇒ `/pages/tender-radar.html` 404；啟用 ⇒ 200；撞名 ⇒ 啟動失敗（反向控制）〔更正：撞名 ⇒ 後到的模組記 failed、不掛（同上）；停用 ⇒ 404＋提示頁（D2 更正）〕 |
| C2 | 路徑解析集中：`core.source_tree.page_file(name)`（依 page_map），測試與工具改用它；dep_scan 的 `page:` 單位名改成**邏輯名**（`page:pages/x.html`，與實體位置無關）⇒ modules.json／test_map 不用跟著搬家改 | 全量；守門：`frontend/pages` 字面值只准出現在 `source_tree`（反向控制：新增一處寫死 ⇒ 紅） |
| C3 | 選單：`menu_groups.json`、`menu_l1.json`、各模組 `pages[].menu`、`/api/platform/menu`；**新舊並行**：`sidebar.js` 仍用舊選單 | **對等守門**：以超級管理員與每一種單一模組權限，比對 API 產生的選單與舊 `buildSidebar()` 的項目（href、label、群組、順序）完全一致 |
| C4 | `sidebar.js` 切到 API；刪 `_hideUnavailableModulePages`／`_FILE_MODULE` | e2e：停用模組 ⇒ 選單項消失、頁面 404（PLAYBOOK §A 完成條件）；所有會開頁的 e2e（〈頁面結構改動的 e2e 範圍〉） |
| C5 | 逐模組實體搬家（依 PLAYBOOK §B 的模組順序，搬一個合一個）：`git mv` 頁面與專屬 JS，module.json `pages` 補齊 | 該模組的 e2e＋tests/platform；`product_select`／`module_update` 的包內路徑改為模組資料夾（見 §6）〔補（稽核 D P-O2，2026-09-26）：`core.pages.PAGE_NAME` 只接受 `.html`；模組頁面要附圖片或 js 時，另訂位置或放寬規則，並一併補守門〕 |

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
| D2 | 停用模組的頁面回 404 或導向「模組未啟用」說明頁 | **404**（與端點一致、守門好寫）；前端 `auth-guard` 可以在 404 時顯示友善訊息〔更正（B，2026-09-26 01:14）：這個推薦是在沒看到 STATES-PLATFORM P-FE-03（A2，「直接打網址 ⇒ 提示頁，不是 404」）的情況下做的，設計時漏查。主持裁示改採選項 A：**HTTP 404＋伺服器產生的提示頁**（四種文案、`data-testid=module-unavailable`），頁面本體不送出；sidebar.js 的前端提示框留作後備（伺服器不認得該頁屬於哪個模組時）〕 |
| D3 | 頁面 URL 要不要加伺服器端權限檢查 | **本階段不加**：頁面是殼、資料由 API 守門；加了要處理未登入導向 login 的流程，另開一項 |
| D4 | 選單群組是否允許模組自訂 | **不允許**（固定鍵＋L1 定義），自訂選單屬於 CUSTOMIZATION（使用者層），不是模組層 |

## 8. 不在本階段

- 選單的使用者自訂（隱藏、排序、改名）：屬 CUSTOMIZATION-SPEC，建在本階段的 menu API 之上。
- 端點登錄表 `GET /api/platform/endpoints`（ROADMAP 階段 C 第三項）：與頁面無相依，另開一項。
- 行動版（R7）。
