# 稽核：B 的 e2e 每題死線＋teardown 看門狗不再結束行程（wip/b-e2e-deadline cccd80fc；疊在 b-o9 上）（D，2026-09-26 18:25）

> 完整稽核（fixture 層）。稽核者 D 沒有寫過任何受稽核的程式碼。

## 0. 結論

- **必修 1、觀察 2**。
- 反向控制在 `-n 0` 與 `-n 2` 都成立；看門狗已經不用 `os._exit`。
- 必修的原因：主持要求「軟上限先於硬上限、兩套規則不可以打架」，但這條規則沒有被守住。

## 1. 實測

| 項目 | 結果 |
|---|---|
| `os._exit` | conftest 已經沒有（grep 只剩說明文字）；teardown 逾時改成在瀏覽器自己的事件迴圈上關掉瀏覽器，並讓那一題 teardown error |
| 反向控制（D 探針，不提交）：`evaluate` 回傳永不 resolve 的 fetch，之後接一題正常題；`MOTRIX_E2E_TEST_LIMIT=15` | **`-n 0`**：22 秒結束，1 failed、1 passed；報告附「e2e 超過每題死線 15 秒」與 `14.6s GET /api/o5-hang?pt=***&q=***`（值已遮）。**`-n 2`**：21 秒結束，結果相同。兩次的秘密字串 DSECRETY 都 0 外洩 |
| 突變 DL2：死線到了不關 context | 紅（`test_deadline_breaks_a_never_settling_evaluate`；該輪卡到 128 秒才由硬上限收尾） |
| 突變 DL3：teardown 逾時不讓題目失敗 | 紅（`test_rc_teardown_hang_fails_only_that_test[n0]` 等 2 題） |
| 突變 DL1：軟上限改成「硬上限＋30」（比硬上限晚到） | **存活**（23 過）⇒ E2D-M1 |

## 2. 發現

### 必修

**E2D-M1　「軟上限＝硬上限－30、必須先到」沒有守門，覆寫值也沒有夾住**
- DL1 存活：預設公式改成晚於硬上限，沒有任何題會紅。
- `_e2e_limit_of`：`@pytest.mark.e2e_limit(秒)` 與 `MOTRIX_E2E_TEST_LIMIT` 都原樣採用。設成大於等於 `MOTRIX_E2E_HARD_CAP` 時，在 xdist 下硬上限會先把 worker 結束，軟上限的「讓這一題失敗並說出卡在哪」永遠輪不到。這就是主持說的兩套規則打架。
- 反過來，把 `MOTRIX_E2E_HARD_CAP` 調小（例如 30）時，軟上限由公式跟著降（最少 10），這一邊沒問題。但 teardown 看門狗的 `MOTRIX_E2E_TEARDOWN_LIMIT`（預設 60）不隨硬上限變：硬上限小於 60 時，teardown 也是硬上限先到。
- 修法：
  - 軟上限與 teardown 上限一律取 `min(設定值, 硬上限 − 30)`。被夾住時說出來。
  - 補題：①預設值小於硬上限；②marker 或環境變數大於等於硬上限時會被夾住並說明。修完後 DL1 要轉紅。

### 觀察

- **E2D-O1**：`-n 0` 的輸出多一行 `ERROR asyncio: Exception in callback Connection.dispatch…_done_callback`，是在事件迴圈上關掉 context 後，Playwright 內部還在等回應的任務被取消所產生的。不影響判定，但看起來像另一個錯誤，會把查的人帶偏。
- **E2D-O2**：每題預設上限是 90 秒（硬上限 120 − 30）。本包合回後，原本跑 90～120 秒而能過的 e2e 會改成失敗。列車目前不跑全量，建議第一次全量時看 `full_results` 的最慢清單（b-modtest-durations）確認沒有這樣的題。

## 回覆（B，18:46，wip/b-e2e-deadline-2 78d372b9）

| # | 回覆 | commit |
|---|---|---|
| E2D-M1 | 修正：`_clamp_soft` 把標記、MOTRIX_E2E_TEST_LIMIT、teardown 上限（標記與環境變數）一律夾在硬上限－30 以下，被夾住時 stderr 說出來；題：預設＝硬上限－30、各來源超過都被夾、跟著硬上限變、下限 10；DL1（＋30）⇒ 兩題紅 | 78d372b9 |
| 觀察（90～120 秒的題） | 實量：全部 e2e 加 `--durations-min=30`，超過 30 秒的只有 48.4s（子行程反向控制）、40.5s（p8 模組建構器驗收）；最慢 ×1.5＝73 秒 < 90 ⇒ 預設不改、不需個別標記 | — |

閘門：全部 e2e（-n 2）463 過；tests/platform（-n 4）1091 過。


## 3. E2D-M1 複核：wip/b-e2e-deadline-2 78d372b9（D 18:55）

- 修法：`_clamp_soft` 讓軟上限一律取 min(設定值, 硬上限 − `SOFT_MARGIN`＝30)，被夾住時寫 stderr。範圍包含 e2e_limit 標記、`MOTRIX_E2E_TEST_LIMIT`、e2e_teardown_limit 標記、`MOTRIX_E2E_TEARDOWN_LIMIT`。
- 突變 4/4 紅（都在 `test_soft_limits_stay_below_the_hard_cap`）：
  - E2D1：公式改成「＋30」
  - E2D2：標記不夾
  - E2D3：環境變數不夾
  - E2D4：teardown 不夾
⇒ **E2D-M1 關閉（78d372b9）**。
