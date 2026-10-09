# 閘門加速：持續管線設計（編排角度；第 50 班，唯讀諮詢）

> hichan-ab，2026-10-09。**只設計，沒有跑任何重的東西。** 硬體不變。前提＝不弱化閘門：正式閘門仍驗**凍結樹**；下面所有「沿用」都沿用既有的指紋規則（同指紋、嚴格全綠、同日 12 小時內，`build_test_reuse.py`），不新增放水。

## 0. 已經有的零件（不要重造）
`modtest.py`（`--changed-since`／`--dry-run`：改動檔→單位→`test_map`＋`dep_graph` 反向擴大→受影響題＋契約題）；`failfast`／`fail_stream` plugin（`MOTRIX_FAILFAST=0` 可關）；`conftest` 全機鎖（`MOTRIX_PYTEST_SLOTS` 預設 2 格、`EXCLUSIVE`、pid 登記＋逾時清除）；`build_test_reuse.py` 分段紀錄（`not_e2e`／`e2e`，指紋＝整棵 tracked tree＋環境）；`modtest --full` 在**乾淨樹**會寫同一份紀錄；`gate_slices`／`preflight_seconds`／`known_flakes`。缺的不是工具，是**編排**：誰在什麼時候跑什麼、結果給誰看、怎麼不互相拖垮。

## 1. 持續增量跑者（整合分支背景守望）
`tools/platform/ci_watch.py`，跑在**自己的專用 worktree**（整合分支 `train/tNN-int` 的唯讀 checkout，不碰共用樹）。
- 迴圈：每 60 秒 `git fetch`；`origin/<int>` 的 HEAD 變了且機器空閒（見 §3）⇒ `modtest --changed-since <上次測過的 sha> --dry-run` 取題單 ⇒ 實跑（2 worker、低優先、`FAILFAST` 開）。契約題（`tests/platform`）每次必跑；改到 fixture 層（modtest exit 3）⇒ 不增量，改排一次 §2 的完整演練。
- **發布狀態行**（人和機器都讀）：原子覆寫 `D:\開發測試檔\_ci\status.txt` 與 `status.json`：`<sha8> | 範圍 12 單位／340 題 | 綠|紅 3：test_a, test_b… | 耗時 4m10s | 時間`；另追加 `history.jsonl`。任何視窗 `type D:\開發測試檔\_ci\status.txt` 就看得到，不必問 PM。
- 嚴守界線：**增量結果只是預警，永遠不寫 green 紀錄**（不進 `test_results`／`stages`），不能替代正式閘門。紅了＝把題名連同作者（`git log -1 --format=%an -- <測試檔>`）丟進狀態行，作者在凍結前就修。
- 價值（誠實）：它不縮短凍結後那一次完整閘門；它把『凍結後才發現紅 ⇒ 重跑整段（t47 實測每次約 65 分）』變成『整合期間就發現』。

## 2. 正式閘門怎麼吃快取、同時仍驗凍結樹
1. **「一次找出全部紅」的正式相容選項**：`run-stage` 加 `--no-failfast`（等同 b7 今天手動做的；只把 `MOTRIX_FAILFAST=0`、其餘 plugin／指令／指紋完全相同），結果多記 `reds:[題名…]`。**全綠的 run，failfast 本來就不可能截斷（執行題數＝收集題數）⇒ 無 failfast 的全綠與有 failfast 的全綠是同一份證據，可照舊被沿用**；有紅的 run 照舊不沿用。第一次用它跑完 → 一次拿到全部紅清單、一輪修完，而不是每輪只看到前 10 筆。
2. **演練→凍結沿用（不弱化）**：夜間／空檔，ci_watch 對整合 HEAD 跑 `modtest --full`（**乾淨樹**、無縮小範圍，已會寫分段紀錄；環境同正式閘門）。凍結的那個 commit 若**指紋與演練相同**，正式閘門 `lookup-stage` 直接沿用＝0 分鐘，且仍是『同一棵凍結樹全綠』的證據。要讓它成立的唯一編排工作：**取號／重產（`train_number assign`、`regen_all`）提早到演練之前**，讓凍結 commit 之後只剩打 tag、不再動 tree；凍結後若還要改任何 tracked 檔 ⇒ 指紋變 ⇒ 老實重跑（不要為了沿用去縮小指紋——O6 仍待使用者裁示）。
3. 沿用條件不動：同日、12 小時、嚴格全綠；演練紀錄標 `source=rehearsal`，稽核看得出來。`failfirst`（上次紅的先跑）與 `LPT` 順序照舊；ci_watch 順手更新 `gate_file_seconds`（`MOTRIX_GATE_RECORD=1`）。

## 3. 全機負載治理（5 個視窗）
現況是『鎖＋2 格＋逾時』：只擋同時開太多，沒有**排隊、優先序、誰在跑的可見度**。擴充（包在現有鎖外，不取代）：`tools/platform/heavy_run.py -- <指令>`。
- **分級**：`light`（單檔、1 worker、< 2 分，直接跑）；`heavy`（pytest ≥2 worker、建包、`modtest --full`）；`e2e`（瀏覽器，獨佔）。一律 `BELOW_NORMAL_PRIORITY_CLASS`，**正式閘門＝NORMAL**。
- **佇列**：`_ci\queue\<序號>-<視窗>-<級別>.json`（`O_EXCL` 建檔；內容 pid／指令／開始時間；pid 死掉或逾時即視為過期並清掉）。規則：同一時間**只有一個 heavy**；`e2e` 要等所有 heavy 結束且會擋住新 heavy（獨佔）；順序＝正式閘門 > e2e > 作者 heavy > ci_watch（最低）。記憶體可用 < 4 GB 不開 e2e（沿用既有規則）。
- **自願讓位**：ci_watch 每個測試檔之間看佇列，有更高級在等就中止並下次重排（pytest plugin 的 `pytest_runtest_logreport` 檢查旗標檔即可）；不殺別人的行程。
- **可見度**：`heavy_run.py --status` 一行印出『跑：b7 official e2e (pid, 38m)｜等：05 heavy、ab light』；PM 不必再逐窗問。

## 4. 推出順序（最小第一步優先）
| # | 內容 | 工 | 風險 | 效益 |
|---|---|---|---|---|
| 0 | `heavy_run.py --status`（唯讀：讀現有鎖登記＋最近 `full_results`）＋PLAYBOOK §C-13 補分級規則 | 0.5 天 | 零 | 馬上看得到誰在吃機器 |
| 1 | `run-stage --no-failfast`＋紀錄 `reds` 欄＋測試（全綠仍可被沿用、有紅不沿用） | 0.5 天 | 低 | 一輪看到全部紅 |
| 2 | `heavy_run.py` 佇列／優先序／低優先（各視窗改用它；舊鎖仍在當最後防線） | 1 天 | 低中（有人繞過就退回現況） | 不再互相拖到 playwright 逾時 |
| 3 | `ci_watch.py`＋狀態行（先只跑 `--dry-run` 題單＋契約題，觀察一週再開實跑） | 1.5 天 | 低（預警，不寫 green） | 凍結前就修掉大部分紅 |
| 4 | 夜間演練＋取號提前＋凍結沿用（§2.2） | 1 天＋跑一班驗證 | 中（流程順序變） | 正式閘門 0 分鐘（指紋相同時） |
| 5 | O6（分段指紋排除沒人讀的檔）、O3（續跑）——**需使用者書面裁示**，仍照 T47 文件的等價性要求 | — | 高 | 另案 |

**預期**：1～3 不改任何閘門判定，只改『何時發現紅、機器怎麼分』；4 是唯一會讓正式閘門『跳過重跑』的，且靠既有指紋規則保證等價。我不估分鐘數的把握：2～4 的實際節省取決於夜間演練的命中率（凍結後有沒有再動 tree），第 3 步跑一週後才有數字。
