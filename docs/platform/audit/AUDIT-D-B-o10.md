# 抽查：B 的 O10——選單序號題改「題目放行第一趟」（wip/b-o10 cc550c64）（D，2026-09-26 18:39）

> §G4 抽查，只改測試。主持要求確認三點。

| # | 主持的問題 | D 的驗證 | 結果 |
|---|---|---|---|
| 1 | 新題等的是狀態終點＋序號，不是時間 | 讀 diff：第一趟扣住，直到題目呼叫 `window.__releaseFirst()`；放行後等 `window.__staleRead === true`（產品碰到 ok 或 json 才會設），再等兩個 macrotask（`setTimeout 0` 兩層），然後斷言 `data-menu-state`。原本的 `setTimeout 1500` 與 `wait_for_timeout(100)` 都已拿掉 | 成立（「兩個 macrotask」是讓 then／catch 鏈跑完的最小等待，不是牆鐘時間） |
| 2 | 重現方式（logo 延後 2.5 秒）能讓原題紅 | D 自寫 pytest 外掛（不提交）：每個 e2e context 對 `**/static/logo.png` sleep 2.5 秒再放行 | **原題（cc550c64^）**：一般 2 過、延後 **2 紅**；**新題（cc550c64）**：一般 2 過、延後 **2 過** |
| 3 | 產品端丟棄舊回應在負載下也有題守 | 突變 `sidebar.js`：拿掉成功路徑、失敗路徑的 `if (my !== _menuSeq) return`，一般與延後各跑一次 | **4/4 紅**（成功路徑 ⇒ `test_stale_layout_response_is_dropped`；失敗路徑 ⇒ `test_stale_failed_response_is_dropped`） |

⇒ 通過、必修 0。
