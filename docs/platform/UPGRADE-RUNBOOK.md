# V9 → 新版 升級轉換與回滾 操作手冊（UPGRADE-RUNBOOK）

> 規格：CORE-SPEC §9b。工具：`tools/platform/upgrade.py`（核心 `backend/core/upgrade.py`）。
> 🔴 **對正式機執行是使用者的動作。** 本手冊的每一步都由人在正式機上手動執行、逐步確認；工具不連任何遠端、不猜路徑。
> 下文 `<ROOT>` ＝ V9 安裝根目錄（含 `backend\`、`frontend\` 的那一層），`<BK>` ＝ 備份目錄，`<NEW>` ＝ 新版程式目錄。

## 0. 事前準備（升級前一天以前）

| # | 動作 | 為什麼 |
|---|---|---|
| 0.1 | 在雲端硬碟「我的雲端硬碟」底下手動建立 `系統存檔_個資`，右鍵 → Google 雲端硬碟 → 共用，收窄權限（DR-SOP §3a） | 新版的整庫備份與個資只放這裡；不存在 ⇒ 雲端沒有整庫備份（會告警，但不會自動建） |
| 0.2 | 準備 `<NEW>`：解開新版部署包到**安裝目錄以外**的位置 | 工具拒絕放在 `<ROOT>` 裡的來源 |
| 0.3 | 準備 `<BK>`：一個**新的空目錄**，在安裝目錄以外、空間 ≥ 資料庫大小×3＋程式目錄大小 | 工具拒絕非空或在 `<ROOT>` 裡的備份目錄 |
| 0.4 | 確認 `<ROOT>` **沒有** `.no_email_send`、`.no_cloud_archive` | 有的話轉換後不寄信／不上雲（預檢會擋） |
| 0.5 | 確認 V9 最近一次每日備份正常（本機 `backend\db_backups\<今天或昨天>\.done`）、`backup_alerts\BACKUP_ALERT.txt` 不存在 | 〈出修補包前先查正式機健康〉：有問題先處理，不要疊在升級上 |

## 1. 停服務

停掉 V9（排程工作的自動重啟也要停），確認正式 port 沒有人在聽。

## 2. 預檢（不改任何東西）

```
python <NEW>\tools\platform\upgrade.py preflight --root <ROOT> --v9-port <正式 port>
```

- 輸出 `"ok": true` 才往下。任一 `problems` ⇒ 處理後重跑。
- 檢查項目：安裝目錄結構、主庫存在、`schema_version ≤ 116`、磁碟空間 ≥ DB×3、最近快照 `.done`（今天或昨天）、無備份告警、服務已停、無開發機標記。
- ⚠️ 若 `system_settings` 的 `*_pdf_base_path` 指到安裝目錄以外（例如網路碟），那些目錄**不在**清單比對範圍內：本工具不讀也不寫它們，升級前後也不需要動。

## 3. 備份（＋自動試還原）

```
python <NEW>\tools\platform\upgrade.py backup --root <ROOT> --backup-dir <BK>
```

- 主庫與 demo 庫用 SQLite Online Backup API；程式目錄與設定／身分檔（heartbeat_config、license、憑證、`.env` 類、初始帳密檔）逐檔複製；資料目錄（uploads、7 類 PDF、db_backups…）**原地不動，只記清單與雜湊**。
- 完成後自動把備份還原到暫存位置、逐檔比對 SHA256、主庫 integrity_check 與各表列數。**不通過 ⇒ exit 2，不可以往下。**
- 產出：`<BK>\upgrade_manifest.json`（每個備份檔的雜湊）、`<BK>\backup_verify.json`。

## 4. 轉換

```
python <NEW>\tools\platform\upgrade.py convert --root <ROOT> --backup-dir <BK> --new-source <NEW>
```

- 沒有通過驗證的備份就拒絕執行。
- 刪掉 V9 程式檔、換上新版程式檔；資料、DB、設定一律不動。
- 用新版的 `init_db` 補跑基準 migration 到 v116，並建 `module_schema_versions`。
- 設定只補缺的鍵（目前只有 `payslip_archive_path`＝空字串，意思是用預設目錄）；既有值不改。
- 產出：`<BK>\conversion_log.json`。

## 5. 驗證

```
python <NEW>\tools\platform\upgrade.py verify --root <ROOT> --backup-dir <BK> --port <正式以外的 port，例如 6671>
```

- 先比資料：各表列數與轉換前相同、既有設定逐項相同、只多出宣告過的新設定鍵、資料目錄清單相同。
- 再在**非正式 port** 啟動新版、`/api/ping` 200、停掉；啟動後既有設定仍不得被改寫。
- 通過 ⇒ 用正常方式在正式 port 啟動新版（排程工作）。不通過 ⇒ exit 3 ⇒ 進 §6。

## 6. 回滾（出問題時）

| 模式 | 指令 | 效果 | 何時用 |
|---|---|---|---|
| **只回程式**（建議先用） | `upgrade.py rollback --root <ROOT> --backup-dir <BK> --mode code` | 換回 V9 程式；**保留**轉換後寫入的資料 | 新版有問題，但資料要留著 |
| **完整回滾** | `upgrade.py rollback --root <ROOT> --backup-dir <BK> --mode full [--yes]` | 程式＋DB＋設定還原成備份時的樣子（雜湊逐一相等）；轉換後才出現的設定檔會刪掉 | 資料本身有疑慮，要回到升級前那一刻 |

- 完整回滾前工具會列出「轉換後新增的列數」；沒有 `--yes` 不執行。**那些列會消失。**
- 兩種模式都會逐檔比對雜湊（程式；完整回滾另比 DB 與設定），不一致 ⇒ exit 5。
- 回滾完：在非正式 port 啟動 V9 確認 `/api/ping` 200，再恢復正式服務。
- 「只回程式」成立的前提：新版對 DB 只做新增（CORE-SPEC §6）。演練已驗證 V9 讀得了新版寫過的庫並正常啟動。

## 7. 事後

- `<BK>` 保留到新版穩定運作為止（建議至少一個月的月備份已產生在 `系統存檔_個資\月備份\`）。
- 設定頁「雲端備份目標」確認「個資存檔（勞報單）雲端資料夾：已就緒」。

## 附：開發機演練（不碰正式機）

```
python tools/platform/upgrade_drill.py --mode both [--source-db <開發機 V9 測試庫>]
```

- 在 `%TEMP%` 建 V9 形狀的安裝目錄（程式取 `c83dae6e`），跑 預檢 → 備份＋試還原 → 轉換 → 驗證 → 寫入一筆新資料 → 回滾 → V9 啟動 ping。
- 演練路徑不可以含 `V9.0`（V9 的寄信判定看安裝路徑）；啟動一律 `MOTRIX_DISABLE_SCHEDULERS=1`、`MOTRIX_CLOUD_ARCHIVE=off`、`MOTRIX_EMAIL_SEND=off`，並放 `.no_cloud_archive`。
- `--source-db` 以 Online Backup API 唯讀複製，來源檔不變（2026-09-25 實測雜湊前後相同）。
- 自動化測試：`backend/tests/test_upgrade_drill_2026_09_25.py`（兩種模式）、`backend/tests/platform/test_core_upgrade.py`（純函式）。
