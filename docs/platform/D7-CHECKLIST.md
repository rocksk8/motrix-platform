# D7 正式轉移升級演練 · 檢核清單

> 2026-09-26 11:20 D 起草（主持派工）。依據：RUN-PLAN §3（D7 定義）、UPGRADE-RUNBOOK、`tools/platform/final_drill.py`、`tools/platform/upgrade_drill.py`、`tools/platform/product_select.py`、`tools/platform/product_drill.py`、`backend/tools/build_deploy_package.ps1`、`backend/tools/verify_package.py`。
> 前哨演練紀錄：第 5 次（03:08，C，約 224 秒）、第 6 次（11:14，D，約 103 秒，RUN-PLAN §6）。兩次都是 **11 步全過**，新版程式都是 `git archive`，**不是部署包**。
> 本清單管的是**正式 D7**：新版程式必須是使用者實際會部署的那一份部署包。

## 0. 不可違反的前提

| # | 前提 | 怎麼確認 |
|---|---|---|
| P1 | 只用開發機資料（U3）；**絕不連正式機**、不讀 G: | 演練指令裡沒有正式機主機名稱或 G: 路徑；`final_drill.py` 開頭的安全段落 |
| P2 | V9 開發目錄 `C:\Users\hichan\Desktop\MOTRIX-ERP` **只讀** | 見 §6「V9 未被動到的證據」 |
| P3 | 演練路徑不含 `V9.0`（V9 以安裝路徑判斷正式機，會真的寄信） | `final_drill.py` 已擋；報告寫出演練根目錄 |
| P4 | 所有啟動都帶 SAFE_ENV（不跑排程、不上雲、不寄信），放 `.no_email_send`、`.no_cloud_archive` | 報告第 2 步列出標記檔 |
| P5 | **建包是使用者的動作**；用哪一種方式建，由主持判斷。稽核者、各線不代打包 | 報告寫明「包由誰、在哪個 commit、用哪個指令建」 |
| P6 | 低優先權；不與列車全量搶測試鎖（全機最多 2 組全量，PLAYBOOK §C-13） | 起跑前查鎖檔；報告記開始與結束時間 |
| P7 | 演練完只刪自己建的暫存樹與備份；**磁碟根下一層的目錄刪除需要人工核准**（第 6 次實際被擋），留給使用者 | 報告列出「留下待人工刪除的路徑」 |

## 1. 部署包：怎麼建、怎麼驗

### 1-1 建包（使用者執行）

```powershell
# 在乾淨的 platform 工作樹（git status 乾淨），選定要驗的 commit
powershell -ExecutionPolicy Bypass -File backend\tools\build_deploy_package.ps1 -Product full   [-OutDir <目錄>]
```

- 模組選配的包，照 §3 的矩陣各建一份：`-Product full`、`-Product core-only`，以及各單一模組的產品設定檔（`product/<名稱>.json`，`"modules": ["<key>"]`）。
- 建包腳本會做的事（**確認它們真的有發生，不要假設**）：git 狀態乾淨、`.ps1` 語法檢查、版本紀錄兩方向守門、規格覆蓋守門、全量（或同一份 tree 12 小時內已全綠）、`git archive` 匯出、`.build_commit`、產品選配與 `modules.lock.json`、`deploy_manifest.json`（commit、branch、built_at、耗時、題數）。

### 1-2 驗包（每一份包都做，紀錄寫進報告）

| # | 檢查 | 指令／方法 | 過關條件 |
|---|---|---|---|
| V1 | 驗包工具 | `python backend\tools\verify_package.py <包目錄> --expect-db-version <N>` | exit 0；**正對照（工作樹先命中）有過**，否則整份報告作廢 |
| V2 | 選配與 lock | `python tools\platform\product_select.py check --pkg <包目錄>` | exit 0：lock 存在；列出的模組等於包內模組資料夾；版本等於各自的 module.json；內容雜湊一致；L0／L1 必要檔不缺；`tools/platform/upgrade.py` 在包裡 |
| V3 | **檔數**：包 vs 應有 | 應有＝`git ls-tree -r --name-only <commit>` 扣掉 `export-ignore`（`git check-attr export-ignore`），再扣掉沒選到的模組資料夾與 `removed_pages`；包＝包目錄逐檔列舉 | 兩份清單**逐檔相等**（只比數量不夠：數量一樣也可能是互相抵消）。差異逐一列出 |
| V4 | **runtime 不缺檔**（主持 2026-09-26：export-ignore 會靜默漏檔，已知漏 tests/、docs/windows/，runtime 沒驗證過） | ①在包裡跑 `core.source_tree.product_files()／page_files()／router_files()`，每一個檔都在；②新版在包目錄啟動後，`sys.modules` 裡所有來自包目錄的模組，其檔案都在包裡；③`grep` 產品碼中讀取相對路徑的地方（`open(`、`Path(...)/`、`read_text`）所指的資料檔在包裡 | 三項都沒有缺檔。任何一個被 export-ignore 的路徑出現在①②③ ⇒ **必修** |
| V5 | 雜湊 | 包內每一檔 sha256 清單存成 `package-sha256.txt`；`deploy_manifest.json` 的 commit 等於 `.build_commit` 等於要驗的 commit | 三者一致；雜湊清單附在報告 |
| V6 | modules.lock | `lock_version`、`kind=full_package`、`product`、`core_version` 等於包內 `core/registry.CORE_VERSION`；每個模組的 `sha256` 由 V2 驗過 | 一致 |
| V7 | 不該進包的沒進 | `backend/tests/**`、`backend/conftest.py`、`backend/modules/*/tests/**`、`docs/windows/**`、`.initial_*credentials*.txt`、`*.db` | 包內 0 個（V1 會驗一部分；這裡列成獨立項） |

## 2. 演練環境

| 項目 | 設定 |
|---|---|
| 來源 | `C:\Users\hichan\Desktop\MOTRIX-ERP`（V9 開發目錄，只讀） |
| 演練根目錄 | `D:\MOTRIX-FINAL-DRILL`（RUN-PLAN §3 指定；`source-backup` 保留到使用者回來，§3-7）。前哨用自己的目錄（例如 `D:\MOTRIX-FINAL-DRILL-D6`），不動正式那一份 |
| 工具 | `python tools\platform\final_drill.py --package <包目錄> --drill-root D:\MOTRIX-FINAL-DRILL --report docs\platform\FINAL-DRILL-REPORT.md` |
| Python | `D:\MOTRIX-PLATFORM\.venv312`（只用，不改） |
| 優先權 | BelowNormal（子行程繼承）；不跑 pytest |
| 時間預估 | 前哨約 100～230 秒／份包；矩陣 §3 共 N 份 ⇒ 預估 N×4 分鐘；死線＝預估×1.5（MEMORY〈長時間沒有輸出的動作要有死線〉） |

## 3. 11 步 × 模組選配矩陣

`final_drill.py` 的 11 步：1 備份來源 → 2 建演練安裝目錄 → 3 取新版程式（**`--package`**）→ 4a 預檢 → 4b 備份＋試還原 → 4c 轉換 → 4d 驗證（新版啟動） → 5 冒煙 → 6a 完整回滾 → 6b 再轉換 → 6c 只回程式。

| 選配 | 包 | 11 步 | 另外要驗 |
|---|---|---|---|
| 完整產品 | `-Product full` | 全部 | 冒煙打每個模組宣告的 probes，都要 200（§4） |
| 只有核心 | `-Product core-only` | 全部 | 被排除的每個模組：probes 回 404、`removed_pages` 回 404；首頁、出納、報表等 L1 頁面在模組缺席時「明說」，不回 500、不寫「0 筆／沒有」（各 IP 的缺席說明） |
| 各單一模組 | `product/<key>-only.json`，對每個 L2 模組各一份 | 至少 1～4c＋5 | 那個模組的 probes 200；其他模組的 probes 404；它依賴的 IP（例如 M04 需要 case.access）在對方缺席時明說 |

- 單一模組各跑完整 11 步太貴時，至少跑 1～4c＋5（轉換＋冒煙）；完整產品與只有核心兩份一定要跑完 11 步。
- `product_drill.py --pkg <包>` 是空庫的選配演練；`final_drill.py` 是 V9 真實資料的轉換演練。兩者都要。

## 4. 冒煙清單：改讀各模組宣告的 probes

- 目前 `final_drill.SMOKE` 是寫死的 15 項，其中「獎金」「出納」「營運報表」等已搬進 M07、M05、M08。完整產品時照舊會過；**只有核心**時這幾項必然 404，而工具會把它判成失敗。
- 正式 D7 之前要改成：
  - **L1 冒煙**：只列 L1 的頁面與 API（首頁、登入、模組管理、版本、自訂模組等），任何選配都要 200。
  - **模組冒煙**：讀包內每個 `backend/modules/<key>/module.json` 的 `provides.probes`（b-m08-2 起的格式；主持在 b-m08-2 合回後補 tender_radar，daily_tasks、netplan 由擁有者補）。依 `modules.lock.json`：列了的要 200，沒列的要 404。
  - 沒宣告 probes 的模組列在報告的 `undeclared_probes`，並且在 D7 之前補齊，**不可以帶著未宣告的模組進正式 D7**。
- 這項改動屬於 `final_drill.py` 的擁有者（C），或由主持指派；它要有題：完整產品、只有核心、單一模組三種 lock 各自產生正確的冒煙清單。

## 5. 回滾兩種

| 步 | 做法 | 過關條件 |
|---|---|---|
| 6a 完整回滾 | 用**第一份**升級備份還原程式與資料 | 與 `source-backup` 的**邏輯內容**相等（`logical_digest`，不是檔案雜湊：Online Backup 會重寫頁面）；V9 啟動 ping 200 |
| 6b 再轉換 | 同 4c | 同 4c＋4d |
| 6c 只回程式 | 只還原程式，資料保留在新版結構 | V9 啟動 ping 200；報告寫明「只回程式」後，V9 讀新版結構的資料有哪些已知限制（UPGRADE-RUNBOOK） |

每一種選配（§3）都要做 6a；6c 至少在完整產品與只有核心各做一次。

## 6. V9 未被動到的證據（每一次都要附）

| # | 證據 | 方法 |
|---|---|---|
| E1 | 來源庫的修改時間都早於演練開始 | 對每個 `*.db` 讀 mtime，與報告的開始時間比較 |
| E2 | 來源沒有 `-wal`／`-shm` 在演練期間產生 | 列出並比對時間 |
| E3 | `source-backup` 的雜湊等於第 1 步的紀錄 | ⚠ 第 1 步記的是**備份複本**的雜湊，**不能**拿來源檔去比（第 6 次前哨 D 犯過：Online Backup 會重寫頁面，來源檔雜湊本來就不同） |
| E4 | 來源目錄的檔案清單（路徑＋大小＋mtime）演練前後相同 | 演練前後各列一次，逐行比 |

## 7. 報告格式（`docs/platform/FINAL-DRILL-REPORT.md`）

1. 標頭：產生時間（由程式產生，不手打）、執行者、包的來源（誰建、commit、指令、`deploy_manifest.json` 摘要）、演練根目錄、來源目錄（只讀）。
2. 驗包：§1-2 的 V1～V7，逐項結果與證據（檔數差異清單、雜湊清單的檔名）。
3. 矩陣：§3 每一份包一節，每節列 11 步：步名、結果、耗時（秒）、關鍵數據（冒煙逐項狀態碼、`logical_equal_to_source`、V9 ping）。
4. V9 未被動到：§6 的 E1～E4。
5. 發現：分必修／建議／觀察，比照 AUDIT 檔格式；每一項寫發現的步、證據、處置。
6. 清理：刪了什麼；**留下待人工刪除的路徑**；確認沒有殘留行程。
7. 總判定：通過或未通過，以及未通過的項目。

## 8. 排程

| 次序 | 時機 | 內容 |
|---|---|---|
| 前哨第 6 次 | ✅ 2026-09-26 11:14（D） | `git archive origin/platform` 003151f3；11 步全過、約 103 秒 |
| **前哨第 7 次** | **M04、M07、M08 都合回之後** | 仍可用 `git archive`，但冒煙要先改讀 probes（§4），並加跑「只有核心」一份，驗模組缺席時的轉換與冒煙 |
| 正式 D7 | §4 冒煙改版合回、各模組 probes 補齊之後；使用者建包 | 本清單全部項目 |
