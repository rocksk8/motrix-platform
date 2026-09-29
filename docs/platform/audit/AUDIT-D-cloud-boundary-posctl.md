# AUDIT-D：wip/cloud-boundary-posctl（e30a666b，基底 70ec2523）

2026-09-29｜只改測試（`tests/platform/test_module_boundaries.py`）。**必修 0 項；建議 0 項。**

- 消失的邊改用合成 L2 模組（tmp_path 內 zz_p→zz_q），走真掃描器 `dep_scan.build` 與真判定 `check_import_baseline`，不再因基線清空而 skip；新增跨組新增題 ✔
- 本檔 27 過（自跑）
- **自做突變（2）**：`check_import_baseline` 的「消失」恆回 `[]` ⇒ `test_rc_vanished_baseline_edge_is_caught` 紅；「新增」恆回 `[]` ⇒ 4 題紅（含合成新增題與 end-to-end）✔（已還原）
- 邊界情形：zz_p 不在 modules.json 登記，不會被「沒裝的已登記模組」規則吃掉（題內註明）；組內 import 不算跨組（題有斷言）✔
- repo 現況的「零新增／只准減少」原題未動 ✔
