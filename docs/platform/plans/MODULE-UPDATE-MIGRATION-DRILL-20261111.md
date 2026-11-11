# 單模組更新（帶 migration）實跑演練紀錄（2026-11-11）

> 目的：`docs/platform/MODULE-UPDATE-DELIVERY.md`、`UPDATE-DELIVERY.md` 的標題原本寫「設計，未實作」；`ROADMAP.md` S-PLD12 與三份 CHANGELOG 還掛著「migration 失敗無撤回」的待辦。
> 2026-11-11 先對程式與 commit 查證（見兩份交付文件的狀態區塊），再用**真的帶 migration 的單模組更新**走完一輪，留這份紀錄。
> 性質：日期快照（`plans/` 下的檔案不隨程式更新）。**演練在沙箱做，沒有碰任何正式機或共用資料庫。**

## 1. 演練對象

| 項目 | 值 |
|---|---|
| 模組 | `subcontract`（外包工班） |
| P（正式機基準） | `b2f311a11`＋演練專用提交 `aaa8509cd`（只把 module.json 版本改成 1.1.60） |
| X（要送的版本） | `b06a69397`（31-B S1：migration `0005_remit_kinds_voucher_rebuild.py`，**重建 `contractor_payment_vouchers` 表**＋`remit_split.py`）＋演練專用提交 `4c070642e`（版本改成 1.1.61） |
| 為何選它 | 這支 migration 是 DDL 重建（建新表→搬資料→DROP 舊表→改名），是最容易出事的一類 |
| 沙箱 | `D:\Claude-pm\hichan9-mig-drill\`（P、X 各一個 worktree、安裝目錄 `install\`、出貨包 `pkg\`）；演練完整個刪除 |
| 演練專用提交 | **不推、不合**（只存在沙箱 worktree） |

## 2. 步驟與結果（皆為實際輸出）

| # | 做什麼 | 結果 |
|---|---|---|
| 0 | 用 `backend/tools/drill_module_apply.py make_install` 以 P 建安裝目錄，跑 `migrate_like_startup.py` 建庫；塞 1 承攬商、3 派發、3 張匯款申請（待匯款／已匯款含 `remit_actual`、`paid_log`、`snapshot_json`）；存下 before 快照 | 建庫 OK（P 的 migrations 0001～0004） |
| 1 | `ship_tier.tier_for(P, X)` | `tier 2`、`key=subcontract`、`offenders=[]`；變更 7 檔，全歸 `module:subcontract` |
| 2 | `module_update.ship("subcontract", …, run_tests=False)` | 出貨包 `…subcontract_1.1.61_4c070642`；`prod_base_commit=aaa8509cd`、`tier=module`、`core=>=1.0,<2.0`；包內 migrations 0001～0005 俱全；`check()` 回 `[]` |
| 3 | `module_update.py preflight --require-base --json` | `ok:true`、1.1.60→1.1.61、`has_migrations:true` |
| 4 | 乾跑（照 `apply_module_update.ps1` 步驟 5）：`module_apply_steps.py overlay` 疊出新樹，在**資料庫快照副本**上跑 `migrate_like_startup.py --expect-module subcontract=1.1.61` | `OVERLAY_OK 393`；`MODULE_LOAD_OK subcontract=1.1.61`、`MIGRATE_LIKE_STARTUP_OK`；副本已有 `kind` 欄、3 列；**真庫沒有 `kind` 欄（乾跑沒動到真庫）** |
| 5 | `module_update.py apply --require-base` | rc 0，「1.1.60 → 1.1.61（備份 `install\module_backups\subcontract\…`）。⚠ 需重啟服務才生效」；安裝目錄模組樹改 4 檔（`__init__.py`、`migrations/0005…`、`module.json`、`remit_split.py`）；`modules.lock.json` 記 1.1.61 與 sha256 |
| 6 | 「重啟服務」＝用安裝目錄的新程式對真庫跑啟動規則的 migration | `MODULE_LOAD_OK`、`MIGRATE_LIKE_STARTUP_OK`；新欄位 `kind kind_name seq ratio pretax_amount void_reason` 都在；**3 列→3 列，舊欄位逐值相等**；舊列的新欄預設 `('' , 0, '')`；索引含 `idx_cpv_dispatch_kind_seq`、`idx_cpv_dispatch_legacy` |
| 7 | 行為抽查 | 舊式整筆：同一派發第二張（未作廢）仍被擋（`UNIQUE constraint failed: contractor_payment_vouchers.dispatch_id`）；款別分期（`kind='deposit'`、`seq` 1／2）可在同一派發建兩張（驗完刪除）；`core.migrations.current_version("subcontract")=5`、`incomplete()=None` |
| 8 | `module_update.py rollback --key subcontract` | rc 0，「已回滾……（雜湊逐一相等）」；`modules.lock.json` 版本回 1.1.60；回滾後模組樹與 P 相比只差 `SPEC.md`——**原因：`SPEC.md` 是 export-ignore，本來就不在安裝目錄**（不是回滾缺漏）；舊程式讀重建後的新表仍可讀（3 列） |
| 9 | **負向**：在疊加樹的 `0005` 裡 `DROP TABLE` 之後插入 `raise RuntimeError`，對舊 schema 的庫（同樣種子）乾跑 | `MODULE_LOAD_OK` 後 `MIGRATE_LIKE_STARTUP_FAIL`（rc 2）；**真表仍在、沒有 `kind` 欄、3 列逐列相等、沒有殘留 `…_new` 表**——DDL 連同資料變更整段被 `SAVEPOINT motrix_module_migration` 撤回 |

## 3. 結論

- 單模組更新包「帶 migration」的端到端路徑（出貨等級判定→出貨→preflight→乾跑→套用→migration→回滾）**確實能走通**；兩份交付文件的「已實作」成立。
- migration 失敗的撤回**確實存在而且涵蓋 DDL**（步驟 9），所以 ROADMAP S-PLD12、三份 CHANGELOG 的「失敗後留半套表」警告已過期，已更正。
- 回滾只還原**檔案**；資料庫已被 migration 改過的部分不會退（步驟 8 的舊程式仍能讀新表只是因為這支 migration 是加欄＋放寬索引）。**不能反向的 migration 要有自己的下行路徑**——這點沒有被這次演練證明，也沒有被文件承諾。

## 4. 限制（這次沒驗到的）

- `ship(run_tests=False)`：演練沒有跑出貨前的測試門（目的是驗流程，不是驗 31-B 的程式）。
- 沒有真的執行 `apply_module_update.ps1`、沒有停／啟 Windows 服務、沒有真的 HTTP 起服務；「重啟服務」用 `migrate_like_startup.py` 代替（它與啟動規則共用 `run_all()`）。
- 演練用的是種子資料，不是正式機資料；筆數只有 3。大表的重建時間沒量。
- 演練專用提交 `aaa8509cd`、`4c070642e` 只存在沙箱。腳本不入庫（一次性）；步驟與輸出都在上表。
