# MOTRIX ERP — 備份與還原（§8）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

---

## §8 · 備份與還原

> 整台正式機硬體故障時的完整重建流程，見獨立文件 [`DR-SOP.md`](../../DR-SOP.md)（2026-08-07 新增）。
> 這裡的 §8.1–§8.4 是日常備份機制；DR-SOP.md 是「機器掛了怎麼辦」的實際操作步驟。

---

### §8.0 · 雲端備份目標可插拔（2026-09-07，架構地圖 §6.4）

`archive.py` 原本只支援「本機掛載的雲端硬碟磁碟機」（下方 §8.1，磁碟機代號漂移已造成過真實備份靜默失效事故）。新增 `cloud_storage.py`，可切換成 S3 相容物件儲存（AWS S3／Backblaze B2 皆可，B2 有 S3 相容端點）：

```
system_settings.cloud_backup_target = { backend: "local_drive" | "s3", s3: {bucket, endpoint_url, region, prefix} }
GET/PUT /api/settings/cloud-backup-target（superadmin only，無前端頁面，比照 edge-path 等技術設定慣例）
```

- **憑證一律不存 DB**——走 boto3 標準憑證鏈（環境變數 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` 或 `~/.aws/credentials`），設定裡只有 bucket/endpoint/region/prefix 這類非機密值
- `archive.py` 內所有原本「寫本機掛載磁碟機路徑」的地方（即時/每日/週備份、uploads 鏡像、SQLite 快照複製、過期備份清除）都已改走 `_cloud_write_json()`/`_cloud_copy_file()`/`_cloud_stat()`/`_cloud_marker_exists()`/`_cloud_write_marker()`/`_cloud_list_top_level()`/`_cloud_delete_dir()` 這組派送層——`backend="local_drive"`（預設）時這些函式的行為與改動前逐位元組相同（本機路徑計算完全沒變，只是多繞一層），`backend="s3"` 時才會改呼叫 `cloud_storage.py`
- **目前沒有真實 S3/B2 帳號可測試**，S3 路徑只用假的記憶體 S3 client 做過完整單元測試（`tests/test_cloud_storage_2026_09_07.py`，18 題）；要在正式機真正啟用，需要①先申請一個 AWS S3 或 Backblaze B2 帳號建 bucket ②在正式機環境變數設定 access key ③呼叫上面的 PUT 端點切換 backend。切換前這些都還沒做，正式機目前**維持 §8.1 原本的本機磁碟機模式**

---

### §8.1 · 路徑

> **⚠️ 2026-09-14 保留政策改版（使用者裁示）**：每日 60 天／週 90 天／**新增月備份永久保留**。
> 三層的角色不同，不要混在一起看——每日層是日常誤刪誤改的回溯窗口，週層是中期粗顆粒窗口，
> 月層是長期法遵與歷史查詢。改短前兩層是刻意的：舊值（每日 1825 天＝5 年、週 730 天）等於把
> 長期保存壓在「每天一份整庫 .db」上，成本隨資料庫大小線性成長，而真正需要長期保留的是月粒度。
>
> **上傳檔案鏡像與 PDF 存檔鏡像任何情況都不清除**（使用者明訂長久保留）——`_prune_cloud_backups()`
> 只走每日／週／月三個目錄，`test_backup_retention_policy_2026_09_14.py` 有一題專門守這件事，
> 不要為了「順手清一下舊照片」把鏡像目錄加進 prune 清單。
>
> ⚠️ 正式機若曾呼叫過 `PATCH /api/settings/backup-retention`，舊數字會固化在 DB 裡，
> **改預設值完全不會生效而且不會有任何錯誤訊息**（`_backup_retention()` 是 `{**預設, **DB 存的值}`）。
> 所以另外做了 **DB v83**（`db.py::_m083_backup_retention_policy`）把儲存值一併改成新政策。

```
雲端（磁碟機代號不固定，掃 A–Z 找，見下方說明）
  <任一磁碟機>:\我的雲端硬碟\系統存檔\
    .motrix_archive_owner   （2026-09-14 新增，存檔所有權標記，見 §8.1b）
    即時備份\報價單|客戶|供應商\
    每日備份\YYYY-MM-DD\  （JSON 41 表 + motrix_erp.db；**保留 60 天**，超過自動清除整個日期資料夾）
    週備份\YYYY-WNN\      （**保留 90 天**，超過自動清除整個週別資料夾）
    月備份\YYYY-MM\       （2026-09-14 新增，**永久保留**。內容與每日備份完全相同——41 張表
                            JSON ＋ 整份 motrix_erp.db，共用 `_export_table_json_set()` 同一段
                            匯出邏輯，日後新增資料表兩邊會一起有、不會只有其中一邊。
                            **執行時機是「當月第一次成功的每日備份」**，不是月底也不是 1 號——
                            綁死日期的話那天沒開機或備份失敗，整個月就沒有長期備份且沒人發現。
                            整庫 .db 一定要收：JSON 那層刻意不含憑證欄位與內嵌影像（見 §8.3），
                            長期保留的那一份如果只有 JSON，等於長期保留了一份殘缺的資料。
                            有表匯出失敗時**不寫 .done**，隔天的每日備份會再試一次——
                            寧可晚一天，也不要把一份殘缺的當成這個月的永久備份）
    上傳檔案鏡像\          （2026-08-08 新增，uploads/ 專案照片等實體檔案，_mirror_uploads() 依大小+
                            修改時間增量同步，不是每日整包複製；demo 隔離目錄不同步；只增不減）
    PDF存檔鏡像\{類別}\    （2026-09-07 新增，報價單/出貨單/承攬商匯款申請/開票申請憑據/請款單/
                            結案報表 6 類，_mirror_pdf_archives() 同一套增量同步邏輯；跟隨
                            system_settings 裡各自 pdf_base_path 的實際設定值，非固定預設路徑）

本機（不依賴雲端碟，務必保留）
  backend\db_backups\YYYY-MM-DD\motrix_erp.db   ← SQLite Online Backup，保留 30 天
  backend\db_backups\pre_update_YYYYMMDD_HHMMSS\
                                                ← apply_update.ps1 套用前整庫快照。
                                                  2026-09-14 起**按份數**保留最新 5 份。
                                                  原本完全沒被清過：清理迴圈只刪「檔名 parse
                                                  得出日期」的資料夾，`pre_update_...` 直接
                                                  跳過——開發機實測累積 49 份、db_backups 吃掉
                                                  1.8 GB，正式機只會更多（那才是真正跑套用的
                                                  地方）。用份數不用天數：這些快照的價值來自
                                                  「最近幾次部署」而不是「最近幾天」，隔三個月
                                                  才部署一次的話用天數會把唯一一份退路也刪掉
  backend\db_backups\quotation_instant\          ← 雲端碟不可用時的即時報價單 JSON fallback
  backup_alerts\BACKUP_ALERT.txt                ← 雲端異常醒目警示
  backup_alerts\YYYY-MM-DD.log
```

---

### §8.1b · 存檔所有權標記（2026-09-14）

**要解決的問題**：這個存檔目錄原本沒有任何「這是誰的」概念。`_detect_archive_base()` 是掃 A–Z 找第一個含 `我的雲端硬碟\系統存檔` 的磁碟機（磁碟機代號會漂移，掃描是刻意的設計），而 `main.py:414` 是**無條件**啟動 `_schedule_daily()`／`_schedule_weekly()`。所以任何跑這份程式碼、又掛著同一顆雲端碟的機器（開發機、備援機、DR 還原出來的機器、未來的分公司機）都會寫進同一組資料夾。兩個實際後果**都是靜默的**：

1. `.done` marker 在雲端。先跑的那台贏，後跑的那台走 `_clear_backup_alert_if_healthy(); return`——**還順手把警示清掉**。正式機當天沒備份，但備份頁面綠燈、沒有 audit、沒有信。
2. `_snapshot_sqlite()` 的雲端複製不看 marker，第二台會直接覆蓋當天的 `每日備份/{date}/motrix_erp.db`——那是還原優先序的**第二層**。

這不是假想：2026-09-07「conftest 雲端備份隔離死碼把測試假資料寫進真實 G: 碟」就是同一類。

**作法**：存檔根目錄放 `.motrix_archive_owner`（JSON：`instance_id`／`machine`／`claimed_at`）。`_archive_ok()` 改成「目的地連得上 **且** 所有權相符」，所有原本只問「碟掛著沒」的呼叫點都走它，一次覆蓋即時／每日／週／月備份與兩組鏡像，不用逐一改呼叫端。

- **識別碼綁在資料庫**（`system_settings.archive_instance_id`）而不是機器名——DR 換機時資料庫是跟著還原過去的，新機器應該要能接手舊機器的存檔目錄；真正要擋的是「同一個存檔目錄被兩套**不同的資料庫**寫」。
- **第一次看到沒有 marker 的目錄會自動認領**：正式機明天第一次備份就把 marker 寫下去，不需要任何人工步驟。
- **不符時整組雲端備份停寫並寄 ERROR 警示信**，但**本機 SQLite 快照照做**——停掉它等於為了防一個問題製造一個更大的問題。
- **轉移所有權**：刪掉 `.motrix_archive_owner` 再重啟即可重新認領（警示訊息裡就直接寫著這一步）。
- **讀不到／寫不進 marker 一律 fail-open**：這層是針對罕見情境的防呆，不該因為一次暫時性 IO 錯誤就把每天的備份整個停掉。
- S3 後端不做這個檢查——bucket + prefix 是明確指定的，本來就不會「掃到別人的」。
- **判定快取以「存檔根目錄路徑」為鍵**（300 秒 TTL）。不以路徑為鍵的話，磁碟機代號漂移之後會沿用上一顆碟的結論——這不是理論問題，實測時就因此讓一支無關的備份鏡像測試吃到別題留下的 False， 在掛鏡像之前就早退，**序列跑綠、平行跑紅**。

測試：`backend/tests/test_archive_ownership_2026_09_14.py`（9 題，含「別人的當日整庫備份不可以被蓋掉」與「不可以用『碟沒掛上』這個錯誤理由蓋掉真正的原因」）。

---

### §8.2 · 排程架構（雙層）

| 層 | 機制 | 觸發時間 | 說明 |
|----|------|---------|------|
| **主**（可靠） | Windows 工作排程器 | 每日 02:00 | `backup_job.py`；server crash 也跑；開機後補執行 |
| **冗餘** | `threading.Timer` | 每 2h 日備；每 6h 週備 | server 在線時提供即時觸發 |

`.done` marker 確保同日/週/月不重複備份。設定：`setup_backup_task.ps1`（初次部署執行一次）。

**月備份的觸發點在每日備份裡**（`_daily_backup()` 匯出成功後呼叫 `_monthly_backup()`），不是另一個排程——同月第二次之後只是一次 marker 檢查就返回，成本可以忽略。

**⚠️ 這一整套的告警全部是「備份自己回報自己壞了」**：碟掉了、表匯不出來都會寫 `BACKUP_ALERT.txt` 並寄信，但「備份**根本沒有跑**」這件事沒有任何人會講——排程被停用、Timer 執行緒沒起來、另一台機器搶先寫了當日 `.done` 害本機早退，症狀全部是**一片安靜**（伺服器活著、heartbeat 照打、備份頁面綠燈），只有真的要還原的那天才會發現最後一份是三個月前的。2026-09-14 補上兩支**外部視角**的每日檢查（掛在既有的 08:00 排程，比照 `_check_cert_expiry()`，不另起 job）：

| 檢查 | 位置 | 條件 | 通知 key |
|------|------|------|----------|
| 備份新鮮度 | `daily_tasks.py::_check_backup_freshness()` | 本機快照或雲端每日備份超過 **36 小時**沒有成功紀錄 | `backup_stale` |
| 磁碟空間 | `daily_tasks.py::_check_disk_space()` | 剩餘同時 **< 10% 且 < 20 GB**（兩個門檻都沒過才叫） | `disk_space_low` |

- 兩支各自用 `system_settings` 當 guard，**一天最多一封**；恢復正常時清掉 guard，同一天再壞叫得出來。
- 新鮮度分「本機 SQLite 快照」與「雲端每日 JSON」兩條線各自判斷：本機那條斷掉代表備份程式本身沒在跑；**本機還活著而只有雲端那條斷掉，正是「另一台機器搶先寫了 .done」的症狀**，信裡會指名是哪一層。
- `backup.daily_partial` 算「有跑」（那個情境有自己的告警，不重複叫）。
- 全新環境（一筆備份紀錄都沒有）**不告警**——那是還沒跑過第一次，不是壞掉；誤報會讓人第一天就學會忽略這封信。
- 磁碟兩個門檻取「較寬鬆的滿足就算健康」：只看百分比的話 2 TB 的碟剩 8%（164 GB）就叫太早，只看絕對 GB 的話 256 GB 的系統碟剩 20 GB 已經很緊卻還不叫。

**雲端備份清除**（2026-08-01 新增，`_prune_cloud_backups()`）：`每日備份`／`週備份` 原本永不清除、會無限期累積；現在 `_daily_backup()` 跑完後會呼叫，各自依保留天數（預設每日 365 天、週備份 730 天）刪除整個過期的日期/週別資料夾。安全機制比照既有 `_prune_local_db_backups()`：只刪「資料夾名稱能正確解析成日期」的項目（`YYYY-MM-DD` / `YYYY-WNN`），其他檔名一律不動；H: 未掛載時整段略過，不會誤判成「全部過期」。

**`logs/server.log` 大小輪替**（2026-09-07 新增，`archive.py::_rotate_server_log_if_large()`）：`autostart.bat` 用 shell `>>` 把伺服器 24/7 的 stdout/stderr 直接導向這個檔案（見 §1.1），完全不是走 Python `logging` 的 handler，先前沒有任何大小上限或輪替機制，長期下來可能把磁碟塞滿（正式機曾經因為另一張表無限增生塞爆過每日備份空間，是同一類風險）。`_daily_backup()` 一開頭（不受雲端是否可用、今天是否已備份過影響）就會檢查：超過 50MB 就用 **copytruncate**（複製到 `server.log.1`，舊的 `.1~.4` 依序遞增一代，`.5` 直接砍掉）原地把 `server.log` 清空成 0 bytes，而不是改檔名——因為 `apply_update.ps1` 的健康檢查寫死讀 `logs/server.log` 這個檔名，換檔名輪替會讓那個檢查悄悄失效。**⚠️ 尚未在真正跑著 `autostart.bat` 的正式機上驗證過**（Windows 上 cmd `>>` 開檔的共用權限是否真的允許外部行程同時 truncate，這裡沒有實機測試過，失敗會直接放棄、log 檔案維持原樣繼續成長，不會比現狀更糟）——下次部署後留意 `logs/server.log` 是否真的有被清空過。

---

### §8.3 · 行為

| 條件 | 行為 |
|------|------|
| G: 正常 | 即時 JSON（**原子寫入**）+ 每日 JSON + 雲端 DB 副本 + 本機快照 |
| G: 未掛載 — 即時備份 | 寫至 `db_backups/quotation_instant/{no}.json`（本機 fallback） |
| G: 未掛載 — 排程備份 | 寫 `BACKUP_ALERT.txt` + audit `backup.alert`；**仍做本機 SQLite 快照** |
| 恢復正常 | 清除 sticky 警示檔 |
| Server crash | Task Scheduler 仍在 02:00 執行本機快照 |

**原子寫入**：所有 JSON 備份均先寫 `.tmp` 再 `os.replace()`，崩潰時不產生損毀檔。

Audit：`backup.daily_ok` · `backup.weekly_ok` · `backup.sqlite_snapshot` · `backup.alert`

**audit_log 保留**：每次每日備份後執行 `_prune_audit_log(keep_days=730)`，自動刪除 2 年前舊紀錄（先備後刪，雲端 JSON 永久保存）。

**還原優先序**：本機 `db_backups` 整庫 → 雲端`每日備份` 的 `motrix_erp.db` → 雲端`月備份` 的 `motrix_erp.db`（超過 60 天的時間點只剩這一層）→ JSON 重建（最後手段）

> 2026-09-14 起每日層只保留 60 天、週層 90 天。**要還原三個月以前的狀態，去 `月備份/YYYY-MM/`**——那一層永久保留，而且含整份 `.db`（不是只有 JSON）。

> **JSON 這一層涵蓋 41/76 張表**（2026-09-14 傍晚補齊，原本只有 8 張）。
> 沒進去的 35 張是刻意的：選型資料庫七類（由 `sync_*.py` 產生、git 裡有來源）、
> 登入態與鎖、流水號、操作軌跡與時數、個人排序偏好——重建它們沒有意義。
> 清單與逐項理由在 `backend/tests/test_system_audit_2026_09_14.py`
> 的 `_NOT_IN_JSON_BACKUP`，新增資料表沒做決定那支會變紅。
>
> ⚠️ **從 JSON 還原時，使用者的憑證欄位是刻意不備份的**
> （`totp_secret`／`totp_recovery_codes`／各種 password hash）——
> 那些是可以直接拿去產生有效驗證碼的金鑰，不該出現在人看得懂的備份檔裡。
> 所以走到這一層之後：帳號、角色、模組、部門歸屬都救得回來，
> 但**所有人都要重設密碼、重新綁定 2FA 與 Passkey**。
> （前兩層是整個 .db 檔，不受此限。）
>
> ⚠️ **JSON 這一層也不收內嵌影像與線上祕密**：
> ・承攬人員的身分證正反面／存摺掃描件，以及協力廠商 `data_json`、承攬付款憑據
> 　`snapshot_json` 裡包的存摺影像，一律換成佔位字串（通則式處理，
> 　見 `archive._strip_inline_images()`）。實測每天 5.5 MB 降到 1.4 MB，
> 　重點不是省空間，是**不要每天把一疊身分證掃描件複製到雲端資料夾**。
> ・`system_settings` 的 `email_notify.smtp_password`、
> 　`google_calendar.client_secret` 與 `refresh_token` 用 `json_remove()` 挖掉，
> 　其餘設定照常保留。還原後這三個值要重新填。
> 影像與祕密在前兩層（整庫 .db）都是完整的。
>
> 另外：單張表匯出失敗現在會送 `backup.daily_partial` 並留下警示，
> 不會再像以前那樣照樣報 `backup.daily_ok`。
