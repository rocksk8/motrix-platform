# 閘門加速管線 步驟 0–2：用法（第 51 班；設計見 SPEEDUP-PIPELINE-T50.md）

> 範圍僅限步驟 0–2。**沒有任何快取結果可以取代凍結樹的正式閘門**（步驟 3–5 另案，需使用者書面同意）。

## 步驟 0　誰在吃機器（唯讀）
```
python tools/platform/heavy_run.py --status
→ 跑：b7 official(pid 123, 38m00s)｜等：05 heavy、ab e2e｜輕：1｜conftest 鎖：lock pid 56192 2m08s
```
讀兩個來源：`D:\開發測試檔\_ci\queue\`（`MOTRIX_CI_DIR` 可改）的票根，與 conftest 的全機鎖檔（`%TEMP%\motrix-pytest-full-regression.lock*`，只列行程還活著的）。

## 步驟 1　一次找出全部紅
```
python backend/tools/build_test_reuse.py run-stage --stage not_e2e --no-failfast
```
只把 `MOTRIX_FAILFAST=0`，其餘指令／plugin／指紋與正式 `run-stage` 完全相同。有紅 ⇒ 紀錄的該段多 `reds:[…]`、`failfast:false`，輸出列出全部紅題（讀 fail_stream 專用目錄，不碰共用的 `tools/platform/fail_stream/`）；紅的段照舊**不被沿用**。
全綠 ⇒ 與有 failfast 的全綠是同一份證據（failfast 截不到全綠的 run），照舊可被建包沿用。

## 步驟 2　重型執行排隊（包在現有鎖外面，不取代）
```
python tools/platform/heavy_run.py --class heavy    --window <視窗> -- <指令…>     # pytest ≥2 worker、建包、modtest --full
python tools/platform/heavy_run.py --class e2e      --window <視窗> -- <指令…>     # 獨佔
python tools/platform/heavy_run.py --class official --window <視窗> -- <指令…>     # 正式閘門：最高優先、獨佔、不降權
python tools/platform/heavy_run.py --class light    --window <視窗> [--track] -- <指令…>   # 單檔 < 2 分：不排隊
```
- 優先序 official > e2e > heavy > watcher；同級先到先跑；重型全機同時一個；e2e／official 獨佔，且擋住在它之後入列的重型。其餘一律 `BELOW_NORMAL` 優先權。
- 票根建檔用 `O_EXCL`；行程已死、檔壞、超過 12 小時的票根自動清掉；不殺任何人的行程。等太久可 `--max-wait <秒>`（逾時回 75，不跑）。
- 結束碼＝被包指令的結束碼。conftest 的鎖仍是最後防線（`MOTRIX_PYTEST_SLOTS`／`EXCLUSIVE`）。
- 還沒有任何視窗被強制使用它；採用前先用 `--status` 觀察。

## 測試
`backend/tests/platform/test_heavy_run_tool.py`（票根排序／清除／規則／包裝／狀態行）、`test_build_stage_no_failfast_t51.py`（旗標、reds、可沿用／不沿用）。
