# MOTRIX ERP — 開發快速參考

> 允碩整合集創（統編 60575481）｜ Tel: 04-3610-6566 ｜ info@miactw.com  
> 文件版本：**2026-09-16**（通行金鑰備份失敗修復＋Passkey 功能暫緩，DB 無異動，見 §12 最新兩則）
>
> **2026-09-13 新增互補文件**：[`MODULE-AUDIT-2026-09-13.md`](MODULE-AUDIT-2026-09-13.md)——模組機制的三方（權限目錄／側欄／後端）逐 key 對照，七項已修、五項待決策。**動權限／模組相關的東西之前先看那份**，§3.4 只是摘要。
> **⚪ 2026-09-11 待決策（時效性已解除）**：要不要改用 Let's Encrypt 公開憑證、把 RP ID 換成 `erp.miactw.com`——見 **§3.3c** 與 §11 對應列，計畫書 [`LETSENCRYPT-PUBLIC-CERT-PLAN.md`](LETSENCRYPT-PUBLIC-CERT-PLAN.md)。
> **2026-09-16 更新：原本的急迫性（「換 RP ID 會讓既有 Passkey 全部失效，現在只有 1～2 張是成本最低的時刻，越拖越貴」）已不再成立**——Passkey 功能本日起暫緩使用（§12 2026-09-16），沒有人在用，換 RP ID 的失效成本歸零。這件事現在可以純粹按憑證需求決定，不必再被 Passkey 的時效推著走。反過來說：**若日後要恢復 Passkey，順序應該是先把 RP ID 定案再開功能**，否則又會回到「開了之後不敢換」的局面。
>
> **2026-09-10 新增互補文件**：[`WEEKLY-AUDIT-2026-09-07_2026-09-10.md`](WEEKLY-AUDIT-2026-09-07_2026-09-10.md)——本週 82 個 commit 的逐模組拆解、異常時間軸（含每個異常的起點 commit 與根因檔案:行號）、12 項排查排程 checklist、已驗證缺陷清冊、未部署差異。**正式機出事時先看那份定位，再回來這裡看行為規格。**
>
> **§2/§7/§11/§13 已於 2026-09-01 依實際程式碼盤點（`db.py` CURRENT_VERSION=68、`git log` 最新 commit `8f40e4e`）補齊落後內容，§12 逐日 changelog 本身仍是最新的**（本文件是持續累積的活文件，不是單一時間點快照）；同日新增互補文件 `MOTRIX-ERP-ARCHITECTURE-MAP.md`（架構地圖＋建議＋踩坑索引）

---

## § 對照表（2026-09-23 拆分）

本檔只留 §0／§1 與維護規則；其餘章節依模組拆到 `docs/quick/`，**§ 編號不變**。程式註解寫「QUICK.md §N」時，查下表。

| § | 標題 | 位置 |
|---|---|---|
| §0 | 多機同步須知（每次工作階段開始必讀） | 本檔 |
| §1 | 啟動與位址 | 本檔 |
| §1.1 | 正式環境自動啟動與監控（2026-08-01） | 本檔 |
| §1.2 | 心跳監控（dead man's switch，2026-08-01） | 本檔 |
| §2 | 系統架構總覽 | [`docs/quick/architecture.md`](docs/quick/architecture.md) |
| §3 | 安全（2026-07-18 強化後） | [`docs/quick/security.md`](docs/quick/security.md) |
| §3.1 | 帳號與密碼 | [`docs/quick/security.md`](docs/quick/security.md) |
| §3.2 | 解鎖密碼（報價單解鎖編輯） | [`docs/quick/security.md`](docs/quick/security.md) |
| §3.3 | Session 與 API 保護 | [`docs/quick/security.md`](docs/quick/security.md) |
| §3.3b | TOTP 兩步驟驗證（自助啟用，DB v72，2026-09-07） | [`docs/quick/security.md`](docs/quick/security.md) |
| §3.3c | Passkey／WebAuthn 與 HTTPS 憑證（2026-09-11 起… | [`docs/quick/security.md`](docs/quick/security.md) |
| §3.4 | 角色與模組 | [`docs/quick/security.md`](docs/quick/security.md) |
| §3.5 | Demo 展示帳號（隔離空白資料庫） | [`docs/quick/security.md`](docs/quick/security.md) |
| §4 | 資料模型 | [`docs/quick/data-model.md`](docs/quick/data-model.md) |
| §4.1 | 主要資料表 | [`docs/quick/data-model.md`](docs/quick/data-model.md) |
| §4.2 | data_json 與熱路徑同步 | [`docs/quick/data-model.md`](docs/quick/data-model.md) |
| §4.3 | 樂觀鎖（併發保護） | [`docs/quick/data-model.md`](docs/quick/data-model.md) |
| §5 | 核心業務流程 | [`docs/quick/mod-quotation.md`](docs/quick/mod-quotation.md) |
| §5.1 | 報價狀態機 | [`docs/quick/mod-quotation.md`](docs/quick/mod-quotation.md) |
| §5.2 | 案件進度 dealTag | [`docs/quick/mod-quotation.md`](docs/quick/mod-quotation.md) |
| §5.2b | 報價清單動態徽章（quotations.html） | [`docs/quick/mod-quotation.md`](docs/quick/mod-quotation.md) |
| §5.2c | 報價單 PDF 匯出 | [`docs/quick/mod-quotation.md`](docs/quick/mod-quotation.md) |
| §5.3 | 簽核（tiers 並行層） | [`docs/quick/mod-quotation.md`](docs/quick/mod-quotation.md) |
| §5.4 | 案件管理 Tab 結構 | [`docs/quick/mod-case.md`](docs/quick/mod-case.md) |
| §5.4b | 動態 Tab（案件留言板） | [`docs/quick/mod-case.md`](docs/quick/mod-case.md) |
| §5.5 | 成本精算 settlement | [`docs/quick/mod-case.md`](docs/quick/mod-case.md) |
| §5.6 | 專案 | [`docs/quick/mod-case.md`](docs/quick/mod-case.md) |
| §5.7 | 承攬商派發狀態機 | [`docs/quick/mod-contractor.md`](docs/quick/mod-contractor.md) |
| §5.8 | 出貨單（案件管理子項目，2026-08-01） | [`docs/quick/mod-shipping.md`](docs/quick/mod-shipping.md) |
| §5.9 | 承攬商匯款申請／發票開立簽核單（2026-08-20） | [`docs/quick/mod-contractor.md`](docs/quick/mod-contractor.md) |
| §5.10 | 額外支出改版（2026-09-11 交辦，**已完成並上線**） | [`docs/quick/mod-case.md`](docs/quick/mod-case.md) |
| §5.11 | 執行進度勾選 → 兩張行事曆（2026-09-11 交辦，DB v76） | [`docs/quick/mod-case.md`](docs/quick/mod-case.md) |
| §5.12 | 收款資料異常：「已收款」與「收款日期」是兩個欄位（2026-09-11） | [`docs/quick/mod-case.md`](docs/quick/mod-case.md) |
| §5.13 | 完工單（2026-09-12 交辦，DB v77） | [`docs/quick/mod-case.md`](docs/quick/mod-case.md) |
| §6 | Sidebar 結構 | [`docs/quick/architecture.md`](docs/quick/architecture.md) |
| §7 | API 速查（base `/api`） | [`docs/quick/api-core.md`](docs/quick/api-core.md) |
| §7.1 | Auth / Users | [`docs/quick/api-core.md`](docs/quick/api-core.md) |
| §7.2 | 報價 / 簽核 / 精算 | [`docs/quick/mod-quotation.md`](docs/quick/mod-quotation.md) |
| §7.3 | 主檔 / 專案 / 報表 / 系統 | [`docs/quick/api-core.md`](docs/quick/api-core.md) |
| §7.5 | 業務開發 CRM（DB v27；連結報價單審核制 DB v42，見 §12 20… | [`docs/quick/mod-crm.md`](docs/quick/mod-crm.md) |
| §7.4 | 承攬商管理（DB v22–v25） | [`docs/quick/mod-contractor.md`](docs/quick/mod-contractor.md) |
| §7.6 | 場域選型導覽（DB v30） | [`docs/quick/mod-selection-guides.md`](docs/quick/mod-selection-guides.md) |
| §7.7 | 網路架構選型導覽（DB v31） | [`docs/quick/mod-selection-guides.md`](docs/quick/mod-selection-guides.md) |
| §7.8 | 出貨單（DB v34） | [`docs/quick/mod-shipping.md`](docs/quick/mod-shipping.md) |
| §7.9 | 監控系統選型導覽（DB v39） | [`docs/quick/mod-selection-guides.md`](docs/quick/mod-selection-guides.md) |
| §7.10 | 門禁系統選型導覽（DB v40） | [`docs/quick/mod-selection-guides.md`](docs/quick/mod-selection-guides.md) |
| §7.11 | 承攬商匯款申請／發票開立簽核單（DB v45/v46，見 §5.9，2026-0… | [`docs/quick/mod-contractor.md`](docs/quick/mod-contractor.md) |
| §7.12 | 網路架構規劃書（DB v64，2026-08-26，見 §5 補充／`NETWO… | [`docs/quick/mod-selection-guides.md`](docs/quick/mod-selection-guides.md) |
| §7.13 | 簽核代理人（DB v67，2026-08-28） | [`docs/quick/mod-quotation.md`](docs/quick/mod-quotation.md) |
| §7.14 | 自動化系統選型導覽（DB v65，2026-08-26 起，選型資料庫第七類） | [`docs/quick/mod-selection-guides.md`](docs/quick/mod-selection-guides.md) |
| §7.15 | 個人化清單偏好（DB v56） | [`docs/quick/api-core.md`](docs/quick/api-core.md) |
| §7.16 | 案件代辦事項 / 出納彙總視圖 | [`docs/quick/mod-case.md`](docs/quick/mod-case.md) |
| §7.17 | T100（鼎新）傳票批次匯出（2026-09-01，DB v69，見 §12 同… | [`docs/quick/mod-case.md`](docs/quick/mod-case.md) |
| §7.18 | 進貨批次供應商/發票/付款狀態（DB v70，2026-09-01） | [`docs/quick/mod-inventory.md`](docs/quick/mod-inventory.md) |
| §7.19 | 採購建議（2026-09-07，架構地圖 §6.6） | [`docs/quick/mod-inventory.md`](docs/quick/mod-inventory.md) |
| §7.20 | 叫料（材料訂購）（後端 2026-09-10、前端 2026-09-11，DB … | [`docs/quick/mod-inventory.md`](docs/quick/mod-inventory.md) |
| §7.21 | 單據存檔版本與編輯紀錄（2026-09-14，DB 無異動） | [`docs/quick/api-core.md`](docs/quick/api-core.md) |
| §8 | 備份與還原 | [`docs/quick/ops-backup.md`](docs/quick/ops-backup.md) |
| §8.0 | 雲端備份目標可插拔（2026-09-07，架構地圖 §6.4） | [`docs/quick/ops-backup.md`](docs/quick/ops-backup.md) |
| §8.1 | 路徑 | [`docs/quick/ops-backup.md`](docs/quick/ops-backup.md) |
| §8.1b | 存檔所有權標記（2026-09-14） | [`docs/quick/ops-backup.md`](docs/quick/ops-backup.md) |
| §8.2 | 排程架構（雙層） | [`docs/quick/ops-backup.md`](docs/quick/ops-backup.md) |
| §8.3 | 行為 | [`docs/quick/ops-backup.md`](docs/quick/ops-backup.md) |
| §9 | 前端規範 | [`docs/quick/architecture.md`](docs/quick/architecture.md) |
| §10 | 成本公式（報價） | [`docs/quick/mod-quotation.md`](docs/quick/mod-quotation.md) |
| §11 | 已知限制與後續建議 | [`docs/quick/known-limits.md`](docs/quick/known-limits.md) |
| §12 | 變更摘要（最新兩版） | [`docs/quick/changelog.md`](docs/quick/changelog.md) |
| §12（舊） | 2026-09-06～09-13 條目 | [`docs/quick/changelog-2026-09-06_13.md`](docs/quick/changelog-2026-09-06_13.md) |
| §13 | 目錄結構（精簡，2026-09-01 依實際程式碼盤點更正） | [`docs/quick/architecture.md`](docs/quick/architecture.md) |
| §14 | 跨機核對與拉檔流程 | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §14.1 | 核對優先順序 | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §14.2 | 從正式機拉檔案回來的具體步驟 | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §14.3 | 之後才考慮的方向 | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §14.3b | WinRM 網路直連設定（2026-09-08） | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §14.3c | 本機部署儀表板（2026-09-08） | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §14.3d | 兩邊同時有人／有 AI session 在動時的交接協定（2026-09-10） | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §14.3e | 正式機漂移檢查（`check_prod_drift.ps1`，2026-09-1… | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §14.4 | 選型資料庫雙機內容核對（API 版，2026-08-10） | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §15 | 更新模式（測試機 → 正式機，半自動，2026-08-01） | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §15.1 | 兩支腳本 | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §15.2 | 打包（開發機） | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §15.3 | 套用（正式機） | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §15.3b | 正式機輔助工具的分工（2026-09-08 新增） | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |
| §15.4 | 已知限制 | [`docs/quick/ops-deploy.md`](docs/quick/ops-deploy.md) |

---

## §0 · 多機同步須知（每次工作階段開始必讀）

本專案有兩台實體機器，**目前完全靠人工複製檔案同步，沒有任何自動化機制**，過去已多次發生「正式機做了什麼，開發機這裡不知道」的落差（見下方已知落差紀錄）。每次在此專案開始工作時，**先依路徑判斷目前是哪一台機器並明確告知使用者**（例如「目前偵測到是開發機／hichan 帳號」），不要默默假設。

| 項目 | 開發／備份機（多數時候是這台） | 正式機 |
|------|------|------|
| 帳號 | `hichan` | `Motrix`（AutoAdminLogon，開機自動登入） |
| 專案路徑 | `C:\Users\hichan\Desktop\MOTRIX-ERP` | `C:\Users\Motrix\Desktop\V9.0` |
| 用途 | 開發、測試、備份 db 存放處 | 客戶實際在用 |
| 排程工作 | 無 | `MOTRIX ERP Server Autostart` / `Daily Backup` / `Heartbeat` 三個 Windows 工作排程器（見 §1.1／§1.2） |

**若判斷目前是正式機**：改用更保守的操作方式——**不啟動測試用 server、不寫入測試資料、不做實驗性操作**；任何資料庫/程式碼變更都要假設影響真實客戶資料，修改前務必先跟使用者確認。（本文件開發機章節中提到的「用瀏覽器實測」「建立測試出貨單」等做法，都是在開發機上做的，正式機不可比照辦理。）

**已知落差紀錄**（每次跨機核對後於此累積更新，核對流程見 §14）：

| 日期 | 落差內容 | 狀態 |
|------|---------|------|
| 2026-08-01 | `backend/db.py` 少了正式機已在跑的 2 個 migration（v32/v33，交換器選型導覽 switch_guide 表結構） | ✅ 已補回（用正式機 db 實際 schema 反推重建，見 §12 2026-08-01e） |
| 2026-08-01 | `backend/setup_autostart_task.ps1`、`backend/setup_heartbeat_task.ps1` 兩個部署排程設定腳本，正式機有（§1.1／§1.2 有描述其行為）、這台開發機完全沒有檔案 | ✅ 2026-08-08 已解決——透過 RDP 連上正式機，原始檔案改名 `.orig` 保留後貼回內容逐行 diff 校正一致（差異細節見 `DR-SOP.md` §3 第 1 點），已 commit 進 git 並隨這次更新包一併部署 |
| 2026-08-01 | 已知程式碼未 commit 進 git（`git log` 停在較舊的提交，工作區有大量未 commit 變更）；正式機的程式碼版本與 git 歷史的對應關係目前不明 | ✅ 已於合併正式機更新模式匯出檔案時一併 commit（見 §12 2026-08-01j）；正式機仍無 git，日後版本比對仍需靠 §15 `deploy_manifest.json` 記的 commit 值 |
| 2026-08-05 | 本文件與程式碼（`main.py` CORS 白名單／`email_notify.py` 與 `system.py` 的 email base_url 預設值／`notification-settings.html` 預設值）長期記載正式機區網位址為 `172.16.11.211:666`，實際上是 `172.16.10.177:666`（使用者於本次對話中指正並確認為固定 IP，非 DHCP 動態配發；已用 `curl` 實測連線成功） | ✅ 本次一併修正上述 5 處程式碼與 §1 位址表 |
| 2026-09-10 14:28 | **兩邊同時有 Claude session 在動同一個功能（WebAuthn）**：開發機這邊已打包好 `20260910_142806_625b0d6`（內含 `routers/system.py` 的 WebAuthn 設定端點改動）正要部署，使用者即時告知「正式機 Claude 正在跑 webauthn」才停手。若已套用，會直接覆蓋正式機上那個 session 正在改的檔案並重啟服務。**部署包已保留未套用**，等兩邊協調後再處理。正式機當下 `/api/system/webauthn-config-status` 仍是 `configured:false`，代表對方尚未成功寫入設定 | 🟡 **事實上已被覆蓋，但從未查證**——2026-09-10 21:49~2026-09-11 00:59 正式機又從本 repo 連續套用四輪（`37bd985`→`0da86bf`→`4ffe190`→`34e0ce1`，每輪修 Passkey 路上的一個坑，見 §3.3c）。**正式機那個 session 到底改了哪些檔案、有沒有進 git，始終沒有人去確認**；若它有未進 git 的改動，已隨這四輪 `apply_update.ps1` Step 3 一併覆蓋掉。保留未套用的 `20260910_142806_625b0d6` 部署包已無意義（內容早被後續版本涵蓋），可刪。**這正是 §14.3d 交接協定（`AGENT-HANDOFF-TEMPLATE.md`）要防的情境——當時兩邊都沒留交接檔** |
| 2026-09-11 | **正式機的 `system_settings` 有兩個關鍵值不在 git 裡**：`webauthn_rp_id`=`motrix.internal`／`webauthn_origin`=`https://motrix.internal:666`（2026-09-11 由 superadmin 於 `company-profile-settings.html` 填入）。重建環境或還原舊 db 時這兩個值會整個消失，Passkey 端點會回到 503 而看起來像壞掉 | 🟢 已記錄於此（§14 第 4 項本來就提醒過這類設定不在 git）；另**「系統網址」設定是否已改成 `https://motrix.internal:666` 仍未確認**（通知信連結讀的是它），見 `PASSKEY-CA-ROLLOUT.md` 第 8 步 |
| 2026-08-20 | 開發機當時無法連線，承攬商匯款申請／發票開立簽核單功能（DB v45/v46，見 §12）直接在正式機開發，開發機完全沒有這批程式碼 | ✅ 2026-08-23 已回推：`verify_manifest.py` 核對 43/43 相符、開發機本機啟動 server 驗證 `/api/ping`＋schema_version=52 正常後 `git commit`（累計至第 42 輪 2026-08-23q，DB 已到 v52，非僅 v45/v46） |

---

## §1 · 啟動與位址

| 項目 | 值 |
|------|-----|
| 開發啟動 | `backend\start.bat` |
| 更新後重啟 | `backend\restart.bat` |
| 本機 | http://localhost:666 |
| 區網（IP） | **https://172.16.10.177:666**（2026-09-10 起正式機已是 HTTPS，見 §3.3c；憑證 SAN 含此 IP，但**瀏覽器仍會警告簽發者不受信任**，除非該台裝了 mkcert 根 CA） |
| 區網（網域） | **https://motrix.internal:666** ← **Passkey 只在這個位址能用**（RP ID 綁的是它）；前提是該台①裝了 mkcert 根 CA ②解析得到 `motrix.internal` |
| SQLite | `backend\motrix_erp.db`（WAL 模式） |

> ⏳ **這張表的網域欄位有可能整批改掉**：`LETSENCRYPT-PUBLIC-CERT-PLAN.md` 若採用，全站改走
> `https://erp.miactw.com:666`，上面兩個 https 位址都會變成「憑證主機名不符」。決策點見 §11 與 §3.3c。

```
依賴關係：
  db.py ← helpers/ ← archive.py / pdf_gen.py / photos.py
                   ← routers/*.py ← main.py（wiring only）
```

### §1.1 · 正式環境自動啟動與監控（2026-08-01）

正式機（`Motrix` 帳號，AutoAdminLogon 開機自動登入）以三個 Windows 排程工作維持常駐：

| 排程工作 | 觸發 | 動作 | 說明 |
|---------|------|------|------|
| `MOTRIX ERP Server Autostart` | 登入時 +90 秒延遲 | `autostart_hidden.vbs` → `backend\autostart.bat` | 90 秒延遲避開 GoogleDriveFS（同樣登入時啟動）掛載 H: 的搶跑窗口；`autostart.bat` 內建 **crash-restart 迴圈**（uvicorn 意外中止 5 秒後自動重啟，寫入 `logs\server.log`） |
| `MOTRIX ERP Daily Backup` | 每日 02:00 | `backup_job.py` | 見 §8.2 |
| `MOTRIX ERP Heartbeat` | 註冊後立即開始，每 5 分鐘重複（不綁登入） | `heartbeat_job.py` | 見 §1.2 |

`autostart.bat` 開頭 `chcp 65001` + `set PYTHONUTF8=1`：避免中文訊息寫入 log 時因主控台預設編碼（Big5/cp950）產生亂碼。**`.bat`/`.ps1` 檔若含中文註解務必存成 CRLF 換行**——LF-only 換行曾在此機器上讓 cmd.exe 的批次檔解析器直接報「命令語法不正確」而整個腳本失效（且不會有任何 log 紀錄，外觀上排程工作仍顯示執行成功）。

**`.ps1` 檔含中文註解務必存成帶 UTF-8 BOM**（2026-08-08 重建 `setup_autostart_task.ps1`/`setup_heartbeat_task.ps1` 時發現）：Windows PowerShell 5.1（`powershell.exe`，非 pwsh 7）靠檔案開頭 BOM 判斷編碼，沒有 BOM 就會 fallback 到系統非 Unicode 程式的預設編碼（這台機器是 Shift-JIS/932，其他機器可能是 Big5/950），把中文位元組解讀錯誤，導致腳本結構被打亂——實測中 `Write-Error` 呼叫本身被解析錯誤成參數綁定例外，而且是**非終止型錯誤**，腳本會直接跳過「只能在正式機執行」的身分守門判斷式繼續往下執行，`exit 1` 完全沒被執行到。已確認 `backend/tools/apply_update.ps1`、`backend/tools/build_deploy_package.ps1` 本來就有 BOM（沒事）；`setup_backup_task.ps1`/`setup_autostart_task.ps1`/`setup_heartbeat_task.ps1` 原本沒有，已於同日修正。**日後新增或編輯任何含中文的 `.ps1` 檔，務必確認存檔帶 UTF-8 BOM**（PowerShell `Set-Content -Encoding UTF8` 在 Windows PowerShell 5.1 預設就會帶 BOM；純文字編輯器要另外注意）。

手動重啟（`restart.bat`）會一併殺掉 autostart 的 crash-restart 迴圈（比對 commandline 含 `autostart.bat`/`autostart_hidden.vbs`），避免迴圈在手動重啟的同時把 port 666 搶回去。

### §1.2 · 心跳監控（dead man's switch，2026-08-01）

`backend/heartbeat_job.py`（獨立腳本，不 import app，ERP 服務掛了也照樣執行）：

```
每 5 分鐘：
  GET http://127.0.0.1:666/api/ping
    成功 → 讀 heartbeat_config.json 的 ping_url → GET 該網址（打卡）
    失敗 → GET {ping_url}/fail（立即通知，不等逾時）；不執行打卡
```

打卡對象為 [healthchecks.io](https://healthchecks.io)（Period 10 分鐘／Grace 10 分鐘），由該服務判斷逾時（本機或整台主機斷線都會使打卡中斷）並寄信通知 superadmin 信箱。`heartbeat_config.json` 的 `ping_url` 為空時，腳本只做本機健康檢查、略過對外打卡（不會報錯）。日誌：`logs/heartbeat_job.log`。

**新增功能規則**

- API → 對應 `routers/xxx.py`，勿塞進 `main.py`
- 共用邏輯 → `helpers/`（拆 6 個子模組）
- 表結構 → `db.py:init_db()` + `_mNNN_xxx()` migration
- 備份 → `archive.py`（所有 JSON 寫入須用 `_atomic_json_write()`）
- PDF → `pdf_gen.py`；照片水印 → `photos.py`（PIL 可選）

---

---

## 維護規則（每次修改必讀）

### 溝通與撰寫風格（2026-09-15 使用者指示，最高優先）

**專業、簡短、以最佳建議為導向。減少過多解釋、過多備註。**

- 回覆先給結論與建議，不要鋪陳推理過程；要說明時一句到位
- 不逐步報告做了什麼，除非影響使用者的決策
- 有多個選項時直接給推薦做法，不列完所有可能
- 程式碼註解只留「為什麼」與踩過的坑，不寫敘述性長文
- 文件條目同樣從簡：結論、取捨、風險，三項為主

### 版本紀錄登記（強制）

**每次功能變更完成後，必須同步更新以下兩處：**

1. **`backend/version_manifest.json`** — 新增一筆條目，格式如下：

   ```json
   {
     "module": "模組中文名",
     "version": "YYYY-MM-DDx",
     "date": "YYYY-MM-DD",
     "time": "HH:MM",
     "content": "簡要說明（繁中，60–120 字）"
   }
   ```

   | 欄位 | 說明 |
   |------|------|
   | `module` | 對應系統模組（報價單 / 案件管理 / 使用者管理 / 系統設定 / 系統安全 / 前端介面 / …） |
   | `version` | 日期 + 小寫後綴字母（同日第二筆加 `a`，第三筆加 `b`，依序遞增） |
   | `date` | `YYYY-MM-DD` |
   | `time` | **實際完成修改的時間**，24h 制 `HH:MM`（不可省略） |
   | `content` | 說明做了什麼，不要只寫「更新」，要寫具體改動 |

2. **`docs/quick/changelog.md`（原 §12）** — 在最上方加入摘要行。檔案超過 200KB 時，把最舊的整日條目搬到新的 `changelog-<起>_<迄>.md` 封存檔（單檔讀取上限 256KB）。

> **⚠️ 伺服器重啟後**，`_sync_module_versions()` 自動將 manifest 條目同步至 DB `module_versions` 表（UPDATE 邏輯同步修改過的欄位，不影響使用者手動新增的條目）。若修改了已存在條目的 `time` 或 `content`，下次重啟即生效。**DB v35 起 `(module, version)` 已有 UNIQUE 限制**，`INSERT OR IGNORE` 才真正名副其實——v35 之前這個限制不存在，代表每次重啟都會把整份 manifest 重複插入一次，長期下來會讓 `module_versions` 表無限增生（正式機曾實測膨脹到 626,725 列僅 143 種組合，佔掉每日備份 300+MB 中的絕大部分），已修復並清理。

### 跨層一致性稽核（2026-09-14）

**`backend/tests/test_system_audit_2026_09_14.py`** —— 跟著每次 pytest 跑，
不驗證任何功能「做得對不對」，只驗證**跨層的對應關係有沒有漂掉**。
這類缺陷的共同特徵是「每一邊單獨看都正確、合起來才是錯的」，逐功能的測試照不到。

| 守什麼 | 漂掉的症狀 |
|--------|-----------|
| 每張資料表都要明確決定要不要進每日 JSON 匯出 | 平常沒事；要用 §8.3 的最後手段還原時，才發現那張表從來沒被匯出過 |
| 每一條匯出查詢都要真的跑得起來 | 表存在、語法正確，執行時才炸（`ORDER BY id` 但那張表沒有 id）；失敗被 try/except 吞掉，備份頁面照樣綠燈 |
| 單張表失敗不可以還是報 `backup.daily_ok` | 「備份看起來有在跑」型事故：綠燈跑了好幾個月，要還原才發現那張表每天都是空的 |
| 使用者匯出不可以夾帶憑證欄位 | `totp_secret` 被抄進人看得懂的 JSON，備份資料夾變成可直接使用的認證素材 |
| 任何一張表的匯出都不可以夾帶祕密欄位／設定值 | 同上，但發生在下一張新表或下一個新設定上；`system_settings` 的祕密藏在 `value_json` 裡，只看欄位名掃不到 |
| 匯出裡不可以有 base64 內嵌影像 | 身分證與存摺掃描件每天被複製一份到雲端備份資料夾 |
| 每支路由都要呼叫守門函式（16 支公開端點列成白名單） | 端點上線、測試全綠，因為沒有人針對「它應該要擋」寫題 |
| DELETE 端點要檢查角色或擁有者，不能只有「有登入就好」 | 任何登入者都刪得掉別人的東西，而且不可復原 |
| 程式與資料庫裡的角色字串都必須是已知角色 | `role == 'superadmn'` 這種拼錯不會報錯，只會讓那道檢查**永遠不成立** |
| 組織階層外鍵（users→departments→divisions、部門主管） | 部門篩選讓人默默消失、主管簽核找不到人，而不是報錯 |

模組串接**不在這支裡**——`test_module_keys_consistency_2026_09_13.py` 已經完整
覆蓋，而且比臨時寫的更周全（它還守著「擋錯人」：某模組的頁面呼叫到不接受該模組
的 API，畫面一片 403 而後端測試全綠，因為測試多半用 admin 帳號、admin 直通）。

**白名單的意義是讓下一個新增項目變紅，不是讓測試變綠。** 看到紅燈時該做的是判斷
「這個新項目應該進清單，還是應該修程式」。

**寫這支測試當下抓到的兩件事**：

1. `DELETE /api/shipping-notes/{no}/signed-files/{id}` 與完工單的同名端點，
   在此之前**只有 `_require_user()`**——任何登入者都能刪掉任何單據的回簽附件，
   而且會連實體檔案一起移除。已補 admin+（與同日新增的動態附件同一個標準）。
2. 每日 JSON 匯出只涵蓋 **8/76** 張表——§8.3 的最後手段重建不出 `users`／
   `system_settings`／`payslips`／業務開發／三種憑證流。先用一支
   `xfail(strict=True)` 把落差變成會被追蹤的東西，**同一輪內補完了**：
   現在 41 張，xfail 照約定拿掉。補的過程又掃出兩件事：`stock_batches`
   的 `ORDER BY id` 執行時才會炸（表存在、語法正確，前兩題都是綠的），
   以及單張表失敗時 `_daily_backup()` 照樣報 `backup.daily_ok`。兩件都已修，
   並各自補上會紅的測試（含正向控制）。詳見 §12 第十輪第四節。

> **這支測試自己也差點犯同一類錯**：初稿寫死守門函式名稱去掃，誤報 5 支 T100 端點
> （它們有自己的 `_require_t100_admin`）；又誤判 `financial_view`／
> `project_approve_eng` 沒有後端檢查（前者有專屬 helper、後者寫成 `'x' in modules`）；
> 還一度斷言 `_SUPERADMIN_MODULES` 應該等於 `allModules` 並照著去「修」
> `helpers/auth.py`，**打破了既有測試守著的真正不變量**（那份樣板要等於前端的
> superadmin 角色樣板），改動已還原。
> 教訓：**動手改之前先確認有沒有既有測試在守同一件事**，既有的那份通常比臨時
> 想出來的斷言更清楚為什麼要這樣。

### 其他維護提醒

- 功能變更時先更新「對應 §N 章節」所在的 `docs/quick/*.md`（查本檔 § 對照表），再在 `docs/quick/changelog.md` 加摘要。新增 § 時同步補對照表。
- 死碼警告欄位如有整理（移除 .js、改用 include），記得更新 §2 與 §13。
- **新增任何 `import` 第三方套件時，記得同步補進 `backend/requirements.txt`**（2026-09-07 複查發現 `openpyxl`／`Pillow` 這兩個核心功能會直接用到的套件，先前完全沒被記載——`routers/contractors.py` 對 `PIL` 是模組頂層 unconditional import，若一台全新機器照抄 `requirements.txt` 裝環境，裝完直接啟動會在 import 這個 router 時整台伺服器起不來）；只有測試/工具腳本用到、伺服器本身不會 import 的套件（如 `tools/local_research_pipeline.py` 用的 `beautifulsoup4`/`requests`）放進 `backend/requirements-dev.txt` 即可。想確認目前有沒有已知安全弱點，跑 `python backend/tools/check_dependencies.py`（需要先 `pip install pip-audit`，見該腳本 docstring；非排程工具，建議升級套件版本或每季手動跑一次）。
