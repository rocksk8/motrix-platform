# 開發機 ↔ 正式機 Claude 溝通協定

> 建立 2026-09-30（使用者：「正式機會開 Claude，這邊也會開，兩邊能溝通並且確認狀態，這樣兩邊資訊溝通更新比較不會有問題」）。
> 開發機主持＝`node-bb`（本 repo 的派工／合回／建包）；正式機＝電腦 `MOTRIX`、帳號 `Motrix`、安裝目錄 `C:\Users\Motrix\Desktop\V9.0`。

## 1. 管道
- **即時訊息**：兩邊都開 Claude Code 並執行 `/remote-control`；開發機以 `ListAgents` 找正式機 session（標示 Remote Control），用 `SendMessage` 傳訊。session 名稱會變 ⇒ **每次第一則先請對方回報 hostname＋安裝目錄**，對上才往下。
- **留存紀錄**：雲端 `我的雲端硬碟\MOTRIX-交付\`（正式機看到的是 `H:\`）
  - `給正式機Claude_<班次>更新步驟.md`：步驟檔（與 repo `docs/platform/prod-tasks/` 逐字一致）
  - `正式機回報\<yyyyMMdd_HHmmss>_<commit>_<成功|回滾|擋下|狀態>\摘要.md`：正式機的每次回報
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
6. 開發機：RUN-PLAN §6 記錄、`tests/_prod_baseline.py` 基準改新 commit；主持打受信 tag `prod/<新 commit 前 8 碼>` 並推上 origin（範圍驗證的基準只認最新的 `prod/*` tag，PLAYBOOK §D-1a）。

## 5. 異常
- 對方沒回應：訊息不保證已讀 ⇒ 以雲端回報檔為準；超過 30 分鐘沒有新回報檔就請使用者看正式機畫面。
- 兩邊資訊不一致（例：一則說「tools 沒複製」、下一則說「只有部分更新」）⇒ 以狀態快照與檔案實況為準，重新要一次快照，不憑訊息推斷。
