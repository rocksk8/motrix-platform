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

## 回覆（B，17:26，wip/b-o5-s2-2 fd5af159）

| # | 回覆 | commit |
|---|---|---|
| S2-S1 | 修正：`safe_url` 只印路徑＋query 參數名、值 `***`；題「inflight_text 本身不印值」（突變 safe_url 原樣回傳 ⇒ 紅） | fd5af159 |
| O5S2-O1 | 修正（主持改列必做）：e2e 失敗報告任何階段整段 `redact`（Bearer、authorization／cookie 值、JSON token／password、query 的 pt／token／key／sig／q）；反向控制＝真的 Playwright 失敗帶 `?pt=SECRET3`＋`Bearer SECRET3`，原始錯誤含 SECRET3（正對照），經 hook 後不含（突變：hook 不遮 ⇒ 紅） | fd5af159 |
| O5S2-O2 | 查明：D 的探針若寫 `page.evaluate("fetch('/x')...")`，evaluate 會等那個 fetch 的 promise；route 不回應 ⇒ 一直等到 renderer crash（B 實測 50～400 秒以上不定）才丟，之後 close 也卡 ⇒ 看起來是「卡住、沒有輸出」。B 的題最後一個運算式是會完成的 fetch（或包成不回傳的函式 `() => { fetch(...) }`）⇒ 不等。B 探針：回傳 promise ⇒ 卡；函式不回傳 ⇒ 10 秒結束。teardown 的上限另在 O9（wip/b-o9）處理 | fd5af159 |

閘門：全部 e2e（-n 2）460 過；tests/platform（-n 4）1086 過。


## 4. S2-S1 複核：wip/b-o5-s2-2 fd5af159（D 17:46）

主持要求真的造一個 Playwright 失敗。B 的反向控制是把錯誤文字手動餵給 `_drive`，D 另外寫了一支**完整走 pytest 回報流程**的探針：3 題真的失敗，秘密字串設成 `DSECRETX1`，分別跑 `-n 0` 與 `-n 2`，輸出加上 `-rA -l` 與 `--junitxml`，再搜尋 log 與 xml。

| 題（真的失敗） | 秘密出現的位置 | 結果 |
|---|---|---|
| `page.request.get(...?pt=DSECRETX1&q=DSECRETX1, headers={Authorization: Bearer DSECRETX1})` 回 404 | Playwright 的錯誤文字與 call log | **0 外洩**（log 與 xml） |
| `extra_http_headers` 帶 Bearer，逾時 | call log＋逾時報告段 | **0 外洩** |
| `assert tok == ...`，訊息與區域變數帶秘密；另一題 `print` 秘密 | assert 訊息、`-l` 印出的區域變數、Captured stdout | 5 處外洩（`-n 0` 與 `-n 2` 相同） |

- 已知形狀全部遮到：Bearer、authorization、`?pt=`、`?q=`，而且 xdist 也一樣。
- 外洩的 5 處都是**沒有鍵名的裸值**，規則式遮蔽原理上認不出來，不歸本包。記為 **O5S2-O3**：題目本身不要把權杖放進 assert 訊息或 print。
- 突變 S22「不遮 longrepr」⇒ 紅（`test_rc_a_real_playwright_failure_leaks_nothing`）。
⇒ **S2-S1 關閉（fd5af159）**；**O5S2-O1** 同時處理完畢。

**O5S2-O2 更正（原句保留在 §3）**：D 探針卡死的原因已查到，是**探針自己的錯**，不是 fixture：
- `page.evaluate("fetch('/api/…').catch(() => {})")` 的回傳值就是那個永遠不 resolve 的 promise，evaluate 會一直等它。
- B 的題用分號接第二個會完成的 fetch，所以能過。
- 在 b-o9 上用 20 秒的看門狗重跑，照樣卡住 240 秒：卡在題目本體，不在 teardown。
- 這就是〈探針與被測對象糾纏〉。
