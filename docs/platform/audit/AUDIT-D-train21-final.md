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

## 6. T21F-O2：B 的演練結果（包 20260929_040602_29e435df；A 轉述，依裁示採信）

| 場次 | 結果 |
|---|---|
| path1 新安裝／一般客戶確認路徑 | 15/15：未設定 428 ⇒ 設定頁確認 ⇒ configured；刪識別檔 ⇒ install_mismatch＋ERROR ⇒ 重新確認恢復 |
| path2 開發者簽章路徑（基底 0af16ad1） | 22/22：(a) no_record／developer:true ⇒ (b) `--days 7` ⇒ (c) configured／upgrade_backfill ⇒ success／applied／up（17.2 秒）、`::NOTE:: company_bank=ok`；`/docs`、`/openapi.json` 404；沒有「開關沒有生效」誤報；刪簽章檔 ⇒ 428 ⇒ grace 72h（手改 until 無效）；`secrets_left=[]` |
| path3 沒有確認檔直接套（基底 0af16ad1） | refused_company_setup／not_applied；部署標記、schema、本公司設定列、migration 都不變，ping 正常 |

- D 查核的唯一疑點（金鑰）：path2 (b) 要通過「內嵌交付公鑰自驗」。`drill_t21.py` 當場產生**拋棄式**演練金鑰，只在 staging 那份包的**副本**把演練公鑰加進 `PUBKEYS`（一處取代、斷言恰好一次、寫進報告），正本包、repo、正式交付私鑰都不碰；結束時刪除演練私鑰 ✔
- path3 的兩點落差（A 裁示接受）：(i) 預檢前的 `ensure-install-id` 會建 `.install_identity`，而拒絕訊息寫「正式機尚未被觸碰」⇒ 訊息列下一班改成「只建立了安裝識別檔，其餘未動」；(ii) 拒絕時 `service=unknown`（停服前沒有量）⇒ 可接受
- 首輪背景定位只驗到排程啟動 ⇒ 由正式機第 2 段套用後的 `geocode_warm_state` 查核補上

## 7. 第 2 段指示審查（`CLAUDE-正式機安裝指示_29e435df_第2段_確認檔與套用.md`）＋確認檔獨立驗證（D，2026-09-29）

- **判定：第 2 段可以交給正式機。** 必修 0、建議 2
- **正式機第 1 段回報**（`正式機回報\20260929_0420_0af16ad1_install-id\`）：install `9997d33f…4091`；preflight `no_record`、`developer: true`、`missing: []`、`payment_bank_missing: []`（exit 3＝未設定，屬預期；§5 更正後的正常值）
- **確認檔**（`company-confirmation\20260929_0421_9997d33f\company_confirmation.sig`）：D 以 29e435df 的常數**只用公鑰**獨立驗證（不碰私鑰）：
  - 以內嵌交付公鑰驗章：**通過**；`purpose` 正確
  - `permanent: true`、**沒有** `expires`、`issued` 2026-09-29
  - `install` 等於正式機第 1 段回報的值
  - `identity_fp` 在開發者指紋內
  - 欄位只有 identity_fp／install／issued／permanent／purpose／sig
- **第 2 段流程**：第 0 步再核對本地包 `bad=0 files=588` → 第 1 步放確認檔（雜湊比對）→ 第 2 步 preflight 必須 exit 0／configured／upgrade_backfill／`payment_bank_missing: []`，否則**不套用、不刪雲端檔** → 第 3 步預檢通過後才刪雲端那一份 → 第 4 步 robocopy tools（排除 `__pycache__`）、版號 `28k` → 第 5 步套用 → 第 6 步狀態表含 `refused_company_setup`、`company_setup_rolled_back`，回滾目標 0af16ad1 → 第 7 步 ping、`.build_commit`、status configured、「開關沒有生效」0 行、`geocode_warm_state`（補 T21F-O2 的首輪定位）、登入不導頁／無橫幅／報價單 PDF ✔
- 禁止事項列出 grace／sign／編輯確認檔／動 `.install_identity`、`-SkipAutoRollback` 等；回報不可放確認檔、金鑰 ✔

**建議（非必修）**
- **T21P2-S1**：第 5 步的區塊沒有設 `PYTHONDONTWRITEBYTECODE=1`；`apply_update.ps1` 的閘門預檢會從 `$PKG` 執行 CLI（子行程繼承這個 PowerShell 的環境）⇒ 套用時仍會在包裡寫 pyc，並隨 robocopy 進正式機。已判定功能無害（§4 T21F-S1），可在第 5 步區塊加同一行求一致
- **T21P2-S2**：第 7 步可加一項「`/openapi.json`、`/docs` 回 404」（A46 在本包，演練已驗；第十九班起的同一建議）

- 〔補 2026-09-29〕T21P2-S1 已補（第 5 步區塊加 `PYTHONDONTWRITEBYTECODE=1`）；T21P2-S2 不採納——A 理由：path2 已實測 404，正式機 PS 5.1 對自簽 https 量狀態碼容易誤判。D 同意；第 2 段已交主持轉正式機
