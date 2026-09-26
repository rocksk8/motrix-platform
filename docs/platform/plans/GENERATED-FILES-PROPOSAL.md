# 提案：三份產生檔改由列車唯一提交（B，2026-09-26）

> 主持派工（使用者要求定期找優化點）：評估 (a) 分支不 commit 產生檔、守門只在列車驗；(b) 守門改現場產生再比對、檔案只由列車 commit。只評估、不直接改。
> 對象：`docs/platform/UNIT-INDEX.md`、`docs/platform/dep_graph.json`、`docs/platform/test_map.json`。
> 數據：origin/platform 最近 24 小時（量於本檔撰寫當下）；D1b 回放在 `D:\MOTRIX-PLATFORM-B19`（detached，跑完還原）。

## 0. 結論（建議）

**採 (b) 的消費端、(a) 的提交規則，兩者合一**：
1. **分支不改這三份檔**（新守門：分支相對 merge-base 的 diff 不可以含這三檔；列車 commit 例外）。
2. **消費端一律現場產生**：modtest（D1b 選題）預設現場算 test_map＋dep_graph，不讀檔。
3. **「檔案是否最新」的三題只在列車跑**（列車設旗標；分支上 skip 並寫明理由），列車疊完各包後重產一次、commit 一次（現行列車已經這樣做）。

只做 (a) 不行：回放顯示 D1b 會漏掉新增／搬家的測試檔（最多 13 檔，見 §2）。只做 (b) 而分支仍 commit：衝突照舊。

## 1. 現況數據（origin/platform，24 小時）

| 項目 | 數值 |
|---|---|
| commit 總數 | 822 |
| 動到三檔任一的 commit | **60**（test_map 34、dep_graph 24、UNIT-INDEX 19） |
| 三檔的變動行數 | **+29,687／−13,743** |
| 檔案大小 | test_map 368 KB、dep_graph 275 KB、UNIT-INDEX 9 KB |
| 重產耗時（單次、本機） | dep_scan 9.5 s、test_map 8.8 s、unit_index 9.4 s（合計約 28 s） |
| 列車自己的重產 commit | 每班都有一個（例：`fe4ddded chore(train8)`、`2f039d43`（第七班）、`cf217f4c`（第六班）） |

⇒ 分支上提交的版本**一定會被列車再蓋一次**；分支提交它們的唯一作用是讓分支閘門的「是否最新」三題過關，代價是每次 rebase 在這三檔衝突。

B 本 session 的親身紀錄（佐證，不是統計）：
- 在這三檔衝突或必須重產的 rebase：C4 兩次（b-c4-2、b-c4-3）、b-routes-3、b-m08-s-2、b-o5-s1。
- 因為忘了重產而多跑一輪閘門：C4 步驟 ③（test_map）、b-o5-s1（test_map 兩次：一次忘了、一次新檔未 `git add` 所以 test_map 看不到）、b-modtest-env（test_map）、b-m08-attr（dep_graph 只是行號位移也要提交）。

## 2. D1b 選題會不會失準（回放）

做法：同一個分支 HEAD，用 `modtest --dry-run --json --base <merge-base>` 選題兩次——
「新圖」＝分支自己重產並提交的 test_map／dep_graph（現行做法的結果，當基準）；
「舊圖」＝把兩檔換回 merge-base 的版本（＝分支不提交產生檔時 modtest 讀到的）。

| 分支 | 新圖選題 | 舊圖選題 | 舊圖漏掉 | 舊圖多出 | 舊圖漏掉的是什麼 |
|---|---|---|---|---|---|
| b-c4-3 | 580 | 581 | 0 | 1 | — |
| b-o5-s1 | 165 | 163 | 2 | 0 | 新增的 e2e 檔；payroll 的 test_voucher_connectors |
| b-o5-s2 | 166 | 163 | 3 | 0 | 同上＋另一個新增檔 |
| b-m08-attr | 133 | 133 | 0 | 0 | — |
| b-modtest-env | 71 | 71 | 0 | 0 | — |
| a-m03 | 593 | 586 | **9** | 2 | 搬進 `modules/supply/tests/` 的 8 檔＋1 個新 e2e |
| c-probes | 173 | 173 | 0 | 0 | — |
| c-m05b | 596 | 591 | **13** | 8 | 搬進 `modules/arap/tests/` 的 10 檔以上 |
| h-u15-2 | 558 | 557 | 1 | 0 | 新增的測試檔 |

再回放一次「舊的 dep_graph＋現場算 test_map（`--refresh-map`）」：

| 分支 | 漏掉 | 多出 |
|---|---|---|
| a-m03 | 0 | 2 |
| c-m05b | 0 | 10 |
| b-o5-s2 | **1**（test_voucher_connectors：conftest 改動的反向遞移靠 dep_graph） | 0 |
| h-u15-2 | 0 | 0 |

⇒ **(a) 若 modtest 照舊讀檔，D1b 會漏題**（新增／搬家的測試檔不在舊 test_map 裡；模組搬遷那一型漏最多）。
⇒ test_map 現場算可以補回幾乎全部；**dep_graph 也要現場算**才補得回最後一類（改動沿反向 import 擴散）。
⇒ 成本：dry-run 從 11～25 s 變 21～26 s（每次多約 5～10 s；兩份都現場算時再多約 10 s）。可用「以 HEAD tree hash 為鍵的暫存」省掉重複計算（選配）。

## 3. 兩條路逐項比較

| | (a) 分支不 commit、守門只在列車驗 | (b) 守門現場產生再比對、檔案只由列車 commit |
|---|---|---|
| 分支閘門怎麼保持綠 | 「是否最新」三題在分支上必紅 ⇒ 要改成列車才跑（旗標） | 同左：比對對象是「現場產生 vs 已提交的檔」，分支不提交就必紅 ⇒ 一樣要列車才跑。**產生檔以外的不變量**（歸屬錯誤、邊界、單位卡）原本就是現場掃描，分支照驗 |
| D1b 選題 | **失準**（§2，最多漏 13 檔），除非 modtest 改現場產生 | modtest 現場產生 ⇒ 不失準 |
| 衝突 | 分支不動三檔 ⇒ 不衝突 | 若分支仍可提交 ⇒ 照衝突；要配「分支不可動三檔」的守門 |
| 列車步驟 | 疊完各包 → 重產 → commit → 全量（含三題） | 同左 |
| 人讀的文件（UNIT-INDEX） | 分支上看的是 origin 版（少了本包新增的單位） | 同左；要看最新的現場跑 `unit_index.py` |

兩條路在「分支閘門」與「列車步驟」上其實一樣；差別只在 D1b——**(a) 若不改 modtest 就會漏題**。所以建議合成一條（§0）。

## 4. 建議的具體改動（交裁示後才做）

1. **modtest**：預設現場建 test_map（等同現在的 `--refresh-map`）與 dep_graph（呼叫 dep_scan.build()）；`--use-files` 保留給除錯。含**未 `git add` 的新測試檔**（現在 test_map 只看已追蹤的檔，B 在 b-o5-s2 踩到）。
2. **「是否最新」三題**（`test_generated_maps::test_dep_graph_json_is_current`、`::test_test_map_json_is_current`、`test_unit_cards::test_unit_index_is_current`）：只在 `MOTRIX_TRAIN=1` 時跑，否則 skip 並寫「產生檔由列車提交（PLAYBOOK §G3）」。
   - 反向控制：列車清單加一條「全量結果裡這三題必須是 passed，不可以是 skipped」（列車長核對；可再加一題讀 full_results）。
3. **新守門「分支不動產生檔」**：`git diff --name-only <merge-base>..HEAD` 含三檔之一 ⇒ 紅，訊息指路「刪掉你的改動，列車會重產」。列車 commit（訊息以 `chore(trainN)` 開頭）例外。反向控制：合成一個動到 test_map 的分支 ⇒ 紅。
4. **列車**（PLAYBOOK §G3）：現行「疊完 → 重產 → commit」不變，只加 `MOTRIX_TRAIN=1` 跑全量。
5. **過渡**：守門上線那一刻，已登記月台的分支會帶著舊的產生檔改動 ⇒ 列車在疊包時對三檔一律取 origin 版（`git checkout --ours`，B 本 session rebase 時就是這樣處理），再重產；已登記的包不必重推。

## 5. 預估節省

- **commit**：24 小時內 60 個動到三檔的 commit，列車自己的約 7 個（每班一個）⇒ 約 **50 個分支上的產生檔 commit 消失**。
- **衝突**：每一包平均 1～2 次 rebase，而產生檔幾乎每次都衝突（主持觀察；B 本 session 5 次中 5 次）⇒ 每班 8 包約 **8～16 次衝突處理消失**。
- **token**：一次產生檔衝突處理（看衝突 → 取 ours → 重產 → 再驗）約 5k～15k；一次「忘了重產」多跑的閘門約 5k＋5～10 分鐘機時 ⇒ 每班粗估 **省 60k～200k token、1～2 小時的線上時間**（估算，依 §1 的紀錄外推，不是量測）。
- **代價**：每次 modtest dry-run 多 5～20 s（現場產生）；列車不變。

## 6. 風險

- 列車忘了設 `MOTRIX_TRAIN=1` ⇒ 三題被 skip、產生檔過期沒人發現 ⇒ §4-2 的反向控制（全量結果裡三題必須 passed）。
- 分支上看 UNIT-INDEX 會少本包新增的單位 ⇒ 要看最新的現場跑；單位卡本身的檢查（`test_existing_cards_are_valid`）照舊在分支上跑，不受影響。
- modtest 現場產生若失敗（dep_scan 例外）⇒ 應該明說並退回讀檔，不可以靜默改成「不選題」。

## 7. 需要裁示

- 採 §0（合一）或只採 (a)／(b) 其一。
- `MOTRIX_TRAIN` 旗標名稱與設在哪裡（列車長腳本）。
- 由誰實作（估：modtest＋守門＋題約 2 小時，B 可接）。
