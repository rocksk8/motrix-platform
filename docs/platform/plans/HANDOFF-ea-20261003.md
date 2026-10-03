# 整合與階段測試線（ea）結案交接 2026-10-03 15:40

> 角色：hichan-ea。不寫產品功能；擁有整合分支、取號、重產生成檔、批次預演、單檔提示性驗證。主持 bin-1c。
> 本檔取代並補足 `HANDOFF-EA-20261003.md`（第 33 班 A 結案時寫的，在分支 `wip/t34-handoff-ea`）。

## 1. 結果
- **第 33 班 A**：`8ae8b8cc` 於 2026-10-03 04:32 上線，無回滾。
- **第 34 班**：`6927e222` 於 2026-10-03 15:34 上線，無回滾；`origin/platform` = `4b18cd01`（基準更新提交）。
- 新班次基底一律用 `origin/platform`；`wip/train-33-*`、`wip/train-34-*` 留作紀錄，不刪。

## 2. 第 34 班整合紀錄（`wip/train-34-int1`，基底 `1184efb0`）
| 順序 | 內容（作者） | 來源 sha | 整合後 int1 | 取號 |
|---|---|---|---|---|
| 1 | author_gate globals（a3） | `55a3a53d` | `e54e39cb` | 無 |
| 2 | M2 coverage（2e）＋歸屬修正 | `7834687b`→`493ebc63` | | case 1.0.108 |
| 3 | M2＋D7 鎖定（d7；migration 0006） | `8464604d` | | case 1.0.109–1.0.111 |
| 4 | 出納款別／期別（a3） | `f6f69a40` | | arap 1.0.35 |
| 5 | ship-case（2e） | `15ee77ff` | `683b8be9` | case 1.0.112 |
| 6 | provider 登記修正＋extras（nits＋(d)＋audit 豁免＋IP-111）（2e） | `791b44aa`、`e7ff57ab` | `2f027536` | case 1.0.113–114、subcontract 1.1.17 |
| 7 | M2 wire2（2e） | `5bf475bd` | `01c23448` | case 1.0.115 |
| 8 | D12（c7） | `937cace2` | `daca7449` | 無（純前端） |
| 9 | ship-link（c7） | `e8e4fa20` | `03b6b86a` | case 1.0.116–117、supply 1.0.19 |
| 10 | M2c（d7） | `06c68501`（`wip/t34-m2final4-d7`） | `f3eaf086` | case 1.0.118 |
| 11 | mlImport（c7） | `994d639b` | `ebc6ac67` | case 1.0.119 |
| 12 | manifest 第 34 班五筆（我） | — | `249d851a`（**作廢**） | `2026-10-03e`–`i` |
| 13 | **金額洩漏 must-fix**（d7，da 抓到） | `c05e5b72` | **`6927e222`（出貨）** | case 1.0.120 |

- 退路 sha（由新到舊）：`ebc6ac67`→`f3eaf086`→`03b6b86a`→`683b8be9`；但 `249d851a` 之前的 M2 都含「變更申請 API 洩漏採購單行金額給無財務檢視權者」，所以最終沒有安全退路，必須用 `6927e222`。
- 預演／備援分層（33A）：4a2 `06e88542`、4a3 `9b575d2a`、4b' `eaa0463b`、4c2 `f2bde586`、4d `8ae8b8cc`（出貨）、4a4 `97945097`。
- 第 33 班 A 的批次 sha 見 `HANDOFF-EA-20261003.md`（`wip/t34-handoff-ea`）。

## 3. 每片併入後的標準步驟（可重用）
1. 合併前核 ancestry：`git merge-base --is-ancestor`、`git rev-list --count HEAD..<sha>`；`git merge-tree --write-tree --name-only HEAD <sha>` 唯讀預演。
2. 併入後依序：`backend/tests/platform/_l1_interface.py --update --pending` → `tools/platform/train_number.py assign --base origin/platform` → `dep_scan.py`／`test_map.py`／`unit_index.py` → 查 UU 與殘留 `## (next)`／`"version":"next"`。順序反了，L1 快照 core_version 會停在 next（`test_snapshot_version_is_current` 紅）。
3. **`## (next)` 必須在模組 CHANGELOG 最上面**，否則 `train_number` 不取號。作者的 (next) 常落在已編號條目之下，要先移到最上面。
4. CHANGELOG 合併衝突：新（next）條目放上、已編號條目留下；ours 標題若已取號，丟掉 theirs 最後那個重複的 (next) 標題。
5. `version_manifest.json`：同一模組每包只能一筆（`test_vr3`）；最新日期不可舊於最新 commit 日期（`test_vr1`）。
6. `test_module_changelog_follows_code`：模組最後一次程式改動之後必須有新的版號條目。
7. 新增檔案要登記：`docs/platform/modules.json`（`mod:`／`js:` 歸屬）、`docs/platform/case_read_scope.json`（新的 GET 路徑要歸類）、`INTEGRATION-POINTS.md`（IP 登記；檔尾追加最容易衝突，保留兩邊）、寫入端點稽核的 EXEMPT 清單（純試算 preview 端點）。
8. 黃金檔 `backend/tests/golden_case_page_2026_09_24.json`：API 請求清單要與底座一致。
9. 單檔驗證：`D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp %TEMP%\<自己的名字> -q`；wip 分支上跑 generated_maps 要 `MOTRIX_TRAIN=1`（否則 `test_branch_does_not_touch_generated_files` 必紅）；`PYTHONIOENCODING=utf-8`。
10. 共用樹 `D:\MOTRIX-PLATFORM` 不由我動，請主持 ff；Git Bash 傳含中文路徑給 python 會亂碼，一律用 PowerShell。
11. `check_version_sync.py` 需要資料庫（`--db`），開發機沒有 `motrix_erp.db` 會 FAIL，交建包機跑。

## 4. 教訓
- **兩個作者對同一個共用 fixture 各改一次會互相衝突**（2e 與 d7 的 `_mo` 預設 1000×2 vs 100×2）：先要求其中一方重基到另一方的做法。
- **新增 GET 端點、新檔、新 JS 時，歸屬／分類登記是最常見的紅燈**（modules.json、case_read_scope.json、IP 登記、稽核豁免）；請作者自查 `dep_scan.py --check-modules`。
- **整包前的單檔驗證省了很多 40 分鐘重跑**；但單檔驗證涵蓋不到「使用者可見金額洩漏」這類語意問題，最後是 da 稽核抓到（M2 變更申請 API 洩漏採購單行金額）。出貨前稽核不可省。
- 預演版與已推版不一致時用 `git reset --hard <已推 sha>` 再重併（只在自己的整合 worktree 上做）。
- 取號會順延先前已推 sha 內的號碼（數字尚未出貨，不影響功能），但會讓「前一輪已推 sha」與「後一輪」的 CHANGELOG 號碼對不上；回報時要寫明。

## 5. 待辦／清理
- 無待辦。第 35 班新分支基底用 `origin/platform`。
- 我的 worktree（`D:\開發測試檔\wt-int33`、`wt-int33-b3`）與本機分支已清理；`%TEMP%\motrix-pytest-*` 我的部分已刪。
