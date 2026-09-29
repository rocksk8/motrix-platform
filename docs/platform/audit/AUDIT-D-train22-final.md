# 稽核：第二十二班最終審（origin/platform b6182dbf，部署包 20260929_161131_b6182dbf_full）（D，2026-09-29）

> 依 8c34f08a：建包測試（非 e2e 6156 過、e2e 567 過）採信，未重跑；D 只做包與來源的獨立比對。

## 0. 判定
- **包：可上正式機。** 必修 0；觀察 3
- 正式機安裝指示與 apply 演練（path1／2／3）尚未出，出來後另審

## 1. 內容範圍（29e435df..b6182dbf）
產品檔（排除 docs、tests、.md）共 14 個，**全部逐位元組等於獨立審過的來源**：
| 檔 | 來源（已審） |
|---|---|
| lodging：`__init__`／`api`／`module.json`／`pages/lodging-overlay.js`／`source.py`、`frontend/pages/lodging-records.html` | wip/l-lodging-daily-2 c1a86740（lodging 1.2.1，複核必修 0） |
| tender_radar：`__init__`／`api`／`listing`／`module.json`／`source.py`、`frontend/pages/tender-radar.html` | wip/tr-precompute-3 91a8fa44（tender_radar 1.5.1，TR-M1 複核通過） |
| `tools/platform/final_drill.py` | 只改預設演練根目錄與說明（D:\開發測試檔\），無邏輯變動 |
| `backend/version_manifest.json` | 見 §2 |
`backend/main.py`、`core/`、`helpers/`、`tools/`（含 apply／rollback 腳本）**與第二十一班相同、未動**（本班不含第二十三班的 rowaccess／startup-timing 包）。簿記：`tests/_prod_baseline.py` 基準 54a2d6b6 → 29e435df（測試用，不進行為）。

## 2. 包的驗證（D 獨立重做）
| 項目 | 結果 |
|---|---|
| 簽章 | 以 `helpers/company_setup.PUBKEYS`（內嵌交付公鑰）驗 `signed_bytes(delivery.json, package.sha256)` ⇒ **通過** |
| `package.sha256` 的 SHA256 | 68B75F85…（與 hichan-90 提供的一致） |
| 檔數／逐檔雜湊 | 清單 592、payload 592；雜湊不符 0、清單有而包沒有 0、包有而清單沒有 0 |
| `delivery.json` | kind=full、commit=b6182dbf…、files=592、`apply_script_version`=**2026-09-28k**（≥28k ✔；ps1 內 `$ApplyScriptVersion = "2026-09-28k"`，`tools/` 與第二十一班相同） |
| 逐檔對 git blob（b6182dbf） | 564 相同、24 只差 CRLF、1 不同＝`version_manifest.json`、3 為建包產生（`deploy_manifest.json`、`backend/.build_commit`、`backend/modules.lock.json`） |
| `.build_commit` | b6182dbfaca2…（與 delivery.json 一致） |
| pyc／F3 類檔（`.install_identity`、確認檔、放行檔、初始帳密、資料庫、私鑰） | 包內 0 |
| 雲端 payload vs stage（stage-t22） | 592 對 592，只在一邊 0、內容不同 0 |
| `version_manifest` | 432 筆（第二十一班 430 ＋ 2）、與 git 順序相同、**除 `time` 欄投影外內容相同**；最上兩筆：附近旅宿 2026-09-29d（改名、系統群組、每日自動更新、當天連續失敗 3 次停）、標案雷達 2026-09-29c（清單預算＋搜尋停手才送）；內文只述功能，無識別值 |
| ship_tier `--prod 29e435df` | **等級 3**（manifest 一次夾帶兩個模組、final_drill 屬建包／更新工具）⇒ 完整包合理 ✔ |

## 3. 觀察（不擋）
- **T22F-O1　本機建包目錄仍有 3 個 pyc**（`deploy-out-t22\20260929_153109_b6182dbf\backend\core\__pycache__\{paths,upgrade,__init__}.cpython-312.pyc`）：與第二十一班 T21F-S1 同源（發布流程從包目錄 import `core`）。雲端（正式機要拿的）與 stage 都是 pyc 0 ⇒ 不影響交付；「發布工具改 `-B`／設 `PYTHONDONTWRITEBYTECODE`」仍是待辦。
- **T22F-O2　docs 整包出貨**：`docs/platform/prod-tasks/20260929-tender-radar-measure.md`（含正式機安裝路徑 `C:\Users\Motrix\Desktop\V9.0`）與 D 的稽核文件隨包出貨，屬「販售包去識別化」暫緩中的已知類別，本包正式機自用，不擋；販售包前要處理。
- **T22F-O3　時間戳**：`built_at` 15:31:12、包名／發布 16:11:31／16:11:44，相隔約 40 分鐘（建包 → 驗證 → 發布）；delivery.json 的 commit 與 `.build_commit` 一致，確認 b6182dbf 為建包當下的 HEAD。無影響。

## 4. 待審
正式機安裝指示（步驟檔）與 apply 演練 path1／2／3 結果：hichan-90 完成後我再審（比照第二十一班 §3、§6、§7）。RA-M1（rowaccess）依主持裁示暫緩。
