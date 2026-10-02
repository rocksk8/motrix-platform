# 作者端守門集（author_gate）：推「最終 sha」前的標準動作（一頁）

> 第 33 班起每個視窗在推最終 sha 給主持**之前**跑一次。它只是作者端預檢——**不替代**建包／整合樹的完整階段，結果檔只當提示、不讓任何人少跑任何題。

## 怎麼跑
```
# 在你自己的 worktree（工作樹必須乾淨；用專案 venv 的 python）
D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe tools/platform/author_gate.py --dry-run     # 先看選了什麼、預估幾分鐘（不跑）
D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe tools/platform/author_gate.py               # 真的跑（預設 -n 2、低優先權、不跳視窗）
```
- 基準預設＝你的分支與 `origin/platform` 的分歧點；`--base <ref>` 可改。`--workers 1` 不用 `-n`（約 2 倍時間）；`--skip-e2e` 略過 e2e 那一段。
- 結束印一行：`作者閘門：綠／紅，實跑 N 題，M 分鐘（預估 E 分），tree=…，結果檔=…`；綠 exit 0、紅 exit 1、拒絕執行（髒樹、找不到基準）exit 2。紅的題單獨列在下面，照題名單檔重跑。
- 結果檔 `tools/platform/author_gate_results/<head前12碼>.json`（不進 git）：綁 head／tree／選題器雜湊、`partial_evidence_only:true`。回報時把那一行貼給主持。

## 它跑什麼（聯集，去重）
| 組 | 內容 |
|---|---|
| A1 | `tests/platform` 整個目錄（`-m "not e2e"`）；工具演練檔（scope_gate、modtest*、module_update_delivery…）**只有動到 tools／core／modules.json／選題器時才跑** |
| A2 | 檔名樣式守門檔——**唯一一份清單在 `tools/platform/guard_patterns.json`**（approval、queue、pii、privacy、archive、migration、spec_coverage、font_zoom、money_round、legal_amount_rounding、wording、changelog、form_version、module_registry；掃 `backend/tests`、`core/tests`、`modules/*/tests`）＋ `pre_train_check.GUARDS` |
| A3 | `stage_select` 依你改的檔選出的受影響題 |
| A4 | 你新增／修改的測試檔本身 |
| e2e | 受影響的 e2e 另成一段（單獨計時；不計入預算警告） |
`tests/platform/test_no_swallowed_dict_keys_*`（M-1 型：字典項目中間的行內註解吞掉後面的鍵）在 A1 內，自動跑。

## 時間
實測（a5dea50c）：`tests/platform` 單行程 28 分、`-n 4` 約 6 分半；沒動工具的分支預設 `-n 2` 約 12～13 分鐘。**預算只警告，不砍題**；機器忙時請先看 `--dry-run` 的預估再決定時段。同一時間全機最多 2 組重型測試（測試鎖會排隊）。

## 它抓不到的（誠實）
- 合併後才出現的組合問題（兩個分支各自綠、合起來紅）→ 整合樹的 `pre_train_check`／建包抓。
- 負載相關的時序偶發 e2e（第 32 班的總帳作業頁 409、住宿圖層）→ 只有「改到那一頁時被選到並實跑」才可能撞到，不保證紅（已記在回放表 `uncatchable`）。
- 檔名不符樣式的跨檔守門 → 發現就往 `guard_patterns.json` 補一列（附 why）；守門題會擋「死樣式」。

## 回放驗證（維護者用）
`python tools/platform/author_gate.py replay` 對 `author_gate_replay.json` 的每輪紅燈（第 31 班 10 案、第 32 班 6 案）離線檢查「該輪預期紅的守門檔，在紅燈前一個 commit 的樹上是否被選到」；`--run` 在獨佔窗口實跑（fix^ 必須紅、fix 必須綠）。
環境變數：`MOTRIX_SHOW_WINDOWS=1` 才會顯示子行程視窗（預設全部隱藏）。
