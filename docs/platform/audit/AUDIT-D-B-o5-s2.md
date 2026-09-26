# 稽核：B 的 O5-S2——e2e 逾時時附上未完成的請求（wip/b-o5-s2 c7940387；疊在 o5-s1 上；合回前）（D 稽核，2026-09-26 16:58）

> 完整稽核（動到 fixture 層：conftest 的 `E2E_CONTEXT_HOOKS`＋`pytest_runtest_makereport`）。稽核者 D 沒有寫過任何受稽核的程式碼。

## 0. 結論

- **必修 0、建議 1、觀察 2**。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 新題 `test_e2e_inflight_report` | 3 過 |
| conftest 裡有沒有同名的 hook | 沒有：`pytest_runtest_makereport` 只有這一個，不會蓋掉別的 |
| 記帳是否套到 `e2e_browser.new_context()`（golden、arap 題都用這個寫法） | 會：`e2e_browser` 是 `new_context` fixture 的薄殼，hook 一律套用 |
| 突變 S2：不限定逾時，所有失敗都附報告 | 紅（`test_other_failures_and_passes_get_nothing`） |

## 2. 主持指定：會不會把個資或權杖印進失敗訊息

- **標頭不會**：記帳只存 `(時間, method, url)`，Authorization 等標頭不在裡面。
- **query 會**：`inflight_text` 印出 `r.url`，也就是含 query 的完整網址。本包自己的題也證實了這點：`_drive` 的報告裡就是完整 URL。
- 前端實際會帶進 query 的有：
  - `/api/uploads/<路徑>?pt=<簽章>`，8 處。HMAC 簽章、1 小時、綁單一路徑，屬短效權杖。
  - 各頁的 `?q=`／`?key=`／`?no=`，可能是客戶名稱等搜尋字。
- **建議 S2-S1**：報告只印路徑，加上 query 的參數名稱，值一律遮掉，例如 `/api/uploads/x.jpg?pt=…&q=…`。
  - 原因：e2e 失敗訊息常被貼進稽核檔、RUN-PLAN、跨視窗訊息（〈外洩的出口不一定是你寫的〉）。
  - 目前只有開發機的測試資料與測試伺服器的短效簽章，所以列建議不列必修。

## 3. 觀察

- **O5S2-O1（不是本包造成，範圍更大）**：Playwright 自己的錯誤訊息會附 call log，裡面有完整的請求標頭。D 在 M5-M2 的 log（`TargetClosedError … Route.fetch`）裡就看過 `authorization: Bearer <token>`。本包遮不遮 query，都擋不住這條。如果要處理，應該在 makereport 對整份失敗文字把 `authorization: Bearer \S+` 遮掉。
- **O5S2-O2（未解，不歸本包）**：D 寫的探針題「route 永不回應＋fetch」在 o5-s1 和 o5-s2 上都卡住，單題 90 秒逾時、沒有任何輸出，`-o faulthandler_timeout=40` 也沒有吐出堆疊。同樣形狀的 B 自己的題（換成 D 的檔名也試過）卻 3 過。追了 5 輪找不到差異，已停止追查。卡住的行程已用 taskkill /T 清掉，測試檔已移除。
