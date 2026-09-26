# 稽核：B 的 modtest 差異題預設 -n（wip/b-modtest-workers 8eb264da；疊在 b-modtest-batch-2 f3be5cd2 上）（D，2026-09-27 01:54）

> 輕量等級。起因是 D 在 AUDIT-D-C-m01-ca3 的觀察 CA3-O3：差異題不帶 -n 時是串行。
> 內容：`default_workers(extra, limit)`：沒帶 -n，也沒帶 `-p no:xdist` ⇒ 補 `-n <partial_cap>`；`main` 的差異題改成 `cap_workers(default_workers(extra, cap), cap)`。

## 0. 結論

- **必修 2、建議 1**。函式本身正確；兩項必修都在「實際跑起來拿到幾個 worker」這一層。
- 複核 -2（1cb53e52）：**WK-M1、WK-S1 關閉**；新守門在 -3 沒改 run_train 時會先紅（§3）。WK-M2 待 -3。

## 1. 實測

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 相關題 | test_env_and_load_guards＋test_modtest_batches：58 過 | 成立 |
| 突變 | MW1「已帶 -n 也照補」⇒ 紅；MW2「選到 e2e 不降上限」⇒ 紅；MW4「無視 -p no:xdist」⇒ 紅；MW3b「main 改回不補預設」⇒ 紅（字串守門）；**MW3c「補完預設後丟掉、改用原本的 extra」⇒ 存活** ⇒ WK-S1 | 4/5 紅 |
| 主持重點 1：e2e 與非 e2e 同一批取較低上限 | 用 `main()` 攔截 `run_pytest` 實測：選到 132 檔、其中 7 檔 e2e ⇒ `-n 2`（預設）；PARTIAL=4、E2E=3 ⇒ `-n 3`；自己帶 `-n 8` ⇒ 壓到上限；`-p no:xdist` ⇒ 不補 | 成立 |
| 主持重點 2：第十二班 e2e 設 3 會生效 | **只設 `MOTRIX_E2E_MAX_WORKERS=3`（照裁示表的寫法）⇒ 差異題實際是 `-n 2`**，只有再設 `MOTRIX_PARTIAL_MAX_WORKERS≥3` 才會是 3。`--full` 的 e2e 段（`--e2e-workers 3`＋E2E=3）⇒ 3，本包沒有動這條路 | **不成立 ⇒ WK-M1** |
| 列車入口 `--train` | 在 train/0926-2154，**不在本包基底**。`run_train` ① 差異題仍是 `cap_workers(extra, partial_cap(...))`；D 查 TR11 正在跑的 pytest 命令列：**沒有 -n，串行** | **WK-M2** |

## 2. 發現

**WK-M1（必修）　只設 E2E=3 時，差異題仍然只拿到 2**
- `partial_cap` 在選到 e2e 時取的是 `min(PARTIAL 上限, E2E 上限)`，這是 D 在 MT-O1 要求的，防的是 PARTIAL=4 時 e2e 用 -n 4 跑。
- 副作用是 E2E 設得比 PARTIAL（預設 2）高時，E2E 的設定不會生效。commit 訊息寫「選到 e2e 取 MOTRIX_E2E_MAX_WORKERS」，與實際不符。
- 修法二擇一：
  - ① 第十二班裁示表加註 `MOTRIX_PARTIAL_MAX_WORKERS=3`，只改文件；
  - ② 選到 e2e 時，只要 E2E 是**明確設定**的，就用 E2E 上限，不再取 min。
- 不論選哪個，都要補一題：「只設 E2E=3、選到 e2e ⇒ -n 3」（或 ① 的「兩個都設 ⇒ 3」），並把 commit 訊息／docstring 的說法改成實際行為。

**WK-M2（必修，合併時）　列車的差異題入口沒有被涵蓋**
- `run_train`（d7a79b2a／98922bad，在列車分支上）的 ① 差異題直接呼叫 `cap_workers(extra, partial_cap(...))`，不經過 `default_workers`。
- 本包合回後列車仍是串行。實證：TR11 此刻的差異題 pytest 沒有 -n。
- 合併時 `run_train` 也要改用 `default_workers`，並把呼叫端守門擴到 `run_train`。

**WK-S1（建議）　呼叫端守門是字串比對**
- `test_no_call_site_caps_with_the_bare_constant` 驗的是原始碼裡出現 `cap_workers(default_workers(extra, cap), cap)`。補完預設後丟掉、另用原 extra 的寫法（MW3c）會存活。
- 建議改成行為題：攔截 `run_pytest`，跑 `main(["--files", …])`，斷言拿到的 extra 含 `-n <上限>`。D 的探針就是這樣寫的，可以直接拿去用。

## 3. 複核（wip/b-modtest-workers-2 1cb53e52）（D，2026-09-27 02:07）

> 只看 WK-M1、WK-S1 與新守門。WK-M2 等 -3（第十一班合回後 rebase）再看。

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 相關題 | test_env_and_load_guards＋test_modtest_batches：61 過 | 成立 |
| WK-M1：E2E 明確設定就直接用 | 題 `test_explicit_e2e_cap_is_used_as_is`（經 `main`、只設 E2E=3 ⇒ `-n 3`）。突變 WM1「明確設定時仍取 min」⇒ **紅** | **WK-M1 關閉** |
| WK-S1：行為題 | `test_main_partial_run_actually_passes_n` 攔截 `run_pytest`。突變 WS1「補完又丟掉」（上一輪存活的 MW3c）⇒ **紅**；WS2「不補預設」⇒ 紅；WS3「不壓上限」⇒ 紅；WG1「改用關鍵字參數、自己組參數」⇒ 紅 | **WK-S1 關閉** |
| 新守門 `test_every_partial_run_goes_through_partial_pytest_args` | 拿 TR11 真實的 modtest.py 跑同一個 offenders：第 744 行（run_train ①）與第 1260 行（main）都被列出。把 TR11 的 `run_train` 原樣接到本包的 modtest.py（模擬 -3 沒改）⇒ 列出 1 處；改成 `partial_pytest_args(extra, picked, tmap)` ⇒ 0 處 | **成立：-3 若沒改 run_train，這道守門會先紅；改了就轉綠** |

- 觀察 **WK2-O1（射程）**：新守門只認「第一個位置參數叫 `picked`、第二個是位置參數」的呼叫。改用關鍵字（`extra=`）或換變數名稱就看不到。
  - 對 main，行為題補得住（WG1 紅是行為題抓到的，不是新守門）。
  - 對 run_train，只有這道結構守門。-3 若照 TR11 現有寫法（位置參數、`picked`）會被抓到；若順手改了寫法就不會。-3 複核時 D 會直接驗 run_train 實際傳出的參數。
- 觀察 **WK2-O2（等價突變）**：WM2「選到 e2e 一律用 E2E 上限」、WM3「沒設 E2E 也當成明確設定」⇒ 存活。只有在 PARTIAL 小於 E2E 預設（2）時結果才會不同，例如 PARTIAL=1、選到 e2e：應為 1，突變後是 2。要鎖住就補「PARTIAL=1、未設 E2E、選到 e2e ⇒ -n 1」一題。現行上限都 ≥2，列觀察。
