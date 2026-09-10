# Passkey 啟用 — 憑證與 CA 佈署步驟書

> ## 🟢 執行進度（2026-09-11 01:20 更新，**全部完成，Passkey 已可實際使用**）
>
> | 步驟 | 狀態 | 實際結果 |
> |------|------|---------|
> | 1 前置確認 | ✅ 完成 | 見下方「前置確認的實測結果」——**發現交接檔漏了一件事** |
> | 2 部署最新程式碼 | ✅ 完成 | 目前正式機是 **`34e0ce1`**（2026-09-11 套用）。中間經過 `37bd985` → `0da86bf` → `4ffe190` → `34e0ce1` 數輪，每一輪都是修 Passkey 路上的一個坑。 |
> | 3 重產憑證 | ✅ 完成 | 交握取得的 SAN = `DNS:localhost, DNS:motrix.internal, IP:172.16.10.177, IP:127.0.0.1`，有效期至 2028-12-10。舊憑證備份在 `backend\certs\backup_20260910_144802\`。 |
> | 4 取出根 CA | ✅ 完成 | `fetch_root_ca.ps1` 執行成功，根 CA 已取回開發機，並存下 DPAPI 加密的 `%USERPROFILE%\motrix_cred.xml`（之後跑 WinRM 工具不用再輸密碼）。 |
> | 5 各機器裝 CA | 🟡 正式機 + 開發機 | 兩台都已裝（指紋 `A9AF974F0BD6CE35B47CDB95CAA5E2B324DAE61C`）且都能解析 `motrix.internal`。**其他同事的電腦尚未處理**——每台要做兩件事，缺一不可：(a) `certutil -addstore -f Root rootCA.pem` (b) 能解析 `motrix.internal`。⚠️ 若採用 `LETSENCRYPT-PUBLIC-CERT-PLAN.md` 的方案，**這一步整個不需要做**。 |
> | 6 驗證安全內容 | ✅ 完成 | 開發機瀏覽器實測 `platformAuthenticator: True`、`isSecureContext: true`。 |
> | 7 設定 RP ID | ✅ 完成 | RP ID = `motrix.internal`，Origin = `https://motrix.internal:666`。 |
> | 8 系統網址 | ⬜ **待確認** | 通知信裡的連結讀的是這個設定。請 superadmin 到通知設定頁確認是否已改成 `https://motrix.internal:666`——沒改的話寄出去的信仍指向舊位址（這一步最容易被忘記）。 |
> | 9 端對端實測 | ✅ **完成（2026-09-11）** | 使用者實測：可以註冊 Passkey，**也可以用 Passkey 登入**。在 `34e0ce1` 之前登入從來沒成功過（`login.html` 有兩個 `init()` 互相覆蓋、後端用了 py_webauthn 不存在的 `verified.sign_count`），詳見該 commit。另有自動化 e2e `backend/tests/test_e2e_passkey_2026_09_11.py` 覆蓋整條路。 |
>
> **目前狀態**：Passkey 在「已裝 CA 且解析得到 `motrix.internal`」的電腦上可正常使用。
>
> **下一個決策點不在這份文件裡**：要不要改用公開受信任憑證，見
> **`LETSENCRYPT-PUBLIC-CERT-PLAN.md`**。那條路可以讓第 5 步（每台裝 CA + 改 DNS）
> 整個消失，Windows／macOS／手機／Firefox 全部開箱即用，代價是所有人要改用
> `https://erp.miactw.com:666` 這個新網址。
>
> ⏳ **RP ID 越晚換越貴**：改動 RP ID 會讓**所有既有 Passkey 失效且無法救回**
> （`webauthn_credentials` 刻意沒存 rp_id）。現在只有 1～2 張，成本最低。
>
> ### 前置確認的實測結果（第 1 步）
>
> | 項目 | 實測 |
> |------|------|
> | mkcert | `C:\Users\Motrix\Desktop\V9.0\backend\tools\mkcert.exe` |
> | CAROOT | `C:\Users\Motrix\AppData\Local\mkcert\`（`rootCA.pem` 1655 bytes、`rootCA-key.pem` 2484 bytes） |
> | **DNS（重要）** | **正式機自己也解析不到 `motrix.internal`**——主網卡 DNS 設的是 `8.8.8.8`，不是 Peplink。交接檔用 `nslookup motrix.internal 172.16.10.1` 驗證，那是**指定**問路由器、繞過了機器本身的 DNS 設定。開發機同樣是 `8.8.8.8`。已在正式機 hosts 加一行解決，但**每台要用 Passkey 的電腦都要處理** |
> | 服務 | port 666 由 PID 2760 監聽中，健康 |
>
> ### 執行中踩到、已修正到步驟書裡的兩件事
>
> 1. **`mkcert -install` 在 WinRM 遠端 session 下會失敗**：`ERROR: add cert: failed adding cert: The request is not supported.`
>    改用 `certutil -addstore -f Root <rootCA.pem>` 成功（`.NET X509Store` 直接寫入也可以）。
>    第 5 步本來就是寫 `certutil`，這裡確認了它是可行的那條路。使用者在自己機器上
>    互動式執行 `mkcert -install` 應該沒問題，但腳本化一律用 `certutil` 比較保險。
> 2. **PS 5.1 原生執行檔 stderr 地雷（本專案第 4 次）**：`mkcert` 往 stderr 印一行
>    `Note: the local CA is not installed...`，在 `$ErrorActionPreference = "Stop"` 底下
>    被 `2>&1` 包成 `NativeCommandError` 直接中止腳本——即使指令本身成功（憑證確實產出來了）。
>    先前 pip install / tar / db備份 各踩過一次。呼叫原生執行檔前後要把 `ErrorActionPreference`
>    切成 `Continue`。
>
> ---
>
> 產出：2026-09-10｜原始狀態：尚未執行，待確認
> 目標：讓 `https://motrix.internal:666` 在瀏覽器是「乾淨的鎖頭」，Passkey／WebAuthn 才能真正啟用。
> 相關：`MOTRIX-ERP-QUICK.md` §3.3b（TOTP）／§14.3d（兩機交接）／`backend/tools/https_setup.ps1`

---

## 0. 為什麼需要做這一整套

現況（皆為實測，非推論）：

| 項目 | 現況 | 影響 |
|------|------|------|
| 內部 DNS | `motrix.internal` → `172.16.10.177`（Peplink 172.16.10.1 已設定，`nslookup` 驗證過） | ✅ 已完成 |
| 憑證 SAN | `DNS Name=localhost` / `IP Address=172.16.10.177` / `IP Address=127.0.0.1` | ❌ **沒有 `motrix.internal`**，用網域存取一定跳憑證主機名不符 |
| CA 信任 | `https_setup.ps1` 檔頭明載「刻意不執行 `mkcert -install`」，靠使用者點「繼續前往」 | ❌ 網址列永遠是警告狀態 |
| 開發機 DNS | `8.8.8.8`（`motrix.internal` 解析失敗；直接問 Peplink 則正常） | ⚠️ 依機器而異，需逐台確認 |
| WebAuthn 設定 | `configured:false`，端點回 503 | 尚未啟用（**這是目前最誠實的狀態，先別急著填**） |

**關鍵**：WebAuthn 要求「安全內容」，瀏覽器對憑證有錯的頁面會限制高權限 API。
只把 RP ID 填下去，`configured` 會變 true、Passkey 按鈕會亮起來，然後在憑證錯誤下失敗——
**那比現在誠實回 503 更難查**。所以順序不能顛倒：**先把憑證弄乾淨，最後才設 RP ID**。

---

## ⚠️ 動手前必讀：CA 私鑰的風險

`mkcert` 的根 CA 目錄（`mkcert -CAROOT`）裡有兩個檔案：

| 檔案 | 能不能外流 | 說明 |
|------|-----------|------|
| `rootCA.pem` | ✅ 可以分發 | 這是公開憑證，要裝到每台電腦的就是它 |
| `rootCA-key.pem` | 🚫 **絕對不能離開正式機** | 這是 CA 私鑰。**任何拿到它的人，都能為任意網站簽出被這些電腦信任的憑證**（Google、銀行、公司內部系統都算），對所有裝了這張 CA 的電腦發動中間人攻擊 |

裝 CA 這個決定，等於把「信任這台正式機上的一個私鑰檔」寫進每台員工電腦。這在公司內網
是常見且可接受的取捨，但前提是那個私鑰要被當成密碼等級的機密保管：

- 不要複製到雲端硬碟、不要放進 git、不要用 email 傳
- 分發時只複製 `rootCA.pem` 一個檔，不要整個 CAROOT 目錄一起拷
- 正式機本身的存取控制就是這張 CA 的安全邊界

若之後要撤銷，要逐台把憑證從「受信任的根憑證授權單位」移除——**沒有遠端撤銷機制**。

---

## 1. 前置確認（不做任何改動，5 分鐘）

### 1-1 決定範圍：哪些人／哪些裝置要用 Passkey？

這直接決定工作量差很多：

| 情境 | 難度 | 說明 |
|------|------|------|
| 公司內網的 Windows PC，用 Chrome／Edge | 🟢 容易 | Chrome/Edge 直接用 Windows 憑證存放區，`certutil` 一行搞定 |
| 有人用 Firefox | 🟡 要多做一步 | **Firefox 有自己的憑證存放區，預設不看 Windows 的**。需開 `security.enterprise_roots.enabled=true`，或手動匯入 |
| 要在手機上用 Passkey | 🔴 明顯更麻煩 | iOS 要安裝描述檔＋到「關於本機→憑證信任設定」手動開啟完全信任；Android 各家做法不一。且手機要連在會用 Peplink DNS 的 WiFi 才解析得到 `motrix.internal` |

> 建議第一輪只做「公司內網 Windows + Chrome/Edge」，確認整條路走得通再擴大。
> 既有的 TOTP 與手機掃 QR 核准登入**完全不受影響**，可以繼續用，不急著一次到位。

### 1-2 確認要用的機器解析得到網域

每台目標機器上執行：

```powershell
Resolve-DnsName motrix.internal
```

解析不到的話，看它的 DNS 設定：

```powershell
Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object { $_.ServerAddresses }
```

- 若指向 Peplink（172.16.10.1）→ 正常
- 若指向公用 DNS（如 8.8.8.8，**開發機目前就是這樣**）→ 該機器解析不到。
  要嘛改成用 Peplink，要嘛在該機加 hosts：
  `C:\Windows\System32\drivers\etc\hosts` 加一行 `172.16.10.177  motrix.internal`（需系統管理員）

---

## 2. 部署最新程式碼（約 2 分鐘，含一次服務重啟）

`https_setup.ps1` 的 `-ExtraNames`／`-Force` 是 2026-09-10 才加的（commit `1e9c471`），
正式機目前跑 `2471747` 還沒有這些參數，所以先部署。這批同時會帶上 WebAuthn 設定端點的
格式驗證（會擋掉「RP ID 填 IP」這種必錯的設定）。

1. 開發機打包：`powershell -ExecutionPolicy Bypass -File backend\tools\build_deploy_package.ps1`
2. 部署儀表板（`http://127.0.0.1:8765`）→ 選新的部署包 → 輸入正式機密碼 → 兩段式確認
3. 確認 `GET https://172.16.10.177:666/api/system/deployed-version` 回報新的 commit

> **回滾**：`apply_update.ps1` 會自動建立 db 與程式碼快照；健康檢查失敗會自動回滾。
> 也可從儀表板手動選快照回滾。

---

## 3. 重產憑證，把 `motrix.internal` 加進 SAN（約 2 分鐘，含一次服務重啟）

**在正式機上執行**（可透過 WinRM，或直接坐在正式機前）：

```powershell
cd C:\Users\Motrix\Desktop\V9.0\backend\tools
powershell -ExecutionPolicy Bypass -File https_setup.ps1 -ExtraNames motrix.internal -Force
```

- `-Force` 會先把舊憑證備份到 `backend\certs\backup_<timestamp>\` 再重產（**回滾就是把這個目錄的檔案複製回去**）
- 腳本產完會自動把實際 SAN 印出來，**務必肉眼確認 `motrix.internal` 在裡面**

然後重啟服務：

```powershell
C:\Users\Motrix\Desktop\V9.0\backend\restart.bat
```

**驗證（此時還是會有警告，因為 CA 還沒裝，這是預期的）**：

```powershell
# 主機名檢查應該從「不符」變成只剩「簽發者不受信任」
$tcp = New-Object System.Net.Sockets.TcpClient("motrix.internal", 666)
$ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false, {$true})
$ssl.AuthenticateAsClient("motrix.internal")
$c = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ssl.RemoteCertificate)
($c.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.17" }).Format($true)
$ssl.Dispose(); $tcp.Close()
```

> 查 SAN 一定要用 OID `2.5.29.17`，**不要用 `FriendlyName` 比對英文字串**——中文版
> Windows 會在地化成「主體別名」，用英文比對會查不到，誤以為憑證沒有 SAN。

---

## 4. 取出根 CA（正式機，1 分鐘）

```powershell
mkcert -CAROOT
# 典型輸出：C:\Users\Motrix\AppData\Local\mkcert
```

該目錄下的 **`rootCA.pem`** 就是要分發的檔案。

🚫 **`rootCA-key.pem` 留在原地，不要複製、不要外傳**（理由見上方「動手前必讀」）。

把 `rootCA.pem` 複製到一個方便取用的位置（例如共用資料夾），或用 WinRM 從開發機拉回來。

---

## 5. 在每台目標電腦安裝 CA（每台約 1 分鐘）

### Windows（Chrome／Edge 適用）

以**系統管理員**開啟 PowerShell 或 cmd：

```
certutil -addstore -f Root C:\path\to\rootCA.pem
```

驗證：

```powershell
Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -like "*mkcert*" } |
    Select-Object Subject, NotAfter
```

> 沒有系統管理員權限時的替代方案（只影響當前使用者）：
> `certutil -user -addstore Root C:\path\to\rootCA.pem`

### Firefox（如果有人用）

Firefox 不看 Windows 憑證存放區。擇一：

- 網址列輸入 `about:config` → 搜尋 `security.enterprise_roots.enabled` → 設為 `true`（會改成讀 Windows 存放區）
- 或 設定 → 隱私權與安全性 → 憑證 → 檢視憑證 → 憑證機構 → 匯入 `rootCA.pem`，勾選「信任此 CA 以識別網站」

### 這是本階段最花時間的一步

沒有網域環境（workgroup，無 AD／GPO），**每台都要人去做一次**。若電腦數量多，
可以考慮寫一支腳本配合遠端執行，但那需要另外評估。

---

## 6. 驗證安全內容（關鍵關卡 — 沒過就停在這裡）

在**已裝 CA 的目標電腦**上，用 Chrome／Edge 開：

```
https://motrix.internal:666
```

必須同時滿足三項，缺一不可：

1. ✅ 網址列是**乾淨的鎖頭**，沒有「不安全」或「您的連線不是私人連線」
2. ✅ 開發人員工具 → Console 輸入 `window.isSecureContext` → 回 `true`
3. ✅ Console 輸入 `!!window.PublicKeyCredential` → 回 `true`

> **任何一項沒過就不要往下走**——往下走只會得到一個「看起來啟用了但不能用」的 Passkey，
> 比現在誠實回 503 更難查。沒過的話回頭檢查：憑證是不是真的重產了（SAN）、
> CA 是不是裝進「受信任的根憑證授權單位」（不是「中繼」）、瀏覽器有沒有重開。

---

## 7. 設定 RP ID / Origin（1 分鐘）

第 6 步全過之後才做這一步。

superadmin 登入 → `company-profile-settings.html` →「Passkey / WebAuthn 網域設定」：

| 欄位 | 值 |
|------|-----|
| RP ID | `motrix.internal` |
| Origin | `https://motrix.internal:666` |

或用 API：

```
PATCH /api/settings/webauthn-config
{"rp_id": "motrix.internal", "origin": "https://motrix.internal:666"}
```

> 部署第 2 步之後，這支端點會驗證格式（RP ID 不得含 scheme/port、不得是 IP、
> Origin 的 host 必須等於 RP ID 或其子網域、除 localhost 外必須 https）。
> 上面這組值會通過驗證。
>
> 另外：若之後改動 RP ID，**既有的 Passkey 會全部失效**（憑證被瀏覽器綁在註冊當下的
> RP ID 上，而 `webauthn_credentials` 沒有存 rp_id 欄位）。端點會回傳受影響張數並寫進稽核。

---

## 8. 一併更新「系統網址」（1 分鐘，容易忘）

`https_setup.ps1` 檔尾就有提醒：通知信裡的連結是讀「系統網址」設定，不改的話寄出去的信
還是指向舊位址。

superadmin → 通知設定頁 → 系統網址改成 `https://motrix.internal:666` → 存檔。

> 順帶一提：`main.py` 的 CORS 白名單（L34-43）寫死了 IP，沒有 `https://motrix.internal:666`。
> **這不會造成問題**——前端是同一個 FastAPI app 以靜態檔提供的，同源請求不走 CORS。
> 補進去只是整潔，不是阻斷點。

---

## 9. 端對端實測（10 分鐘）

1. 在已裝 CA 的電腦上，用一個**測試帳號**（不要先拿 jeff／corbin 這種業主帳號試）登入
2. 進「修改密碼」頁 → Passkey 裝置管理 → 註冊一張 Passkey（會跳 Windows Hello／指紋／PIN）
3. 登出，改用 Passkey 登入
4. 回到裝置管理，確認可以改名、可以撤銷
5. **確認既有登入方式沒有被影響**：密碼登入、TOTP、手機掃 QR 核准，三種各測一次

---

## 各階段的回滾方式

| 階段 | 出問題時怎麼退回 |
|------|-----------------|
| 2 部署 | 儀表板手動回滾到套用前快照；健康檢查失敗本來就會自動回滾 |
| 3 憑證 | 把 `backend\certs\backup_<timestamp>\` 的兩個檔複製回 `backend\certs\`，重跑 `restart.bat` |
| 5 裝 CA | `certutil -delstore Root <憑證指紋>`，逐台移除（**沒有遠端撤銷機制**） |
| 7 RP ID | 設定頁把兩個欄位清空存檔（同時清空是合法的），端點回到 503，Passkey 按鈕自動隱藏 |
| 8 系統網址 | 改回 `https://172.16.10.177:666` |

**整體回滾**：把 RP ID 清空（第 7 步）就能立刻讓 Passkey 停用，其餘登入方式不受影響。
憑證與 CA 可以留著不動——`172.16.10.177` 仍在 SAN 裡，用 IP 存取一切照舊。

---

## 時間估計

| 階段 | 時間 | 備註 |
|------|------|------|
| 1 前置確認 | 5 分 | 不做改動 |
| 2 部署 | 2 分 | 含一次服務重啟 |
| 3 重產憑證 | 2 分 | 含一次服務重啟 |
| 4 取出 CA | 1 分 | |
| 5 裝 CA | **每台 1 分** | ← 主要成本，取決於電腦數量 |
| 6 驗證 | 2 分 | 關鍵關卡 |
| 7-8 設定 | 2 分 | |
| 9 實測 | 10 分 | |

服務中斷總計約 2 次、每次不到 1 分鐘（第 2、3 步各一次）。
