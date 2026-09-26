# 稽核：B 的 C4 側欄選單改由伺服器提供（wip/b-c4-2；合回前）（X 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 X 沒有寫過任何受稽核的程式碼。
> 對象：`origin/wip/b-c4-2` `dd20cc5d`（月台登記在 origin/platform `3e017154`）。依據：STAGE-C-DESIGN.md L79 起的主持裁示 A 三點更正、RUN-PLAN §6 的 C4 裁示。
> 環境：X 自己的稽核樹 `D:\MOTRIX-PLATFORM-XC4`（detached 於 dd20cc5d），`.venv312`；`MOTRIX_PYTEST_SLOTS=4`；非 e2e 用 `-n 4`，e2e 用 `-n 2`；起跑前可用記憶體 12.9 GB；basetemp 用專屬資料夾（`bt_xc4`、`bt_xc4b`），用完只刪這兩個。沒有跑全量，也沒有改受稽核分支。突變由腳本套用（取代前先 assert 只對到一處），跑完寫回原內容並比對。

## 0. 結論

**必修 1、建議 5、觀察 7。**
- 競態的三道防線都有題，而且突變會紅：序號（成功路徑）、`layout-failed`＋console、`data-menu-state` 等待終點、徽章保留。
- 外洩守門有效：公司名稱與自訂模組名稱寫進宣告時都會紅。
- 7 項搬遷實測通過：刪掉 5 個模組資料夾後，7 個入口從 `MOTRIX_MENU`、`/api/platform/menu` 的 groups 與 layout 全部消失；`check_l1_pages` 的反向控制在完整樹與縮減樹都會紅。
- **必修**：「hide 不影響伺服器端權限」這一題是假綠燈（C4-M1）。把伺服器改成「版面 hide ⇒ 403」之後，這一題照樣綠。

## 1. 基準

| 範圍 | 結果 |
|---|---|
| `tests/platform/test_menu.py`、`test_menu_inject.py`、`test_menu_layout.py`（-n 4） | 34 passed，0 skip |
| `tests/platform/test_e2e_menu_layout.py`＋`tests/test_e2e_unread_marks_clear_on_click_2026_09_24.py`（-n 2） | 13 passed |
| 拿掉 crm／daily_tasks／netplan／payroll／subcontract 後（`ls backend/modules` 只剩 `__init__.py`、analytics、tender_radar）：上面三個非 e2e 檔＋X 的探針題 | 35 passed |
| 同一棵縮減樹：`test_e2e_menu_layout.py`（-n 2） | 5 passed |

`_pick()` 在完整樹取到的模組是 `analytics`（`reports.html`，probe 是 `/api/dashboard/stats`）。

## 2. 突變結果

| # | 突變（檔案） | 題 | 結果 |
|---|---|---|---|
| X1 | 成功路徑拿掉 `if (my !== _menuSeq) return`（sidebar.js:1059） | e2e 選單 5 題 | **紅**（`test_stale_layout_response_is_dropped`） |
| X2 | 失敗路徑拿掉序號檢查（sidebar.js:1067） | e2e 選單 5 題 | **綠 5 passed** ⇒ C4-S2 |
| X3 | 拿掉 `_setMenuState('layout-failed')` | `test_layout_failure_keeps_declared_menu_and_says_so` | 紅（逾時） |
| X4 | 拿掉 console.warn（失敗不明說） | 同上 | 紅 |
| X5 | 失敗時清空選單（`_layoutGroups = []; _rebuildMenu()`） | 同上 | 紅 |
| X6 | `_rebuildMenu` 不還原徽章的 display 與 text（sidebar.js:1030 起） | unread_marks e2e 8 題 | **紅 3**（B 說已修，X 確認有效） |
| X7 | 前端把版面 hide 掉的項目算進 `_deniedPages` | `test_role_layout_hides_the_item_but_not_the_page` | 紅 |
| X8 | **伺服器** `require_any_module`：非最高管理者且角色版面有 hide ⇒ 403（helpers/auth.py） | `test_menu_layout.py` 10 題 | **綠 10 passed** ⇒ C4-M1 |
| X9 | `sidebar_js_source` 在第二行加上 `window.MOTRIX_CUSTOM = <已發布自訂模組>` | `test_menu_inject.py` | 紅 1，但紅的是 `test_sidebar_js_is_prefixed_with_the_declaration`（本體比對），**外洩題本身是綠的** ⇒ C4-S3 |
| X10 | `menu_declaration` 加入 `system_settings.company_profile` 的內容 | `test_menu_inject.py` | 紅（`test_motrix_menu_contains_no_database_strings`） |
| X11 | `check_l1_pages` 一律回 `[]` | `test_menu.py` | 紅（`test_rc_l1_item_pointing_at_a_module_page_is_caught`） |
| X12 | 把 `dev-crm.html` 加回 `menu_l1.json`（完整樹） | `test_menu.py` | 紅 2（validate 重複、`test_l1_menu_never_points_at_a_module_page`） |
| X13 | 同 X12，但在拿掉 crm 等 5 模組的樹上跑 | `test_menu.py` | 紅 2（`test_l1_menu_never_points_at_a_module_page`、`test_removed_module_pages_are_not_in_the_served_menu`）：modules.json 的登記在模組不在時照樣生效 |

## 3. 逐項驗收

### ① 先渲染、再非同步套用的競態
- 序號：成功路徑會丟掉舊回應（X1 紅）；失敗路徑的序號沒有題守（X2，C4-S2）。
- 失敗時有明說：`data-menu-state="layout-failed"`，console 印 `[menu] … 保留宣告版`（X3、X4、X5 都紅）。
- `data-menu-state` 可以當首次載入的等待終點；但 `MotrixMenu.refresh()` 不會重設這個狀態，所以不能當「第二輪」的終點（C4-S1）。
- 徽章：`_rebuildMenu` 會記下 `#app-mainnav` 裡每個有 id 的元素的 display 與 textContent，重建後還原。notif.js 對徽章只寫這兩項（notif.js:287-293、312-318、343-349），所以覆蓋得到。X6 紅。

### ② 外洩
- 在完整樹上，`MOTRIX_MENU` 只有 `{v, groups, pageModules}`；自訂模組只在 `/api/platform/menu` 的 `layout` 出現（`core.menu.merge_custom`，menu.py:192）。
- 正對照（哨兵字串先寫進 DB，再用登入 API 讀回來）有效；X10 會紅。X9 見 C4-S3。

### ③ 權限
- 本分支沒有改到任何頁面或 API 的權限判斷。`custom_records.list_custom_modules` 改成呼叫 `CM.visible_to`（helpers/custom_modules.py:450），邏輯等價。前端的 perm 過濾只決定選單顯示；`/pages/*` 與各 API 的檢查照舊在伺服器端，而 `helpers/auth.py`、`core/pages.py` 都沒有讀 layout（X 已 grep 確認）。
- 伺服器端「hide 不是權限」目前沒有有效的題（C4-M1）。

### ④ 7 項搬遷
- 7 項為 dev-crm、vendor-contractors、network-plans、bonus、contractors、payslips、daily-tasks。宣告照原值（group／order／perm／badge／active／extra_badge）搬進 5 個 module.json。`menu_l1.json` 另外新增 `module-builder.html`（取代 custom-modules-nav.js 原本在「系統」組追加的那一項）。
- 刪掉資料夾實測（見 §1）：`DECL∩7 = API∩7 = LAYOUT∩7 = []`，宣告項目從 43 降到 36。正對照是完整樹上 7 項都在。
- sidebar.js 已經沒有寫死的入口。只剩徽章對照 `_FILE_MODULE`（sidebar.js:547）與 `_MOD_BADGES`（:959），見 C4-O6。

### ⑤ 版號與 CHANGELOG
- origin/platform 目前是 crm 1.0.5、daily_tasks 1.0.2、netplan 1.0.3、payroll 1.0.2、subcontract 1.0.4；本分支分別 +1，CHANGELOG 都有對應段落，與 h-probes（已合回）不撞號。
- **與 `origin/wip/c-probes`（8c440c47，尚未合回）撞號**：c-probes 也用了 crm **1.0.6**、payroll **1.0.3**、subcontract **1.0.5**，內容不同（C4-S5）。daily_tasks 1.0.3 與 netplan 1.0.4 不撞。

### ⑥ custom-modules-nav.js 退場
- 已刪除，repo 裡沒有頁面再引用它。e2e `test_custom_module_appears_after_layout` 通過：自訂模組項目出現，模組建構器也在，而且頁面上沒有 `script[data-custom-modules-nav]`。
- 行為差異見 C4-S4、C4-O7。

### ⑦ golden 忽略 `/api/platform/menu`
- 這個判斷合理。它與 `/api/auth/me`、`/api/custom-modules` 同一類：每頁都會打、與案件頁無關，次數還會隨 session 刷新而變（權限有變時多打一次）。golden 比對的是案件頁自己的請求清單，選單不在它的責任範圍。
- 真正的缺口是「選單每頁打幾次」目前沒有人守，見 C4-O2。這不構成後門，因為忽略清單只影響請求計數，不影響頁面文字比對。

## 4. 發現

### 必修

**C4-M1　「hide 不影響伺服器端權限」的題是假綠燈**（`backend/tests/platform/test_menu_layout.py:112`）
- 題目用 **superadmin** 登入。superadmin 在 `require_any_module` 第一行就直通（helpers/auth.py `if user["role"] == "superadmin": return`）。
- 題目打的是 `_pick()` 模組的 `probes[0]`，也就是 `/api/dashboard/stats`（modules/analytics/api/dashboard.py:26）。這支只呼叫 `_require_user(authorization)`，**完全不檢查模組權限**。
- 兩者加在一起，這一題不可能因為「伺服器端權限開始看版面」而紅。X8 已經實作這種退步（非最高管理者、角色版面有 hide ⇒ 403），`test_menu_layout.py` 10 題全綠。
- 主持裁示要求的是「附題：hide 不影響伺服器端權限」，目前等於沒有這一題。
- 修法：
  - 改用**非最高管理者**（例如 admin），只給該選單項 perm 裡的模組。
  - 打一支會呼叫 `require_any_module`／`_require_user(module=…)` 檢查**該模組權限**的端點，或者直接打頁面 `/pages/<href>`。
  - 正對照：拿掉那項模組權限 ⇒ 403。這一步要先確認端點真的會擋。
  - 發布該角色的 hide ⇒ 仍然 200。
  - 反向控制：用 X8 這類突變確認會紅。

### 建議

**C4-S1　`MotrixMenu.refresh()` 不重設 `data-menu-state`**（sidebar.js:1053-1073）
- 第一輪完成後，狀態已經是 `layout`。呼叫 `refresh()` 之後等 `layout` 會立刻成立，而第二輪其實還沒回來。
- 註解說 refresh 是給「P9 發布後、或 e2e 驗序號用」。P9 或 e2e 照這個方式等，就是〈e2e 等待的終點〉那一型的假綠。
- `test_stale_layout_response_is_dropped` 會過，是因為第一趟被刻意延遲 1.5 秒，狀態還停在 `declared`。
- 建議：`_applyLayout` 一開始就設 `data-menu-state="pending"`（或另加 `data-menu-seq`，完成時寫入序號），然後補一題「先完成一輪，再 refresh，等待點必須等到新的一輪」。

**C4-S2　失敗路徑的序號沒有題**（sidebar.js:1067；X2 綠）
- 情境：舊的一趟晚回來而且失敗，這時新的一趟已經成功。拿掉這行檢查之後，畫面停在新版面，狀態卻被改成 `layout-failed`，console 也多一筆錯誤。
- 建議比照 `test_stale_layout_response_is_dropped` 補一題：第一趟延遲後回 500，第二趟先成功，最後狀態要是 `layout`。

**C4-S3　外洩題只檢查第一行**（test_menu_inject.py:121）
- `head = r.text.partition("\n")[0]`：資料庫字串如果被放在其他行（X9：第二行 `window.MOTRIX_CUSTOM = …`），外洩題照樣綠。這次會紅，只是因為另一題恰好比對了本體。
- 判準應該針對「未登入就拿得到的整份回應」：改成 `_leaks(r.text)`（`/static/sidebar.js` 整份回應）。

**C4-S4　自訂模組改成依附 `/api/platform/menu`**（platform_menu.py:30-63；sidebar.js:1066-1070）
- 原本 custom-modules-nav.js 自己打 `/api/custom-modules`。現在這支讀不到（任何 5xx、逾時、版面那一段丟例外）⇒ **自訂模組入口整批消失**。
- console 只寫「套用角色版面失敗，保留宣告版」，沒有說自訂模組不見了。這是〈防護的副作用落在盲側〉：宣告版保住了，自訂模組這一側反而更難被發現。
- 建議：失敗訊息明確寫「自訂模組暫不顯示」。或者讓 `_layout_for` 在版面那段失敗時仍然回傳自訂模組（版面錯誤列進 `errors`、不丟 500），並補一題：版面讀取丟非預期例外時，自訂模組仍在。

**C4-S5　版號與 c-probes 撞號**
- crm 1.0.6、payroll 1.0.3、subcontract 1.0.5 在兩條線上內容不同。B 在 CHANGELOG 寫了「列車取號」。
- 目前的安全網：
  - `test_changelog_sections` 抓得到重複的段落標題。
  - 兩邊的 module.json `version` 行改成同一個值，git 會**無衝突合併**；只有 CHANGELOG 會衝突。解衝突的人要記得把後到那一包的 module.json 一起改號。
- 建議在月台登記寫明：後上車的那一包改為 crm 1.0.7、payroll 1.0.4、subcontract 1.0.6，module.json 與 CHANGELOG 一起改。

### 觀察

- **C4-O1**：`refresh()` 先成功、後失敗時，保留的是**上一輪的版面**，不是宣告版，而 console 寫「保留宣告版」。行為可以接受，但文字不準確。
- **C4-O2**：沒有題守「每次載入頁面，`/api/platform/menu` 只打一次（session 沒變時）」。golden 忽略它是合理的，但重複打或迴圈打沒有人會發現。建議在 `test_e2e_menu_layout.py` 加一題計數。
- **C4-O3**：未登入就能看到 `MOTRIX_MENU.groups`（只含已載入的模組）與 `pageModules`（含已安裝但沒載入的模組）。兩者一比，就能推出哪些已安裝的模組是停用、未授權或載入失敗。主持判定「透露裝了哪些模組可以接受」，但裁示也寫了「模組狀態不放」，這裡等於可以推出狀態。請主持確認是否接受。
- **C4-O4**：`pageModules` 來自 `_PAGE_MAP`，只含**已安裝**的模組；資料夾不在的模組，它的頁面不在裡面（X 縮減樹實測 `PAGEMODULES∩7 = []`）。platform_menu.py 的 docstring 寫「含沒載入的」，只對「已安裝但沒載入」成立。前端「missing」提示路徑因此只能靠伺服器 core.pages 處理，現況與設計一致，只是文字要精確。
- **C4-O5**：C 的 M05（wip/c-m05b）在 RUN-PLAN 寫明「選單項交 B 的 C4 一併處理」，但 cashier 等 M05 頁面的選單項目前仍在 `menu_l1.json`。M05 合回時，`test_l1_menu_never_points_at_a_module_page` 會紅，逼它把宣告搬進 module.json。守門有效，但需要事先通知 C。
- **C4-O6**：sidebar.js 仍寫死 `_FILE_MODULE`（:547）與 `_MOD_BADGES`（:959），用在徽章與「看過」判斷。STAGE-C §4 原本寫「切換完成後刪除」，C4 沒有處理，不影響選單正確性，建議列入後續。
- **C4-O7**：custom-modules-nav.js 的行為差異：
  - 只有一項的「自訂模組」預設組，舊版保持下拉，新版由 `renderMainNav` 畫成頂層連結。
  - 模組建構器原本是「系統」組第一項（order −1），現在 L1 order 5。
  - 自訂模組併進只有一項的既有組時，舊版會另開同名組，新版正確併入（改善）。
  - 以上都只影響外觀。

## 5. 回覆欄（被稽核者填；X 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | X 確認 |
|---|---|---|---|
| C4-M1 | | | |
| C4-S1 | | | |
| C4-S2 | | | |
| C4-S3 | | | |
| C4-S4 | | | |
| C4-S5 | | | |
| C4-O3 | （需主持確認） | | |

## 6. 自查

- 模組移除用的是**在 X 自己的稽核樹刪資料夾**，沒有用 sparse，也沒有經過 MSYS 路徑轉換。跑之前先 `ls backend/modules` 確認只剩 `__init__.py`、analytics、tender_radar；跑完用 `git checkout -- backend/modules` 還原，`git status` 乾淨。
- 探針題（`test_zz_xc4_*.py`）只放在稽核樹，用完已刪除，沒有 commit。
- 突變 X1–X13 都是套上、跑完、寫回原內容，並比對內容一致。
- 沒有被權限擋下需要繞過的動作。Git 指令一律拆成單純的 `git -C <路徑>` 形式執行。
