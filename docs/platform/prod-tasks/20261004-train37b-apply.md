# 給正式機 Claude：第三十七班B（熱修）更新步驟（8b44ca78 → 3b107abf）——候選定稿（2026-10-04 19:40 發布）

> 格式同第三十七班。路徑、授權、停止規則同前：安裝目錄 `<ROOT>`；staging＝`<ROOT>\..\motrix-staging`；服務 `https://127.0.0.1:666`（略過憑證檢查）。**任何一步不符預期一律停下回報，不重試、不臨場改寫。**
> **本班驗證全部唯讀；不要在正式機送審、核可、付款、作廢、上傳檔案、建立任何單據、完結或重開精算來「測試」。**
> 使用者授權主持「熱修完成後直接發布並上正式機」。**沒有收到主持（hichan-6b）明確傳的「可以套用」之前，只做步驟 0～1，不要套用。**
> 若套用被權限分類器擋下：不要繞過，回報使用者。

## 這一班有什麼（精算頁版面熱修，只動前端 `settlement.html`）
- 使用者在正式機回報：精算頁內容靠左（右邊大片空白）、頂部「毛利／毛利比」「最終淨利／淨利比」指標卡右側文字被裁切。
- 修正：內容改為置中容器（最大寬 1400px、左右對稱）；五張指標卡自動排列、字級隨寬度縮放，金額與比例窄時換行，不再裁切。列印版型不變。
- **只改版面，不動任何計算、不動後端、不動資料。** 版本：`case` 1.0.131 → **1.0.132**；其餘模組不變；db_version 116 不變；沒有 migration。api_version 預期 `2026-10-04d`。
- 驗證：範圍驗證（基準 8b44ca78、僅 `case`）全綠；獨立稽核 must-fix 0（含 8,825 萬金額、長名稱、四種寬度實測無裁切）；簡化演練 PASS；包完整性 PASS；探針乾淨。套用腳本本身不在開發機演練；第三十七班在正式機首次實跑正常。

## 步驟 0：前置
1. `<ROOT>\backend\.deployed_commit.json` 的 `commit` 以 `8b44ca78` 開頭（已是新版 ⇒ 回報「已是這一版」結束；其他值 ⇒ 停下回報）。
2. stage 後讀 `payload\deploy_manifest.json`（utf-8-sig）的 `verification`：預期 `mode`＝`scoped`，`scoped.base`＝`8b44ca7883ef1324dc9d50923946a43e24f82064`，`scoped.units`＝`["case"]`；不符 ⇒ 停下回報。
3. `.install_identity`、`company_confirmation.sig` 存在；`GET /api/ping` 200；系統碟可用空間 ≥ 5 GB；備份健康（`backup_alerts` 無新告警、最近一次每日備份存在）。
4. 記下套用前 `module_states.json`（模組數與每個 key／version／state），以及唯讀 `mode=ro` 的筆數基準：`audit_log`、`quotations`、`case_extra_expenses`、`case_material_payments`、`contractor_dispatches`、`tender_fetch_log`，與 `settle_status='finalized'` 筆數（上班為 10）。

## 步驟 1：取包並驗證（不套用）
包名：`20261004_193743_3b107abf_full`（commit `3b107abffadeec4ea0da671614dcddba66363a0d`）；`package.sha256` 的 SHA256 必須等於 `158F1BAD8987CD423958A26096B7617DAE85FB1F5FBA1E0510DA491FA382C94B`，行數 `892`；payload 檔案數 892。
```powershell
python <ROOT>\backend\tools\delivery.py stage  --root "H:\我的雲端硬碟\MOTRIX-交付" --name <包名> --staging <ROOT>\..\motrix-staging
python <ROOT>\backend\tools\delivery.py verify --staged <ROOT>\..\motrix-staging\<包名> --install-root <ROOT> --skip-verify-package
python <ROOT>\..\motrix-staging\<包名>\payload\backend\tools\verify_package.py <ROOT>\..\motrix-staging\<包名>\payload --expect-db-version 116
```
判準同第三十七班：`DELIVERY_STAGE_OK`／`DELIVERY_VERIFY_OK`（`ok=true`、`problems=[]`）／verify_package 0 項 FAIL；雜湊與行數相符。雲端未同步完 ⇒ 等，不要暫存。任一不符 ⇒ 停下回報。完成後**先回報「已暫存，等主持的可以套用」**。

## 步驟 2：套用（收到主持「可以套用」之後；兩次分開呼叫，只執行一次）
```powershell
Copy-Item "<ROOT>\..\motrix-staging\<包名>\payload\backend\tools\*" "<ROOT>\backend\tools\" -Recurse -Force
powershell -NoProfile -ExecutionPolicy Bypass -File <ROOT>\backend\tools\apply_update.ps1 -PackagePath <ROOT>\..\motrix-staging\<包名>\payload -Yes
```
記下 `<t0>`。不加 `-Force`／`-SkipAutoRollback`／`-MaxDeleteFiles`。最後 `::RESULT::` 為 `status=success rolled_back=applied service=up exit=0` ⇒ 步驟 3；其他 ⇒ 停下回報（附 `::RESULT::` 行與 `apply_update_<時間戳>.result.json`）。

## 步驟 3：套用後檢查（唯讀）
| # | 檢查 | 通過條件 |
|---|---|---|
| 1 | 版本 | `.deployed_commit.json` 的 `commit` 以 `3b107abf` 開頭；`/api/system/version` 回 `2026-10-04d` |
| 2 | 健檢 | `/api/ping` 200 |
| 3 | 開關誤報 | 套用輸出／result.json／plan.txt 不含「開關沒有生效」 |
| 4 | API 文件關閉 | `/openapi.json`、`/docs` 皆 404 |
| 5 | 模組載入 | `started_at` ≥ `<t0>`；模組總數與每個 state 同步驟 0；版本變化僅限 `case` 1.0.131→1.0.132 |
| 6 | 伺服器 log | 最後一次「Uvicorn running on」之後，濾掉良性 ConnectionResetError：指向 `case`、`core`、`helpers`、`routers`、`main` 的 Traceback ＝ 0 |
| 7 | 服務行程 | 埠 666 監聽、PID 只有一個 |
| 8 | 資料 | db_version 116；步驟 0 各表筆數與套用前相同；`finalized` 筆數相同 |
| 9 | 新版面靜態存在 | `Select-String <ROOT>\frontend\pages\settlement.html -Pattern 'stl-k__v2'` ≥1；`-Pattern 'stl-kpis'` ≥1；`case\module.json` ＝ 1.0.132 |
| 10 | 狀態快照 | `prod_status_snapshot.py --out "H:\我的雲端硬碟\MOTRIX-交付\正式機回報\status\latest.json"` exit 0；`deployed_commit` 相符、`errors` 為 `{}` |
| 11 | 啟動耗時 | `<t0>` 到 `started_at` 的秒數寫進摘要 |

全部通過 ⇒ 步驟 5。#1～#5、#7～#9 任一不過，或 #6 有上列 Traceback ⇒ 步驟 4。

## 步驟 4：只回程式的回滾（僅 apply 顯示 success 但步驟 3 不過時）
`<時間戳>`＝`<ROOT>\backend\logs\apply_update_*.result.json` 時間戳最大那份；執行 `powershell -NoProfile -ExecutionPolicy Bypass -File <ROOT>\backend\tools\rollback_update.ps1 -SnapshotTimestamp <時間戳> -Yes`（不帶 `-IncludeDatabase`／`-ConfirmDatabaseOverwrite`）；回滾後 `commit` 以 `8b44ca78` 開頭、`/api/ping` 200；停下回報。

## 步驟 5：回報
`H:\我的雲端硬碟\MOTRIX-交付\正式機回報\<yyyyMMdd_HHmmss>_3b107abf_<成功|回滾|擋下>\摘要.md`（寫檔被擋時把摘要全文貼回覆）：`::RESULT::` 行、步驟 0 #2、步驟 3 十一項結果、耗時、前後 commit。

## 需要使用者自己做的
使用者驗收：開精算頁，寬螢幕下內容置中、指標卡「毛利／毛利比」「最終淨利／淨利比」不再被裁切。
