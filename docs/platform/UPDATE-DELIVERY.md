# 更新流程簡化：雲端交付＋正式機一鍵套用（設計，未實作）

> A，2026-09-28 01:33。依據：CORE-SPEC 裁示表「更新流程簡化（下一版）」（使用者 2026-09-28 00:18）、RUN-PLAN §6 同時間條目。
> **前提**：apply_update 安全修正（wip/h-apply-platform）四條路演練通過＋D 單獨完整稽核。本文件只寫設計；程式、題目、演練另外派工。
> 資料夾位置、權限、確認次數等使用者決定事項列在 §7（U 題）。文件中以 `<交付資料夾>` 代表使用者指定的雲端硬碟資料夾。

## 0. 目標與邊界

- 使用者的操作只剩兩次按鍵：
  1. 開發機儀表板按「建包並交付」
  2. 正式機儀表板按「套用更新」
- 總時間 30 分鐘內。
- **開發機不連正式機**（不走 WinRM）。兩台之間唯一的通道是 `<交付資料夾>`：
  - 開發機寫包
  - 正式機讀包、寫結果
- 正式機的動作一律在**正式機本機**執行，並由使用者在正式機上按下，符合 PLAYBOOK §C-10「正式機的動作由使用者執行」。
- 不變：
  - 套用由 `apply_update.ps1` 執行（含刪除計畫、快照、乾跑、停服、回滾）
  - 結果判定沿用 `::RESULT:: v=2` 協定與 `deploy_dashboard.py` 的值域
  - 本設計只換「包怎麼到正式機」與「誰按下套用」

## 1. 流程總覽

```
開發機                                   <交付資料夾>（雲端硬碟）                正式機
──────                                   ────────────────────                    ──────
①建包（沿用 12 小時內全量；build-gate）
②寫入 incoming/<包名>.partial/   ───▶   incoming/<包名>.partial/
③寫 manifest＋sha256 清單＋簽章
④改名為 <包名>/（發布＝最後一步）───▶   packages/<包名>/  ─── 同步 ───▶   儀表板偵測（輪詢）
                                                                              ⑤複製到本機暫存 staging\<包名>\
                                                                              ⑥驗：簽章、sha256、檔數、verify_package
                                                                              ⑦畫面顯示「可套用：<commit>」
                                                                              ⑧使用者按「套用更新」（＋確認）
                                                                              ⑨複製包裡 backend\tools → 安裝目錄（AH-M2）
                                                                              ⑩apply_update.ps1 -PackagePath staging\<包名>
◀──── 同步 ────  results/<包名>.result.json ◀── ⑪寫結果（::RESULT:: 欄位＋commit＋時間）
⑫開發機儀表板讀結果；/api/prod-status 顯示新 commit
```

## 2. 開發機：建包與交付（對應裁示 ①②）

- 建包沿用 `build_deploy_package.ps1`，以及 `/api/build-gate` 的「同一棵 tree 12 小時內全量全綠」判準。gate 不過就不建包。
- 交付步驟（新增 `tools/platform/deliver.py`，由開發機儀表板呼叫）：
  1. 把包複製到 `<交付資料夾>\incoming\<包名>.partial\`。
  2. 寫出三個檔：
     - `delivery.json`：commit、product、built_at、檔數、總位元組、`apply_update.ps1` 的 `$ApplyScriptVersion`
     - `package.sha256`：逐檔 sha256，格式與 d7-packages 的 `full-package-sha256.txt` 相同
     - `package.sha256.sig`：Ed25519 簽章，見 §5-4
  3. **最後一步**：把 `incoming\<包名>.partial\` 改名成 `packages\<包名>\`，這一步就是「發布」。正式機只看 `packages\`。
- 包名：`<yyyymmdd_HHMMSS>_<commit8>_<product>`，沿用建包命名。
- 保留：`packages\` 只留最近 N 份（U-5）。刪舊包只刪開發機自己發布、而且 `results\` 已有結果的。

## 3. 正式機：偵測、驗證、一鍵套用（對應裁示 ③）

### 3.1 執行主體

- **不放進 ERP 本身**（port 666 的 app）：套用時要停掉它，自己停自己沒有人收尾。
- 正式機另跑一個本機儀表板：`deploy_dashboard.py` 的「正式機模式」，同一支程式、不同進入點。
  - 只綁 `127.0.0.1`；以登入者身分由排程工作或捷徑啟動。
  - 它是 apply_update 的父行程，只有它在套用期間不能被停。`Stop-InstallService` 只停 autostart 迴圈與它的行程樹，不含儀表板，這一點成立。

### 3.2 偵測

- 每 60 秒列一次 `<交付資料夾>\packages\`。只收同時符合兩點的目錄：
  - 有 `delivery.json`
  - 名稱符合包名格式
- **不在雲端資料夾上直接執行或驗證**：先整份複製到 `<ROOT>\..\motrix-staging\<包名>\`（本機、安裝目錄外），之後的驗證與套用都讀這份。
  - 理由：雲端同步中的檔可能被替換，而且 apply_update 讀的內容必須是驗證過的那一份。
- 複製前後各比一次 `delivery.json` 的檔數與總位元組；不同 ⇒ 判「同步中」，下一輪再試（§5-2）。

### 3.3 驗證（全部通過才顯示「可套用」）

1. **簽章**：`package.sha256.sig` 以正式機**已安裝版本**內建的公鑰驗 `package.sha256`（§5-4）。
2. **雜湊**：staging 裡逐檔 sha256 與清單相符；檔數相等；staging 裡沒有清單外的檔。
3. **結構**：`verify_package.py`，照現行用法（正對照＋包側）。
4. **版本**：
   - `delivery.json.commit` 不等於目前 `.deployed_commit.json` 的 commit（重複套用 ⇒ 顯示「已是這一版」，不可按）
   - 退版 ⇒ 顯示並要求 U-3 的確認
5. **腳本版本**：`delivery.json` 的 `$ApplyScriptVersion` 與包裡 `apply_update.ps1` 相符（AH-O7 的雜湊檔同一套）。
6. **前置健康**：沿用 `/api/pre-deploy-check`（備份 `.done`、告警），正在壞的事項顯示出來（記憶〈出修補包前先查正式機健康〉）。

### 3.4 一鍵套用

- 按下後（＋U-3 的確認）依序執行：
  1. 取得套用鎖（§5-1）
  2. 把 `staging\<包名>\backend\tools\*` 複製到 `<ROOT>\backend\tools\`（AH-M2，與 `_dashboard_remote.ps1:117-120` 同一件事）
  3. 執行 `apply_update.ps1 -PackagePath <staging\包名> -Yes`（本機子行程，不經 WinRM）
- 逾時上限沿用 `_JOB_TIMEOUT_MIN["deploy"]`（45 分）。逾時**不自動中止**（沿用「會改東西、而且不是原子的動作不自動中止」）。

## 4. 結果呈現（對應裁示 ③④）

- 判定只看最後一行 `::RESULT:: v=2 status=… rolled_back=… service=… exit=…`（`parse_result_line`／`decide_outcome`，不另寫正則）。
  - 版本不符、值域外、沒有結果行 ⇒ 失敗（fail-closed）
- 畫面三行，全部沿用現有文案表：
  - **結果**：succeeded／failed
  - **正式機現況**：`_ROLLED_BACK_TEXT["deploy"][rolled_back]`，例：「已還原到套用前的版本。」
  - **服務**：up／down／unknown，只講觀察到的
- 各狀態的處置提示照 UPGRADE-RUNBOOK §8 的出口狀態表：
  - `copy_failed_*`／`delete_failed`：顯示「套用到一半、已嘗試重新啟動」，並附手動回滾按鈕，帶入這次的快照時間戳
- 「手動回滾」按鈕：
  - 列出 `rollback_snapshots\` 讓使用者選，呼叫 `rollback_update.ps1`
  - 判定用 `_ROLLED_BACK_TEXT["rollback"]`
- **結果寫回**（④）：
  - 內容：`<交付資料夾>\results\<包名>.result.json`，欄位為 `::RESULT::` 五欄＋commit＋開始／結束時間＋正式機主機名
  - **不含** log 全文與任何資料內容（log 可能有個資；只附 status 與統計）
  - 開發機儀表板讀這個檔，更新 `/api/prod-status`。這也順便修掉「prod-status 讀舊部署工具紀錄」的既有待辦（RUN-PLAN 2026-09-27 23:22 ③）
  - 寫法：先寫 `.tmp` 再改名
- 歷史：正式機儀表板寫本機 `deploy_history.json`，沿用 `_history_lock` 與 pending 合併邏輯。

## 5. 失敗情境與防護（對應 ④ 的五項）

| # | 情境 | 防護 | 使用者看到 |
|---|---|---|---|
| 5-1 | **併發**：兩人同時按、或儀表板與手動 apply_update 同時跑 | ①儀表板內 `_active_job_lock`（現有）②**新增**：`apply_update.ps1`／`rollback_update.ps1` 開頭建立 `<ROOT>\backend\.apply.lock`（排他開檔，寫 PID＋開始時間），結束刪除；已存在而且 PID 還活著 ⇒ `apply_locked`（新出口值，未觸碰）；PID 已死 ⇒ 顯示殘留鎖、要求人確認後才清 | 「另一個套用正在進行（開始於 hh:mm，PID n）」 |
| 5-2 | **半下載／同步中** | 發布以改名收尾（開發機）；正式機只看 `packages\`；複製前後比 `delivery.json` 的檔數與總位元組；staging 雜湊逐檔核對；不符 ⇒ 標「同步中」，不顯示可套用 | 「偵測到新包，同步中（已到 n／N 檔）」 |
| 5-3 | **雲端同步延遲**：開發機已發布，正式機好幾分鐘都沒看到；或 `results\` 回傳慢 | 正式機：顯示「上次掃描時間」與雲端用戶端狀態（能讀就顯示，讀不到不猜）。開發機：交付後 N 分鐘（U-6）還沒看到結果 ⇒ 顯示「正式機尚未回報」，**不代表失敗**；絕不因逾時自動重送 | 「已交付 hh:mm；正式機尚未回報」 |
| 5-4 | **包被竄改**（能寫雲端資料夾的人換掉檔） | sha256 清單本身也在同一個資料夾，只防傳輸損壞、不防竄改 ⇒ 清單要**簽章**：開發機以私鑰簽 `package.sha256`，正式機以**目前已安裝版本**內建的公鑰驗（新包不能自帶公鑰替自己背書）。可重用 `helpers/licensing` 的 Ed25519 簽／驗；私鑰保管見 U-4。驗不過 ⇒ 包移到 `staging\rejected\`，畫面標紅，不提供套用 | 「簽章不符：這個包不是由開發機發布的，已拒絕」 |
| 5-5 | **權限**：誰能按 | 儀表板只綁 `127.0.0.1` ⇒ 只有在正式機本機（或遠端桌面）登入的人能按。按下前要求輸入 ERP 的 superadmin 帳密，儀表板打本機 `/api/auth/login` 驗證，不存密碼；稽核紀錄寫進 ERP 的 audit log（who／when／commit）。細節見 U-2 | 登入框；紀錄在「稽核日誌」 |
| 5-6 | 套用中儀表板本身被關掉或當機 | apply_update 是子行程，會繼續跑完；儀表板重開後讀 `.apply.lock` 與 `logs\apply_update_<ts>.*`，顯示「上一次套用的結果」。apply_update 需要**新增**：把最後的 `::RESULT::` 行寫到 `logs\apply_update_<ts>.result`（現在只印在 stdout） | 「上一次套用：<狀態>」 |
| 5-7 | 正式機磁碟不足 | 複製到 staging 前檢查可用空間 ≥ 包大小×3（staging＋快照＋餘裕），不足就不複製 | 「磁碟空間不足（需要 X GB）」 |

## 6. 與現有 `_dashboard_remote.ps1`／`deploy_dashboard.py` 的差異與重用

| 項目 | 現有（開發機經 WinRM） | 新設計（正式機本機） | 重用 |
|---|---|---|---|
| 傳輸 | `Copy-Item -ToSession` 推到正式機 | 雲端資料夾＋staging 複製 | — |
| 誰執行 | 開發機 PowerShell 遠端呼叫 | 正式機儀表板本機子行程 | `_run_job`（背景執行緒、串流輸出、逾時） |
| 先複製 tools（AH-M2） | `_dashboard_remote.ps1:117-120`，**沒有 else**（包裡沒有 tools 時安靜跳過） | 同一件事搬到正式機端；**沒有 tools ⇒ 拒絕**，不安靜跳過 | 邏輯照搬，補 else |
| 密碼 | WinRM 帳密經 stdin | 不需要 WinRM；改驗 ERP superadmin（§5-5） | — |
| 結果判定 | `parse_result_line`／`decide_outcome`／`_STATUS_*`／`_ROLLED_BACK_TEXT` | 相同 | **全部重用，不另寫** |
| 鎖 | `_active_job_lock`（只擋同一個儀表板） | ＋`.apply.lock`（跨行程） | 現有鎖保留 |
| 歷史 | `deploy_history.json`＋pending | 正式機本機一份；結果另寫回雲端 | `_history_lock`／`_merge_pending` |
| 快照清單／回滾 | `list-snapshots`／`rollback` 經 WinRM | 本機直接列、直接呼叫 | 參數驗證（時間戳只准字母數字底線連字號）照搬 |
| 健康 | `/api/prod-health` 經網路打 666 | 本機打 127.0.0.1:666 | `_healthcheck_ping.py` |
| 升級精靈（V9→新版） | `-Action upgrade -Step …` | **不在本設計範圍**（只做 platform→platform 日常更新） | — |

- **保留** WinRM 路徑作為備援（U-7），不刪。
- 實作切分建議（每一項各自可驗證）：
  - (a) `deliver.py`＋簽章
  - (b) 正式機模式：偵測、staging、驗證
  - (c) 一鍵套用：鎖、tools 複製、呼叫
  - (d) 結果寫回＋開發機讀結果
  - (e) apply_update 補 `.apply.lock` 與 `.result` 檔

## 7. 需要使用者決定的事（U 題；以表單詢問，一題一決定）

| # | 問題 | 選項（推薦在前） |
|---|---|---|
| U-1 | `<交付資料夾>` 位置 | 使用者指定雲端硬碟裡的一個專用資料夾（例：`<雲端硬碟>\MOTRIX-交付\`），只放包與結果，**不可以與個資雲端資料夾共用** |
| U-2 | 誰能按「套用更新」 | ①正式機本機登入＋ERP superadmin 帳密（推薦）②只要能登入正式機 Windows 就能按 ③指定帳號清單 |
| U-3 | 要不要二次確認 | ①一次確認框，顯示 commit／變更摘要／刪除檔數（推薦；符合「按兩次」）②再輸入 commit 前 4 碼 ③不確認 |
| U-4 | 簽章私鑰放哪 | ①開發機本機檔＋使用者另存離線備份（推薦）②與授權金鑰同一把（不推薦：用途混用）③不簽章、只驗 sha256（不防竄改） |
| U-5 | 雲端資料夾保留幾份包 | ①最近 3 份（推薦）②最近 1 份 ③不自動刪 |
| U-6 | 開發機多久沒收到結果要提示 | ①60 分鐘（推薦；套用上限 45 分＋同步延遲）②30 分鐘 |
| U-7 | WinRM 推送路徑要不要保留 | ①保留為備援、畫面上收起來（推薦）②移除 |
| U-8 | 正式機儀表板怎麼啟動 | ①登入時排程啟動、常駐（推薦）②要套用時由使用者點捷徑啟動 |

## 8. 不在本設計範圍

- 單一模組小包（裁示 ⑤，P7b 帶 migrations 的模組）：另立設計。交付通道可以共用 §2 的發布／簽章／驗證。
- 大改版的 D7 級演練（裁示 ⑥）：照 RUN-PLAN §3。
- AH-S7（停服後失敗時啟動半套用程式）的處置：待 D＋使用者裁示，本設計照當時的 apply_update 行為呈現。

## 9. 實作狀態與寫死的介面（2026-09-28 使用者裁示 U-1～U-8 全照推薦；U-1＝`我的雲端硬碟\MOTRIX-交付`，使用者自建）

### 9.1 已實作：(a) 發布＋簽章、(b) 偵測／staging／驗證（`backend/tools/delivery.py`，題 `tests/platform/test_delivery_2026_09_28.py`）

- 交付資料夾結構、包名、`delivery.json` 欄位、`package.sha256` 格式見 `delivery.py` 檔頭。包的內容放在 `packages\<包名>\payload\`，交付檔與包分開，不混進包裡。
- **簽章涵蓋 `delivery.json`＋`package.sha256`**（`signed_bytes`）：只改畫面上顯示的 commit，也驗不過。
- 公鑰 `DELIVERY_PUBKEY_PEM` 目前是空的 ⇒ 正式機一律拒絕，不退回「不驗章」。使用者執行 `python backend/tools/delivery.py keygen --private-out <開發機本機路徑>`：私鑰寫到那個檔，公鑰印出後貼進 `DELIVERY_PUBKEY_PEM`，隨版本出貨（U-4：私鑰另外做離線備份）。
- 結構檢查用**正式機已安裝版本**的 `verify_package.py`。`--expect-db-version` 取自已安裝的 `db.py`（V9 基準凍結＝獨立訊號，不取自包本身）。
- 腳本版本（AH-O7）：包裡 `$ApplyScriptVersion`＝`apply_update.version.json` 的 version，而且內容雜湊相符，才發布、才驗得過。
- 保留份數（U-5＝3）：更舊的只刪「`results\` 已有結果」的包；正式機還沒回報的不刪。

### 9.2 (e) apply_update／rollback_update 要補的兩個檔（**介面寫死**，H 照這裡接；改動要先改本節）

**套用鎖** `<ROOT>\backend\.apply.lock`
- 建立：腳本在身分守門之後、任何備份之前，以**排他建立**（`[IO.File]::Open(path, 'CreateNew')`）寫入。已存在 ⇒ 見下方「殘留鎖」。
- 內容（UTF-8 JSON，無 BOM）：`{"pid": <int PowerShell 行程>, "script": "apply_update"|"rollback_update", "started_at": "YYYY-MM-DDTHH:MM:SS", "package": "<PackagePath 或 SnapshotTimestamp>", "host": "<COMPUTERNAME>"}`
- 移除：腳本結束時一律移除（`try/finally`，含所有 `Fail` 出口）。
- 殘留鎖：檔在，而 `pid` 的行程不存在（或存在、但不是 powershell）⇒ **不自動清**，出口 `apply_locked_stale`，訊息列出鎖的內容，由人確認後手動刪除。行程還在 ⇒ 出口 `apply_locked`。
- 兩個新出口都是 `rolled_back=not_applied service=unknown`，要登記進 `deploy_dashboard._STATUS_FAILED`。

**結果檔** `<ROOT>\backend\logs\<script>_<timestamp>.result.json`
- `<script>`＝`apply_update` 或 `rollback_update`；`<timestamp>`＝腳本內的 `$timestamp`（`yyyyMMdd_HHmmss`，與快照目錄同名）。
- 寫入時機：`Emit-Result` 印 `::RESULT::` 的同時寫；先寫 `.tmp` 再改名。stdout 那一行不變（判定仍以它為準）。
- 內容（UTF-8 JSON，無 BOM）：`{"protocol": 2, "status": ..., "rolled_back": ..., "service": ..., "exit": <int>, "script": ..., "script_version": "<$ApplyScriptVersion>", "timestamp": "<yyyyMMdd_HHmmss>", "package": "<PackagePath 或空>", "commit": "<包的 commit 或空>", "started_at": ..., "finished_at": ...}`
- 前五欄必須與同一次 stdout 最後一行的 `::RESULT::` 逐欄相同（守門比對兩者；不同 ⇒ 以 fail-closed 判失敗）。
- 讀取：儀表板取檔名時間戳最大的那一份，當作「上一次套用的結果」（§5-6）。寫回雲端的 `results\<包名>.result.json` 由 (d) 從這個檔轉出，只帶這些欄位，不帶 log。
