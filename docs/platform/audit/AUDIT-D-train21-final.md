# 稽核：第二十一班最終審（origin/platform 29e435df，部署包 20260929_040602_29e435df）（D，2026-09-29）

> 依使用者裁示 8c34f08a：建包測試（非 e2e 6129 passed／59 skipped，e2e 564 passed／2 skipped，A 的 build_t21b.log）採信，未重跑。

## 0. 判定

- **包：可上正式機。**
- **正式機指示第 1 段（`CLAUDE-正式機安裝指示_29e435df_第1段_安裝識別.md`）：可以交給正式機。** 第 2 段另審
- 必修 0、建議 1、觀察 2

## 1. 內容範圍：逐檔對照審過的來源

0af16ad1..29e435df 改到 60 個產品檔（排除 docs、tests、.md）。D 逐檔比 blob：
- 44 個檔**逐位元組等於**某個獨立審過的 head（B 64b38f39、A 844268be、E4 e4b7be5d、A48 f4d8bbf7、A49 aec09a2e、branding 28cc1854、conftest ae27088f、A46 309e28ed、0af16ad1）
- 16 個檔是多個來源合併，逐一以最接近的審過版本做差異，多出來的部分全部來自：
  - 另一個審過的來源：ae27088f（帳密導向）、B55 S2（`.deployed_modules.json` 設定檔登記、module_states 寫入）、A48（archive 背景化）、A49（`Get-StartupRange`、UTF-8）、`--permanent`（38c5156d）、branding 代數、E4S3-S1 匯款註記（模組 ps1）、modtest `_collect_env`（aa160b18）
  - 列車交會修正（本次首次看）：
    - 9de4cc8e：apply／rollback 所有 robocopy `/XF` 只加了 `.deployed_modules.json`（逐列比對 token），補齊 CGI-S3「`/XF` ⊇ `CONFIG_FILES`」；apply 版號取新號 **28k** 並重算 version.json 雜湊（SW-O1 已處理）
    - 0b31d783：`modtest --json` 時提示改印 stderr（stdout 只留 JSON）
    - 1ad0d669：測試＋「部署工具」28l／28m 合成一筆（VR3，§15.5 第 2 項）
    - e04ed977：測試正規式＋標案雷達版本紀錄
    - 95c258bb：tender_radar 註解更正（B54-S2 之後的反例不成立，原句以更正保留）＋模組版本 1.3.3 → 1.3.4
- B55F-M1 的回滾模式（1128a3ac 系列）**不在**本班（依計畫排下一班）；本班只出完整包

## 2. 包的驗證（D 獨立重做）

| 項目 | 結果 |
|---|---|
| 雲端 payload（packages\20260929_040651_29e435df_full） | **588 檔**，與 `package.sha256` 一致；SHA256＝1E8B0325…B59F，與 A 提供的一致 |
| 逐檔對 git blob（29e435df） | 560 相同、24 只差 CRLF、3 為建包產生、1 不同＝version_manifest（430 筆順序相同，只有 51 筆 `time` 投影） |
| F3 檔（`.install_identity`、確認檔、放行檔、初始帳密） | 包內 0 |
| 本機建包目錄 | 591 檔：多 3 個 `backend/core/__pycache__/*.pyc`，時間 04:07:00，落在發布期間（04:06:51～04:07:06）⇒ 發布流程從包目錄 import `core` 時寫入。**雲端那份（正式機要拿的）與 t21-verify 的 stage 都沒有** ⇒ 不影響交付（見建議 T21F-S1） |

## 3. 正式機指示第 1 段

- 只做 §6.7(a)：版本檢查 0af16ad1、雜湊 1E8B0325…、`bad=0 files=588`、ensure-install-id＋唯讀 preflight、回報；明寫不套用、不停服、不動 `V9.0`（`.install_identity` 例外）、不印金鑰 ✔
- 已帶 SG-S1／§6.7(a)-4 的提醒（第 2 段前不要用舊版腳本套別的包）✔

## 4. 建議與觀察

- **T21F-S1　從包目錄執行 CLI 會把 pyc 寫進包**：D 以包的暫存複本重現第 1 段第 64、65 行（`python "$PKG\backend\tools\company_setup_cli.py" ensure-install-id／preflight`）⇒ 包裡多出 **24 個 `.pyc`**（`backend/`、`core/`、`helpers/` 的 `__pycache__`）。第 2 段套用時 robocopy 不排除 `__pycache__` ⇒ 會一起複製進正式機；它們由同一份新版原始碼編譯，同版 Python 有效、不同版會被忽略，功能無害；`apply_update.ps1` 的公司閘門預檢本來也從包執行 CLI，每次套用都會這樣（演練在這個條件下通過）⇒ **不擋**。下一班：指示與 `Invoke-CompanySetupCli` 用 `python -B`（或設 `PYTHONDONTWRITEBYTECODE=1`），發布工具同樣處理，讓包保持「pyc 0」
- **T21F-O1**：version_manifest 沒有 E4（本公司資料設定閘門）的條目（最上面是標案雷達 29a、系統備份 28n、部署工具 28m、附近旅宿 28k）。已設定的正式機畫面無可見變化，不擋；但這是對客戶有感的大功能，下一班補一筆（同 T18F-O1）
- **T21F-O2**：B 的演練（基底 0af16ad1，§6.7(d) 路徑二＋「沒有確認檔 ⇒ refused_company_setup、正式機不動」）結果出來後再附上；依主持安排，演練與本審平行，演練發現問題才擋

- 〔補 2026-09-29〕T21F-S1 已先在第 1 段落實：第 3 步同一個區塊內、兩行 `python` 之前設 `$env:PYTHONDONTWRITEBYTECODE = "1"`（第 64 行）✔；第 2 段同樣照做；`Invoke-CompanySetupCli`／發布工具改 `-B` 與 T21F-O1 列下一班

## 5. 更正（2026-09-29 04:40，B 演練發現）：第 1 段預期的 reason

- B 演練：沒有確認紀錄時 preflight 回 **`no_record`**（`developer: true`、`missing: []`），不是 §6.7 寫的 `developer_identity_unsigned`
- D 對照 `company_setup.status()`（29e435df :328-351）：判定順序是「欄位不合格 ⇒ fields_invalid」→「**沒有確認紀錄 ⇒ no_record**」→ 識別不符 → 欄位變更 →「開發者身分且簽章檔不在／無效 ⇒ developer_identity_unsigned」。開發者資料又沒有簽章檔時，preflight 模擬的 backfill 是 `waiting_signature`（不寫紀錄）⇒ 停在 no_record ⇒ **程式正確，文件寫錯**
- 第 1 段第 3 步已改成「`no_record`（developer:true、missing:[]）或 `developer_identity_unsigned` 都算正常」，並保留更正註記 ✔
- 下一班：
  - E：COMPANY-SETUP-GATE §6.7(a)(d) 的預期文字更正
  - `apply_update.ps1`（第 807 行）拒絕訊息的處置說明只列 `developer_identity_unsigned`／`install_mismatch`，要補「`no_record` 且 `developer:true` ⇒ 同樣把 install 交給開發者簽確認檔」，否則正式機 Claude 看到 `no_record` 會對不上處置
- D 自己的同類錯誤：AUDIT-D-E4-company-gate.md §4.1-①、§7.1 的表格寫「漏了第一、二步 ⇒ 預檢得 `developer_identity_unsigned`」——結論（停服前拒絕、正式機不動）不變，原因碼應為 `no_record`（developer:true）。已在該檔補更正（原句保留）
