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
- `auth-guard.js`（每頁最先載入、本來就要驗登入）改打 **一支** `/api/bootstrap` 當登入驗證；結果放 `window.MotrixBoot`（Promise → bootstrap JSON 或 `null`）。非 200 的處理：401／402 同 `auth/me`；403（必須改密碼）、428、404（舊伺服器）、5xx ⇒ 退回打 `/api/auth/me`，行為與改版前完全相同；6 秒等不到 ⇒ `MotrixBoot` 變 `null`。
- `motrixBootFetch(url, opts)` 與 `fetch` 同簽章：**第一次**要某區段時（同一個 token、20 秒內、GET、無 query、帶 Authorization）回一個由 bootstrap 內容組成的 `Response`（`r.ok`／`r.json()` 與原端點相同），否則就是真的 fetch。同一資料有兩個載入點的（`me`、`branding`、`approvalCount`）可供應 2 次，其餘 1 次。⇒ 呼叫端只要把 `fetch(` 換成 `(window.motrixBootFetch || fetch)(`，其餘邏輯不動。
- 使用者動作事件（`motrix:approval-changed`、`motrix:reads-changed`、`motrix:item-read`、`motrix:item-read-failed`）⇒ 整份啟動資料作廢，之後一律真的請求（重抓拿到真資料）。
- 第一次供應時補上 bootstrap 那次回應的橫幅標頭（`X-Motrix-License`、`X-Motrix-Company-Setup`），由 `notif.js` 匯出的 `motrixApplyBanners` 處理（原本每個 `/api` 回應都會過橫幅邏輯）。
- 已改用的呼叫點：`sidebar.js`（`auth/me`、`platform/menu`、`build-info`、`bonus-module-status`、`modules/availability`、首次 `online-users`）、`notif.js`（`notifications/mine`、`approval-queue/count`、`reads/module-counts`、`totp/status`）。輪詢／focus／事件觸發的重抓不變（真的請求）。
- `index.html` 自己的 `/api/system/branding`、`/api/approval-queue/count` 還是原本的 fetch——hichan-7 改 index.html 時可直接用 `motrixBootFetch`（同簽章）。

## 實測（同第一階段的方法：真 Chromium，130 ms 往返、2.5 Mbps、HTTP 快取有效；本機）
首頁（暖）API 請求 **22 → 13**（剩下的 11 支是 index.html 自己的 fetch：dashboard 六支、branding、approval count、customers、org tree、daily-tasks…，等 hichan-7 改用 bundle 後預計 ≈ 4）；第二頁（暖）**17 → 8**；wire 請求首頁 23 → 14、第二頁 29 → 20。頂欄 0.22 s、load 0.33 s（第一階段 0.24／0.36）。外網每支約 1 s，**省的是瀑布深度**：頁面不再等 `auth-guard` 的 `auth/me` 之後才發 sidebar／notif 的一串請求。

## 相容與退路
- 原端點全部保留；舊前端（沒有 `motrixBootFetch`）照舊各自打原端點。
- 新前端打到舊伺服器（沒有 `/api/bootstrap`）：`auth-guard` 退回 `auth/me`，`MotrixBoot` ＝ `null`，所有 `motrixBootFetch` 變成一般 fetch。
- 既有測試的調整：`test_e2e_approval_dot`（待簽數由 bootstrap 供應，等待條件放寬為 bootstrap 或原端點）、`test_login_return_to`（node 測試的 fetch 模擬加上 bootstrap）、`golden_case_page`（`99 API 請求` 一行：+`/api/bootstrap`，`bonus-module-status` 2→1、`availability` 3→2；其餘 22 段行為快照不變，已重錄）。
