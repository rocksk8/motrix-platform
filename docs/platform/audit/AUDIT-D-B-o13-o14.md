# 稽核：B 的 O13（焦點搬移晚到）與 O14（inflight 子 pytest 排全機鎖）（D，2026-09-27 14:02）

> 標準等級。依 PLAYBOOK §G1 ⓪／§G5（2026-09-27 使用者裁示）：先讀 diff 列疑點，只跑針對疑點的題、突變與反向控制。

## O13：wip/b-o13 d7fb8faf（主持後改派 -2 ea93e37c，見 §O13-2）

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 修法 | `keepSummaryFocus` 記下呼叫當下的 `activeElement`；`$nextTick` 時焦點已移到別處（不是原本那個、也不是 body）⇒ 不搬。呼叫端只有 `srcPanelPick`／`srcPick` 兩處 | 成立 |
| 重現是決定性的 | 題目把頁面上 0 延遲的 `setTimeout` 固定延後 400ms（`add_init_script`），不靠時間窗 | 成立 |
| 正常路徑沒被破壞 | 正對照 `test_o13_focus_still_returns_to_the_summary_when_the_user_stays`（點完沒移開 ⇒ 焦點回摘要） | 成立 |
| 突變 | O13a「拿掉『已移開就不搬』」⇒ 紅；O13b「永遠不搬」⇒ 紅（正對照） | 2/2 紅 |
| 基底 | d7fb8faf 疊在 **c7f02596**（h-m01-6 的第一個 commit），不是 196af8fb；和 196af8fb 做兩點 diff 會把逐參數標記看成「改回」，是假象。動到的兩個檔在 c7f02596..e67879f2 之間沒有被改 ⇒ rebase 到 e67879f2 不會有交會 | 上車前 rebase |

## O14：wip/b-o14 d75b1784

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 根因與修法 | 子 pytest 在 `-n 2` 時被 `_is_heavy_run` 當成重的一輪去排全機鎖；改 `-n 1`（不是重的一輪）＋自己的鎖檔（`MOTRIX_PYTEST_LOCK` 指到本題 tmp），期限＝外層逐題上限 − 20 | 成立 |
| `-n 1` 仍驗到它宣稱要驗的東西？ | 讀碼：teardown 看門狗沒有 worker 專屬分支；`-n 1` 讓三題落在同一個 worker，「卡住後下一題還拿得到瀏覽器」驗的才是同一個 worker 的恢復（`-n 2` 時下一題可能分到另一個 worker）⇒ 理由成立。**但突變 W1「拿掉 `-n 1`，子行程改走單程序」⇒ 存活**（2 過）：題目沒有斷言子行程真的起了 xdist worker | **不成立 ⇒ O14-M1** |
| 看門狗 | 突變 W2「看門狗不關瀏覽器」⇒ n0、n1 都紅（子行程超過期限，以 pytest.fail 說明） | 成立 |
| 期限＜外層上限 | `max(30, cap − 20)`：cap ≤ 50 時等於 30；cap＝30 ⇒ 期限 30＝外層上限，不是「小於」。題只驗 120／90／300 | O14-S1 |
| **全 repo 同型盤點**（主持要求） | 起子 pytest 的題 9 檔。掃「子 pytest 是重的一輪（-n ≥ 2、-full、獨佔）卻沒隔離鎖檔」：初篩 3 檔（bg_thread_isolation、e2e_hard_cap、shared_playwright_event_loop），逐一讀命令列——`-n 6` 只出現在 docstring，實際子行程都是單程序或 `-n 1` ⇒ **沒隔離鎖檔的同型：0 檔**。掃描器的正對照：已知的 inflight 被認出（重、已隔離） | 0 |
| O14 的另一半（子行程期限 ≥ 外層上限） | `tests/test_shared_playwright_event_loop_2026_09_25.py`：外層標 `e2e`（120 秒逐題上限），子行程 `timeout=240` ⇒ 子行程逾時永遠輪不到，負載下會紅成「外層逐題上限」，看不出是子行程慢 | O14-S2 |

**O14-M1（必修）　n1 那格沒有驗到子行程真的走 xdist**
- 把 `cmd[6:6] = ["-n", "1"]` 拿掉，子行程變成單程序，題目照樣 2 過。
- 補斷言：子行程輸出有 xdist 的痕跡（例如 `[gw0]`、`created: 1/1 worker`），而且 n0 那格**沒有**。

**O14-S1（建議）**
- 期限在外層上限 ≤ 50 時不再「小於」外層。改成 `min(cap − 1, max(30, cap − 20))`，或在題目加一個小 cap 的案例。

**O14-S2（建議）**
- `test_shared_playwright_event_loop` 的子行程期限改由外層上限推出（同 `_child_deadline`）。
- §G5 第 8 列「子行程期限＜外層上限」已涵蓋這一條。

## O13-2：wip/b-o13-2 ea93e37c（取代 d7fb8faf；B 做 ⓪ 自查時自己修的）

- 兩題改驗 DOM：借方格的值、摘要格的值、`document.activeElement`；等終點改成 `__slowPending === 0`（被延後的回呼都執行完），不等固定 450ms。
- 突變 O13a「拿掉『已移開就不搬』」⇒ 紅；O13b「永遠不搬」⇒ 紅 ⇒ **O13 通過**（上車前 rebase 到 e67879f2，同上）。

## 複核（2026-09-27 14:14）

| 包 | D 的驗證 | 結果 |
|---|---|---|
| wip/b-o13-3 1c7f0a64 | `git range-diff c7f02596..ea93e37c e67879f2..1c7f0a64`：兩個 commit 都是「=」（內容相同，只換基底到 e67879f2） | **通過** |
| wip/b-o14-2 f189103c：O14-M1 | 探針把子行程的 `PYTEST_XDIST_WORKER` 寫出，n1 必須是 `gw0`、n0 必須是空。`utf8_env` 會清掉所有 `PYTEST_XDIST_*`，外層是 worker 時也不會繼承（外層 `-n 2` 實跑 23 過）。突變 W1「拿掉 -n 1」⇒ **n1 紅**（上一輪存活） | **關閉** |
| O14-S1 | 共用 `child_pytest_deadline`＝上限 − min(20, 上限／4)；題目加驗 50／30／20／8 都 `0 < 期限 < 上限` | **關閉** |
| O14-S2 | `test_shared_playwright_event_loop` 改用同一個期限 | **關閉** |
