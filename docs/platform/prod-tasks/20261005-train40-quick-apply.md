# 給正式機 Claude：第四十班快速更新（文字／外觀）步驟（408286f3 → 5d413330）——定稿（2026-10-05 12:25 發布）

> 格式同第四十班。路徑、授權、停止規則同前：安裝目錄 `<ROOT>`；staging＝`<ROOT>\..\motrix-staging`；服務 `https://127.0.0.1:666`（略過憑證檢查）。**任何一步不符預期一律停下回報，不重試、不臨場改寫。**
> **本班驗證全部唯讀；不要在正式機送審、核可、付款、作廢、上傳檔案、建立任何單據、完結或重開精算來「測試」。**
> 授權：使用者授權主持（node-06）發布並上正式機；正式機「驗證通過＋主持說『可以套用』→ 直接套用，不用等使用者」。**沒有收到主持（node-06）明確傳的「可以套用」之前，只做步驟 0～1。** 若分類器擋下 Copy-Item／apply：停下回報，不繞過，等使用者回「套用」。
> 若開發機連線中斷：本檔即完整指示，可先做步驟 0～1 並把結果寫進 `正式機回報`，等待使用者或主持的「可以套用」。

## 這一班有什麼（只改畫面文字與外觀；不改資料、流程、權限）
- **請款頁改稱「支出申請」**：「我的工作」選單「新增請款」→「新增支出申請」；頁面標題「支出申請」、分頁「新增申請／我的申請」、區塊「申請類型」、說明文字同步。
- **簽核用語**：「案件額外支出」→「案件支出申請」（簽核佇列徽章、簽核設定的單據名稱、申請頁類型下拉）；「額外支出變更」→「支出申請變更」（佇列標題與變更申請的通知／信件文字）。內部代碼 `extra_expense`、通知事件鍵、資料表名都不動。
- **使用者編輯視窗「Email 通知偏好」**：改成與「存取模組」同樣的標籤樣式（勾選＝✓＋主色底、不可收件者灰色）。勾選與儲存行為不變。
- 版本：`case` 1.0.139 → **1.0.140**；其餘模組不變；db_version 116 不變；**沒有 migration**。api_version 記錄實際值即可。
- 驗證：完整測試（非 e2e 8900 passed／e2e 929 passed，兩階段都實際執行，0 失敗，無重試）；獨立審查（文字差異）必修 1 項（版本字母撞號）已修；演練步驟 0～1 PASS（實際包目錄，缺檔 0、多出 4 個建包產物檔、內容只差 `version_manifest.json` 的 BOM／空白／`time:null`）；`verify_package` 0 FAIL；包內無 `__pycache__`。**本班只改文字與外觀，未做獨立探針。**

## 步驟 0：前置
1. `<ROOT>\backend\.deployed_commit.json` 的 `commit` 以 `408286f3` 開頭（已是新版 ⇒ 回報「已是這一版」結束；其他值 ⇒ 停下回報）。
2. stage 後讀 `payload\deploy_manifest.json`（utf-8-sig）的 `verification`：預期 `mode`＝`full`，`stages.not_e2e`＝`ran`、`stages.e2e`＝`ran`，`flaky_retried`＝`[]`；不符 ⇒ 停下回報。
3. `.install_identity`、`company_confirmation.sig` 存在；`GET /api/ping` 200；系統碟可用空間 ≥ 5 GB；備份健康（`backup_alerts` 無新告警、最近一次每日備份存在）。
4. 記下套用前 `module_states.json`（模組數與每個 key／version／state）及唯讀 `mode=ro` 筆數基準：`audit_log`、`quotations`、`case_extra_expenses`、`case_material_payments`、`contractor_dispatches`、`tender_fetch_log`，與 `settle_status='finalized'` 筆數。

## 步驟 1：取包並驗證（不套用）
包名：`20261005_122253_5d413330_full`（commit `5d4133302d65ff491551d1bd02c5f766b732e86b`）；`package.sha256` 的 SHA256 必須等於 `E02C5F3B176307C51B1857848EB7A62102E1D9FEB9D1D1C92176198D9CAD378F`，行數 `898`；payload 檔案數 898。
```powershell
python <ROOT>\backend\tools\delivery.py stage  --root "H:\我的雲端硬碟\MOTRIX-交付" --name <包名> --staging <ROOT>\..\motrix-staging
python <ROOT>\backend\tools\delivery.py verify --staged <ROOT>\..\motrix-staging\<包名> --install-root <ROOT> --skip-verify-package
python <ROOT>\..\motrix-staging\<包名>\payload\backend\tools\verify_package.py <ROOT>\..\motrix-staging\<包名>\payload --expect-db-version 116
```
判準同前：`DELIVERY_STAGE_OK`／`DELIVERY_VERIFY_OK`（`ok=true`、`problems=[]`）／verify_package 0 項 FAIL；雜湊與行數相符。雲端未同步完 ⇒ 等，不要暫存。任一不符 ⇒ 停下回報。完成後**先回報「已暫存，等主持的可以套用」**。

## 步驟 2：套用（收到主持「可以套用」之後；兩次分開呼叫，只執行一次）
```powershell
Copy-Item "<ROOT>\..\motrix-staging\<包名>\payload\backend\tools\*" "<ROOT>\backend\tools\" -Recurse -Force
powershell -NoProfile -ExecutionPolicy Bypass -File <ROOT>\backend\tools\apply_update.ps1 -PackagePath <ROOT>\..\motrix-staging\<包名>\payload -Yes
```
記下 `<t0>`。不加 `-Force`／`-SkipAutoRollback`／`-MaxDeleteFiles`。最後 `::RESULT::` 為 `status=success rolled_back=applied service=up exit=0` ⇒ 步驟 3；其他 ⇒ 停下回報（附 `::RESULT::` 行與 `apply_update_<時間戳>.result.json`）。

## 步驟 3：套用後檢查（唯讀）
| # | 檢查 | 通過條件 |
|---|---|---|
| 1 | 版本 | `.deployed_commit.json` 的 `commit` 以 `5d413330` 開頭；`/api/system/version` 的 api_version 記錄實際值（只要 commit 對） |
| 2 | 健檢 | `/api/ping` 200 |
| 3 | 開關誤報 | 套用輸出／result.json／plan.txt 不含「開關沒有生效」 |
| 4 | API 文件關閉 | `/openapi.json`、`/docs` 皆 404 |
| 5 | 模組載入 | `started_at` ≥ `<t0>`；模組總數與每個 state 同步驟 0；版本變化僅限 `case` 1.0.139→1.0.140 |
| 6 | 伺服器 log | 最後一次「Uvicorn running on」之後，濾掉良性 ConnectionResetError：指向 `case`、`analytics`、`core`、`helpers`、`routers`、`main` 的 Traceback ＝ 0 |
| 7 | 服務行程 | 埠 666 監聽、PID 只有一個 |
| 8 | 資料 | db_version 116；步驟 0 各表筆數與套用前相同；`finalized` 筆數相同 |
| 9 | 新文字靜態存在 | `Select-String <ROOT>\frontend\pages\payment-request.html -Pattern '支出申請'` ≥1；`Select-String <ROOT>\backend\routers\approval_queue.py -Pattern '案件支出申請'` ≥1；`Select-String <ROOT>\frontend\pages\users.html -Pattern 'notify-type-'` ≥1；`case\module.json` ＝ 1.0.140，且含 `新增支出申請` |
| 10 | 狀態快照 | `prod_status_snapshot.py --out "H:\我的雲端硬碟\MOTRIX-交付\正式機回報\status\latest.json"` exit 0；`deployed_commit` 相符、`errors` 為 `{}` |
| 11 | 啟動耗時 | `<t0>` 到 `started_at` 的秒數寫進摘要 |

全部通過 ⇒ 步驟 5。#1～#5、#7～#9 任一不過，或 #6 有上列 Traceback ⇒ 步驟 4。

## 步驟 4：只回程式的回滾（僅 apply 顯示 success 但步驟 3 不過時）
`<時間戳>`＝`<ROOT>\backend\logs\apply_update_*.result.json` 時間戳最大那份；執行 `powershell -NoProfile -ExecutionPolicy Bypass -File <ROOT>\backend\tools\rollback_update.ps1 -SnapshotTimestamp <時間戳> -Yes`（不帶 `-IncludeDatabase`／`-ConfirmDatabaseOverwrite`）；回滾後 `commit` 以 `408286f3` 開頭、`/api/ping` 200；停下回報。無 migration，DB 不需回滾；**DB 回滾須使用者同意**。

## 步驟 5：回報
`H:\我的雲端硬碟\MOTRIX-交付\正式機回報\<yyyyMMdd_HHmmss>_5d413330_<成功|回滾|擋下>\摘要.md`（寫檔被擋時把摘要全文貼回覆）：`::RESULT::` 行、步驟 0 #2、步驟 3 十一項結果、耗時、前後 commit。

## 需要使用者自己做的
1. 告知使用者：選單與頁面「請款」改稱「支出申請」；簽核徽章「案件額外支出」改稱「案件支出申請」、「額外支出變更」改稱「支出申請變更」；使用者編輯視窗的 Email 通知偏好改為標籤樣式（行為不變）。
2. 驗收：「我的工作」選單顯示「新增支出申請」；簽核佇列中無類型的申請單徽章顯示「案件支出申請」；編輯使用者時 Email 通知偏好可點選標籤切換、已勾選顯示 ✓。
