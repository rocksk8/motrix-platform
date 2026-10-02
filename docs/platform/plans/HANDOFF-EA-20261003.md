# 整合與階段測試線（ea）交接 2026-10-03 04:35

> 角色：hichan-ea，第 33 班「整合與階段測試線」。不寫產品功能；擁有整合分支、取號、重產生成檔、批次預演。主持 bin-1c。

## 1. 結果
- 第 33 班 A 已上線：`8ae8b8cc`（2026-10-03 04:32，無回滾）；基準改 `8ae8b8cc`、`origin/platform` = `1184efb0`。
- 第 34 班（33B）新分支基底一律用 `origin/platform`，不再用 `wip/train-33-*`。

## 2. 整合分支與批次（歷史，皆已不再需要）
`wip/train-33-int1`（基準 52033606）→ 批2 `744ddf05` → 批3/3b/3c/3d（`ec887e93`／`72f3854e`／`13deff6b`／`31bc6bd0`）→ 4a2 `06e88542` → 4a3 `9b575d2a`／4b' `eaa0463b`／4c2 `f2bde586` → **4d `8ae8b8cc`（出貨）**；備援 4a4 `97945097`。
我的 worktree：`D:\開發測試檔\wt-int33`（int1 線）、`D:\開發測試檔\wt-int33-b3`（批3 以後）。可刪（見 §5）。

## 3. 作法（可重用）
1. 合併前核 ancestry：`git merge-base --is-ancestor`、`git rev-list --count HEAD..<sha>`；`git merge-tree --write-tree --name-only HEAD <sha>` 預演。
2. 每次合併後依序：`backend/tests/platform/_l1_interface.py --update --pending` → `tools/platform/train_number.py assign --base origin/platform` → `dep_scan.py`／`test_map.py`／`unit_index.py` → 查 UU 與殘留 `## (next)`／`"version":"next"`。順序反了會讓 L1 快照 core_version 停在 next（`test_snapshot_version_is_current` 紅）。
3. **`## (next)` 必須在模組 CHANGELOG 最上面**，否則 `train_number` 不取號（出現過：M1-r2 的三個 (next) 落在 1.0.85 之下）。
4. CHANGELOG 合併衝突的標準解法：新（next）條目放上、已編號條目留下；ours 標題若已取號，丟棄 theirs 最後那個重複的 (next) 標題。
5. `version_manifest.json`：同一模組每包只能一筆（`test_vr3`）；最新日期不可舊於最新 commit 日期（`test_vr1`）。
6. 版號守門 `test_module_changelog_follows_code`：模組最後一次程式改動之後必須有新的版號條目。
7. 黃金檔 `backend/tests/golden_case_page_2026_09_24.json` 的「API 請求」清單要與底座一致（a3 S0 帶來 `GET /api/remit-kinds ×1`）。
8. 單檔驗證：`D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp %TEMP%\<自己的名字> -q`；wip 分支上跑 generated_maps 要 `MOTRIX_TRAIN=1`（否則 `test_branch_does_not_touch_generated_files` 必紅）。
9. 共用樹 `D:\MOTRIX-PLATFORM` 不由我動；請主持 ff。Git Bash 傳含中文路徑給 python 會亂碼，一律用 PowerShell。

## 4. 待辦（第 34 班）
- 等主持依使用者上午裁示派工；清單在 `docs/platform/plans/TRAIN31-BACKLOG.md` 底部。
- 33B 範圍（使用者前裁示）：變更申請 M2、出貨單連動 S1–S3、K-2 並行戳後續、設計器兩處預設開（D12，`wip/t33-d12-c7@807c7613`）、請購類型範本重發（已進 33A 的 D14/D15 除外）、建包優化。
- 作者端守門 `author_gate.py --quick`（a3）已進；建包優化 `--only-failed`（d7）進度待問 d7。

## 5. 清理（我自己的，可手刪）
- worktree：`D:\開發測試檔\wt-int33`、`D:\開發測試檔\wt-int33-b3`（皆為整合暫存，已推遠端；刪前 `git worktree remove`）。
- 本機分支：`b3-build`、`b4a3`、`b4b`、`b4b2`、`b4c`、`b4c2`、`b4d`、`b4a4`、`b-handoff`（遠端有對應 `wip/train-33-int-*`）。
- `%TEMP%\motrix-pytest-*`（int／b3／4a／4b／4c／4d 等）：已在各輪後刪，餘者可再清。
