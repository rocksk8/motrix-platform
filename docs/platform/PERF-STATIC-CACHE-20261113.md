# 外網載入效能：靜態資源版本化＋快取表頭（2026-11-13）

分支 `perf/static-cache-20261113-h11`（基底 `adc6bd58d`；PM 指定的 `perf/static-cache-20261113` 已被 hichan-2 的 worktree 佔著，內容只有一支未接線的草稿，已併入本分支）。
程式：`backend/helpers/static_cache.py`（版本計算、引用改寫、表頭）、`backend/main.py`（接線）、`frontend/static/sidebar.js`＋`pages/online-stats.html`（輪詢）。
測試：`backend/tests/test_static_cache_versioning_2026_11_13.py`（24 題）。

## 問題（正式機量測，PM 提供）
本機首頁 14～24 ms；外網每個請求約 1 s（公司網路走 IPv4 被 Cloudflare 繞美西，單趟約 130 ms）。伺服器與 DB 不是瓶頸。
所有 `/`、`/static/*`、`/js/*`、`/css/*` 都是 `no-cache, no-store, must-revalidate`，JS 引用沒有版本字串 ⇒ 瀏覽器**完全不快取**，每換一頁重抓全部 JS。

## 做法
**不手改任何一頁 HTML**（hichan-1／4／7 同時在改 HTML）。伺服器在送出前改寫：

1. **內容版本**：`frontend/static`（不含 `vendor/`）、`frontend/js`、`frontend/css`、已載入模組提供的 `/js` 檔、動態產生的 `/static/sidebar.js`（含選單宣告）的**內容雜湊**，取前 12 碼。
   一個全站共用的版本、不是每檔各一個（sidebar.js 動態載入別的 js，各檔各自版本會有互相依賴）。任何一支內容變 ⇒ 版本變 ⇒ 所有引用的網址都變；只有 mtime 變 ⇒ 版本不變。
   選單宣告隨模組狀態變，已進雜湊 ⇒ 模組開關後版本也變，舊選單不會被釘住。重算最多每 3 秒一次（stat 簽章沒變就不重雜湊；實測整棵樹 95 檔／2 MB，首次 59 ms、之後每次檢查約 6 ms）。
2. **改寫引用**：HTML、JS、CSS 本體送出前，引號包起來的 `static/…`、`js/…`、`css/…` 資源網址（含 `../`、`./`、`/` 前綴；含 sidebar.js 動態載入的 `'static/ux-help.js'`）補上／換掉 `?v=<版本>`（原本 style.css 手寫的 `?v=20260805g` 也一併換成雜湊）。`static/vendor/` 與外部網址不動。
3. **表頭**

| 請求 | Cache-Control | 其他 |
|---|---|---|
| `/static`、`/js`、`/css` 的 js／css／圖，`?v=` ＝目前版本 | `public, max-age=31536000, immutable` | 拿掉 Pragma／Expires |
| 同上，沒帶 `v` 或 `v` 是舊的（舊分頁、手打網址） | `no-cache`（不是 no-store） | ETag／304；回的是**現在**的內容，不會把新內容用 immutable 釘在舊網址上 |
| HTML（`/`、`/pages/*`、`*.html`） | `no-cache` | 弱 ETag（改寫後內容的雜湊），`If-None-Match` 命中回 **304** 空本體 |
| `/static/vendor/*` | `public, max-age=31536000, immutable`（不變） | |
| `/fonts/*` | `public, max-age=604800`（不變） | |
| `/api/*` 與其他 | 不動（沒有表頭或端點自己設的 no-store） | |
| 非 200（404 等） | 舊規則（no-store） | 錯誤頁不可被快取 |

4. **緊急開關**：環境變數 `MOTRIX_STATIC_CACHE=0` 重啟 ⇒ 整套退回舊行為（no-store、不改寫、不加版本）。預設開。

## 請求耗時（log）
`slow_request_log`（既有）擴充：
- **每個請求**回應帶 `Server-Timing: app;dur=<ms>`（不寫碟）。瀏覽器 DevTools → Network → Timing 看得到伺服器耗時；與整體耗時相減＝路途。
- 慢於 `MOTRIX_REQ_LOG_MS`（預設 100 ms）或狀態碼 ≥ 400 ⇒ 寫一行 INFO，logger `motrix.req`：`REQ GET /pages/x.html 200 123ms`（只記路徑、不記 query）。設 `0` ＝全記。
  常駐程式的磁碟寫入是預算，所以預設只記慢的與失敗的。原本的 `SLOW REQUEST`（`/api/` 且 ≥ 5 s，WARNING）不變。
- ⚠️ 與 hichan-2 的日誌分流（`fix/backlog-bugs-20261113`，`helpers/log_setup.py`）的銜接：該分支把 INFO 分到 `app.log`，`motrix.req` 會跟著進 `app.log`。若要改進 `access.log`，在 `log_setup.install()` 掛一個只接 `motrix.req` 的 handler 即可；本分支不碰那支檔（避免衝突），**兩分支合併後由整合者決定**。
- 位置限制：`slow_request_log` 在 `auth_middleware`／授權閘門的**內側**，未登入 401、被閘門擋下的請求不會經過它（既有行為，沒改），所以這些請求沒有 `Server-Timing`、也不進 `motrix.req`。

## 輪詢
- `/api/online-users`（只有最高管理者的頂欄）：60 s → **120 s**，且分頁看不見（`document.hidden`）時不打、回到前景若已超過間隔就補一次。`online-stats.html` 的 60 s 輪詢同樣處理。共用 `window.motrixVisiblePoll`（sidebar.js 提供，沒有就退回原本的 setInterval）。
- `/api/reads` **沒有輪詢**：只在載頁、`motrix:reads-changed`、回前景（60 s 節流）時打；沒有可降的定時器，沒動。整個前端只剩 `change-password`／`login`（QR 輪詢）、`custom-records`、`edit-presence`（編輯中心跳）還有 `setInterval`，都不是這張票的對象。

## 實測（本機 uvicorn＋真瀏覽器，CDP 模擬 130 ms 往返、2.5 Mbps；持久化 context，HTTP 快取有效）
首頁登入後；「暖」＝第二次以後。`topbar`＝頂欄畫出；`load`＝load 事件；`wire`＝真的走網路的請求（快取命中不算）。

| | 改前 topbar | 改後 topbar | 改前 load | 改後 load | 改前 wire 請求／KB | 改後 wire 請求／KB |
|---|---|---|---|---|---|---|
| 首頁（冷） | 0.73 s | 0.66 s | 4.27 s | 4.27 s | 33／7380 | 33／7381 |
| 首頁（暖） | 0.48 s | **0.24 s** | 0.98 s | **0.36 s** | 29／362 | **23／42** |
| 第二頁 quotations（暖） | 0.80 s | **0.59 s** | 1.36 s | **0.72 s** | 36／542 | **29／291** |
| 第三頁 customers（暖） | 1.15 s | **0.86 s** | 1.72 s | **1.03 s** | 35／1372 | **24／1016** |

- 冷啟動 4.27 s 是兩支 woff2 字型共約 7 MB 在 2.5 Mbps 下的下載（字型本來就有 7 天快取；真實外網不會這麼慢）。
- 暖載入剩下的 wire 請求幾乎都是 `/api/*`（首頁 22 支）＋ HTML 的 304 重驗：**靜態檔已經不是瓶頸，API 瀑布才是**（見第二階段）。第三頁剩的 1 MB 是第一次到該頁才抓的 `xlsx` vendor（861 KB，之後走快取）與頁面本身 88 KB（HTML 每次重驗，內容變了才重抓）。
- 以真實外網（每請求 ≈1 s）估：暖載入每頁省下的是 **JS／CSS 約 6～17 個請求**（這些以前是 6 個並行 ×數趟），首頁暖載入頂欄預期從約 1.5～2 s 降到約 1 s（HTML 304＋auth/me 兩趟）。實際值要正式機上線後用 `Server-Timing` 與 DevTools 對照量，這裡的數字是模擬。

## Cloudflare 邊緣快取規則建議（只快取帶版本的靜態檔）
前提：網址帶 `?v=<雜湊>` ＝內容不可變，換版網址就變，**不需要 purge**。目前 Cloudflare 預設會依副檔名快取 js／css／圖（只要原站表頭允許）；以前因為 `no-store` 完全沒被邊緣快取，改版後帶 `public, max-age=31536000, immutable` 就會開始被快取——這是想要的，但請明確規則化，避免 HTML／API 被誤快取：

1. **Cache Rule A（快取）**：條件 `(starts_with(http.request.uri.path, "/static/") or starts_with(http.request.uri.path, "/js/") or starts_with(http.request.uri.path, "/css/")) and http.request.uri.query contains "v="` ⇒ *Eligible for cache*；Edge TTL ＝ *Use cache-control header if present*（原站 1 年）；Browser TTL ＝ *Respect origin*；Cache key 用預設（**query string 必須在 key 裡**，不可選 ignore query string）。
2. **Cache Rule B（不快取）**：`starts_with(http.request.uri.path, "/api/") or starts_with(http.request.uri.path, "/pages/") or http.request.uri.path eq "/"` ⇒ *Bypass cache*。（HTML 原站是 `no-cache`＋ETag，邊緣不該存；API 帶登入資料，**絕對不要**開 Cache Everything。）
3. **字型** `/fonts/*`：維持原站 `max-age=604800`，可併入規則 A 的路徑條件（字型網址沒有 `v=`，用 `starts_with(... "/fonts/")` 另開一條 *Eligible for cache*、Edge TTL 7 天）。
4. 其他：關閉 *Always Online*；壓縮（Brotli）維持開；Argo Smart Routing 若有預算，對「公司網路被繞美西」的路徑有效（HTTP/3 已開）。
5. 驗證：`curl -sI "https://<網域>/static/sidebar.js?v=<版本>" | findstr /i "cf-cache-status cache-control"`，第二次應 `cf-cache-status: HIT`；`/api/…` 與 `/pages/…` 不應出現 `HIT`。

## 部署注意
- 上線後第一次：版本是新的 ⇒ 所有使用者的 JS／CSS 重抓一次（之後都走快取）。已開著的舊分頁引用舊 `v`：拿到現在的內容但標 `no-cache`（會每次重驗，不會壞）。
- 要退回：`MOTRIX_STATIC_CACHE=0` 重啟（不必換包）。
- 動態組網址的寫法（`'static/' + name`、`` `static/${name}` ``、帶別的查詢字串）改寫器看不見 ⇒ 守門題會紅；請寫成完整字串字面值。`/map-overlays/*` 與 `/api/*` 底下的腳本不在改寫範圍（不影響正確性，只是沒有長效快取）。
- 既有 4 題「no-store」斷言已改成新規則（`test_vendor_cache_headers`、`test_font_cache_headers`、`test_remit_kinds_js_asset`、`test_menu_inject`）。

## 第二階段（只出提案，未動手）：登入後首頁的請求盤點與合併
**實測首頁暖載入 32 個請求，其中 API 22 支**（瀏覽器端 6 並行；經 Cloudflare 每支約 1 s，所以瀑布深度比支數更重要）：

| 來源 | 請求 |
|---|---|
| auth-guard.js | `/api/auth/me` |
| sidebar.js | `/api/auth/me`（**重複**）、`/api/platform/menu`（24 KB）、`/api/system/bonus-module-status`、`/api/system/modules/availability`、`/api/build-info`、`/api/online-users`（最高管理者）、`/api/system/branding/logo-dark`（圖，304） |
| notif.js `init()` | `/api/notifications/mine`、`/api/approval-queue/count`、`/api/daily-tasks?date=…`、`/api/reads/module-counts`、（`/api/auth/totp/status`，admin） |
| index.html | `/api/system/branding`、`/api/approval-queue/count`（**重複**）、`/api/dashboard/stats`、`/api/dashboard/monthly`、`/api/dashboard/expenses-monthly`、`/api/dashboard/funnel`、`/api/dashboard/ops-alerts`、`/api/dashboard/activity-feed`、`/api/customers`（新手清單）、`/api/org/tree` |

**瀑布問題（index.html 第 1020～1031 行）**：`stats`＋`approval-mine` 並行 → **`monthly` → `expenses-monthly`（兩個串行 await）** → `funnel`／`ops-alerts`／`activity-feed` 並行。儀表板內容要 **4 趟**才齊，每趟在外網約 1 s。

提案（由小到大，風險由低到高）：

1. **零後端改動、風險最低**：`monthly` 與 `expenses-monthly` 改 `Promise.all`，連同 funnel／ops-alerts／activity-feed 全部同時發 ⇒ 儀表板 4 趟 → 2 趟（stats 一趟、其餘一趟；stats 若不依賴其他可再併成 1 趟）。外網預估省 **約 2 s**。另外去掉兩處重複（`auth/me` 由 auth-guard 存結果給 sidebar 用、`approval-queue/count` 由 notif 與 index 共用同一個 Promise）⇒ 少 2 支請求。
2. **啟動 API `GET /api/bootstrap`**：一次回 `auth/me`、`platform/menu`、`branding`、`build-info`、`bonus-module-status`、`modules/availability`、`approval-queue/count`、`notifications/mine`、`reads/module-counts`、`daily-tasks` 計數、`totp/status`、`online-users`。後端各自的函式原地呼叫（同一個 DB 連線、同一個 auth 檢查一次）；前端各元件改讀 `window.MotrixBoot`（Promise，沒有就退回各自 fetch，舊頁面不壞）。**12 支 → 1 支**，且 auth 只驗一次（現在每支請求各驗一次 token＋授權閘門，伺服端也省）。
3. **儀表板打包 `GET /api/dashboard/bundle`**：`stats`＋`monthly`＋`expenses-monthly`（有財務權限才含）＋`funnel`＋`ops-alerts`＋`activity-feed` 一次回；各段失敗只讓該段為 `null`，不整包失敗（前端現在就是各段各自 try）。**6 支 → 1 支**。
4. 延後載入：`customers`、`org/tree`、`daily-tasks`、`online-users` 用 `requestIdleCallback`（或首屏畫完後）再發，不佔首屏瀑布。

估算（外網每支 ≈1 s、瀏覽器 HTTP/2 並行不受 6 條限制）：現況暖載入首屏關鍵路徑 ≈ HTML 重驗 1 趟 ＋ auth/me 1 趟 ＋ 儀表板 4 趟 ≈ **6 趟**；做完 1 ⇒ ≈ 4 趟；再做 2＋3 ⇒ **HTML → bootstrap ∥ dashboard bundle ≈ 2～3 趟**；請求數 32 ⇒ 約 12（1 HTML 304、1 bootstrap、1 bundle、字型／圖若干）。伺服端：每個頁面載入的 token 驗證＋授權閘門次數由 22 次降到 2～3 次。
風險：bootstrap／bundle 是新端點，要補權限守門（逐項沿用原端點的檢查，不可因打包而放寬）、`planned` 模組／未載入模組的欄位形狀要與原端點一致（契約測試逐項比對原端點回應）、`route_registry`／locale 守門要登記。建議先做 1（半天、純前端、可獨立上線），2 與 3 另開票。
