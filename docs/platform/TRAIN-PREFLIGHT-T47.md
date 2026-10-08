# 列車預檢（train preflight，第 47 班）

> 起因：第 46 班列車為「便宜的登記類紅燈」重跑約 5 次全閘門（約 3 小時）：CHANGELOG 佔位順序、IP 登記表、scope-gate 全域清單、approval_flow_scope、BEGIN 白名單、golden。它們都能在幾分鐘內發現，卻被 fail-fast 一次只露一個。
> 目標：**整合／取號之後、`run-stage` 之前**，一個指令、一次、不 fail-fast，把這類紅燈在 **10 分鐘內全部列出**。工具 `tools/platform/train_preflight.py`；與 `pre_train_check.py`（作者在分支階段預演合併）互補：preflight 跑在**已整合的列車樹**上。

## 用法
```
python tools/platform/train_preflight.py [--base origin/platform] [--static-only] [--no-impacted] [--dry-run] [--json-out F]
python tools/platform/train_preflight.py measure      # 閒置時更新各測試檔耗時（寫 tools/platform/full_results/preflight_seconds.json，不進 git）
```
結束碼：0 全綠；1 有紅（靜態發現或測試紅，報告依歸屬分組）；2 工具本身出錯。`--dry-run` 只印「會跑什麼」。

## 三層（同一份報告，不 fail-fast）
| 層 | 內容 | 時間 |
|---|---|---|
| **A 靜態旗標**（純 Python，秒級） | 六類已知紅燈，**直接呼叫各守門自己的掃描函式**（不重寫規則，避免兩邊漂移）；每筆附一行修法 | < 1 分（A0 重用 regen_all --check 約 42 秒，其餘約 10 秒）|
| **B 便宜守門測試**（單一行程 `-p no:xdist`） | 自動挑選：`tests/platform` 全部（扣掉 `gate_slices.json` 的 exclude＝測工具本身的慢題）＋ slice0 守門＋掃整棵樹的測試（`scope_gate` 全域訊號＋ `rglob/glob/ast.parse/source_tree` 掃描特徵）＋**實測 < 10 秒**的測試檔（耗時取 `full_results/file_seconds.json`、`preflight_seconds.json`，再退回 `gate_file_seconds.json` 種子；另有**固定清單** `ALWAYS_FILES`（本班抓到過紅燈的守門：generated_maps、module_changelog_follows_code、version_manifest VR1、v9_baseline、core_upgrade、l1_interface_snapshot、product_drill_probes…，不論有沒有耗時資料都跑）；**沒有量過的檔不猜**，只靠前面三條規則入選） | 目標 < 8 分 |
| **C 受影響測試** | 對 `base...HEAD` 變動檔重用 `pre_train_check.touched_modules／module_test_dirs`，加跑動到模組的 `tests/`（與 B 去重） | 視變動量 |

B、C 合成**一次** pytest（`MOTRIX_TRAIN=1`、`-m "not e2e"`、`-rf`、`--basetemp %TEMP%\pt_preflight_*`、跑完刪），紅的題用 `pre_train_check.group_reds` 依歸屬分組、附單獨重跑指令。

## A 層八類（對應第 46 班的實際紅燈；另加 ab 提供的兩類）
| # | 旗標 | 來源守門（呼叫其函式） | 修法提示 |
|---|---|---|---|
| A1 | CHANGELOG `(next)` 被埋在版號標題之後／版號未遞減／內文重複 | `tests/platform/test_changelog_sections.problems` ＋ 自己的 `(next)` 位置檢查 | 把 `## (next)` 移到檔案最上面 |
| A2 | 程式有 provider／consumer，`INTEGRATION-POINTS.md` 沒有 `## IP-NNN` 節 | `test_integration_points_registered.mismatches` | 補 IP 節（提供方／使用方／形式／回傳／契約版本／守門） |
| A3 | 新的「掃整棵樹」測試沒進 `bottom_layer.json` `global_tests`（或已過期） | `scope_gate.global_test_candidates` | 加入／移除該路徑 |
| A4 | 新 `register_doc_type` 沒進 `test_approval_flow_scope.py` 的 `EXPECTED_SCOPE`／`FULL_SCOPE_BODY`，或 `check_approval_queue_coverage.py` 兩張表 | AST 比對（常數 `DOC_TYPE` 會解析） | 各加一行 |
| A5 | 新的 `BEGIN`（`BEGIN IMMEDIATE` 等）不在白名單 | `test_begin_only_via_begin_write._all_sites／ALLOWED` | 改用 `core.txn.begin_write`，或比照 bonus.py 登記白名單 |
| A6 | 動到被 golden 檔涵蓋的頁面／JS | 掃 golden 對應的 e2e 檔引用的頁面（及同名 `js/<頁>*.js`）∩ 變動檔 | 以對應角色重錄 golden，附差異說明 |
| A0 | 產生檔（dep_graph／test_map／UNIT-INDEX）過期 | 呼叫 `tools/platform/regen_all.run(repo, check_only=True)`（ab，`wip/t47-build-optimization`；還沒進樹就略過，B 層 `test_generated_maps` 仍會抓） | 執行 regen_all 後提交（順序：取號→dep_scan→test_map→unit_index） |
| A7 | 測試寫死 `--expect-db-version N`，N ≠ `db.CURRENT_VERSION`（stepfile 演練慢，~80 秒，故靜態先抓；檔內自造假 db.py 者不算） | 正則比對 | 改引用 `db.CURRENT_VERSION` |
| A8 | 這次新增／修改的測試函式呼叫 `get_db()` 卻沒有 client／make_user 等夾具（xdist worker 第一題會 no such table） | AST（只掃變動檔，避免對存量噪音） | 加 `client` 夾具 |
- 工具的任一掃描函式匯入失敗 ⇒ 該項標「**未能檢查**」並列在報告最前（不靜默當綠）。

## 不做／限制
- 不取代全閘門與 e2e；只攔「便宜、登記類」紅燈。預檢綠 ≠ 閘門綠。
- B 層的 < 10 秒清單只在有耗時資料後才涵蓋「普通小測試」；第一次用先跑 `measure`（閒置、單行程，約 20–30 分，列車前做一次）。
- 不寫任何追蹤檔、不 commit、不 push；唯一寫入是 basetemp（用完刪）與 `measure` 的耗時檔。

## 驗收
`backend/tests/platform/test_train_preflight_t47.py`：六類各有正對照（合成樹會被抓到）與反向對照（乾淨樹不誤報）；B 層選擇規則（耗時門檻、未量測不猜、排除表）；C 層去重；報告分組；`--dry-run` 不執行 pytest。

## A6 誤報處理（第 47 班，實測）
golden 分兩種：**內容 golden**（錄頁面文字／API 請求）與**樣式 golden**（錄被選元素的 computed style，e2e 檔含 `getComputedStyle`）。樣式 golden 只有在動到 CSS 檔、`<style>`，或 diff 的增刪行含該 golden 所選的 class 名時才旗標；只加內容區塊（行內 style）不旗標。實例：第 46 班 `case-management` 派發區塊 P3 → `golden_case_page_theme` 曾被誤報，全 e2e（950 過）證實該 golden 未受影響。
