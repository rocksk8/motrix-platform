# AUDIT-0C — 第 35a 班「包」層稽核（`deploy_packages/20261003_205354_326e6676`）

- 稽核對象：D:\開發測試檔\train35a-int1\deploy_packages\20261003_205354_326e6676（建自 `326e6676` ＝ `origin/wip/train-35a-int1` tip）。對照：正式機基準包 `20261003_150757_6927e222_full`（G:，唯讀）與 `git archive 326e6676`。
- 唯讀：未改包、未改建包工作樹；`git archive` 解到 scratchpad；`verify_package.py` 自己的 worktree（detached 於 326e6676）執行；用完已清除暫存。稽核者 hichan-0c，2026-10-03。

## 結論

**PASS（可出貨）。無 must-fix。** 包的內容 ＝ `git archive 326e6676` ＋ 4 個建包產物；相對正式機基準包，只多了 35a 差異檔與帳務檔；包內無開發庫／金鑰／日誌／暫存；`verify_package.py` 全過（db 116）。

## (1) 包內容 vs `git archive 326e6676`

- 檔數：git archive 883、包 887。包多出的 4 個＝建包產物：`deploy_manifest.json`、`backend/.build_commit`（內容＝`326e6676…`）、`backend/export_ignore.json`、`backend/modules.lock.json`。**反向（archive 有、包沒有）＝0。**
- 逐檔 sha256（883 檔）：只有 `backend/version_manifest.json` 位元組不同；語意比對（忽略建包把缺 `time` 的條目正規化成 `time: null`、加 UTF‑8 BOM／CRLF）**與 git archive 相同（491 筆）**。
- 「記載的排除」＝ `export_ignore.json`（1333 條）：與 `git ls-tree 326e6676` 減 `git archive` 的差集**逐條相同**（集合相等、差集空）。
- 禁品掃描（包內全檔）：`*.db/*.sqlite*/*.pem/*.key/*.pfx/*.log/.env*/*credential*/*secret*/*.pyc`＝0；`.venv*`／`__pycache__`／`.git`／`deploy_packages`／`node_modules`＝0；**`backend/motrix_erp.db` 不在包內**（`backend/` 根層無任何 db）。唯一名為 data 的是 `backend/data/account_items_112.json`（科目表種子，與基準包同 sha）。`verify_package.py` 的 12 類（含 dotenv／pycache／開發機標記／公司設定檔）包側皆 0 命中。

## (2) `deploy_manifest.json` 與模組鎖

- `commit=326e667608e7b57cb60a017cc51c2b477f549d6b`、`branch=wip/train-35a-int1`、`product=full`；**`verification.mode=full`、`scoped=null`**（非 scoped，故無基準限制）；測試為重用 `20:40:08`（not_e2e）／`20:52:11`（e2e），皆標明 standalone、commit `326e6676`，flaky_retried 空。
- `326e6676` ＝ `origin/wip/train-35a-int1` tip；其祖先含 S1 修正 `1effaf98`（`recognition._qty_or_none`，包內 `recognition.py` 即為該版）與正式機基準 `6927e222…`。
- `version_manifest_latest`＝「案件管理/精算 2026-10-03j」；包的 version_manifest 491 筆，**基準包 490 筆為其尾段（後綴相等）**⇒ 只新增 1 筆（最前面）。
- `modules.lock.json`：`core_version 1.109`（未變）；**13 個模組**：accounting, analytics, arap, case, crm, daily_tasks, filehub, lodging, netplan, payroll, subcontract, supply, tender_radar。與基準包逐項比對：**只有 `case` 變**（`1.0.120 → 1.0.121`，sha256 `0c1995b0…→62ef78dc…`）；其餘 12 模組版本與 sha 完全相同。`case/module.json` 同為 1.0.121。
- `db_version 116`：包內 `db.py` `CURRENT_VERSION=116`、`len(_MIGRATIONS)=116`、最後一筆 `_m116_case_roles_username`，與期望值 116、與工作樹相同（見 (5)）。本班沒有新遷移。

## (3) 包 vs 正式機基準包 `20261003_150757_6927e222_full`

基準包 887 檔、包 887 檔；無「只在新包」、無「只在基準」。**內容不同的只有 13 檔：**

| 檔 | 原因 |
|---|---|
| `backend/modules/case/recognition.py`、`settlement_actuals.py` | 35a 後端（加欄位＋S1 修正） |
| `frontend/pages/settlement.html`、`case-management.html`、`css/case-management.css` | 35a 前端（精算入口、未對應列標籤） |
| `backend/modules/case/CHANGELOG.md`、`module.json` | 帳務：1.0.121 條目與版本 |
| `backend/version_manifest.json` | 帳務：+1 筆 2026-10-03j |
| `docs/platform/test_map.json` | 帳務：重生，2 個鍵（新 e2e 題的 units／evidence） |
| `backend/modules.lock.json` | 建包產物（case 版本與 sha） |
| `deploy_manifest.json`、`backend/.build_commit`、`backend/export_ignore.json` | 建包產物（commit／時間；export_ignore 只有 `commit` 欄變，1333 條路徑集合不變） |

對照 `git diff 6927e222…326e6676` 中**會被匯出的檔**（9 個：case CHANGELOG／module.json／recognition／settlement_actuals／version_manifest／test_map／css／case-management.html／settlement.html）：**全部且僅有這些**出現在上表（另 4 個建包產物）。git 差異裡不匯出的 5 檔（測試 2、`tests/_prod_baseline.py`、`docs/quick/*` 2）不在包內，符合預期。
基準包的 `package.sha256` 以抽驗 8 個檔對 G: 上實檔重算：8/8 相符（清單可信）。

## (4) 機密／個資

- 13 個變動檔與「新增的文字行」（version_manifest 新條目、各 changelog、test_map）以 PEM 私鑰／雲端金鑰／token／password／Bearer／電子郵件／內網 IP／`C:\Users\<名>` 樣式掃描：**0 命中**。
- `deploy_manifest.json` 含建包機的 Python 路徑 `D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe`，**基準包同樣有**（非新增，無個資，僅本機路徑）。
- 新 version_manifest 文字：「案件頁分頁列在「額外支出」右邊新增「精算 ▶」入口…金額與規則不變」——僅功能說明，無內部帳號、金額或客戶資料。

## (5) `verify_package.py … --expect-db-version 116`

在 detached 於 `326e6676` 的獨立工作樹執行（對包唯讀）：**「✅ 全部通過（0 項 FAIL）」，exit 0。** 要點：包側 12 類 0 命中（且工具先在工作樹跑正對照）；必須存在檔 OK；排除清單 ∩ MUST_EXIST ＝ 空；Leaflet 五檔 sha 與 PROVENANCE 相符 5/5；`version_manifest.json` 491 筆皆含 module/version/date/content；db 版本三者一致 116＝期望值；`modules.lock.json` ＝ 包內 13 模組、L0／L1 必要檔齊全。

## 觀察（非缺陷，皆與基準包相同）

- `backend/tools/issue_license.py`（授權簽發器）在包裡——工具標「在包裡」，基準包亦同；屬既有設計決策，本班未變動。
- `autostart.bat` 的 cd 目標為 `C:\Users\Motrix\Desktop\V9.0\backend`——既有、與基準包同。
- 本地包目錄尚無 `delivery.json`／`package.sha256`／`.sig`（那些在發布到 G: 時才產生）；發布後應對新包的 `package.sha256` 再做一次與本表同樣的抽驗。
