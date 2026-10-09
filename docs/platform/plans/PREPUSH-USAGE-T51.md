# 推送前檢查：使用說明（第 51 班；設計見分支 `wip/t50-speedup-prepush` 的 SPEEDUP-PREPUSH-T50.md）

每個視窗／clone 做一次（worktree 共用）：
```
python tools/platform/setup_prepush.py            # 登記 .githooks（core.hooksPath）
python tools/platform/setup_merge_drivers.py      # 兩邊各新增 `## (next)` 併成一塊（merge_drivers.py 有更新，複本要重登記）
python tools/platform/setup_prepush.py --check    # 開工第一件事
```
日常：`git push` 自動跑 `tools/platform/prepush_check.py --hook`（閒置機器 ≈ 1 分鐘；硬上限 90 秒）。手動：`python tools/platform/prepush_check.py [--static-only] [--base origin/platform]`。

| 情況 | 結果 |
|---|---|
| 有紅（靜態 A1～A8、wip 帶了產生檔、動到模組的 changelog_follows_code、FORM_VERSION、便宜守門檔） | 擋推送，印「檔案／原因／修法」 |
| 超過時間預算（預設 wip 90 秒、整合模式 300 秒——整合模式光靜態實測 ≈ 147 秒；`--budget-sec` 可改）未完成 | 警告放行（輸出明寫「不可當綠」） |
| 推 `train/*`、`platform`（整合模式：A0 產生檔過期＋全模組 changelog） | 只警告、不擋 |
| 推的不是目前 HEAD／刪除遠端分支 | 略過 |
| 緊急 | `git push --no-verify`（在推送說明寫理由） |

**絕不做**：取號、重產（只 check_only）、commit／push／checkout、設 `MOTRIX_TRAIN=1`、跑 e2e、寫任何綠燈紀錄。預檢綠 ≠ 閘門綠。

整合分支背景檢查：`.githooks/post-commit` 只在 `train/*` 排一次 `tools/platform/integ_watch.py`（去抖 60 秒；別的 pytest 在跑或可用記憶體 < 4 GB 就略過）；
測試逐檔跑，**每一檔開跑前**再查一次別的 pytest／記憶體，閘門中途開跑就讓出（狀態 `yielded`，不當綠）。
結果只寫 `tools/platform/full_results/integ_watch/status.json`（已 gitignore），讀法：`python tools/platform/integ_watch.py --status`。
