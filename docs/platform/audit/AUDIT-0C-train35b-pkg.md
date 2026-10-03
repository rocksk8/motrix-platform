# AUDIT-0C — 第 35b 班「包」層稽核（`train35b-int2/deploy_packages/20261004_025246_345a34cd`）

- 對象：D:\開發測試檔\train35b-int2\deploy_packages\20261004_025246_345a34cd（建自 `345a34cd`＝`wip/train-35b-int2` tip，full）。對照：`git archive 345a34cd`、正式機基準包 `20261003_211316_326e6676_full`（G:，唯讀；清單 `package.sha256` 887 行）。
- 唯讀：未改包與建包工作樹；`git archive` 解到 scratchpad；`verify_package.py` 在自己的 worktree（detached 於 `345a34cd`）執行；暫存已清。稽核者 hichan-0c，2026-10-04。

## 結論

**PASS（可出貨）。無 must-fix。** 包 ＝ `git archive 345a34cd` ＋ 4 個建包產物；相對正式機基準包，變動的檔案**逐一對得上** `326e6676..345a34cd` 的 git 差異（30 個匯出檔）＋ 4 個建包產物，沒有任何多出來的檔；無開發庫／金鑰／日誌／暫存；`verify_package.py` 全過（db 116）。1 項小觀察（manifest 條目順序）。

## (1) 包內容 vs `git archive 345a34cd`

- 檔數：git archive 887、包 891。包多出的 4 個＝建包產物：`deploy_manifest.json`、`backend/.build_commit`、`backend/export_ignore.json`、`backend/modules.lock.json`。**反向（archive 有、包沒有）＝0。**
- 逐檔 sha256（887 檔）：只有 `backend/version_manifest.json` 位元組不同；語意比對（忽略建包把缺 `time` 的條目正規化為 `time: null`、BOM／CRLF）**與 git archive 相同（493 筆）**。
- 記載的排除＝`export_ignore.json`（1351 條）：與 `git ls-tree 345a34cd` 減 `git archive` 的差集**集合相等**。
- 禁品掃描（整包）：`*.db`／`*.sqlite*`／`*.pem`／`*.key`／`*.pfx`／`*.log`／`.env*`／`*credential*`／`*secret*`／`*.pyc`＝0；`.venv*`／`__pycache__`／`.git`／`deploy_packages`／`node_modules`＝0。**`backend/motrix_erp.db` 不在包內**（`backend/` 根層無 db 檔；唯一的 `backend/data/` 內容是 `account_items_112.json`，與基準包同 sha）。
- `backend/modules/tender_radar/holidays_tw.json`（2400 bytes）**在包內**；`calendar_tw.py` 亦在。兩者自我上次標案稽核（`f85e25fb`）後在 `345a34cd` **沒有任何改動**（`git diff` 空）。

## (2) `deploy_manifest.json`、模組鎖、遷移

- `commit=345a34cd59c89bbf3de8f4c683a0000d4956f28d`、`branch=wip/train-35b-int2`、`product=full`；`verification.mode=full`、`scoped=null`；測試重用 `02:39:02`（not_e2e）／`02:51:52`（e2e），皆 standalone、commit `345a34cd`，`flaky_retried` 空。
- `modules.lock.json`：`core_version 1.109`（未變）、**13 個模組**（accounting, analytics, arap, case, crm, daily_tasks, filehub, lodging, netplan, payroll, subcontract, supply, tender_radar）。相對 35a 的基準包鎖，**只有 3 個模組變**：`analytics 1.0.28→1.0.29`、`case 1.0.121→1.0.129`、`tender_radar 1.5.4→1.5.6`（與主持給的版本一致）；其餘 10 個模組版本與 sha256 完全相同。
- **沒有新遷移**：`backend/db.py` 與 `migrations_frozen/` 都不在變動清單；包內 `CURRENT_VERSION=116`、`len(_MIGRATIONS)=116`、最後一筆 `_m116_case_roles_username`，與期望值 116 及工作樹一致。
- 版本紀錄（`version_manifest.json`）493 筆；基準 491 筆**全部原樣保留**（無任何既有條目被改動）；新增 2 筆：`案件管理/精算 2026-10-04b`、`標案雷達 2026-10-04a`。

## (3) 包 vs 正式機基準包 `20261003_211316_326e6676_full`

基準包 887 檔、包 891 檔；基準有、包沒有＝0；包新增 4 檔；內容不同 30 檔（含 4 個建包產物中的 4 個）。與 `git diff 326e6676 345a34cd`（57 檔，其中**匯出的 30 檔**）逐檔比對：**包的變動集合 ＝ 這 30 檔 ∪ 4 個建包產物，兩邊都沒有多出**。

| 類別 | 檔 |
|---|---|
| 新增檔（4） | `backend/modules/tender_radar/calendar_tw.py`、`…/holidays_tw.json`、`docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md`、`docs/platform/plans/USER-DECISIONS.md` |
| 案件／精算 | `case/settlement_actuals.py`、`case/api/quotations.py`、`case/README.md`、`case/CHANGELOG.md`、`case/module.json`、`frontend/pages/settlement.html`、`frontend/pages/case-management.html`、`frontend/js/case-management-dispatch.js`、`backend/pdf_gen.py` |
| 讀取遮罩 | `backend/helpers/financial_mask.py`（重新開啟理由遮蔽） |
| 營運報表 | `analytics/api/reports.py`、`analytics/CHANGELOG.md`、`analytics/module.json` |
| 標案雷達 | `tender_radar/api.py`、`source.py`、`notify.py`、`README.md`、`CHANGELOG.md`、`module.json`、`frontend/pages/tender-radar.html` |
| L1 登記 | `backend/helpers/notification_prefs.py`（`tender_detail_blocked`） |
| 帳務／產生檔 | `backend/version_manifest.json`、`docs/platform/modules.json`、`dep_graph.json`、`test_map.json`、`UNIT-INDEX.md` |
| 建包產物 | `deploy_manifest.json`、`backend/.build_commit`、`backend/export_ignore.json`、`backend/modules.lock.json` |

git 差異裡**不匯出**的 27 檔（測試、fixtures、`tests/golden_case_page_2026_09_24.json`、`tests/platform/l1_interface_snapshot.json`、`tests/_prod_baseline.py`、`docs/quick/changelog.md`）不在包內，符合預期。
稽核對照：包內的案件／標案程式與我複審過的 sha 一致——`345a34cd` 相對 `8e2ea5fc`（案件）只差 CHANGELOG／module.json；相對 `f9eda556`（標案）只差 CHANGELOG／module.json。

## (4) 機密／個資

- 30 個變動檔（與其中新增的行）以 PEM 私鑰／雲端金鑰／token／password／Bearer／電子郵件／內網 IP／`C:\Users\<名>` 樣式掃描：**0 命中**；`version_manifest`、`test_map`、`dep_graph`、`UNIT-INDEX`、`modules.json` 的新增行亦 0 命中。
- 使用者可見的新 manifest 文字（精算 2026-10-04b、標案雷達 2026-10-04a）逐字檢視：只有功能說明，無帳號、金額、客戶資料或內部路徑。精算那條較長，含「屬設計」「避免偽造的利潤進入報表與獎金」等語氣偏內部的說明——不是缺陷，若要面向一般使用者可再精簡。
- `holidays_tw.json` 內容為官方公開的辦公日曆（來源網址、sha256、涵蓋範圍），無個資。

## (5) `verify_package.py … --expect-db-version 116`

在 detached 於 `345a34cd` 的獨立工作樹執行（對包唯讀）：**「✅ 全部通過（0 項 FAIL）」，exit 0。** 正對照成立；包側 12 類 0 命中；Leaflet 五檔 5/5；`version_manifest.json` 493 筆皆含 module/version/date/content；db 版本三者一致 116＝期望值、與工作樹相同；`modules.lock.json`＝13 模組、L0／L1 必要檔齊全。

## 觀察（非缺陷）

1. **manifest 條目順序**：新增的 `標案雷達 2026-10-04a` 排在 `案件管理/精算 2026-10-03j` 之後（不在最前面）；各條都有日期，守門測試（唯一版本、已出貨不可變）通過，只是畫面若依檔案順序顯示，最新的標案雷達條目會排第三。
2. 與 35a 相同、基準包也有：`backend/tools/issue_license.py` 在包裡、`autostart.bat` 的 cd 目標為 `…\V9.0\backend`。
3. 本地包尚無 `delivery.json`／`package.sha256`／`.sig`（發布到 G: 才產生）；發布後請對新包的 `package.sha256` 再做一次與 35a 相同的全檔重算（我可代做）。
