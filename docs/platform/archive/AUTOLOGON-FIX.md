# 開機顯示「帳號或密碼錯誤」— 故障紀錄

> 記錄日期：2026-07-31

## 問題現象

開機時 Windows 登入畫面顯示「帳號或密碼錯誤」。

## 診斷過程

1. 一開始誤判為 MOTRIX ERP 網頁登入（`http://localhost:666`）問題，查了：
   - `backend/logs/server.log`：伺服器今日 23:44 剛正常重啟，近 10 筆 `POST /api/auth/login` 全部 200 OK，無 401 失敗紀錄
   - `motrix_erp.db` 的 `login_rate_limit` 表：空，無鎖定紀錄
   - `users` 表：jeff / corbin / queena / test / test2 / test3 / demo 皆 `active=1`
   - 結論：ERP 網頁登入本身沒有異常
2. 確認後才發現問題其實是 **Windows 開機自動登入（AutoAdminLogon）**，不是 ERP 網頁登入
3. 檢查登錄檔 `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon`：
   ```
   AutoAdminLogon    = 1
   DefaultUserName   = Motrix
   DefaultDomainName = .
   DefaultPassword   = （空白）
   ```
   → 開機時 Windows 拿使用者名稱 `Motrix` + 空密碼自動登入，但該 Windows 帳號實際上有設密碼，於是登入失敗顯示「帳號或密碼錯誤」

## 根本原因

`DefaultPassword` 登錄值未設定（為空），與 Windows 帳號 `Motrix` 的實際密碼不一致。

## 修復步驟

以**系統管理員身分**開啟 PowerShell，執行：

```powershell
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name 'DefaultPassword' -Value '<Motrix帳號的Windows登入密碼>' -Type String
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name 'AutoAdminLogon' -Value '1' -Type String
```

執行後重開機測試即可。

> 註：一般使用者權限的 PowerShell 無法寫入 `HKLM`（`Set-ItemProperty : Requested registry access is not allowed.`），必須用系統管理員權限執行。

## 已知取捨

- `DefaultPassword` 是以**明文**存在登錄檔中，任何有本機系統管理員權限的使用者或程式都讀得到
- 若要避免明文密碼留在登錄檔，可改用 Sysinternals 的 **Autologon** 工具，密碼會加密存成 LSA secret，效果相同但較安全（需另外下載安裝：https://learn.microsoft.com/sysinternals/downloads/autologon）
- 若之後 Windows 帳號密碼變更，此登錄檔的 `DefaultPassword` 必須同步更新，否則會再次出現此問題

## 相關檔案

- 開機自動登入設定：`HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon`
- MOTRIX ERP 後端啟動腳本（與此問題無關，僅開機後自動啟動 ERP server）：`backend\autostart.bat` / `backend\autostart_hidden.vbs`
