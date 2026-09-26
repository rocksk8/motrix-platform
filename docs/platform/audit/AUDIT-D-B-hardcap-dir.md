# 稽核（輕量）：B 的 e2e 逐題上限目錄收尾（wip/b-hardcap-dir 0eddad8d）（D，2026-09-26 21:28）

> 改動：
> - 主控在 `pytest_unconfigure` 呼叫 `_cleanup_hard_cap_dir()`：只有**空目錄**才 `os.rmdir`。
> - 有逾時堆疊檔時保留，摘要印出路徑。
> - 堆疊檔改成印完不刪。

| 主持的問題 | D 的驗證 | 結果 |
|---|---|---|
| 刪除只在主控、而且在所有 worker 結束之後 | 讀碼：呼叫點在 `pytest_unconfigure`，加了 `not hasattr(config, "workerinput")`；xdist 主控的 unconfigure 在 worker 全部結束之後才跑。清理只用 `os.rmdir`，非空目錄一定失敗，不可能刪到檔案 | 成立 |
| 有逾時堆疊檔時一定保留 | 突變 HC2「改成 `shutil.rmtree` 整個刪」⇒ 紅（`test_timeout_keeps_the_run_dir_and_prints_its_path`） | 成立 |
| 兩個視窗互不影響 | 讀碼：每個主控在 `pytest_configure` 無條件產生新的 `MOTRIX_E2E_HARDCAP_RUN`（uuid），worker 繼承；子 pytest 是獨立行程，也會取得自己的 uuid；backend 裡沒有在同一行程呼叫 `pytest.main` 的題 | 成立 |
| 基準 | `test_e2e_hard_cap` 8 過；突變 HC1「不清理」⇒ 紅（`test_normal_run_leaves_no_run_dir[n0/n1]`） | — |

- 觀察 **HC-O1**：突變 HC3「worker 也清理」存活，但屬無害：worker 同樣只 `rmdir` 空目錄，別的 worker 下一題進入時 `makedirs(exist_ok=True)` 會重建。
- 觀察 **HC-O2**：本包之前累積的舊目錄仍在。D 在 21:28 看到 `%TEMP%\motrix-e2e-hardcap-*` 有 **1085** 個，這是各視窗的歷史產物。依規則 D 不用萬用字元整批刪別人的東西；請主持決定由誰、用什麼條件（例如只刪空的、而且超過 1 小時的）一次清掉。

⇒ 通過、必修 0。
