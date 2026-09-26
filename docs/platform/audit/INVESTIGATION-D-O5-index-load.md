# 調查：O5 登入後 index.html 的 load 逾時（產品競態調查）（D，2026-09-26）

> 主持派工：第七班全量 e2e 紅 2 題（`test_e2e_login_enter_submits::test_enter_that_only_reaches_the_page_as_keyup_still_submits`、`test_e2e_login_page::test_a_page_level_enter_in_the_code_step_submits`）。列車長查到：網址已到 `/index.html`、domcontentloaded 已觸發，**逾時的是 load 事件**；基底 82bbca0e 也會紅、每次紅的題不同。
> 樹：`D:\MOTRIX-PLATFORM-D`（origin/platform 9e7efdef），Python `.venv312`。暫時探針 `tests/_d_o5_probe.py` 跑完即刪。

## 0. 結論

- **機制已確認**：`index.html` 的 load 事件被兩個約 5 MB 的字型檔綁住（`/fonts/LINESeedTW-Regular.otf` 5,246,068 B、`/fonts/LINESeedTW-Bold.otf` 5,431,204 B，由 `css/style.css` 的 `@font-face` 載入）。字型延遲多久，load 就延後多久。
- **沒有外部資源**：`index.html`、`style.css`、`auth-guard.js`、`notif.js`、`sidebar.js` 都沒有外部 CDN、網路字型、iframe、long-poll；sidebar 動態插入的 `custom-modules-nav.js` 是同源小檔。⇒ **不是離線依賴問題**，正式機離線也不會因此掛住。
- **沒有在我能製造的負載下重現逾時**：因此**不能斷言**列車上那兩次就是字型；字型是 load 路徑上最長、最大的一支，是最可能的尾巴。
- 建議 3 項（無必修）。

## 1. 子資源清單（靜態）

`index.html`：`static/favicon.png`、`static/auth-guard.js`、`static/vendor/alpine-3.17.1.min.js`（defer）、`css/style.css`、`static/notif.js`、`static/sidebar.js`；`style.css` 的 `@font-face` 4 支 otf（Thin／Regular／Bold／ExtraBold，共約 21 MB，首頁實際用到 Regular、Bold）；sidebar 動態插入 `static/custom-modules-nav.js`；`/static/logo.png` 97 KB；其餘都是 `/api/*` 的 fetch（fetch 不擋 load）。

## 2. 時間線（Playwright `request`／`requestfinished`／`requestfailed`／`load`）

| 情境 | 結果 |
|---|---|
| `-n 2`，6 份 | 每份 28 個請求；DOMContentLoaded 0.12～0.16 s；**load 0.91～1.22 s**；最慢的永遠是兩支字型（0.62～1.05 s），其次 logo.png 約 0.45 s；未完成的只有 `/api/*` fetch（不擋 load） |
| 背景 `tests/platform -n 4`（1076 passed）同時跑，探針 `-n 2` 16 份 | load 0.84～1.20 s，**沒有逾時** |
| **因果**：`page.route("**/fonts/*")` 每支延遲 20 秒後放行（讀瀏覽器端 Navigation Timing） | DOMContentLoaded **115 ms**；字型 responseEnd **20,202 ms、40,210 ms**；**loadEventStart 40,319 ms** ⇒ load 等字型 |

## 3. 判斷

- **產品面**：不是離線依賴。但首頁第一次載入要下載約 10.7 MB 的 otf（4 支合計約 21 MB），在慢網路上 load 會明顯延後；`.otf` 沒有設快取標頭（`main.py:no_cache_static` 只給 vendor 長效快取），靠 ETag／Last-Modified 重新驗證。
- **測試面**：每一題 e2e 開新的 browser context，快取不跨題 ⇒ 全量 452 題、每題打到首頁就下載約 10 MB，全部由該 worker 的 live_server 送出。負載高時，字型是最可能拖過逾時的一支；而這兩題等的是 `load`，不是它們真正要驗的東西。

## 4. 建議（交對應擁有者）

- **O5-S1（測試夾具，B）**：`E2E_CONTEXT_HOOKS` 加一個 hook，把 `**/fonts/*` 換成極小的替身（`route.fulfill` 一個空字型或 204），行為題不需要真字型；全量可省約 4.5 GB 的傳輸。另外這兩題等 `load` 的地方改等「登入後首頁的應用就緒訊號」（例如特定元素出現），不等整頁子資源。
- **O5-S2（測試夾具，B）**：e2e 逾時的時候，自動把「已發出而未完成的請求」清單附進失敗訊息（`request`／`requestfinished`／`requestfailed` 記帳）。這次沒能重現，下次紅的時候就能直接看到是哪一支，而不是再猜一次。
- **O5-S3（產品，擁有前端資產的人／主持指派）**：字型改成 woff2 並做中文常用字子集（預期可從每支約 5 MB 降到 1 MB 上下），並給 `/fonts/` 長效快取標頭（檔名帶版本時）。這同時改善正式機慢網路的首頁體驗。

## 5. 限制

- 在 D 能製造的負載（platform `-n 4`＋e2e `-n 2`）下沒有重現；全量列車同時有多組 e2e 與全量，負載型態不同。本報告只證明「load 被字型綁住」與「字型是最長的一支」，**沒有證明列車上那兩次的逾時就是字型**。O5-S2 就是為了補上這個證據。

## 6. 後續（D，14:27）

- 主持裁示 O5-S3：先轉 woff2、**不做子集**（罕用字會變方框），再加快取。第一步 `wip/h-fonts` `7728934b`：`/fonts/` 給 `public, max-age=604800`（7 天、可用 ETag／Last-Modified 重新驗證，不用 immutable）。D：題 2 passed；突變「字型不給快取」紅、「字型規則也吃到 /css/」紅 ⇒ **通過（7728934b）**。
- ⚠ 這一步改善的是**正式機的重複造訪**；e2e 每題都開新的 browser context，快取本來就不跨題，所以對列車上的 O5 沒有幫助——測試那一側要靠 O5-S1（字型替身，已交 B）。

