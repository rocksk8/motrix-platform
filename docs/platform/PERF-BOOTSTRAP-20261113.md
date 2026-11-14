# 外網載入效能 第二階段：`GET /api/bootstrap`、`GET /api/dashboard/bundle`（2026-11-13）

分支 `perf/bootstrap-bundle-20261113`（疊在第一階段 `perf/static-cache-20261113-h11` 之上；第一階段說明見 `PERF-STATIC-CACHE-20261113.md`）。

## 鐵則：不比原端點多給任何資料
兩支新端點的每個區段都是**直接呼叫原端點的處理函式**（同一份程式、同一個權限檢查與遮蔽、同一個 `authorization`），所以區段內容與單打原端點逐欄相同。放與不放都只會**變少**。
守門（逐區段、逐角色、逐欄比對原端點）：`tests/test_bootstrap_bundle_2026_11_13.py`、`tests/test_bootstrap_setup_gate_2026_11_13.py`、前端端 `tests/test_bootstrap_frontend_2026_11_13.py`。

## `GET /api/bootstrap`（`routers/bootstrap.py`）
回 `{"v": 1, "<區段>": <原端點的回應>, …, "errors": {"<區段>": <狀態碼>}}`。區段與原端點：

| 區段 | 原端點 | 誰會有 |
|---|---|---|
| `me` | `/api/auth/me` | 所有人 |
| `menu` | `/api/platform/menu` | 所有人 |
| `branding` | `/api/system/branding`（帶 token ⇒ 含統編） | 所有人 |
| `buildInfo` | `/api/build-info` | 所有人 |
| `bonusModuleStatus` | `/api/system/bonus-module-status` | 所有人 |
| `moduleAvailability` | `/api/system/modules/availability` | 所有人 |
| `approvalCount` | `/api/approval-queue/count` | 所有人 |
| `notifications` | `/api/notifications/mine` | 所有人 |
| `moduleCounts` | `/api/reads/module-counts` | 最高管理者、管理員 |
| `totp` | `/api/auth/totp/status` | 最高管理者、管理員 |
| `onlineUsers` | `/api/online-users` | 最高管理者 |

- **本公司資料未設定（428 閘門）**：原端點除白名單外一律 428 ⇒ 只放白名單內的區段（`me`、`menu`、`branding`、`totp`），其餘不給資料、`errors[區段]` ＝ 428。`GET /api/bootstrap` 本身已加入 `main._COMPANY_SETUP_ALLOWED`（理由欄寫明）。守門確認 `SETUP_GATE_OK` 恰等於「原端點在 main 白名單或公開清單」。
- 授權閘門（402）、必須先改密碼（403）：本端點不在豁免／白名單 ⇒ 與其他 `/api` 一樣被擋；前端收到非 200 就退回各自打原端點。
- 某區段原端點丟 HTTPException／出錯 ⇒ 該區段缺、`errors` 記狀態碼，不整包失敗。
- 沒放進去的：`/api/daily-tasks?…`（`daily_tasks` 模組自己的端點，L1 不 import 它）、`/api/system-hub`（只有系統中心頁用）、`/api/system/branding/logo-dark`（圖，走 304）。
- 操作軌跡：`/api/bootstrap` 列入 `trail.SKIP_PREFIXES`（每頁自動打的，人沒按過）。

## `GET /api/dashboard/bundle`（`modules/analytics/api/dashboard.py`）
`?department_id=<id>&activity_limit=8`（1～100）⇒ `{"stats","monthly","expenses","funnel","opsAlerts","activityFeed","errors"}`；各區段＝對應原端點（`/stats`、`/monthly`、`/expenses-monthly`、`/funnel`、`/ops-alerts`、`/activity-feed?limit=`）的回應。沒有財務權限的人 `monthly`／`expenses` 是原端點的空殼（不是 null）。某段被拒／出錯 ⇒ 該段 `null`＋`errors`；整包的 401／402／428 與其他 `/api` 相同。併入 `trail` 的「開啟營運儀表板」群組。
**index.html 的改用由 hichan-7（P1.5 角色化儀表板）負責**（協調結果：本分支不碰 index.html 的 fetch；hichan-7 以 `/api/dashboard/bundle` 取代首頁六支、失敗退回舊端點；`/api/customers`、`/api/org/tree` 改延後載入也在他那邊）。

## 前端：`window.MotrixBoot`、`motrixBoot(name)`、`motrixBootFetch(url, opts)`（`static/auth-guard.js`）
- `auth-guard.js`（每頁最先載入）：**放行頁面只看快的 `/api/auth/me`**（與改版前逐字相同的處理：ok ⇒ 顯示、402 ⇒ 授權頁、其他 ⇒ 轉登入），**同時並行**發出 `/api/bootstrap` 取其餘啟動資料，結果放 `window.MotrixBoot`（Promise → bootstrap JSON 或 `null`）。bootstrap 慢（11 個區段）不擋首繪；它非 200（401／402／403／404／428／5xx）或 1.5 秒等不到 ⇒ `MotrixBoot` ＝ `null`、各處退回打原端點（放行／轉頁的結果仍只由 `auth/me` 決定）。（審查 B1：第一版讓 guard 等整包 bootstrap 才放行，首繪慢 0.2～0.3 s，已改。）
- 後端 `/api/bootstrap` 的區段**並行**執行（專用執行緒池、每段在 `copy_context()` 複本裡跑，demo 旗標照帶；回應鍵序仍固定）；`buildInfo` 區段快取 60 s（`stale` 要能在套用更新後出現，所以不是行程內永久快取；原端點 `/api/build-info` 不快取）。區段內的請求脈絡設成原端點路徑（稽核「是哪支端點被拒」不會記成 `/api/bootstrap`）。`/api/bootstrap`、`/api/dashboard/bundle` 回 `Cache-Control: no-store`。守門：每支被直接呼叫的處理函式的參數必須恰好是 `authorization`（bundle 的 6 支各自與 bundle 傳的一致）。
- `motrixBootFetch(url, opts)` 與 `fetch` 同簽章：**第一次**要某區段時（同一個 token、20 秒內、GET、無 query、帶 Authorization）回一個由 bootstrap 內容組成的 `Response`（`r.ok`／`r.json()` 與原端點相同），否則就是真的 fetch。同一資料有兩個載入點的（`me`、`branding`、`approvalCount`）可供應 2 次，其餘 1 次。⇒ 呼叫端只要把 `fetch(` 換成 `(window.motrixBootFetch || fetch)(`，其餘邏輯不動。
- 使用者動作事件（`motrix:approval-changed`、`motrix:reads-changed`、`motrix:item-read`、`motrix:item-read-failed`）⇒ 整份啟動資料作廢，之後一律真的請求（重抓拿到真資料）。
- 第一次供應時補上 bootstrap 那次回應的橫幅標頭（`X-Motrix-License`、`X-Motrix-Company-Setup`），由 `notif.js` 匯出的 `motrixApplyBanners` 處理（原本每個 `/api` 回應都會過橫幅邏輯）。
- 已改用的呼叫點：`sidebar.js`（`auth/me`、`platform/menu`、`build-info`、`bonus-module-status`、`modules/availability`、首次 `online-users`）、`notif.js`（`notifications/mine`、`approval-queue/count`、`reads/module-counts`、`totp/status`）。輪詢／focus／事件觸發的重抓不變（真的請求）。
- `index.html` 自己的 `/api/system/branding`、`/api/approval-queue/count` 還是原本的 fetch——hichan-7 改 index.html 時可直接用 `motrixBootFetch`（同簽章）。

## 實測（同第一階段的方法：真 Chromium，130 ms 往返、2.5 Mbps、HTTP 快取有效；本機）
（B1 修正後重測，見文末）首頁（暖）API 請求 **22 → 13**（剩下的 11 支是 index.html 自己的 fetch：dashboard 六支、branding、approval count、customers、org tree、daily-tasks…，等 hichan-7 改用 bundle 後預計 ≈ 4）；第二頁（暖）**17 → 8**；wire 請求首頁 23 → 14、第二頁 29 → 20。頂欄 0.22 s、load 0.33 s（第一階段 0.24／0.36）。外網每支約 1 s，**省的是瀑布深度**：頁面不再等 `auth-guard` 的 `auth/me` 之後才發 sidebar／notif 的一串請求。

## 相容與退路
- 原端點全部保留；舊前端（沒有 `motrixBootFetch`）照舊各自打原端點。
- 新前端打到舊伺服器（沒有 `/api/bootstrap`）：`auth-guard` 退回 `auth/me`，`MotrixBoot` ＝ `null`，所有 `motrixBootFetch` 變成一般 fetch。
- 既有測試的調整：`test_e2e_approval_dot`（待簽數由 bootstrap 供應，等待條件放寬為 bootstrap 或原端點）、`test_login_return_to`（node 測試的 fetch 模擬加上 bootstrap）、`golden_case_page`（`99 API 請求` 一行：+`/api/bootstrap`，`bonus-module-status` 2→1、`availability` 3→2；其餘 22 段行為快照不變，已重錄）。

## B1 修正後重測（真 Chromium，130 ms 往返、2.5 Mbps、HTTP 快取有效；各跑兩次，與第一階段 5f17749ac 並排）
| 指標（暖載入） | 第一階段 5f17749ac | 本分支 |
|---|---|---|
| 頁面放行（auth-guard reveal） 首頁 | 307／320 ms | 324／325 ms |
| 頁面放行 第二頁（quotations） | 327～495 ms | 326～479 ms（兩邊都有同樣的雜訊，單次 ≈ 0.33 或 ≈ 0.48） |
| 頂欄出現 首頁／第二頁 | 0.35～0.37／0.63～0.64 s | 0.36～0.37／0.72～0.74 s（第二頁 +0.09 s：sidebar 等 bootstrap 一次到齊，不再各自並行發） |
| API 請求數 首頁／第二頁 | 22／17 | 14／9（比第二階段第一版多 1：guard 自己的 `auth/me`） |
放行時間持平（B1 的驗收）；請求數仍大幅減少（22→14、17→9）。頂欄在第二頁慢約 0.1 s 是取捨：想拿回可以把 sidebar 的首次載入改成不等 bootstrap（那就回到各自發請求）。

## T86 追加：案件管理頁首屏併單（`GET /api/bootstrap?page=case`，2026-11-14）
- 問題：案件管理頁首次載入 19 支 API，其中 8 支是「登入即可讀」的小請求，各自等一個往返：onepipe 旗標、版面與規則設定群組（`builder_*`、`ui_format`）、利潤門檻、可選使用者、公司公開資料、清單排序偏好（`case_list`）、兩支承攬商下拉。
- 作法：`routers/bootstrap.py::PAGE_SECTIONS["case"]` 多放這 8 段（`onepipeFlags`、`builderGroups`、`profitWarning`、`usersSelectable`、`companyProfilePublic`、`listPrefCase`、`vendorsSelectable`、`contractorsSelectable`）。鐵則不變：直接呼叫原端點的處理函式（固定的路徑參數／查詢值用 `functools.partial` 先綁）、同一份權限檢查，原端點拒絕（403…）就不給、`errors` 記同一個狀態碼；本公司資料未設定時一個都不給（428）；沒帶或不認得的 `page` ＝與今天逐位元相同。
- 前端：只有案件管理頁才多帶 `?page=case`、才在 `BOOT_SECTIONS` 登記這些路徑；其他頁的網址不在表內，照舊直接 fetch（不會多等 bootstrap）。案件頁的載入點（`onepipe.js`、`profit-warning.js`、`public-flags.js`、`list-sort.js`、`case-management-core.js`／`-dispatch.js`／`-close.js`）改用 `(window.motrixBootFetch || fetch)`；側欄與案件頁各用一次的 `auth/me`、`modules/availability`、`bonus-module-status` 在這一頁供應兩次。
- 分頁內容本來就是切到才載入（CM8 `ensureTabData`），本次不動。
- 實測（本機 Chromium，同一份種子資料，唯一差別是這支分支；括號為額外加 150 ms 單程延遲）：清單首次載入 API **19 → 9**（含靜態檔 71 → 61）；開一個案件（`?q=` 直開）**25 → 14**；清單載入時間 1.7 → 1.4 s（3.31 → 2.71 s）、直開案件 1.4 → 1.3 s（2.40 → 1.95 s）。開案件時剩下的請求都是這個案件自己的資料。
- 同批修正（#15）：業務、工程師開財務分頁（或存款項、處理承攬商憑證）時，前端會對 `/api/quotations/{no}/finance-summary` 發請求，後端只給財務角色與最高管理者 ⇒ console 一筆 403。現在 `loadFinanceSummary` 與畫面同一條規則（`canSeeFinancial()`），不是財務角色就不送。

### T86 第二輪（#10 複測「70 → 62 降得不夠」；`feat/t86-case-ux-h1b`）
- 那個「62」是**總請求數**：案件頁 63 個請求 ＝ **9 支 API ＋ 54 個靜態檔**（47 支 js、css、字型等）。靜態檔帶 `?v=` 雜湊，暖啟動（重新整理）全由快取供應，實際走網路的只有 9 支 API；所以能降的是 API。第一輪已把 8 支登入即可讀的小請求併進 bootstrap（19 → 9）；本輪再收：
  - 出貨單分頁排序偏好 `list-prefs/sn:{單號}`：開案件時就讀，現在切到出貨單分頁才讀（開案件 API 14 → **13**）。
  - 財務可視：`financeView` 衍生區段（`routers/bootstrap.py::_finance_view`，直接呼叫 `helpers.auth.can_see_financial`）。前端 `canSeeFinancial()` 以它為準，旗標 `finance_via_effective` 開啟時不再只看角色；`effective_modules`／`auth/me` 欄位不動（牽涉面太大）。測試含旗標 off／shadow／on 三態逐人比對。
- 刻意不併：報價單清單與計數（主資料，不該等 bootstrap 最慢區段，且 1.5 s 退回機制會讓慢的時候更慢）、`daily-tasks`、`POST /api/reads`、`auth/preferences`、logo（各依使用者／案件參數或寫入性質）；47 支 js 不改成延遲載入（Alpine mixin 組合順序風險）。
- 分頁內容本來就是切到才載入（CM8 `ensureTabData`），本輪只把出貨單的排序偏好也納入。
