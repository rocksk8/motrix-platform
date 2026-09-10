# 公開受信任憑證（Let's Encrypt + Cloudflare）— 讓 Passkey 不再需要每台裝 CA

> 產出：2026-09-11｜狀態：**規劃完成、尚未執行**（DNS 與正式機的動作都需要你本人操作）
> 起因：「能否讓使用者瀏覽器點選 PASSKEY 自動下載認證跟執行，windows、macos 都可以」
> 相關：`PASSKEY-CA-ROLLOUT.md`（自簽 CA 那條路，本文件是它的替代方案）

---

## 0. 先回答那個問題：瀏覽器不可能自動安裝根 CA

這是 Windows 與 macOS **共同的安全邊界**，不是缺功能。任何網頁都無法把憑證寫進系統
信任存放區——可以的話，任何網站都能讓你信任它偽造的憑證。所以「點一下自動裝好」
在自簽憑證的前提下，兩個平台都做不到。能做到的最接近版本是「下載檔案 → 執行 →
輸入管理員密碼」，那正是 `setup_passkey_client.ps1` 已經在做的事。

**但這個問題有另一個解法：把「需要裝 CA」整件事消滅掉。**

`miactw.com` 的 DNS 在 Cloudflare（實測：`maria.ns.cloudflare.com` /
`cameron.ns.cloudflare.com`），這代表可以用 Let's Encrypt 簽一張**全世界瀏覽器本來
就信任**的憑證。不用裝 CA、不用發檔案、不用改 hosts——Windows / macOS / iOS /
Android / Firefox 全部開箱即用。

| | 使用者要做的事 | 支援範圍 |
|---|---|---|
| 現況（自簽 CA） | 每台跑腳本 + 管理員密碼 + 要能解析 `motrix.internal` | 只做了 Windows，macOS 沒有對應腳本 |
| **Let's Encrypt** | **什麼都不用做** | 全平台，含手機、Firefox |

---

## 1. 為什麼這條路走得通（三個關鍵前提，都已確認）

| 前提 | 實測 |
|------|------|
| 網域在可控的 DNS 商 | ✅ `miactw.com` 在 Cloudflare，有 API |
| 子網域未被佔用 | ✅ `erp.miactw.com` 目前是 NXDOMAIN |
| 主機不需要對外開放 | ✅ 用 **DNS-01** 驗證：證明你控制 DNS 區域即可，Let's Encrypt **不會**來連你的主機 |

第三點是重點。一般人印象中「申請憑證要開 80 埠讓對方來驗」，那是 HTTP-01。
DNS-01 只需要主機能**對外**連到 Let's Encrypt 與 Cloudflare API，正式機本身
永遠不必暴露在網際網路上。

---

## 2. 順帶解掉的兩個既有隱憂

**① RP ID 未來被迫變更的風險。**
你先前提過「未來會有 VPN，主機可能變更網路環境」。目前 RP ID 是 `motrix.internal`，
那是一個只在內網有意義的名字；一旦網路架構改動而必須換名，**所有既有 Passkey 會
全部失效且無法救回**（`webauthn_credentials` 刻意沒存 rp_id，系統查不出哪張屬於哪個 RP，
見 `routers/system.py` 的 `set_webauthn_config` 註解）。
改用 `erp.miactw.com` 之後，換網段、加 VPN、換辦公室都不影響——RP ID 綁的是主機名，不是 IP。

**② 每台機器要能解析 `motrix.internal` 的問題。**
現在必須改 DNS 指向 Peplink 或手動加 hosts（開發機與正式機的主網卡 DNS 都是 8.8.8.8，
兩台都曾解析失敗）。`erp.miactw.com` 放在**公開** DNS 之後，任何機器用任何 DNS 都解析得到。

---

## 3. 執行步驟

> 順序不可顛倒，理由與 `PASSKEY-CA-ROLLOUT.md` §0 相同：
> **先把憑證弄乾淨，最後才改 RP ID**。反過來做只會得到一個「看起來啟用了但不能用」
> 的 Passkey，比誠實地失敗更難查。

### 步驟 1｜Cloudflare 加一筆 DNS 記錄（1 分鐘）

Cloudflare 控制台 → `miactw.com` → DNS → Add record：

| 欄位 | 值 |
|------|-----|
| Type | `A` |
| Name | `erp` |
| IPv4 address | `172.16.10.177` |
| Proxy status | **DNS only（灰色雲，務必關掉橘色 proxy）** |
| TTL | Auto |

**proxy 一定要關**：Cloudflare 的 proxy 連不到私有 IP，而且會在它那邊終止 TLS，
封包根本到不了正式機。

> ⚠️ **這個決定的代價**：內網 IP 會出現在公開 DNS，任何人查得到
> `erp.miactw.com = 172.16.10.177`。這在企業內是常見且普遍接受的做法（外面的人
> 查得到也連不進來），但它是一個要有意識做的取捨。
>
> 不能接受的話，替代方案是把這筆記錄放在 Peplink 的內部 DNS——但那樣就回到
> 「每台機器的 DNS 必須指向 Peplink」的老問題，等於放棄本方案最大的好處。
> 憑證本身仍然有效（DNS-01 驗證的是**你對 DNS 區域的控制權**，不是 IP 指向哪裡），
> 所以「憑證用 Let's Encrypt、解析走內部 DNS」也是成立的組合。

驗證：

```powershell
Resolve-DnsName erp.miactw.com -Server 8.8.8.8
```

### 步驟 2｜建立 Cloudflare API Token（2 分鐘）

Cloudflare → 右上角個人選單 → **My Profile** → **API Tokens** → Create Token
→ 用 **Edit zone DNS** 範本：

| 設定 | 值 |
|------|-----|
| Permissions | Zone → DNS → **Edit** |
| Zone Resources | Include → **Specific zone** → `miactw.com` |
| Client IP Filtering | （選填）限制成公司對外 IP，更保險 |

這個 token **只能改這一個網域的 DNS 記錄**，碰不到官網、郵件或帳號設定。
產生後只會顯示一次，複製下來。

> 🚫 這是一組真的憑據。不要進 git、不要用 email 傳、不要寫進任何 .md。
> 下一步輸入時腳本會用 `-AsSecureString`，不會顯示在螢幕上。

### 步驟 3｜在正式機簽出憑證（5 分鐘）

在**正式機**上以系統管理員開 PowerShell：

```powershell
Install-Module -Name Posh-ACME -Scope AllUsers -Force
Import-Module Posh-ACME

# 先用測試環境跑一次，確認整條路通了再換正式——
# Let's Encrypt 正式環境有頻率限制（同一組網域一週 5 張），試錯會把額度用光
Set-PAServer LE_STAGE
$cfToken = Read-Host "Cloudflare API Token" -AsSecureString
New-PACertificate 'erp.miactw.com' -AcceptTOS -Contact 'rockskt9@gmail.com' `
    -Plugin Cloudflare -PluginArgs @{ CFToken = $cfToken }
```

跑得過就換正式環境重跑一次：

```powershell
Set-PAServer LE_PROD
New-PACertificate 'erp.miactw.com' -AcceptTOS -Contact 'rockskt9@gmail.com' `
    -Plugin Cloudflare -PluginArgs @{ CFToken = $cfToken }
```

過程中 Posh-ACME 會自動在 Cloudflare 建一筆 `_acme-challenge.erp.miactw.com`
的 TXT 記錄、等 Let's Encrypt 查驗、然後刪掉它。全程不需要開任何對外連接埠。

> 參數名若有出入，以 `Get-PAPlugin Cloudflare -Help` 的輸出為準（不同版本的
> Cloudflare 外掛曾用過 `CFToken` / `CFTokenInsecure` / 舊式的 `CFAuthEmail`+`CFAuthKey`）。

查看產出的檔案位置：

```powershell
Get-PACertificate | Format-List Subject, NotAfter, FullChainFile, KeyFile
```

### 步驟 4｜換上新憑證並重啟（2 分鐘）

用本專案新增的腳本一次做完（備份舊憑證 → 複製新的 → 重啟 → 驗證）：

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\Motrix\Desktop\V9.0\backend\tools\letsencrypt_renew.ps1 -Force
```

`-Force` 表示「不管到期日，現在就把目前這張裝上去」。手動做的話等同於：

1. 備份 `backend\certs\cert.pem` 與 `key.pem` 到 `backend\certs\backup_<時間>\`
2. `FullChainFile` → `backend\certs\cert.pem`（**要用 fullchain，不是 cert.cer**，
   少了中繼憑證有些客戶端會驗不過）
3. `KeyFile` → `backend\certs\key.pem`
4. `restart.bat`

### 步驟 5｜驗證（關鍵關卡 — 沒過就停在這裡）

在一台**完全沒有裝過 mkcert CA、也沒改過 hosts** 的電腦上（這才是這次要證明的事），
用 Chrome / Edge 開 `https://erp.miactw.com:666`，必須三項全過：

1. ✅ 網址列是乾淨的鎖頭
2. ✅ Console 輸入 `window.isSecureContext` → `true`
3. ✅ Console 輸入 `!!window.PublicKeyCredential` → `true`

順便在 macOS（Safari）與手機上各開一次——這正是本方案的賣點，值得當場確認。

### 步驟 6｜切換 RP ID / Origin / 系統網址（3 分鐘）

**⚠️ 這一步會讓現有那 1 張 Passkey（jeff，2026-09-11 00:10 註冊）失效。**
只有 1 張，現在換的成本最低；累積幾十張之後再換會非常痛。

superadmin 登入 → `company-profile-settings.html` →「Passkey / WebAuthn 網域設定」：

| 欄位 | 新值 |
|------|------|
| RP ID | `erp.miactw.com` |
| Origin | `https://erp.miactw.com:666` |

端點會回報受影響張數並寫進稽核。接著把失效的舊憑證列刪掉（留著也永遠驗不過，
只會讓使用者在裝置清單看到一張沒用的），再重新註冊。

再到通知設定頁把**系統網址**改成 `https://erp.miactw.com:666`——通知信裡的連結
讀的是這個設定，不改的話寄出去的信還是指向舊位址。

> 為什麼 RP ID 用 `erp.miactw.com` 而不是 `miactw.com`：
> 用主網域的話，憑證會對**所有** `*.miactw.com` 來源有效，包含公開官網
> `www.miactw.com`——官網若被植入指令碼就能向使用者索取簽章。收斂到
> `erp.miactw.com` 沒有任何機能損失（換 IP、加 VPN 都不影響），攻擊面小得多。

### 步驟 7｜設定自動續期（2 分鐘）

Let's Encrypt 憑證 **90 天到期**。續期失敗 = HTTPS 壞掉 = Passkey 全部不能用，
所以這一步不是可選的。

以系統管理員執行一次即可（腳本會自己建排程工作）：

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\Motrix\Desktop\V9.0\backend\tools\letsencrypt_renew.ps1 -InstallSchedule
```

排程每天凌晨 03:30 跑一次；Posh-ACME 只在進入續期視窗（到期前 30 天）時才真的
去要新憑證，其餘日子是空轉。真的換了新憑證才會重啟服務。

---

## 4. 這次切換的代價（務必先讓大家知道）

**Let's Encrypt 的憑證只涵蓋 `erp.miactw.com` 一個名字。**
Let's Encrypt 不可能為私有 IP（`172.16.10.177`）或不存在於公開 DNS 的名字
（`motrix.internal`）簽發憑證。所以切換之後：

| 舊網址 | 切換後 |
|--------|--------|
| `https://172.16.10.177:666` | ❌ 憑證主機名不符警告 |
| `https://motrix.internal:666` | ❌ 憑證主機名不符警告 |
| `https://erp.miactw.com:666` | ✅ 乾淨的鎖頭 |

**所有人都要改用新網址、更新書籤。** 這是一次性成本，但如果沒有事先講，
第二天早上會收到一整批「系統壞了」。

（服務本身沒壞，用舊網址點「繼續前往」還是進得去，只是會有警告——而且
Passkey 在那個 origin 下不會運作，因為 origin 對不上。）

---

## 5. 長期要盯的三件事

| 風險 | 徵兆 | 對策 |
|------|------|------|
| 續期靜默失敗 | 90 天後某天早上全公司連不上 | `letsencrypt_renew.ps1` 會在剩餘天數 < 20 且沒有成功續期時，往 log 寫 `[警告]`；建議每季看一次 `backend\logs\letsencrypt_renew.log` |
| Cloudflare token 外洩 | — | token 只能改這一個 zone 的 DNS；懷疑外洩就到 Cloudflare 撤銷並重發，然後重跑步驟 3 |
| 網域搬離 Cloudflare | 續期開始失敗 | 換 Posh-ACME 的 `-Plugin` 為新 DNS 商對應的外掛 |

## 6. 這條路做完之後，自簽 CA 那套怎麼辦

`PASSKEY-CA-ROLLOUT.md` 那套**不需要拆掉**，但也不必再推廣：

- 你自己這台已經裝的 mkcert CA 可以留著（無害），也可以用
  `certutil -delstore Root A9AF974F0BD6CE35B47CDB95CAA5E2B324DAE61C` 移除
- `fetch_root_ca.ps1` / `setup_passkey_client.ps1` 保留備用——萬一未來要在
  一個沒有網際網路、無法續期的環境跑，自簽仍是唯一解
- 正式機的 `rootCA-key.pem` 依然要當機密保管（它還在那台機器上）
