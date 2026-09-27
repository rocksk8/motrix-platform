# 稽核：B 的探針寫 tmp＋殘檔守門（wip/b-probe-tmp 4ecf73ea）（D，2026-09-27 10:28）

> 標準等級（動到 conftest）。起因是 D 在 AUDIT-D-C-m01-4 的觀察 M4-O3：inflight 探針殘留在受測樹，被別的 worker 收集成紅。
> 內容：
> - `tests._subproc.probe_pytest_args`：探針寫在 tmp，子 pytest 以 `-c pytest.ini --rootdir/--confcutdir <探針目錄> -p conftest` 吃 backend 的 conftest；
> - 三支探針改寫：inflight_report、hard_cap、pytest_guards NG1；
> - conftest `pytest_probe_leak_sessionstart／sessionfinish`：一輪結束時 tests/ 與 modules/*/tests/ 多出 test_*.py ⇒ 判紅。

## 0. 結論

- **通過。必修 0、建議 2、觀察 1**。
- 複核 b-probe-guard-s 04c0e912：**PT-S1、PT-S2 關閉**（§3）。

## 1. 實測

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 受影響題 | test_probe_leak_guard、test_subproc_helper、test_pytest_guards、test_e2e_hard_cap、test_e2e_inflight_report（-n 2）：**61 過** | 成立 |
| 子 pytest 用 utf8_env | inflight 的 `_run_probe` 改成 `utf8_env(...)`。`test_subproc_helper_2026_09_21::test_every_test_that_spawns_pytest_builds_its_env_with_utf8_env` 在 221adaa0 是紅（M4-O4），在本包**綠** ⇒ 成因確認 | 成立 |
| 別的探針還有沒有寫進 tests/ | grep 測試裡所有寫檔：其餘都寫在 tmp_path／沙盒 | 成立 |
| **真實受測樹**的反向控制（不用 `MOTRIX_PROBE_LEAK_ROOTS`） | ① 在 tmp 的探針寫一個 `backend/tests/test_zz_d_leak_probe.py` 留著 ⇒ rc 1，並列出該檔；② `-n 2`、由 worker 寫進 `modules/crm/tests/.hid/` ⇒ rc 1，並列出該檔 | 成立（預設範圍今天有效） |
| 突變 | PL3「多出檔也不判紅」⇒ 紅；**PL1「預設範圍改成空」、PL2「預設範圍不含 modules/*/tests」⇒ 存活** ⇒ PT-S1 | 1/3 紅 |

## 2. 發現

**PT-S1（建議）　預設監看範圍沒有題鎖住**
- `test_probe_leak_guard` 的反向控制與正對照，都用 `MOTRIX_PROBE_LEAK_ROOTS` 把範圍換成 tmp 裡的假目錄，所以 `_probe_leak_roots()` 的預設值從來沒被驗到。
- 把預設範圍改成 `[]` 或拿掉 `modules/*/tests` ⇒ 全綠，而守門在真實的一輪裡什麼都不看（〈守門守的對象被搬走〉）。
- 建議補一題：不設環境變數時，範圍含 `backend/tests` 與每一個 `modules/<key>/tests`（以 `modules/*/tests` 實際存在的清單比對）。
- D 已在真實樹手動證明今天的預設有效（§1），所以列建議，不擋車。

**PT-S2（建議）　`MOTRIX_PROBE_LEAK_ROOTS` 會一路傳給子孫行程**
- `utf8_env` 沒有 pop 它。外層一旦設了（例如反向控制的子 pytest，或有人在殼層設了），往下的每一輪都會靜靜地改看別的目錄，守門等於關掉，而且不會說出來（〈環境變數旗標會漏進子 pytest〉）。
- 建議在 utf8_env 的清除清單加上它（反向控制的題是用 `run_python(..., MOTRIX_PROBE_LEAK_ROOTS=...)` 明傳，不受影響），並在設了它時印一行提示。

**觀察**
- **PT-O1**：共用工作樹裡，一輪期間別的視窗新增的測試檔也會把這一輪判紅（訊息有寫明）。列車在自己的工作樹不受影響；主工作樹上的全量（30 分鐘以上）若被這樣判紅，重跑成本高。

## 3. 複核（wip/b-probe-guard-s 04c0e912）（D，2026-09-27 10:50）

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 相關題 | test_probe_leak_guard＋test_subproc_helper：15 過 | 成立 |
| PT-S1：預設監看範圍有題鎖住 | 新題 `test_default_watch_roots_are_tests_and_every_module_tests`（不設環境變數，範圍含 backend/tests 與每一個實際存在的 modules/*/tests）。突變 PS1「預設改空」、PS2「不含 modules」、PS3「只含一個模組」⇒ 3/3 紅 | **PT-S1 關閉** |
| PT-S2：utf8_env 清掉覆寫 | `MOTRIX_PROBE_LEAK_ROOTS` 加進清除清單，明傳時照給。突變 PS4「不清」⇒ 紅 | **PT-S2 關閉** |

- 原建議的「設了覆寫時印一行提示」沒有做；子行程已清掉，只剩外層手動設定這一種情形，列觀察即可。
