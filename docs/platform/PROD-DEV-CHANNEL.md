# 開發機 ↔ 正式機 Claude 溝通協定

> 建立 2026-09-30（使用者：「正式機會開 Claude，這邊也會開，兩邊能溝通並且確認狀態，這樣兩邊資訊溝通更新比較不會有問題」）。
> 開發機主持＝`node-bb`（本 repo 的派工／合回／建包；2026-10-08 第 46 班起主持為 `node-d8`，session 名稱會變，以 `ListAgents` 與 RUN-PLAN §6 當班記載為準）；正式機＝電腦 `MOTRIX`、帳號 `Motrix`、安裝目錄 `C:\Users\Motrix\Desktop\V9.0`（正式機 Claude 在 RUN-PLAN §6 稱 `motrix-a9`）。第 46 班起的授權與外出規則見 §6～§8。

## 1. 管道
- **即時訊息**：兩邊都開 Claude Code 並執行 `/remote-control`；開發機以 `ListAgents` 找正式機 session（標示 Remote Control），用 `SendMessage` 傳訊。session 名稱會變 ⇒ **每次第一則先請對方回報 hostname＋安裝目錄**，對上才往下。
- **留存紀錄**：雲端 `我的雲端硬碟\MOTRIX-交付\`（正式機看到的是 `H:\`）
  - `給正式機Claude_<班次>更新步驟.md`：步驟檔（與 repo `docs/platform/prod-tasks/` 逐字一致）
  - `正式機回報\<yyyyMMdd_HHmmss>_<commit>_<成功|回滾|擋下|狀態|待使用者確認>\摘要.md`：正式機的每次回報（非套用類作業用作業名取代 commit，例 `20261010_010500_管銷切換_成功`；`待使用者確認`見 §7）
  - `正式機回報\status\latest.json`：最近一次狀態快照（格式見 §3）
- 訊息只是通知；**權威紀錄是雲端檔與 repo**（〈要求寫在訊息裡等於沒下達〉）。

## 2. 分工
| 動作 | 開發機主持 | 正式機 Claude | 使用者 |
|---|---|---|---|
| 狀態快照（唯讀） | 請求 | 執行並寫 `status\latest.json`＋回覆 | — |
| 建包、稽核、演練、發布、寫步驟檔 | ✔ | — | — |
| 步驟 0／1（前置、stage、verify） | 下指示 | ✔ | — |
| 步驟 2 套用（停服務、改程式） | — | 權限設定放行時執行 | 否則本人執行 |
| 步驟 3 套用後檢查（唯讀） | 下指示 | ✔ | 目視需登入的畫面 |
| 回滾 | — | 只限步驟檔預先授權的「只回程式」 | 其餘先問使用者 |
| 任何寫入正式資料、改權限設定 | ✘ | ✘ | ✔ |
兩邊都**不代做對方被安全檢查擋下的動作**，也不換寫法重試；停下回報使用者。

## 3. 狀態快照格式（`status\latest.json`，唯讀產生）
產生指令（正式機 Claude 執行；工具 `backend/tools/prod_status_snapshot.py`，只用標準庫；隨下一個部署包進正式機，之前的快照改人工逐項查）：
```powershell
python C:\Users\Motrix\Desktop\V9.0\backend\tools\prod_status_snapshot.py --out "H:\我的雲端硬碟\MOTRIX-交付\正式機回報\status\latest.json"
```
- 同一份 JSON 也印到 stdout ⇒ 直接貼回訊息。`--root` 省略＝工具所在 `backend\tools` 的上兩層；`--port` 預設 666；
  `--archive-root` 省略＝與 `archive._detect_archive_base` 同規則掃磁碟機找 `我的雲端硬碟\系統存檔`（**不讀 DB 裡的「儲存位置」設定**；有設定的機器請帶 `--archive-root`）。
- 🔴 唯讀：不 import 產品程式、不讀 DB、不啟停服務；唯一寫入是 `--out`（原子寫入：先 `.tmp` 再改名；`--out` 在安裝目錄內 ⇒ 拒絕、exit 2；只補建最後一層目錄）。
- 任一來源讀不到 ⇒ 該欄 `null`，原因在 `errors["欄位"]`；不中止。
```json
{"schema": 1, "taken_at": "...", "hostname": "MOTRIX", "install_root": "...",
 "deployed_commit": "<40 碼>", "deployed": {"commit_short": "...", "branch": "...", "applied_at": "...", "built_at": "..."},
 "api_base_url": "https://127.0.0.1:666", "api_version": "2026-09-30g", "ping": 200,
 "modules": [{"key": "...", "version": "...", "state": "loaded"}], "modules_started_at": "...",
 "last_apply": {"timestamp": "yyyyMMdd_HHmmss", "status": "...", "rolled_back": "...", "service": "...", "exit": 0,
                "result_file": "apply_update_<ts>.result.json"},
 "backups": {"archive_root": "...", "archive_root_source": "arg|auto_scan",
             "daily_done_latest": {"date": "yyyy-mm-dd", "done_at": "..."},
             "local_snapshot_done_latest": {"date": "...", "done_at": "..."},
             "alerts_since": {"timestamp": "...", "level": "WARN|ERROR", "reason": "≤200 字"},
             "sticky_alert_file": false, "sticky_alert_at": null},
 "disk_free_gb": 0.0, "port": 666, "service_pids_on_666": [0], "errors": {}}
```
- 來源：`backend\.deployed_commit.json`；`GET /api/ping`、`/api/system/version`（有 `backend\certs\cert.pem` ⇒ https、不驗憑證、逾時 3 秒）；`backend\logs\module_states.json`；`backend\logs\apply_update_*.result.json` 最新一份；雲端 `<存檔根>\每日備份\<日期>\.done` 與本機 `backend\db_backups\<日期>\.done` 最新一份（mtime）；`backup_alerts\<日期>.log` 中晚於每日 `.done` 的最新一筆＋`BACKUP_ALERT.txt` 是否存在；安裝磁碟剩餘 GiB；`netstat -ano` 在該埠聆聽的 PID。
- 測試：`backend/tests/platform/test_prod_status_snapshot_2026_09_30.py`（欄位齊全、各來源缺席、ping 失敗、唯讀整樹比對、`--out` 原子寫入、機敏字詞掃描；含反向控制）。
- 開發機在「建包前」與「發步驟檔前」都先要一次快照，以快照的 `deployed_commit` 當基準（〈先確認正式機跑哪個 repo〉）。
- 快照不含個資、金鑰、帳密。

## 4. 一次更新的標準對話
1. 開發機：「請回報 hostname、安裝目錄，並產生狀態快照」→ 正式機回覆快照。
2. 開發機：建包 → 稽核 → 演練 → 發布，步驟檔放雲端 → 通知正式機「第 N 班步驟檔已放，基準 <commit>」。
3. 正式機：步驟 0～1，結果回覆＋寫回報。步驟 0 必做（PLAYBOOK §D-1a，2026-09-30）：讀部署包 `deploy_manifest.json` 的 `verification`——`mode`＝`scoped` ⇒ `<ROOT>\backend\.deployed_commit.json` 的 `commit` 開頭必須＝`verification.scoped.base`（40 碼），不等 ⇒ 停下回報兩個值（範圍驗證是對著別的基準算的）；`mode`＝`full` ⇒ 記下即可；沒有 `verification` ⇒ 停下回報。範本 `prod-tasks/TEMPLATE-apply.md` 步驟 0 第 2 項。
4. 步驟 2：權限放行則正式機執行；否則開發機請使用者本人執行（附兩行指令）。
5. 正式機：步驟 3 → 寫 `…_成功\摘要.md`＋新的狀態快照 → 回覆全文。
6. 開發機：RUN-PLAN §6 記錄、`tests/_prod_baseline.py` 基準改新 commit；主持打受信 tag `prod/<新 commit 前 8 碼>` 並推上 origin（範圍驗證的基準只認最新的 `prod/*` tag，PLAYBOOK §D-1a）；步驟檔定稿存檔到 `docs/platform/prod-tasks/<日期>-train<N>-apply.md`（與雲端副本逐字一致，文首「定稿」行改為已發布並已套用成功）。整個班次流程見 PLAYBOOK §G7。

## 5. 異常
- 對方沒回應：訊息不保證已讀 ⇒ 以雲端回報檔為準；超過 30 分鐘沒有新回報檔就請使用者看正式機畫面。
- 兩邊資訊不一致（例：一則說「tools 沒複製」、下一則說「只有部分更新」）⇒ 以狀態快照與檔案實況為準，重新要一次快照，不憑訊息推斷。

## 6. 自動套用授權（第 46 班起的常態；步驟檔文首寫明）
> 來源：`docs/platform/prod-tasks/20261008-train46-apply.md` 起各班步驟檔的「授權」段；使用者 2026-09-29 16:46、2026-09-30 的原始授權記在 RUN-PLAN §6。
- **誰授權、誰轉述**：使用者 2026-09-29 16:46 原話「不用等我確認自動部署上正式機，有問題就回滾等我確認，沒問題直接上線」（RUN-PLAN §6）；後來各班步驟檔把「有問題」收窄成下面的停止規則（套用動到資料庫之後不自行回滾），**以步驟檔為準**。每班的步驟檔文首由主持寫明「授權：自動套用（主持轉述；沿用第 N～M 班規則）」。**步驟檔就是授權的範圍**，沒寫的動作不在授權內。
- **流程**：主持發布本包 ⇒ 正式機 Claude 做步驟 0～1（含 staging 驗證）⇒ **兩步全綠才自動進步驟 2 套用**。任何一項不綠 ⇒ 不套用、停下、寫「擋下」報告。
- **硬條件**：套用前備份並驗證（路徑、大小、`integrity_check=ok`、備份 schema 版本、關鍵表筆數與來源相同）；缺一不套用。
- **停止規則**（步驟檔「停止條件」逐班列明，以下為共通部分）：
  - 套用已動到資料庫之後任何失敗 ⇒ **不自行回滾、不重試 apply**，寫報告、等使用者。
  - 自己的分類器擋下 `Copy-Item`／`apply_update`／其他 ⇒ 停下回報，**不換寫法、不繞過**，等使用者處理（第 25 班先例：使用者本人到正式機執行步驟 2）。
  - 步驟 2 的 `::RESULT::` 不是 `status=success rolled_back=applied service=up exit=0`、包雜湊／行數／`verify_package --expect-db-version` 不符、包內出現 `.pyc`／`__pycache__`／`*.db` ⇒ 停。
- **驗證一律唯讀**：正式機上不為了「測試」去送審、核可、付款、上傳、建立單據、改使用者或任何設定；會寫資料的驗收項寫在步驟檔的「需要使用者自己做的」。
- **結果**：正式機 Claude 寫回報資料夾（§1）＋新的狀態快照；主持照 §4 第 6 步收尾。步驟 3 的檢查項隨班次增加（第 46 班 15 項、第 47 班 16 項、第 48a 班起 17 項）；個別項目的字串比對過嚴但意圖達成時，回報寫明「已接受」，不要為了讓字串吻合而改正式機。

## 7. 會寫入正式資料的步驟：要使用者**本人**確認（口徑切換先例，2026-10-10）
> 先例：第 48b 管銷口徑切換（`recalc --apply --set-mode-v2`，會重算 35 張報價單並改 `overhead_rule_mode`）。步驟檔 `給正式機Claude_第五十班後_管銷口徑切換步驟.md`（SHA256 寫在檔內，主持發 GO 時附上，正式機比對一致才開始）；做法見 `plans/OVERHEAD-25PCT-CUTOVER-RUNBOOK-T48.md`。回報：`正式機回報\20261010_003000_管銷切換_待使用者確認`、`…\20261010_010500_管銷切換_成功`。
- **正式機 Claude 的實際行為（也是我們要的）**：第 0～3 節（基準、備份、在備份複本上跑三份報告、閘門 G1～G6）全部做完並寫報告，**停在會寫正式庫的第 4 節之前**，理由是「核准是開發機轉述的使用者事前核准，不是使用者在本對話的直接指示」。使用者在正式機 Claude 的對話裡本人說「同意」之後才停服務、單一指令套用、啟動、做第 5 節檢查。
- **所以**：①凡是寫入正式資料（改單據、改口徑、改 `system_settings`、跑會改資料的遷移工具）的步驟，**主持轉述的授權不夠**；②主持不要催、不要重複轉述、不要把原話改寫後再送——**請使用者本人到正式機 Claude 的對話確認**（或使用者本人執行）；③步驟檔把「唯讀前置」與「寫入」分成不同節，前置做完就能先拿到報告與閘門結果，使用者確認時有現成的數字可看；④等待期間回報資料夾用 `…_待使用者確認` 後綴，內容寫明停在哪一節、下一步要什麼。
- **與 §6 的差別**：§6 的自動套用只涵蓋「發布出來的程式包」（`apply_update.ps1`，有自己的備份、驗證與回滾）；資料修改類作業不在 §6 的授權內。
- 回滾資訊只給使用者決定：正式機 Claude 回報工具的回滾指令與備份檔位置，**不自行執行**。

## 8. 使用者外出期間（離開模式）
> 來源：RUN-PLAN §6 2026-09-30 11:24（「不可回溯與法規留使用者，其餘主持定案」）、2026-10-09 起各班（「使用者外出，主持全權」）。
- **主持可定案**：排程、範圍、裁示類決策；稽核、演練、發布、基準推送與標籤（使用者 2026-10-09 起授權主持自己推送，不用等指令；腳本先讀全文、先 `--check`、被分類器擋下就停）。
- **留給使用者**：不可回溯的動作、法規相關、PLAYBOOK §F 列的事（會改變使用者看得到的行為、權限範圍、個資、碰正式機資料、推翻先前裁示——先問，用表單）、§7 的寫入步驟、所有會寫資料的驗收項、權限規則本身（兩端的 `settings.json` 只有使用者本人能加；主持與正式機 Claude 都不改自己的權限，被擋時不換寫法、**不叫另一端代做**）。
- **套用後檢查失敗**：只記錄、停下，不自行回滾、不重試；回報資料夾寫明現況，等使用者。
- **留紀錄**：每次發布、套用、基準更新在 RUN-PLAN §6 記一筆；使用者回來時，把「需要使用者決定／驗收」的項目集中在最前面交給他。
