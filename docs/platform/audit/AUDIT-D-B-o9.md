# 稽核：B 的 O9——jv7 等畫面終點＋e2e 關 context 看門狗（wip/b-o9 79b89eef；疊在 o5-s2-2 上）（D，2026-09-26 17:46）

> 主持派的是抽查，但本包在 conftest 的 `new_context` teardown 加了會呼叫 `os._exit` 的看門狗，屬 fixture 層，所以 D 多做了行為驗證。

| 項目 | 結果 |
|---|---|
| 基準：voucher_summary＋inflight_report（`-n 2`） | 16 過 |
| 突變 O9a：`_opened` 改回「response＋nextTick」 | 紅（`test_jv7_an_edited_summary_survives_a_reload`；本包用 `.json()` 延後 800ms 把偶發變成必然） |
| 突變 O9b：看門狗不啟動計時器 | 紅（`test_teardown_watchdog_says_why_and_exits`） |
| 看門狗的覆蓋範圍 | 只包住 context／browser 的 close。**題目本體卡住不在範圍內**：D 的探針卡在 `evaluate`，20 秒上限照樣卡 240 秒 |

**觀察**
- **O9-O1**：`os._exit(3)` 在 `-n 0`（沒有 xdist）時結束的是 pytest 主行程本身：沒有報告，basetemp 也不會清。鎖檔會因為持有者死亡而自動放行，這一點已確認。本包的訊息寫「結束這個 worker」，在 `-n 0` 的情況下語意不同，建議在訊息裡補一句。
- **O9-O2**：題目本體沒有預設逾時，Playwright 的 `evaluate` 沒有 timeout。建議 e2e 有一個每題的總上限（例如 pytest-timeout，或同一套看門狗包住 call 階段），否則探針或題目自己寫錯，就會像 D 這次一樣靜默卡死。

⇒ 通過、必修 0。
