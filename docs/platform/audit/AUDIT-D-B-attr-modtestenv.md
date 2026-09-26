# 抽查：B 的 b-m08-attr（52178979）與 b-modtest-env（bf4abacb）（D，2026-09-26）

> 依 PLAYBOOK §G4 抽查（主持派工）：看 diff、跑受影響題、做突變。稽核者 D 沒有寫過任何受稽核的程式碼。

## 0. 結論

- 兩包都是**必修 0**，另有 **1 項觀察**（modtest-env 的 MT-O1）。

## 1. b-m08-attr 52178979（analytics 1.0.2：`_compute_achievement(…, name_to_id=None)`）

| 項目 | 結果 |
|---|---|
| diff | 只在沒有給 `name_to_id` 時才查 `users`；正式呼叫端（reports.py:2289）不帶這個參數，行為不變 |
| `test_reports_sales_owner` 單獨跑（`-n 0`，不依賴別題建庫） | 12 過 |
| 其他不帶對照的呼叫端單獨跑：`test_core`、`test_money_round_half_up` | 16 過、5 過（這兩檔有建庫夾具，不受影響） |
| 突變 A1：無論有沒有給對照都查資料庫 | 紅（2 題） |

## 2. b-modtest-env bf4abacb（MOTRIX_FULL／PARTIAL／E2E_MAX_WORKERS）

| 項目 | 結果 |
|---|---|
| 基準：`test_env_and_load_guards`＋generated_maps | 56 過 |
| E1：`--full` 的 e2e 段改用全量上限 | 紅 |
| E2：拿掉「大於 CPU 數不採用」 | 紅 |
| E3：差異題改回直接用常數、不讀環境變數 | 紅 |

**MT-O1（觀察）**：差異題模式（非 `--full`）如果選到 e2e 題，也只用 `partial_max_workers()` 限制，e2e 沒有另外的上限。
- 預設是 2，沒有問題。
- 但全速時如果設 `MOTRIX_PARTIAL_MAX_WORKERS=4`，被選進來的 e2e 會以 `-n 4` 跑，違反主持的「e2e 一律 -n 2」。這是 13:2x 記憶體不足停掉的同一種情形。
- 要處理的話：差異題含 e2e 時取 `min(partial, e2e_max_workers())`，或者把 e2e 拆成另一段。
