# HTTPS 正式機套用步驟清單

> 對應 commit `d7b8ee9`（2026-08-27，`backend/tools/https_setup.ps1`）。
> 程式碼與工具已經寫好、pytest 179/179 過，這份清單是「正式機上要親自動手做的部分」。
> 全程約 15-20 分鐘，執行時機建議選公司離峰時段（會重啟一次服務）。

## 前置確認

- [ ] 確認目前在**正式機**（`Motrix` 帳號，`C:\Users\Motrix\Desktop\V9.0`），不是開發機
- [ ] 確認正式機目前程式碼版本——執行 `apply_update.ps1` 前，看一下 `backend\.deployed_commit.json` 記錄的 commit（開發機這邊目前記錄是 `f2ef181`／2026-08-17，代表**正式機已經 11 天沒更新過，落後很多支後續開發**，包含這批 HTTPS 改動本身、以及 2026-08-28 這輪財務/視覺化優化）。**建議這次先走一次 §15 一般更新流程（把最新程式碼帶過去），HTTPS 這批改動本來就含在裡面，不需要另外單獨處理程式碼部分**——這份清單只涵蓋 §15 更新流程「之外」、HTTPS 獨有的手動步驟。

## 步驟

1. **下載 mkcert.exe**
   - 前往 <https://github.com/FiloSottile/mkcert/releases>，下載 Windows amd64 版本（`mkcert-vX.X.X-windows-amd64.exe`）
   - 改名成 `mkcert.exe`，放進正式機的 `backend\tools\` 目錄（跟 `https_setup.ps1` 同一層）
   - 不需要安裝、不需要系統管理員權限

2. **確認 §15 一般更新已完成**（如果這次順便一起更新程式碼的話）
   - 依 `MOTRIX-ERP-QUICK.md` §15 走完 `apply_update.ps1`，健康檢查通過、無回滾

3. **執行憑證產生腳本**
   ```powershell
   powershell -ExecutionPolicy Bypass -File "C:\Users\Motrix\Desktop\V9.0\backend\tools\https_setup.ps1"
   ```
   - 預設會用 `172.16.10.177`（正式機固定 IP）當 SAN，一般不需要加參數
   - 若正式機 IP 之後有變動，之後要重跑一次並加 `-Host2 <新IP>`
   - 執行完會在 `backend\certs\` 產生 `cert.pem` / `key.pem`（這兩個檔案**不會**進 git，只存在正式機本機）

4. **重啟服務**
   - 用 `restart.bat`（會自動偵測到 `certs\` 存在，改用 `--ssl-keyfile`/`--ssl-certfile` 啟動）
   - 或直接重開機讓 autostart 排程接手

5. **驗證 HTTPS 生效**
   - [ ] 瀏覽器開 `https://172.16.10.177:666`，出現「連線不安全」警告是**預期行為**（自簽憑證、沒裝 CA），點「進階」→「繼續前往」即可
   - [ ] 能正常登入、頁面功能正常
   - [ ] 舊的 `http://172.16.10.177:666` 網址——若 uvicorn 已改成只監聽 HTTPS，明文連線會直接失敗（連不上），這是預期行為，不是 bug
   - [ ] 檢查 `logs\server.log`，確認 uvicorn 啟動訊息顯示有帶 SSL 參數

6. **更新公司內部書籤/捷徑**
   - [ ] 桌面捷徑、瀏覽器書籤、內部 Wiki/文件裡貼的網址，`http://` 改成 `https://`
   - [ ] 通知同事：第一次連線看到「不安全」警告是正常的，點繼續前往即可（之後瀏覽器通常會記住）

7. **更新 Email 通知設定的網址**
   - [ ] 用 superadmin 登入 → `notification-settings.html` → 確認「系統網址」欄位改成 `https://172.16.10.177:666`（commit 只改了「從未設定過時」的預設值，正式機既有設定值不會自動變更，通知信裡的連結會繼續指向 http 直到手動改這裡）

8. **確認 `apply_update.ps1` 之後仍正常運作**
   - [ ] 下次要走 §15 更新流程時，健康檢查會自動偵測 `certs\` 存在並改用 https 連線（已內建在 commit 裡），不需要額外操作

## 如果出問題想回退

- 把 `backend\certs\` 資料夾整個搬走（或砍掉），重啟服務——三支啟動腳本偵測不到憑證就會自動退回明文 HTTP，不需要改任何程式碼
