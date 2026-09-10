# MOTRIX ERP — 變更記錄

> 允碩整合集創股份有限公司  
> 按版本倒序排列。開發速查請見 `MOTRIX-ERP-QUICK.md`。

---

### 2026-09-11（白天）— 憑證到期告警：唯一一件「一定會發生、而且完全沒人在看」的事

**先記決策：Cloudflare 兩條路都排除。**

| 方案 | 為什麼不做 |
|---|---|
| Cloudflare Origin CA 憑證 | 它的根 CA **不在任何瀏覽器／OS 的信任清單裡**（設計如此——那是給「Cloudflare proxy ↔ 你的主機」那一段用的）。要用就得每台裝 Cloudflare 的根，等於回到現在 mkcert 的處境一台都沒少，還改成信任一個不是自己控制的第三方根。**解決不了原本的問題** |
| Cloudflare Tunnel + Access | 唯一的獨門好處是「從公司外面能用 ERP」。代價：①對外網路一斷，坐在辦公室裡也連不上 ②全部 ERP 流量在 Cloudflare 邊緣解密 ③正式機多一個不在 git 的常駐服務 ④Access 會在 ERP 自己的登入頁之前再插一層登入。而**規劃中的 VPN 解的是同一個問題**，且沒有這四項代價 |

錢完全不是因素（要用的都在免費額度內）。若之後要重開這個討論，前提是「VPN 確定不做」。

---

**接著是這輪真正動手的東西。**

目前服務中的憑證是 mkcert 自簽、**2028-12-10 到期**，而 mkcert 不會自己更新。到期日是星期日，隔天上班全公司的 Passkey 會一起失效——而那時候不會有人記得「mkcert」這三個字，更不會有人想到要去看 `backend\certs\`。

在這之前，**這件事沒有任何監控**。`letsencrypt_renew.ps1` 的 `[警告]` 只寫進 log，而「往 log 寫」正是這件事現在的失敗模式。

**新增 `routers/daily_tasks.py::_check_cert_expiry()`**，掛進既有的每日 08:00 排程（含錯過補跑）。

**① 門檻依「憑證總效期」自動切換 —— 這是整個設計裡最刻意的一點**

| 憑證種類 | 判斷依據 | 門檻 |
|---|---|---|
| 手動簽發（mkcert，822 天） | 總效期 > 180 天 | 60 / 21 / 7 天 |
| ACME 自動續期（LE，90 天） | 總效期 ≤ 180 天 | 21 / 7 / 1 天 |

理由：Posh-ACME 要到「剩 30 天」才會續期。**若對 LE 沿用 60 天門檻，每一張憑證都會在一切正常的情況下誤報一次**，大約每 90 天一次。狼來了的告警等於沒有告警，而這個告警存在的唯一目的，就是在好幾百天後的某一天真的叫得動人。

反過來，LE 剩 21 天還沒換掉，代表自動續期**已經失敗過一輪**，那才是真警報。

**② 讀檔，不對自己開 TLS 連線**

`start.bat`／`autostart.bat` 是 `if exist certs\cert.pem` 才加 `--ssl-*` 參數，uvicorn 載入的就是那個檔。讀檔沒有網路依賴、不受服務當下狀態影響，測試也不必真的起一個 TLS server。憑證檔不存在（純 HTTP 模式，也是憑證出事時的緊急退路）就安靜跳過。

**③ 信裡直接寫「該怎麼修」，而且依簽發者分兩種**

mkcert → 重跑 `https_setup.ps1 -ExtraNames motrix.internal -Force` ＋ 重啟，並註明「同事電腦上的 CA 不用動、Passkey 也不會失效」。
LE → 查排程工作、查 `letsencrypt_renew.log`、查 Cloudflare token 是否失效。

同時把影響範圍講清楚，免得收信的人以為「憑證過期＝系統掛了」而驚動所有人：**Passkey 完全不能用；密碼／TOTP／QR 仍可用**（點「進階 → 繼續前往」）；系統與資料不受影響。

**④ guard key 帶 fingerprint，並且收斂**

換一張憑證就換一組 fingerprint，告警自動重置；比當前更早的門檻永遠不會再被查詢，所以一併刪掉。這個前綴在 `system_settings` 裡最多只佔 1 列——理由同 `_prune_case_project_guard_keys()`，本專案已經為「只寫不刪」付過代價（`module_versions` 曾長到 626,725 列、約佔 301MB 資料庫裡的 270MB）。

**⑤ 週邊**

`cert_expiry` 加進 `notification_prefs.py::EVENT_GROUPS`（漏了會被 `test_notification_prefs_coverage.py` 擋下——那正是 `case_project_overdue` 當初踩的坑）。`cryptography` 補進 `requirements.txt` 與打包守門的 `$depCheck`：先前只是 `webauthn` 的傳遞依賴，既然自己 import 了就該明寫。

**實測**：把正式機真的那張憑證抓下來餵進去 → 822 天 / issuer `mkcert MOTRIX\Motrix@Motrix` / 判定手動簽發 → **第一次告警落在 2028-10-11**（到期前 60 天）。開發機沒有 `certs/` → 靜默、不報錯。

**測試 16 題**，並逐一破壞產品邏輯驗證測試真的抓得到：門檻不切換／過期不分桶／guard key 去掉 fingerprint／遠期不收斂——**四個破壞全部變紅**。全套非 e2e **591 passed**。

> ⚠️ **寫測試時自己踩到的坑，值得記在這裡。** 一開始用「重簽一張憑證」來模擬時間經過，但重簽會換掉 fingerprint，而 fingerprint 正是 guard key 的一部分——於是 `test_expired_next_week_resends` 會在 7 天分桶邏輯壞掉的情況下**照樣變綠**，看起來在驗分桶，其實驗的是「換了憑證會重寄」。**跟 `4ffe190` 是同一種錯**：斷言沒有守住它該守的東西。改成用 `fake_cert` fixture 直接控制 `_read_serving_cert()` 的回傳值，把「同一張憑證變舊」與「換了一張新憑證」分成兩個可以獨立控制的維度。是相鄰那題（`test_expired_within_same_week_does_not_resend`）先紅，才把這件事翻出來。

---

### 2026-09-11（凌晨 01:05）— Let's Encrypt 公開憑證方案：把「每台裝 CA」這件事整個消滅掉

**起點是一個問「能不能自動化」的需求，答案是不能，但問題本身有解。**

使用者問：能否讓瀏覽器點一下 PASSKEY 就自動下載並執行憑證安裝，Windows、macOS 都可以。

**不行，而且這不是缺功能。** 任何網頁都無法把憑證寫進系統信任存放區 —— 這是 Windows 與 macOS 共同的安全邊界。可以的話，任何網站都能讓你信任它偽造的憑證。在自簽憑證的前提下，兩個平台能做到最接近的版本就是「下載檔案 → 執行 → 輸入管理員密碼」，那正是 `setup_passkey_client.ps1` 已經在做的事。

**但這個需求有另一條路：不要讓使用者裝 CA，改用全世界瀏覽器本來就信任的憑證。**

三個前提都實測確認過：

| 前提 | 實測 |
|---|---|
| 網域在可控的 DNS 商 | ✅ `miactw.com` 在 Cloudflare（`maria`／`cameron.ns.cloudflare.com`），有 API |
| 子網域未被佔用 | ✅ `erp.miactw.com` 目前是 NXDOMAIN |
| 主機不需要對外開放 | ✅ 用 **DNS-01** 驗證，Let's Encrypt **不會**來連你的主機 |

第三點是關鍵。一般印象中「申請憑證要開 80 埠讓對方來驗」那是 HTTP-01；DNS-01 只需要證明你控制 DNS 區域，正式機永遠不必暴露在網際網路上。

**順帶解掉兩個既有隱憂**

1. **RP ID 未來被迫變更的風險。** 目前 RP ID 是 `motrix.internal`，一個只在內網有意義的名字。使用者提過「未來會有 VPN、主機可能變更網路環境」—— 那個未來一到就得換名，而**換 RP ID 會讓所有既有 Passkey 失效且無法救回**（`webauthn_credentials` 刻意沒存 rp_id）。改用 `erp.miactw.com` 之後，換網段、加 VPN、換辦公室都不影響。
2. **每台機器要能解析 `motrix.internal` 的問題。** 現在必須改 DNS 指向 Peplink 或手動加 hosts（兩台機器的主網卡 DNS 都是 8.8.8.8，都曾解析失敗）。公開 DNS 上的名字任何機器用任何 DNS 都解析得到。

**新增 `backend/tools/letsencrypt_renew.ps1`（228 行）**，四個刻意的設計決定：

- 比對「服務中的憑證」與「Posh-ACME 手上的憑證」，**有變動才動作**
- 用 **fullchain** 而非單張葉憑證 —— 少了中繼憑證，有些客戶端會驗不過
- **不呼叫 `restart.bat`**：它前景跑 uvicorn 且以 `pause` 結尾，排程會永遠不返回。改為沿用 `apply_update.ps1` 的「只停服、讓 autostart crash-restart 迴圈接手」
- `-InstallSchedule` 會檢查 `POSHACME_HOME` 是否為機器層級變數。Posh-ACME 預設把憑證存在 `%LOCALAPPDATA%`，排程若以 SYSTEM 跑會看不到個人帳號簽的憑證 —— 那會變成**「每天都成功執行但什麼都沒做」，直到 90 天後全站 HTTPS 一起壞掉**

重啟後刻意對 `https://erp.miactw.com:666/api/ping` 而非 localhost 驗一次：要驗的正是「憑證對這個名字有效，且簽發者公開受信任」。

**文件同時寫明這次切換的代價**，不能只講好處：LE 憑證只涵蓋 `erp.miactw.com` 一個名字（Let's Encrypt 不可能為私有 IP 或不存在於公開 DNS 的名字簽發），切換後用 `172.16.10.177` 或 `motrix.internal` 存取都會跳憑證主機名不符警告，**所有人必須改用新網址、更新書籤**。沒有事先講的話，第二天早上會收到一整批「系統壞了」。

另外把 `PASSKEY-CA-ROLLOUT.md` 的進度表更新為實況 —— 它還停在「第 2、3 步完成，卡在第 4 步」，但 4～7、9 步其實都做完了。文件與現實脫節正是本專案一再吃虧的地方。

**尚未執行。** DNS 記錄與正式機上的動作都需要人操作；決策點記在 `MOTRIX-ERP-QUICK.md` §3.3c 與 §11。

---

### 2026-09-11（深夜接續）— Passkey 從「功能上線但從來沒能用」到真的能用

四個根因，**每一個都足以讓整條路走不通**。它們能一路存活到現在，是因為 Passkey 一直卡在更前面的環節（RP ID 未設定、憑證未生效），**從來沒有人真的走到那一步** —— 功能上線但從未被端到端驗證過的典型代價。

**① `a1f56e9` base64url 解碼**

`routers/auth.py` 的 register/complete 與 login/complete 用 `base64.b64decode()` 解 rawId。那是標準 base64 解碼器：不認得 base64url 的 `-` 和 `_`，又要求 padding 長度正確。而前端產出的正是「base64url 且把 `=` 全部去掉」的格式，所以每一次都丟 `binascii.Error: Incorrect padding`。

錯誤被上層的 `except Exception` 收斂成一句籠統的「認證器驗證失敗」，畫面上完全看不出真正原因 —— **是靠正式機 `server.log` 裡的 `WebAuthn registration failed: Incorrect padding` 才定位到的。**

順帶統一前端編碼器：`login.html` 回傳標準 base64、`change-password.html` 是 base64url —— 同一個協定、兩個頁面、兩種格式。後端現在兩種都吃得下，但這正是本專案一再吃虧的漂移模式，統一成 WebAuthn 慣用的 base64url。測試 11 題（8 種長度參數化，padding 需求隨長度 mod 3 變化，只測一種會漏掉真正出事的）。

**② `4ffe190` credential 缺 `type` 欄位**

padding 修好後，正式機 log 的錯誤變成 `Credential had unexpected type`。py_webauthn 會驗 `type` 必須是 `"public-key"`，而前端送的 body 根本沒有這個欄位，後端兩個模型也沒宣告它 —— 就算前端有送，`body.dict()` 也不會帶過去。**兩邊都要改。**

> ⚠️ **這一輪的真正教訓在測試。** 上一輪的端點測試只斷言「錯誤不是 padding」—— 太寬鬆。padding 修好之後測試照樣綠，使用者卻還是拿到「認證器驗證失敗」，等於測試沒有守住它該守的東西，我還因此以為修完了。改成把已知的結構性錯誤全部列為不允許（padding／unexpected type／missing required／not a json object／unable to decode credential），**只有「真的走到密碼學驗證才失敗」才算通過**。

**③④ `34e0ce1` 用 CDP 虛擬認證器把整條路自動走完**

前面四輪來回都停在註冊，**沒有人真的走到「登入頁按 Passkey」那一步**。把註冊 → 重複註冊被擋 → Passkey 登入整條路自動化之後，當場抓到兩個純人工往返碰不到的 bug：

- **`login.html` 有兩個 `init()`**。JS 物件實字重複鍵是後者勝出，**而且不會有任何警告**。`checkWebauthnConfig()` 從來沒被呼叫過，`webauthnConfigured` 永遠是 false，「或使用 Passkey 登入」按鈕永遠不顯示 —— 註冊得起來卻永遠登不進去。
- **`verified.sign_count` 這個屬性不存在**。py_webauthn 3.0.0 的認證結果叫 `new_sign_count`，只有註冊結果才叫 `sign_count`。每次登入丟 AttributeError，被概括的 `except Exception` 收斂成一句 401「認證失敗」。同一段補上 W3C 7.2 的前提：只有新舊計數至少一邊不為 0 時，計數沒前進才算複製徵兆 —— **Windows Hello、iCloud／Google 同步的 passkey 都不實作計數器、永遠回 0**，少了這個前提它們每次登入都會被誤判成重放攻擊。

新增 `backend/tests/test_e2e_passkey_2026_09_11.py`。測試設計上踩到、記在檔頭的坑：測 `excludeCredentials` 不能靠「第二張要註冊成功」（它本來就該失敗）；Passkey 登入必須在同一個 browser context 裡做（虛擬認證器的憑證綁在 context 上）；uvicorn 用 port 0 抽到 1723（PPTP）時 Chrome 回 `ERR_UNSAFE_PORT`；完成訊號改看 ok/err 出現而非 busy 變 false —— **點擊沒生效時 busy 從頭到尾是 false，「什麼都沒發生」會被判成「順利完成」**。

**使用者已實測確認：可以註冊 Passkey，也可以用 Passkey 登入。**

---

### 2026-09-10（最深夜 23:38）— 打包直譯器守門從「只擋」改成「先自己找對的那一支」

同日稍早加的直譯器守門**擋是對的**（總比 470 題全 E 好判讀），但它只解析 PATH 上的第一支 python，缺套件就直接 Fail。問題是這台機器有 4 支 Python，「第一支」是誰完全取決於呼叫端的環境：

| 路徑 | 版本 | 狀況 |
|---|---|---|
| `...\hermes-agent\venv\...\python.exe` | 3.11.15 | 依賴齊全 |
| `...\Programs\Python\Python313\python.exe` | 3.13.3 | 缺 pyotp |
| `...\Microsoft\WindowsApps\python.exe` | (stub) | — |
| `...\AppData\Local\Python\bin\python.exe` | 3.14.5 | 缺 multipart |

我自己的 shell 解析到第一支所以一直能跑，**使用者自己的 PowerShell 解析到 WindowsApps 那支就直接 Fail** —— 同一支腳本一個能跑一個不能，而使用者除了手動改 PATH 沒有別的辦法。

改成把候選逐一試過去，挑第一支依賴齊全的來用；全都不合格才 Fail，**而且列出每一支各缺什麼**。仍然印出實際選中的路徑 —— 守門的原意是可追溯，不是為了擋人。

> ⚠️ **`0da86bf`：新加的探測迴圈立刻踩到 PS 5.1 原生執行檔 stderr 地雷（本專案第 5 次）。** 腳本開頭是 `$ErrorActionPreference = "Stop"`，迴圈用 `2>&1` 收 python 的 ImportError 來判斷缺哪個套件 —— 但在 `Stop` 之下，原生執行檔只要往 stderr 輸出任何東西就會被 promote 成終止型 `NativeCommandError`，**即使那正是我們預期要發生的事**。結果是選對了直譯器卻在下一支候選就整個腳本中止。前四次分別是 pip install／tar／db 備份／mkcert，記憶檔與 QUICK.md 都有記載，**我寫這段修正時卻沒套用**。

---

### 2026-09-10（最終）— 慢請求記錄：不做沒根據的改動，改做看得見

**先更正一個我自己提出的錯誤判斷。** 前一輪把「真人存報價單可能卡 30 秒」歸因於 commit 之後那幾筆 notification／audit_log／module activity 寫入，並打算把它們移出請求路徑。做了**逐段計時的可控實驗**後證實那是錯的：

| 段落 | 另一條連線握鎖 6 秒時的耗時 |
|---|---|
| `_audit` | 0.01s |
| `notify_module_activity` | 0.03s |
| **主 INSERT/commit** | **6.17s** |

被卡住的是主 INSERT/commit 本身 —— **SQLite 單一寫入者的本質，不是哪段程式碼寫錯**。把那幾筆寫入移走完全不會有幫助。

**接著把可能長時間佔鎖的地方全查過一遍**

| 位置 | 實情 |
|---|---|
| `db.py:176` VACUUM | 在 `reset_demo_db()`，只動 demo 那個**獨立檔案**，不鎖正式庫 |
| `db.py:2560` VACUUM | 在 migration 裡，啟動時跑一次，非日常路徑 |
| 三處 `BEGIN IMMEDIATE` | 承攬商／發票／請款的防超額，刻意的短交易 |

**結論：正式路徑沒有任何東西會長時間佔住寫入鎖。** 所以**沒有**對全站共用的寫入路徑動刀 —— 那會是沒有根據的改動。

**改成做可觀測性**

超過門檻（預設 5 秒，可用 `MOTRIX_SLOW_REQUEST_SECONDS` 調整）的 `/api/*` 請求寫一行 `SLOW REQUEST` 到 log，**不改變任何行為**。理由是這種事真的發生時完全看不見 —— 使用者只覺得「這次存檔特別久」，不會回報也沒有紀錄。

> 日後若有人回報「存報價單偶爾要等很久」：先看 `server.log` 裡的 `SLOW REQUEST`。有紀錄就是真的撞到鎖，沒有就要往別的方向查。

**測試** 4 題，含一題端到端釘住真正要抓的情境（另一條連線握著寫入鎖時，建立報價單的請求會被拖住且被記下來 —— 只握 1.5 秒，證明機制成立即可）。靜態檔案刻意不列入，避免稀釋訊號。已用「還原 middleware 再跑一次」驗證會紅。全套非 e2e **563 passed**。

---

### 2026-09-10（追到底）— flaky e2e 的完整真相：前端守門漏洞 ＋ 30 秒鎖等待

做法是**先加強測試自己的診斷**，而不是繼續猜。原本的 dump 只印 approver 那一頁的請求與 console，分辨不出三種不同的失敗原因。加上：

- **(0)** 建立端 page1 的所有 API 往來 ＋ 對話框 ＋ console ＋「送出但沒收到回應」的請求
- **(a)** 資料庫實際有哪幾張單、各自 tiers 數、`quote_seq`、建立時間
- **(b)** approver 頁面的 Alpine 狀態（實際載到哪張單）
- **(c)** 頁面上現有按鈕 ＋ 失敗當下全頁截圖

加強後**第 1～2 輪就抓到**（先前 9 輪抓不到）。

**真相有兩半，而且都跟先前的推論不同**

**① 前端守門有漏。** 使用者在載入時的取號還沒回來就按送審 → POST 帶空號送出 → 後端派了 `001` → 取號這時才回來拿到 `002`，而 `q.quoteNo` **仍是空的**（POST 回應還沒到），所以 `!this.q.quoteNo` 這個守門**放行了**，畫面被寫成 002。測試的等待條件「畫面出現 `MQ-`」立刻被 002 滿足，讀走 002 後 `ctx1.close()` 把還在飛的 POST 一起中止 —— approver 就被送去一張不存在的單。

> 修法：`apiSave()` 一開始就設 `_quoteNoFrozen`，取號守門改看**「有沒有開始存檔」**而不是「目前有沒有號碼」。

**② 鎖等待是真的。** ⚠️ 先前在測試註解裡寫「原作者猜的 SQLite WAL 鎖等待方向是錯的」—— **那句才是錯的，已更正**。`db.py:119` 是 `sqlite3.connect(path, timeout=30)`，任何一次寫入在鎖被佔住時最多等 **30 秒**。建立報價單 commit 之後還要再寫 notification／audit_log／module activity，各自開新連線；只要此時有背景排程（月報、逾期檢查等，整個 pytest session 期間都在跑）正在寫，這支 POST 就會卡滿一輪。

> 修法：測試等待時限從 20 秒放寬到 **45 秒**並在註解寫明理由（必須容得下那 30 秒），等待條件也改成等 Alpine 的 `isNewRecord` 翻成 false（存檔成功才會設），而不是等畫面出現 `MQ-` 字樣。

**結果**

| 階段 | e2e 通過率 |
|---|---|
| 修 peek 競態前 | 6 輪中 **4 輪失敗** |
| 修 peek 競態後、本輪之前 | 12 輪中 **6 輪失敗**（20 秒等待太短，把「只是慢」也判成失敗） |
| **本輪之後** | **10 輪全綠** |

全套非 e2e **559 passed**。

**⚠️ 順帶暴露的正式環境隱憂（本輪未動）**

那個 30 秒 busy timeout 表示真人存檔時若剛好撞上備份或排程寫入，**畫面可能卡住最多 30 秒**。測試環境因為每個測試都重開 server、背景排程整個 session 都在跑而特別容易撞到；正式機只啟動一次、撞到機率低很多，但不是零。

---

### 2026-09-10（收尾）— `copyToNew()` 的 `???` 假單號＋後端單號格式守門

**先更正一個判斷**：前一則說「`???` 一定撞號、後端必定改派」——**那是錯的**，沒查證就講了。實測結果是：

```
ValueError: invalid literal for int() with base 10: '???'   @ quotations.py:913
```

`MQ-202609-???` 這種字串**不會**跟任何既有單號衝突，所以 INSERT 會**成功**，接著解析序號的 `int('???')` 直接炸成未捕捉的 ValueError → 500。使用者只看到「儲存失敗」，而複製的內容在頁面載入時就已經從 sessionStorage 清掉，**重新整理再也回不來**。觸發條件是複製當下取號失敗（後端短暫不通或 `/api/next-quote-no` 出錯）。

**修法三層**

1. **後端守門（最重要）** — 新增 `_QUOTE_NO_RE = ^MQ-\d{6}-\d{3}$`。client 送來的單號格式不合就記一筆 warning 並改由後端派號。不管哪個 client、哪個版本送什麼過來都擋得住 —— 這是今天一連串單號問題的共同教訓：**後端才是單號的權威**。
2. **序號解析加 try/except 兜底** —「解析單號」不值得讓整支建立端點掛掉。
3. **前端不再造假號** — `copyToNew()` 取不到號時改用 `?copy=1` 帶過去，載入端接受這個無號複製模式並走同一支取號。順手把新增模式與無號複製的取號抽成共用 `_peekQuoteNo()`，兩邊才會有同一套「晚到覆蓋」守門（同日 `a619206` 修的那個競態）。

**測試**：`test_quote_no_validation_2026_09_10.py` 11 題（9 種畸形單號參數化 ＋ 合法單號照用 ＋ 後端派號後 `quote_seq` 要前進）＋ e2e `test_e2e_copy_to_new_2026_09_10.py`（把 `/api/next-quote-no` route 成 503 逼出取不到號的路徑，走完複製→存檔）。兩者都用「還原修改再跑一次」驗證會紅（後端紅在 ValueError、e2e 紅在網址帶 `?id=MQ-202609-???`）。全套非 e2e **559 passed**。

**⚠️ 殘留未解，不宜當成已解決**

`test_login_create_submit_approve_smoke` 仍有約 **2/16** 的偶發失敗（30 秒逾時）。`a619206` 修好 peek 競態後曾連 **6 輪全綠**，之後 e2e 檔案增加到 5 個／8 題、負載上升又開始出現。**嘗試 9 輪抓不到診斷 dump，無法確認是同一個根因回來還是純負載。** 目前約略回到今天開工前的基準（當時量到 1/18）。

---

### 2026-09-10（最後）— 報價單單號競態：長年 flaky e2e 的根因，連帶修掉兩個真實缺陷

那支 e2e 的註解原本寫「**根因還沒有抓到**」，靠不斷加大等待時限吸收，推測方向（SQLite WAL 鎖等待）是錯的。這次用可控實驗找到了。

**真正的根因**

`quotation-form.html` 載入時會非同步打 `/api/next-quote-no` 取號。**那個回應可能在使用者按下存檔／送審之後才回來**，直接指派就把存檔回應剛回填的真正單號蓋成新 peek 到的下一號 —— 畫面顯示 `MQ-YYYYMM-002`、資料庫其實只有 001，簽核的人照畫面上的號碼開，就開到一張不存在的單。

跟同日在 `reports.js` 修的是**同一類**「晚到的非同步回應蓋掉新狀態」。

**一共修三個相關缺陷**

1. **peek 競態**（上述）：只有在「還沒有號碼、且還是沒存過的新單」時才採用 peek 結果。
2. **前端不再自己猜號**：`saveDraft()` 原本在 `quoteNo` 為空時**寫死** `MQ-{ym}-001` 當暫用號送出 —— 那個值幾乎一定被用掉了，後端撞號改派下一號，畫面就跟實際存的對不起來。改成拿不到號就送空值交給後端派；存檔回應**一律**回填（原本只在「號碼不同」時才回填，導致前端號碼為空時網址永遠補不上 `?id=`，重新整理就開成一張新的空白單）；載入取號逾時 3 秒 → 10 秒；拿不到號時畫面顯示「（儲存後自動編號）」而不是空白。
3. **送審失敗留下孤兒單**：`create_quotation` 是「先 INSERT+commit，再建簽核層級」。層級解析失敗拋 400 時，那筆 `status='待審核'` 且**沒有任何簽核層級**的單已經留在資料庫 —— 會出現在清單裡、永遠簽不掉，而使用者以為沒建成，再按一次就又多一張（單號還往後跳）。改成**補償性刪除**：建不出簽核流程就把剛建立的那筆連同 `case_stages` 一起收回，並**依實際留存的報價單重算 `quote_seq`**（不是單純減一 —— 併發下會踩到別人剛拿的號），再往外拋。

**驗證**

| | 修復前 | 修復後 |
|---|---|---|
| 可控重現腳本 | 6 次中 **2 次**畫面號碼與資料庫對不起來 | 8 次 **0 次** |
| 完整 e2e | 6 輪中 **4 輪**失敗 | 6 輪 **全綠** |

三項都用「還原修改再跑一次」驗證測試會紅。另修兩支 e2e 的等待條件：smoke test 原本只等 `.form-quote-no` 有內容，新的佔位字會立刻滿足它而在真正號碼回填前就往下走，改成等 `MQ-` 出現；T100 測試只等按鈕存在會讀到空表格，改成等值真的出現。

全套非 e2e **548 passed**／e2e **7 passed**。

---

### 2026-09-10（稽核後續）— 處理三項待決策：刪死碼、接上公司名稱查詢

使用者裁示「沒用的刪、company/search 接上去、projects.py 刪」。

**1. 刪 `/api/cashier/summary`**（`cashier.py:142`）— 全 repo 只有自己的測試引用，內容是 `payable-queue` + `receivable-queue` 兩支的合併版，而前端分開呼叫那兩支。端點與測試一併移除。

**2. 接上 `/api/company/search`** — 客戶／供應商／承攬商三頁先前都只接了統編查詢，使用者必須先知道確切統編才查得到，想用公司名稱找只能自己去經濟部網站查完再回來貼。

- **新增 `frontend/static/gov-lookup.js` 共用查詢邏輯**：三頁的統編查詢已經各自有一份幾乎一模一樣的實作（連錯誤訊息文字都相同），再加三份必然漂移。
- 但**帶入表單各頁欄位名不同**（customers/suppliers 是 `taxId`、vendor-contractors 是 `tax_id`，客戶頁還會推斷產業別），所以只共用「查詢＋錯誤對應」，帶入由各頁自己的 `govApply()` 處理。
- UI 放在既有「政府登記資料查詢」卡片內、統編查詢下方以虛線分隔；結果清單顯示名稱／統編／登記狀態，點一列即帶入。

**3. 刪 `backend/routers/projects.py`**（592 行、19 支端點）— 2026-08-26 專案管理併入案件管理、`6089a8f` 從 main.py 移除註冊後就是死碼。確認過沒有任何 import（`_process_project_photo`/`_photo_root` 在 `photos.py`，`system.py` 是從那邊 import），前端也零呼叫。**`projects`/`project_logs` 資料表保留不動**（歷史資料）。`RETIRED_ROUTERS` 白名單同步清空，機制留著給下次「下線但檔案先留」用。

**測試**：新增 e2e `test_e2e_gov_name_search_2026_09_10.py`，三頁在**同一個 browser／server** 內跑完——不用 `parametrize`，因為每個 param 各起一台 uvicorn 加一個 chromium，會把同批其他 e2e 的等待擠爆（實測既有 `test_login_create_submit_approve_smoke` 的偶發失敗率因此從 1/18 升到 2/4，改成單一 browser 後回到 1/4）。GCIS 是外部政府 API，測試 monkeypatch `dashboard._gcis_get` 回固定資料。已用「還原前端再跑」驗證三頁都會紅，並用 Playwright 截圖肉眼複查版面。全套非 e2e **544 passed**。

**⚠️ 順手定位到既有 flaky 測試的根因**（該測試註解原本寫「根因還沒有抓到」）

診斷 dump 顯示：approver 開的是 `MQ-202609-002`，但簽核流程建在 `MQ-202609-001` —— **表單顯示的單號與實際存檔的單號不一致**。

路徑：`quotation-form.html` 載入時打 `/api/next-quote-no` 只給 **3 秒**（`AbortController`），逾時就讓 `q.quoteNo` 留空；`saveDraft()` 發現空值會**寫死** `MQ-{ym}-001` 當暫用號送出；後端 `create_quotation` 撞號時改派下一號並回傳真正的號碼，前端再回填。慢的時候畫面上的單號會跟實際建立的那張對不起來。

**本輪只定位未修** —— 這屬於報價單建立流程的行為變更，需要決定要改哪一端（拉長/移除前端 3 秒逾時、或不要寫死 001、或改成後端單一權威派號）。

---

### 2026-09-10（稽核）— 全系統模組串接與邏輯排查，修掉三項

使用者要求「按步驟逐步排查各模組系統串接跟邏輯，是否都有正確及遺漏」。以 10 個步驟做**機械化比對**（不是人工翻閱程式碼），每一項發現都附 `檔案:行號`。

**稽核方法**

| 步驟 | 方法 | 結果 |
|---|---|---|
| 前端↔後端 API | 452 個 fetch 呼叫點 vs 468 支已註冊路由雙向比對 | ✅ 零斷點 |
| Router 註冊 | 檔案／import／include 三方比對 | ⚠️ 1 項 |
| 頁面↔Sidebar | 53 頁 vs 導覽與 9 個徽章模組 | ✅ 完整 |
| 權限守門 | 486 個 handler AST 分析 | ⚠️ 1 項 |
| 漏 commit | 寫入 SQL vs commit 掃描 | ✅ 5 個警示全誤判 |
| demo 隔離 | 繞過 `get_db`／裸 `threading.Thread`／寫檔未判 `is_demo_mode` | ✅ 無破口 |
| 通知事件 key | 既有 ast 覆蓋測試 | ✅ 通過 |
| Schema 漂移 | **實際建一個全新 DB**，與既有 DB 逐表逐欄比對 | ✅ 完全一致 |
| 金額換算／簽核代理 | 全呼叫點一致性 | ⚠️ 1 項 |

**修掉三項**

1. **`pdf_gen.py::_case_closing_report_data()` 漏傳 `pretax`** — 13 個存活呼叫點中唯一漏的。2026-08-28 新增這個參數時掃了 reports.py／dashboard.py 的 12 個呼叫點，沒掃到 pdf_gen.py。後果：已核准稅額沖銷（`taxExempt`）的款項，結案報表 PDF 顯示**含稅**、畫面／Excel／營運報表顯示**未稅**，同一筆案件兩個數字。helpers 那句「拿不到 pretax 就維持舊行為」不適用——該函式的 SQL 本來就 SELECT 了 `pretax`，純粹漏接。

2. **`POST /api/quotations` 建立者取自 request body** — `quotations.py` 的 45 支寫入端點裡**唯一**沒有 `_require_user()` 的。`created_by` 與活動通知的操作者都直接用 `body.created_by`（client 送什麼算什麼），對照 `customers.py:84`／`shipping_notes.py:192` 一律從 session 取。已改為以 session 為準。**刻意不加角色限制**——「哪些角色可以建報價單」是 business policy 不是 bug，留給使用者決定。

3. **T100 傳票匯出的「已確認清單」與「反確認」有後端無前端** — `accounting_export.py:461/495` 早就存在，`unconfirm` 的 docstring 自己寫著是「標記錯誤時的**救援手段**」，但前端只接了 vouchers/preview/confirm。「確認已匯入 T100（排除下次匯出）」是一次標記整個日期區間的批次操作，按錯之後畫面上沒有任何回復方式。已補上可展開的已確認清單與逐筆反確認。

**另補一道防呆**：`test_router_registration_2026_09_10.py` 把「哪些 router 刻意不註冊」變成明確白名單。起因是 `routers/projects.py` 的 19 支端點在 `6089a8f` 下線後檔案留著、main.py 不再 include，架構地圖卻寫成「僅保留舊 API 供內部沿用」——實際上**全部 404**。現在新增 router 忘了 include 會被擋，要下線則必須來白名單補一筆寫明原因。架構地圖 §2.10 同步更正。

**驗證**：三項修復的測試都先「**還原修改再跑一次**」確認會紅才算數（PDF 那項紅在 1,050,000 vs 1,025,000、身分那項紅在存成被冒名的 `q_victim`、T100 那項紅在找不到「展開檢視／反確認」按鈕）。T100 新 UI 另用 Playwright 截圖肉眼複查版面。全套非 e2e **541 passed**／e2e **6 passed**。

**待使用者決策、本次未動**

- `/api/cashier/summary` 死碼（僅自身測試引用，內容是 `payable-queue` + `receivable-queue` 的合併版）
- `/api/company/search` 後端做好前端沒接（使用者只能用統編查，不能用公司名模糊搜尋）
- `projects.py` 592 行死碼檔案是否刪除

---

### 2026-09-10（最後）— 營運報表 Excel／PDF 匯出補上「季」範圍

接續同日 `6b9ec5c` 的畫面修復。**匯出先前完全不吃期別的季**：不論 `period` 是 `YYYY-Qn` 還是 `YYYY-MM`，都只產「當月收支」與「今年度收支」兩塊，季報的匯出檔內容跟月報一模一樣。

- 兩支匯出端點（`/api/reports/financial/excel`、`/pdf`）新增 `quarter` 參數，帶了才會多一張**「本季收支」工作表**（Excel）／多一個**本季收支段落**（PDF）。
- 沿用既有的 `write_income_table`／`write_expense_table`／`write_net_summary` 與 PDF 的 `income_rows_html`／`expense_rows_html`，不另寫一套版面。
- **刻意「加一張」而不是「取代當月那張」**：當月／本季／今年度三種口徑並存，跟畫面上三個範圍鈕一致，且不帶 `quarter` 時輸出與先前完全相同（有測試釘住）。
- 前端 `exportFile()` 在 `expensesScope === 'quarter'` 時才送 `quarter`。

**驗證方式（不只看測試綠燈）**

用開發機真實資料實際產出檔案檢查：Excel 工作表清單多出「本季收支」（A1 標題「2026 年第 3 季收支明細」、39 列），季收入 **498,440**／季支出 **307,472** 與該季三個月各自查詢的加總完全相符；真的跑 Edge 產出 **913KB** PDF 確認轉檔沒問題；再用 Playwright 開同一份 HTML **截圖肉眼複查**季段落版面（表格欄寬、合計列、與既有兩段風格一致，無溢出）。不帶 `quarter` 時工作表清單與 HTML 皆無「本季」字樣。

**測試**：新增 3 題（Excel 端點帶/不帶 `quarter` 的工作表差異＋季外案件不得混入、匯出端點的 `quarter` 驗證、`_build_report_html` 段落與合計列）。其中 HTML 那題**改用真實 `_collect()` 組資料而非手搭 dict**——第一版手搭少了 `totalReceivable` 直接 `KeyError`，手搭的假 data 會隨程式演進失效。全套非 e2e **535 passed**／e2e **5 passed**。

---

### 2026-09-10（更晚）— 營運報表期別不同步修復＋新增「季」範圍

**使用者回報：「營運報表切換月／季／年時，財務資料不會跟著切換。」** 查證後確認**後端一直是對的**——`_collect()` 的 `periodCases`/`periodReceived`/`periodNet` 實測確實隨期別變動（開發機真實資料：2026-07 = 498,440、2026-Q3 = 498,440、2026 全年 = 2,279,012）。壞的是前端狀態同步。

**根因**：「本期收支」KPI 區塊與「已收款／未收款／月支出」三個分頁走的是獨立的 `/api/reports/expenses-monthly`、`/api/reports/receivables-monthly` 兩支資料流。2026-09-09 的 `56e52b3`（刻意把 recv/out 改成不跟隨 period-bar）與 `6bfcafb` 只在 `init()` 同步過一次期別，而 `prevPeriod()`／`nextPeriod()`／`switchType()` 以及 period-bar 的年/月/季下拉**全都沒有跟上**——這三個函式自初始 commit 至今從未被改過。結果整頁十四個分頁、三個 KPI 區塊裡，只有「本期新成案」「本期收款」兩張卡片真的會跟著期別切，其餘一律釘在真實當月。

| 區塊 | 修復前 | 修復後 |
|------|--------|--------|
| 業績核心「本期新成案」「本期收款」 | ✅ 會跟著切 | ✅ 不變 |
| 業績核心 精算毛利／覆蓋率／Backlog | ❌ 全歷史（設計如此） | 不變（設計如此） |
| 「當月收支」4 張卡 | ❌ 永遠釘在真實當月 | ✅ 改名「本期收支」，跟著月/季/年 |
| 已收款／未收款／月支出 分頁 | ❌ 各自獨立月份選擇器 | ✅ 跟著 period-bar，選擇器保留可覆寫 |
| 財務概況 6 張卡 | ❌ 全歷史餘額快照（設計如此） | 不變（設計如此） |

**修法**

- **同步點收斂到 `loadData()` 開頭單一處**（新增 `_syncSubPeriods()`）。所有切期別的路徑最後都會走到這裡，日後新增觸發點不必再記得補一次——原本正是「只有 `init()` 做了、其他路徑沒做」才出事。三個各自手拼快取鍵的呼叫點也收斂成 `_expensesKey()`／`_receivablesKey()`（鍵欄位漂移就是本 bug 的成因）。
- **兩支端點新增 `quarter` 參數**（1-4，範圍外 400；非整數由 FastAPI 型別轉換擋成 422）。`_build_income_expense_scopes()`／`_build_receivables_scopes()` 增加 `quarter*` 欄位；`_month_expense_slice()` 抽成 `_months_expense_slice()` 讓季共用同一套截取邏輯（**刻意維持月份前綴字串比對而非日期區間比對**——`details` 的 `date` 不保證是完整 `YYYY-MM-DD`，改成區間比對會把只有 `YYYY-MM` 的資料靜默丟掉）。
- **季是純增量欄位**：不傳 `quarter` 時回空集合，`month*`／`year*` 行為零變化。Excel／PDF／每月結算寄信等既有呼叫端完全不受影響（有測試釘住）。
- 三個範圍的畫面文字改用 `_scopePick()`／`scopeLabel` 統一取值，消掉 7 處只處理兩種範圍的 ternary（加第三種就得逐處補，漏一處就是靜默顯示錯範圍的數字）。

**過程中被新增的 e2e 測試抓到一個競態（修 A 才浮出來的 B）**：`loadExpenses()`／`loadReceivables()` 原本在**回應抵達時**才計算快取鍵。期別若在請求飛行途中被切走（7 月 →8 月按很快），就會把 7 月的資料貼上 8 月的鍵，之後守門看鍵相符便不再重載，畫面**永遠**卡在舊月份。已改為發出請求當下就算好鍵並隨這一次請求走，過期回應直接丟棄；`loadData()` 本身也有同一類競態，一併處理。這個競態在同步修好之前不會顯現（因為根本沒人重載）。

**測試**

- 新增 `test_reports_quarter_scope_2026_09_10.py` 9 題：參數驗證、季 == 該季三個月加總、季恆等式、不傳 `quarter` 時的向後相容、`_months_expense_slice` 重構等價。
- 新增 e2e `test_e2e_reports_period_sync_2026_09_10.py` 1 題：真實瀏覽器切月報 7→8→季報 Q3→年報，逐步斷言 KPI 數字。**已用「還原前端修改後重跑」驗證這支測試確實抓得到本 bug**（切到 2026-07 時當月收入停在 0），不是空轉的測試。
- 全套非 e2e **532 passed**／e2e **5 passed**。

**已知未處理**

- Excel／PDF 匯出仍走既有 `expense_month` 參數、不含季範圍（本次未改，行為與修復前一致）。
- 既有 `test_login_create_submit_approve_smoke` 在 18 輪中偶發 1 次逾時（等「預覽後簽核」按鈕），與本次改動無關，另案。

---

### 2026-09-10（稍晚）— 本週稽核：補回落後文件＋修掉四項已上正式機的缺陷

**新增 `WEEKLY-AUDIT-2026-09-07_2026-09-10.md`**（根目錄）——本週 82 個 commit 的逐模組拆解、異常時間軸（每筆標到根因檔案:行號）、12 項排查 checklist、缺陷清冊、未部署差異。

- **叫料 API（`routers/material_orders.py`）六個缺陷**，全部已在正式機執行中：漏 `conn.commit()`（端點回 200 但資料庫沒寫）、`save_quotation_json()` 參數錯位會污染 `status` 欄位、`_audit()` 簽名錯誤、已結案守門讀錯 key 成死碼、兩支端點皆缺擁有者檢查（IDOR）、GET 直接索引金額鍵。已全數修復。
- **`_check_quotation_owner()` 抽到 `helpers/quotations.py`**（第三個呼叫點），`routers/quotations.py` 改為引用，行為不變。
- **打包測試關卡長期失效**：①PATH 上 4 個 Python，打包解析到沒裝 `python-multipart` 的 3.14 ⇒ 整套測試全 E ②`%TEMP%` 下損壞的 `pytest-current` reparse point 讓 pytest 在 session 收尾拋 `PermissionError`，測試全過也回非 0。後果是 09-10 上線的 `9b0ad79` 沒跑過 pytest。
- **`requirements.txt` 補 `python-multipart>=0.0.9`**（09-07 `90c6f31` 漏掉）。
- **`test_webauthn_basic.py` 3 題失敗隨部署上線**（`f8198e9` 改 503 沒同步改測試）已修，另補一題正面驗證 503 行為。
- **修掉 `ee4664a` 繞過的 flaky 測試本身**（`test_cloud_storage_2026_09_07.py` 斷言範圍太寬，會被其他測試的背景執行緒干擾）。
- 驗證：全套非 e2e **502 passed / exit 0**，本週第一次完全綠燈。
- ⚠️ **這批修復與 `aeefcc6` 都尚未部署**；`aeefcc6` 缺席代表正式機 Passkey 目前不可用（後端會回 503，唯一設定入口在該未部署頁面）。

---

### 2026-09-10 — 月支出顯示修正、WebAuthn 設定可配置化、案件超期通知

**四項重要改動，已部署到正式機 commit 9b0ad79**

#### Workstream B — 營運報表月支出頁籤顯示修正
- **問題**：`reports.html` 頁籤徽章寫死顯示年度總額 (`expensesTotals.total`)，跟同頁其他地方的月/年度 `expensesScope` 切換邏輯不一致
- **修正**：`reports.html:434` 改為依 `expensesScope` 判斷，使用同頁 592 行的正確邏輯：`expensesScope==='month' ? monthExpenseTotal : expensesTotals.total`
- **檔案**：`frontend/pages/reports.html:434`

#### Workstream C — WebAuthn RP ID / Origin 改為系統可設定
- **背景**：原本 `WEBAUTHN_RP_ID`/`WEBAUTHN_ORIGIN` 寫死在環境變數，預設值是 `localhost` 與 `http://localhost:5000`，正式機用 IP 位址服務會導致 Passkey 「invalid domain」 error
- **架構變更**：環境變數 → `system_settings` 表可動態配置
  - `backend/routers/auth.py:724-725` 刪除常數，改用 `_webauthn_rp_id()` / `_webauthn_origin()` 動態取值
  - 四個 WebAuthn 端點（register/login begin/complete）在未設定時回傳 503「尚未設定 WebAuthn 網域」
- **新增後端 API**：
  - `PATCH /api/settings/webauthn-config` — superadmin 可設定 RP ID / Origin（`backend/routers/system.py`）
  - `GET /api/settings/webauthn-config` — superadmin 可查詢現有設定
  - `GET /api/system/webauthn-config-status` — 公開端點，前端用來判斷是否顯示 Passkey 按鈕
- **前端改動**：
  - `login.html` / `change-password.html`：未設定時隱藏 Passkey 按鈕，顯示「尚未設定 WebAuthn 網域」提示
  - 新增 `checkWebauthnConfig()` 方法在頁面初始化時檢查配置狀態
- **檔案**：
  - `backend/routers/auth.py`（724-725, 764-800, 835-839, 863-904, 946-951）
  - `backend/routers/system.py`（新增 707-741）
  - `backend/main.py`（60-63，加入公開端點清單）
  - `frontend/pages/login.html`（180, 235, 300-322）
  - `frontend/pages/change-password.html`（217-218, 207-214）

#### Workstream D — 案件「專案期間」+ 超期通知新功能
- **需求**：案件資訊新增「專案期間」欄位，超過期限每天通知一次，之後每 7 天提醒一次
- **資料結構**：`caseRecord.projectTimeline = {startDate, endDate, status}` 存在 `data_json`（無 schema 異動）
- **前端**（案件管理）：
  - `case-management.js:679` — `ensureCaseRecord()` 加入預設值初始化
  - `case-management.html:824` — 新增「專案期間」區塊（開始日期、預計結束日期、倒數/超期天數顯示）
  - `case-management.js` 新增 `daysUntilDeadline()` 方法計算剩餘/超期天數
- **後端排程**：
  - `daily_tasks.py` 新增 `_check_case_project_timeline_deadline()` — 每日檢查超期案件
  - 超期當天寄一次，之後每 7 天寄一次（guard key: `caseproj_notif.{quote_no}.{days_overdue // 7}`）
  - 已掛進 `schedule_overdue_check()` 的 `_daily_run()` 與 `_startup_catchup()` 兩處
- **通知**：
  - `email_notify.py` 新增 `notify_case_project_overdue()` 函式，發送給所有 admin/superadmin
  - 郵件包含：案件號、客戶名、專案名、預計結束日期、超期天數
- **檔案**：
  - `frontend/js/case-management.js`（679, 1785-1795）
  - `frontend/pages/case-management.html`（824-837）
  - `backend/routers/daily_tasks.py`（24, 1084-1127, 1342-1343, 1356, 1373）
  - `backend/helpers/email_notify.py`（1378-1404）
  - `backend/helpers/__init__.py`（65，導出新函式）

#### 部署記錄
- **Commit 歷史**：
  - `f8198e9` — 四項功能改動
  - `9b0ad79` — 修正 `notify_case_project_overdue` 導出缺漏
- **測試**：正式機部署前所有改動已通過基本語法檢查
- **正式機驗證**：commit 9b0ad79 已成功套用，版本追蹤檔已更新，健康檢查通過
- **使用者操作**：
  - **WebAuthn 設定**：以 superadmin 身份進入 `company-profile-settings.html`，填入內部 DNS 解析的域名作為 RP ID 與 Origin（需先配置 DNS 指向正式機 IP 172.16.10.177）
  - **案件超期**：系統每日自動檢查，超期案件的 admin/superadmin 會收到郵件通知

#### 其他備註
- 營運報表修正後，月支出頁籤徽章會正確反應當月/全年度選擇，不再固定顯示年度總額
- WebAuthn 改動不需要重啟服務即生效（讀 DB，非快取常數）
- 案件超期通知倚賴既有的每日排程機制，無需額外設定
- 資料庫無 schema 異動（所有新欄位存在 `data_json` JSON 欄位內）

---

### 2026-09-09 — 案件財務應收應付總覽、當月收支六輪修正、WebAuthn/Passkey V1

> 本日條目為 2026-09-10 補記（當日未寫入本檔），細節見 `MOTRIX-ERP-QUICK.md` §12 同日各條目。

- **案件財務「應收應付總覽」**（`4c267ce`）：新增 `GET /api/quotations/{quote_no}/finance-summary`，不新增任何資料表/欄位；`helpers/quotations.py::summarize_payment_items()` 抽成共用（第三個呼叫點）。精算「額外支出」新增 `docNo` 單號欄位，後端零改動（settlement 整包存 data_json）。
- **精算未完結的額外支出納入月支出**（`c15ef84`）：`dashboard.py` 與 `reports.py` 原本都只撈 `settlement.status='finalized'`，草稿階段填的支出在任何月度數字裡都不存在；同時發現兩處歸月依據早已分岔。抽出 `helpers/quotations.py::settlement_extra_expenses()` 共用。
- **當月收支一晚六輪**（`3f9755f`→`c063a72`→`3e29ba7`→`c5a5d11`→`da88433`→`6bfcafb`，17:42~22:51）：含一個日期格式造成的跨月污染 bug，以及部門篩選。
- **營運報表當月/當年度應收獨立檢視**（`56e52b3`）：不再跟隨 period-bar，新增 `test_reports_receivables_monthly.py`。
- **WebAuthn/Passkey 裝置綁定登入 V1**（`efdb06f`→`0527524`→`4f14c68`→`cce89fe`）：後端新表＋端點、登入頁按鈕、裝置管理卡片、challenge 編碼檢查；`0527524` 同時修掉 `auth.py` 的用戶枚舉漏洞。
- **打包測試改用 `pytest-xdist` 平行化**（`98f3d7b`）：動手前先驗證序列/`-n auto` 兩邊 470 題 pass/fail 清單逐題一致，390 秒→166 秒。
- 其他：`507fff3` 部署儀表板開關合併成單一 GUI 小程式；`d03f453` 強制填寫收款日期；`aaeffb2` 業務開發暗黑模式白底修正；`0257fe7` 啟動伺服器改純 PowerShell。

---

### 2026-09-08 — 部署工具鏈連續事故排查（20 次部署嘗試／6 次失敗）與 QR 登入強化

> 本日條目為 2026-09-10 補記（當日未寫入本檔）。完整因果鏈見 `WEEKLY-AUDIT-2026-09-07_2026-09-10.md` §C-1，逐條細節見 `MOTRIX-ERP-QUICK.md` §12 同日各條目。

- **新增本機部署儀表板**（`8144d58`）：`backend/tools/deploy_dashboard.py`／`.html`，只綁 `127.0.0.1`，把「打包→推送→套用→回滾」變成按鈕點選；同批新增 `rollback_update.ps1`、`_dashboard_remote.ps1`、公開端點 `GET /api/system/deployed-version`。
- **第一次真實使用即連續踩雷**（由外而內）：`_ps_cmd()` 參數名被當成值加引號（`8d83021`）→ Unix `tar` 把 `C:\` 誤判成遠端主機語法且完全沒檢查 exit code、產出空殼部署包（`549d319`）→ 密碼讀取在管線 stdin 下卡死（`ebd182f`）→ 健康檢查連續三次偽陽性、改用 `_healthcheck_ping.py` 取代 curl.exe（`47d0cca`，**根因為合理猜測未證實**）→ 姊妹腳本 `rollback_update.ps1` 沒同步、打包 commit 記錄時機競態（`46fb6b6`）→ **儀表板「假成功」判定**（`Invoke-Command` 吞掉遠端結束碼）與健康檢查失敗原因被 `2>$null` 整個吞掉（`6ee3a6d`）→ 良性 asyncio `ConnectionResetError` 被算成錯誤（`2ea87e8`）。
- **【當晚最大根因】`ad04397`**：`_dashboard_remote.ps1` 呼叫的是正式機**既有安裝路徑**的 `apply_update.ps1`，PowerShell 進程用的是啟動當下讀進記憶體的內容，複製新檔案不影響本次執行，失敗回滾又會把新檔案蓋回去——**整晚對 `apply_update.ps1` 做的所有內部邏輯修復從未真正執行過**。修法是呼叫前先把套件裡的 `backend/tools/` 同步覆蓋過去。
- **`apply_update.ps1` 強化**：`-CheckOnly` 乾跑模式（`8f1b623`）、`-SkipAutoRollback`（`88abc2f`）、打包新增 `.ps1` 語法驗證關卡（`ece3c48`）、e2e 測試從硬性關卡分離（`55a98b7`）。
- **`GET /api/system/deployed-version` 讀檔沒處理 BOM 回傳空物件**（`1c8f2e8`）——PowerShell 寫出的 JSON 帶 BOM，Python 要用 `utf-8-sig`。
- **TOTP 登入新增手機掃 QR 核准**（`e3717b3`）＋**手機端免密碼核准**（`7596382`）：手機瀏覽器已有有效 session 時自動核准，session token 核對失敗刻意不計入共用鎖定計數器。新增 `test_totp_qr_push_2026_09_08.py`＋e2e 雙 context 測試。
- **`no_cache_static` 不再誤傷自架 vendor 函式庫**（`03723e8`）：`/static/vendor/` 改長效不可變快取，其餘維持 `no-store`；同時是 flaky e2e 的放大因子之一。

---

### 2026-09-07（緊急修復）— 修復 conftest.py 雲端備份隔離死碼，曾讓測試假資料寫進真實 G: 磁碟機

- 背景：這次系統性複查測試基礎建設時發現，`backend/tests/conftest.py` 的 `_app` fixture 原本對 `archive.py` 的隔離設定——patch `archive._ARCHIVE_BASE`／`_REALTIME_DIR`／`_WEEKLY_DIR`／`_DAILY_DIR`／`_UPLOADS_MIRROR_DIR` 五個大寫模組常數——其實早就是死碼：現在的 `archive.py` 已經改成 `_archive_base()`／`_realtime_dir()` 等會動態掃描 A-Z 磁碟機代號、尋找公司雲端硬碟掛載點的**函式**（見 2026-09-07 稍早的「雲端備份目標可插拔」重構），conftest.py 卻沒有跟著更新，導致這五行 patch 對現在的程式碼結構完全不起作用
- 實際影響：任何透過 API 建立/更新報價單、客戶、供應商的測試，其路由端點觸發的背景執行緒（`spawn_bg_thread(_backup_quotation, ...)` 等）呼叫的 `_backup_quotation()`/`_backup_customers()`/`_backup_suppliers()` 完全沒被這層隔離擋住，會做真正的磁碟機代號掃描——在這台開發機上（`G:` 剛好掛載著真實的公司 Google 雲端硬碟備份），這代表整個開發過程中只要曾經在 `G:` 掛載狀態下跑過整套 pytest，測試產生的合成資料就有可能真的寫進 `G:\我的雲端硬碟\系統存檔\即時備份\` 底下
- 逐一核對 G: 磁碟機實際內容後確認：`即時備份\報價單\` 資料夾混進約 30 份測試專用的假單號檔案（`MQ-TEST-*`／`MQ-CRGATE-*`／`MQ-CCR-*`／`MQ-CASH-*`／`MQ-HIST-*`／`MQ-CRINV-*`／`MQ-INVEMPTY-*`／`MQ-MARKPAY-*` 等，來自不同測試檔案各自使用的自訂測試單號），這些是各自獨立的檔案，只是新增雜訊，不影響資料夾裡其餘真實 7、8 月歷史備份的內容。**較嚴重的是** `即時備份\客戶\clients.json` 與 `即時備份\供應商\suppliers.json` 這兩個檔案——它們的設計是「全量快照」（每次呼叫整批覆寫，不是逐筆累加），今天在多次執行整套 pytest 期間，被最後一次跑到的測試所在的隔離假資料庫**整個覆寫掉**，導致這兩個檔案一度存的不是這台機器真實的客戶/供應商清單，而是某次測試的合成資料
- 修復：把這段隔離改成直接 `archive._archive_base = lambda: str(archive_base)`，patch 函式本身而非早已作廢的常數——這樣所有依賴它的 `_realtime_dir()`／`_weekly_dir()`／`_daily_dir()`／`_uploads_mirror_dir()`／`_pdf_mirror_dir()`（今天稍早新增的 PDF 存檔鏡像函式）全部自動一併正確隔離，不需要逐一分別 patch，也避免重蹈「`archive.py` 改了內部實作方式、`conftest.py` 對應的測試隔離設定卻沒有同步更新」這個同一種錯誤模式再發生一次
- 驗證：記錄修復前 G: 磁碟機 `即時備份\報價單\` 的檔案數（82），重新執行既有會建立報價單的測試後檔案數維持 82（沒有再新增），確認修復後測試不會再寫入真實磁碟機；全套 pytest 454/454 全過，確認這個修復本身沒有弄壞任何既有測試
- 善後：已對這台機器真實的開發資料庫執行一次 `archive._backup_customers()`／`archive._backup_suppliers()`，用資料庫目前的真實內容（13 個客戶、24 個供應商）重新整批覆寫 `clients.json`／`suppliers.json`，寫入後核對筆數與公司名稱皆正確對應真實資料。**`即時備份\報價單\` 資料夾裡殘留的測試假單號檔案刻意沒有主動清除**——各自是獨立檔案、不影響任何既有真實備份內容，是否要清掉留給使用者自行決定
- 這個隔離缺口存在的時間點推測早於今天這次系統性複查（很可能是先前某次把 `archive.py` 的常數重構成動態函式時沒有同步檢查 `conftest.py` 造成的），不是今天新引入的問題，只是這次剛好在系統性複查測試基礎建設時被找出來

---

### 2026-09-07（再加開）— 庫存新增自動採購建議（架構地圖 §6.6，DB 無異動）

- 背景：架構地圖 §6.6 原本建議「參考 Zoho Inventory/inFlow 等專業進銷存軟體，依安全庫存缺口＋供應商前置時間自動生成採購建議清單」，並寫「資料已齊備、開發成本不高」。複查後發現這個判斷不完全正確：系統確實有安全庫存門檻（`parts.safety_stock`，DB v66）跟紅/黃/綠水位燈號（`parts_summary()::_stock_level()`），但**完全沒有追蹤供應商前置時間**——`suppliers`／`parts` 兩張表都沒有對應欄位，這部分資料其實不存在
- 因應這個落差，實作時刻意拿掉 ETA 預估這塊，只做「該補多少、上次跟誰買、大概要花多少」：新端點 `GET /api/inventory/purchase-suggestions`。建議採購量 = `ceil(安全庫存 × 1.5) − 目前在庫`（補到既有水位燈號定義的黃燈門檻，不是只補到剛好等於安全庫存——否則採購完成後燈號會立刻從紅燈變黃燈，還是會被同一張建議清單抓到一次，等於沒解決問題）。只回傳目前在紅燈或黃燈區間、且已設定安全庫存（`>0`）的料號，紅燈優先排序、同燈號內依預估金額由高到低
- 供應商/單價來源：該料號最近一筆 `stock_batches` 進貨批次（依 `created_at` 排序，用 SQLite「單一 MAX() 聚合時其餘裸欄位保證來自產生該 MAX 值的那一列」特性一次查完，跟既有 `_m070_stock_batches()` migration 用的是同一個 SQLite 慣例），查無進貨紀錄則供應商留空、單價退回 `parts.cost`（料件標準成本）
- 前端 `inventory.html`：工具列新增「採購建議」按鈕（沿用既有 `lowStockCount > 0` 判斷式，跟「低於安全庫存」篩選 chip 同一組觸發條件，兩者天生一致不用另外同步），開啟唯讀 Modal 顯示清單（水位燈號／料號／品名／在庫／安全庫存／建議採購量／上次供應商／單價／預估金額）與預估總金額；v1 刻意不含「標記已下單」等狀態追蹤，避免範圍蔓延成一整套採購工作流程
- 新增後端測試 `test_purchase_suggestions_2026_09_07.py`（9 題）：無安全庫存門檻時不建議、紅燈料號正確算出補到黃燈門檻的缺口、黃燈納入綠燈排除、供應商正確取自最近批次、無進貨紀錄時供應商留空且單價退回標準成本、排序規則、總金額/筆數彙總、已出貨/報廢的序號不計入在庫
- 另新增一條 Playwright 前端 smoke test（`test_inventory_purchase_suggestions_modal_smoke`，附掛在既有 `test_e2e_playwright_2026_09_07.py`），驗證「採購建議」按鈕真的能點得通、Modal 內容正確渲染——純 API 測試看不出這類純前端 `x-show`/Modal 綁定問題。**這條新測試第一版本身就踩到一個典型的 Playwright 陷阱**：`inventory.html` 底下的主表格本來就會列出同一個測試料號（未篩選狀態），用整頁裸文字搜尋 `"text=料號"` 在 Modal 真正開啟、資料載入完成前就會誤判通過（找到的其實是背景表格裡那一列），修正為把查詢範圍用 `.locator(".modal-box", has_text="採購建議")` 限定在目標 Modal 容器內
- 同一輪順便把既有 `test_login_create_submit_approve_smoke` 的簽核等待時限從 20 秒再加大到 30 秒——這條測試被觀察到即使在「只跑這個檔案 2 個測試」的輕量情境下也會偶爾在同一個等待點逾時，說明先前「系統忙碌時才會慢」的假設不完整，根因目前還沒抓到，先用更寬的時限吸收，並在程式碼註解裡記錄這個未解之謎供下次排查
- pytest 454/454 全過

---

### 2026-09-07（加開）— PDF 存檔納入雲端每日備份鏡像（DB 無異動）

- 背景：QUICK.md §11 長期記載的已知限制——報價單/出貨單/承攬商匯款申請/開票申請憑據/請款單/結案報表這 6 類 PDF 檔案各自存在專案根目錄獨立資料夾（如 `報價單PDF/`、`出貨單PDF/`），不在 `uploads/` 底下，過去 `_mirror_uploads()`（2026-08-08 新增，只掃 `uploads/` 目錄樹）完全沒有覆蓋到。這些 PDF 是簽核完成後系統背景自動產生存檔的正式文件，DB 裡的 `quotations`/`shipping_notes` 等資料表本身有每日 JSON 備份能救回來，但已經產出的 PDF 檔案本身從未被雲端備份過——跟 2026-08-08 修復 uploads/ 照片缺口是同一類風險
- 把 `_mirror_uploads()` 原本的「按檔案 size+mtime 判斷是否需要複製」增量鏡像邏輯抽成共用函式 `_mirror_directory_incremental(local_root, dst_root_abs, s3_dir_root, exclude_demo_dirs=True)`，`_mirror_uploads()` 改成呼叫它的薄包裝（行為完全不變，純重構）
- 新增 `_pdf_archive_dirs()`：回傳目前實際生效的 6 類 PDF 目錄清單，**呼叫 `pdf_gen.py` 各自的 `_get_*_pdf_base()` getter**，不是直接假設專案根目錄下的預設資料夾名稱——這些 base path 可能被 superadmin 透過 `system_settings` 改到公司共用網路磁碟等自訂位置，備份要跟著實際生效的路徑走
- 新增 `_mirror_pdf_archives()`，掛進 `_daily_backup()`，跟 `_mirror_uploads()` 並列執行、各自獨立的 try/except（其中一個失敗不影響另一個），失敗會走既有的 `_write_backup_alert()` 告警路徑。雲端鏡像位置為 `PDF存檔鏡像\{類別}\`（跟 `上傳檔案鏡像\` 同一層），backend="s3" 時對應到 S3 key 前綴 `PDF存檔鏡像/{類別}/`
- 同步更新 `DR-SOP.md` 三處原本標注「仍未涵蓋」的過期記載（§3 第 2 點、Step 3 還原步驟、待辦事項總表）
- 新增測試 `test_pdf_archive_mirror_2026_09_07.py`（5 題）：`_pdf_archive_dirs()` 正確反映自訂設定路徑、6 類全部正確複製、不變檔案不重複上傳、目錄不存在時安全 no-op、`_daily_backup()` 確實有掛上這個新步驟
- pytest 444/444 全過（含既有 `TestMirrorUploads` 測試組全數維持通過，確認共用邏輯抽取沒有改變原本行為）

---

### 2026-09-07（末）— 補齊 requirements.txt 缺漏套件＋新增弱點掃描工具（DB 無異動）

- 背景：正式機長期不重建 Python 環境，`requirements.txt` 只列了 `fastapi`/`uvicorn`/`pydantic`/`aiofiles`/`pyotp`/`qrcode`/`boto3` 七項，但實際靜態掃描全部後端程式碼的 import 之後發現至少 4 個第三方套件完全沒被任何 requirements 檔記載過
- **`openpyxl`**（`network_plan_export.py`／`routers/accounting_export.py`／`routers/reports.py` 三處 Excel 匯出核心功能直接用到）與 **`Pillow`**（`routers/contractors.py` 是模組頂層 `from PIL import ...`，屬於 unconditional import——`photos.py` 對 PIL 的用法有做成函式內 try/except 的「可選」設計，但 `contractors.py` 這處沒有，若照現有 `requirements.txt` 在一台全新機器上裝環境，裝完啟動伺服器會在載入這個 router 的當下就整台起不來）：這兩個已補進 `requirements.txt`
- **`beautifulsoup4`／`requests`**：只有 `tools/local_research_pipeline.py`（一支獨立的一次性研究腳本，`main.py` 完全不會載入 `tools/` 目錄下任何東西）用到，不影響伺服器本身能不能啟動，改放進 `requirements-dev.txt`（跟 2026-09-07 稍早新增的 `playwright` 同一份檔案，測試/工具專用、正式機執行 ERP 服務不需要）
- 新增 `backend/tools/check_dependencies.py`：跑 `pip-audit` 對照 PyPA Advisory Database 分別掃 `requirements.txt`（正式機服務實際需要的）與 `requirements-dev.txt`（開發/測試專用，不影響正式機），支援 `--prod-only`/`--dev-only` 只掃其中一份。**刻意不是排程工具、也不掛進 pytest 套件**——比照 `check_guide_sync.py` 這類「需要時才手動執行」的既有工具慣例：新 CVE 隨時可能被揭露，讓「弱點掃描」變成 pytest 硬性關卡，會導致某天一個完全沒改過的既有套件被揭露新漏洞，就無端擋住 `build_deploy_package.ps1` 的部署打包，這不是我們要的行為——弱點掃描該是「定期人工檢查、決定要不要升級」的節奏，不是自動化測試門檻
- 目前掃描 `requirements.txt`／`requirements-dev.txt` 兩份皆回報「沒有已知弱點」
- **踩坑**：`requirements-dev.txt` 原本用中文寫註解，`pip-audit` 用的 requirements 檔解析器在這台機器（Windows cp932 locale）猜檔案編碼時直接 `UnicodeDecodeError`——這是跟 `.ps1` 檔案需要存成帶 UTF-8 BOM（見 §12 2026-08-08 條目）同一類「工具用系統預設編碼而非 UTF-8 猜檔案內容」的問題，只是換了一個不同的檔案類型與工具。`requirements.txt`/`requirements-dev.txt` 這類會被外部工具解析的純文字設定檔，改用純 ASCII 英文寫註解徹底避開編碼猜測，比加 BOM 更保險（畢竟不是每個解析器都認 BOM）
- pytest 439/439 全過（純依賴聲明調整，不涉及任何程式邏輯變動）

---

### 2026-09-07（完）— `logs/server.log` 新增大小輪替（DB 無異動）

- 背景：正式機 `autostart.bat` 用 shell `>>` 把伺服器 24/7 運行期間的全部 stdout/stderr（含 uvicorn 自己的存取記錄與應用程式的 `logging` 輸出）直接重導向進 `logs/server.log`——這條路徑完全不經過 Python 的 `logging` 模組，`main.py` 裡的 `logging.basicConfig()` 管不到它。伺服器常駐執行、從未重啟過就會一直長，先前沒有任何大小上限或輪替機制，長期下來理論上可能把磁碟塞滿（正式機過去已經踩過一次類似性質的事故——`module_versions` 表無限增生塞爆每日備份空間，見 2026-08-XX 相關記錄）
- 新增 `archive.py::_rotate_server_log_if_large()`，掛在 `_daily_backup()` 函式最開頭執行——刻意放在 `_archive_ok()` 判斷之前、也不受「今天的每日備份是否已經跑過」的 `.done` 早退影響，因為 log 檔案的成長跟雲端備份完全是兩件事，不應該因為雲端磁碟機沒掛載或今天已經備份過就被跳過
- 超過 50MB 觸發輪替，用 **copytruncate** 手法：先複製目前內容到 `server.log.1`（既有的 `.1`~`.4` 依序遞增一代變成 `.2`~`.5`，原本的 `.5` 直接刪除，保留最新 5 個世代），再把 `server.log` 原地 truncate 成 0 bytes——**不是改檔名**。這是刻意的選擇：`apply_update.ps1` 的部署健康檢查（`$logPath = ...` 那段）寫死讀 `logs/server.log` 這個固定檔名判斷「最後一次成功啟動之後有沒有新的錯誤」，如果改用常見的「日期戳檔名」輪替法（如 `server_2026-09-07.log`），會讓那個檢查永遠讀到空的或過期的檔案，等於讓一個現有的部署安全機制悄悄失效，不能單純套用最直覺的輪替寫法
- Windows 上 `autostart.bat` 用 `>>` 開檔屬於 append 模式的 file handle——truncate 原檔之後，同一個 handle 下一次寫入永遠會先 seek 到檔案目前結尾再寫，清空後的結尾就是 0，所以下一次寫入會自然接續在新的（空的）檔案開頭，不需要通知或重啟寫入端。這個假設已經用一個模擬測試驗證過（同一個 Python file handle 在測試進行中 truncate、驗證後續寫入內容正確落在新檔案裡）
- **⚠️ 尚未在真正跑著 `autostart.bat` 的正式機上驗證過**：Windows 上 cmd.exe 的 `>>` 重導向所開檔案的共用權限（sharing flags）是否真的允許外部行程（`backup_job.py`／in-process 的每日排程）同時開啟並 truncate，這裡沒有實機測試過。已做了防禦性設計——truncate 失敗會被 `except Exception` 接住、只留一筆警告 log，`server.log` 維持原樣繼續成長，不會比現狀更糟，只是輪替沒有真的生效；下次正式機套用後，需要留意 `logs/server.log` 是否真的在超過 50MB 後被清空過一次，確認機制真的有效
- 新增測試 `backend/tests/test_log_rotation_2026_09_07.py`（6 題）：檔案不存在/低於門檻不輪替、超過門檻正確 copytruncate 且內容完整保存到 `.1`、既有多代 `.1`~`.3` 正確依序遞增且超過 `keep` 上限的最舊一代被砍掉、同一個 append-mode file handle 在輪替前後持續寫入的內容正確、`_daily_backup()` 不論雲端是否可用都會觸發輪替
- pytest 439/439 全過

---

### 2026-09-07（終）— PDF 產生新增並發限制（架構地圖建議事項，DB 無異動）

- 背景：每一份 PDF 匯出（報價單／出貨單／承攬商匯款申請／發票開立簽核單／請款單／案件結案報表／網路架構規劃書／營運報表）都各自 spawn 一個 `msedge.exe --headless` 子行程。正式機是單一 Windows 主機、沒有任何行程池限制——短時間內多人同時觸發簽核完成（背景執行緒各自產 PDF）或匯出動作，理論上可能同時開出一堆 Edge 行程，把單機 CPU/記憶體吃滿，拖垮正在跑的 uvicorn 本身
- 新增 `helpers/startup.py::EDGE_PDF_SEMAPHORE`（`threading.BoundedSemaphore(3)`，透過 `helpers/__init__.py` 對外重新匯出），`pdf_gen.py`（14 個呼叫點）／`network_plan_export.py::_render_pdf_via_edge()`（1 個）／`routers/reports.py::_html_to_pdf()`（1 個）共 16 處 `subprocess.run([edge, '--headless', ...])` 全部改用 `with EDGE_PDF_SEMAPHORE:` 包住；三個檔案 import 的是同一個全域物件，並發額度是全站共用一份，不是三份各自獨立加總。超過上限的呼叫方單純排隊等待輪到自己，不會報錯，只是慢一點
- 複查全站 Edge 子行程呼叫點時發現 `routers/reports.py::_html_to_pdf()` 是先前完全沒被 §11 或架構地圖記載過的第三個獨立呼叫點（原本以為只有 `pdf_gen.py` 跟 `network_plan_export.py` 兩處各自維護一份轉檔邏輯）
- 新增測試 `test_pdf_concurrency_2026_09_07.py`（3 題）：不透過完整 PDF 產生流程（那部分已有既有的 `generate_*_pdf_bytes` 測試涵蓋），直接測 semaphore 機制本身——起 9 個執行緒搶 3 個名額驗證同時持有數不超過上限且確實有頂到上限、確認同一個物件可以反覆借還不會報廢、確認三個檔案各自 import 到的是同一個全域物件
- 順便修正同一輪意外發現的既有 E2E flaky 問題：`test_e2e_playwright_2026_09_07.py::test_login_create_submit_approve_smoke` 單獨執行連續 3 次都穩定通過，但夾在整批 400+ 個測試中間完整跑一次時因系統負載較高而逾時失敗過一次——把簽核相關的兩處等待時限從 10 秒加大到 20 秒，這類真實瀏覽器測試在系統忙碌時偶爾需要更多緩衝，跟這次的 PDF 並發限制改動本身無關，只是剛好同一輪發現
- pytest 433/433 全過

---

### 2026-09-07（最晚）— 外部函式庫全面自架，移除 CDN 依賴（DB 無異動）

- 背景：正式機是純內網部署（172.16.10.177，設計上不依賴對外網路），但先前 Alpine.js／Chart.js／SortableJS／frappe-gantt／SheetJS 這五套函式庫全部從 `cdn.jsdelivr.net` 動態載入——如果辦公室對外網路中斷，或防火牆/代理設定變動導致 jsdelivr 被擋，整套 ERP 會直接打不開，這對一個刻意設計成內網系統的應用是不必要的外部單點故障
- 下載全部 6 個檔案（Alpine.js、Chart.js、SortableJS、frappe-gantt 的 JS+CSS、SheetJS）到新的 `frontend/static/vendor/` 目錄，全站 55 個前端頁面 + `index.html` 的 `<script src>`/`<link href>` 一律改指向本機路徑；`pages/*.html` 用 `../static/vendor/...`，`index.html` 用 `static/vendor/...`（沿用既有其他 static 資源的相對路徑慣例，無 `../`）
- 順便固定兩處原本用浮動版號的引用：`alpinejs@3.x.x`（實際解析結果為 3.17.1，這裡明確釘住）與 `reports.html` 單獨用的 `chart.js@4`（改成跟 `index.html` 一致的 4.4.0）——浮動版號代表上游隨時可能推新版而沒有人知道，對正式機這種很少重新整理快取的環境是額外風險
- 複查全站 CDN 清單時意外發現架構地圖 §6.5「甘特圖」建議其實早在該文件成文前一週（2026-08-24，commit `9f86d93`）就已經用 `frappe-gantt` 做完——是繼 §6.2（caseRecord.stages Phase 3b）之後第二次「文件盤點沒有先對照程式碼」的過期記載，已一併更正該節內容
- 字型（`LINE Seed TW_OTF`）本來就已經自架，不受這次調整影響；純粹置換 script/link 標籤的來源路徑，前端邏輯本身零改動，理論上不影響任何既有測試
- pytest 430/430 全過（純靜態資源路徑調整，不涉及任何後端程式碼）

---

### 2026-09-07（再更晚）— 新增第一條瀏覽器端對端測試（DB 無異動）

- 全系統 400+ 個 pytest 都是後端 API 整合測試，前端 Alpine inline script 完全沒有自動化測試——過去多次真實回歸（`x-show`/`x-if` 誤用、badge 同步漏更新、日期字串排序）都是純前端邏輯問題，後端 API 測試全綠也攔不下來，只能靠人工在瀏覽器裡肉眼發現。新增 `backend/tests/test_e2e_playwright_2026_09_07.py`：用 Playwright 驅動真實 Chromium 跑一條關鍵路徑 golden path smoke test——登入 → 新增報價單（填客戶/案件/一項品項）→ 送出審核 → 另一位主管登入 → 開啟同一張單 → 簽核 → 確認狀態變成「已送出」
- 新增 `backend/tests/live_server` 測試 fixture：複用既有 `client` fixture 已做好的 DB/uploads 隔離，額外把同一個 `main.app` 用 `uvicorn.Server` 開一個真正的 loopback TCP 監聽（Playwright 是真實瀏覽器程序，不能像 `TestClient` 直接呼叫 ASGI app）
- 新增 `backend/requirements-dev.txt` 記載 `playwright` 為測試專用相依，**刻意不放進** `requirements.txt`（正式機執行 ERP 服務不需要瀏覽器引擎）；沒安裝 playwright 或沒執行過 `playwright install chromium` 的環境，這個測試檔會透過 `pytest.importorskip` 自動整檔跳過，不影響 `build_deploy_package.ps1` 既有的「先跑 pytest 再打包」流程。`pytest.ini` 新增 `e2e` marker 供之後篩選
- **開發過程中意外發現一個目前系統的真實隱性需求，不是這次新增的行為**：簽核解析走 `helpers/tiered_approval.py::resolve_submitter_manager_chain()`（申請人部門主管自動簽核鏈），這是**動態解析、不是送審當下的快照**——申請人若沒有歸屬任何部門，簽核當下才會噴出「申請人尚未歸屬任何部門，請聯絡管理員設定部門後才能送審」，不是送出審核那一刻就會擋下。測試裡刻意建了一個測試部門把建立者掛上去、部門主管設為核准者，讓測試情境符合實際系統要求，同時也把這個容易被忽略的即時依賴用一條會自動跑的測試釘住
- 這條測試本身跑起來約 8 秒（真實啟動一個 uvicorn 執行緒＋一個無頭 Chromium 程序），比其餘純 API 測試慢，但仍在可接受範圍內；多跑 3 次確認沒有時序性 flaky 問題
- pytest 430/430 全過（429 既有 + 這條）

---

### 2026-09-07（更晚）— 雲端備份目標可插拔，新增 S3 相容後端（架構地圖 §6.4，DB 無異動）

- 新模組 `backend/cloud_storage.py`：新增 S3 相容物件儲存後端（AWS S3、Backblaze B2 皆可，B2 提供 S3 相容端點），作為既有「本機掛載雲端硬碟磁碟機」模式（已證實脆弱，磁碟機代號漂移曾造成備份靜默失效長達三週）的替代方案。憑證走 boto3 標準憑證鏈（環境變數／`~/.aws/credentials`／instance profile），**一律不存資料庫**——新設定 `system_settings.cloud_backup_target` 只存 bucket/endpoint/region/prefix 這類非機密值，新端點 `GET/PUT /api/settings/cloud-backup-target`（superadmin only，無前端頁面，比照既有技術設定慣例）
- `archive.py` 重構：所有原本直接操作本機磁碟機路徑的地方（即時備份報價單/客戶/供應商、每日/週備份 JSON、uploads/ 鏡像、SQLite 快照複製到雲端、過期備份清除）改走新的一組派送層函式（`_cloud_write_json()`／`_cloud_copy_file()`／`_cloud_stat()`／`_cloud_marker_exists()`／`_cloud_write_marker()`／`_cloud_list_top_level()`／`_cloud_delete_dir()`），依 `system_settings.cloud_backup_target.backend` 分流。`backend="local_drive"`（預設值，也是目前正式機唯一在用的模式）時，這些函式內部呼叫的本機路徑計算與 `os`/`shutil` 操作跟改動前逐位元組相同，只是多繞一層間接呼叫——確保這次重構對現有正式機行為零回歸，只有主動切到 `backend="s3"` 才會改用新程式碼路徑
- **目前沒有真實 S3/B2 帳號可測試**，S3 路徑完全靠一個記憶體版的假 S3 client（只實作 `put_object`/`head_object`/`list_objects_v2`/`delete_objects`/`head_bucket`/`upload_file` 六個實際會用到的方法）做單元測試，未曾對接過真實 bucket。要在正式機真正啟用，需要使用者：①自行申請 AWS S3 或 Backblaze B2 帳號並建立 bucket ②在正式機的服務執行環境設定 access key 環境變數 ③呼叫上述 PUT 端點切換 `backend` 為 `"s3"` 並填入 bucket 等設定。這三步都還沒做，正式機目前維持原本的本機磁碟機模式不受影響
- 新增測試 `test_cloud_storage_2026_09_07.py`（18 題）：涵蓋 `cloud_storage.py` 本身（put/stat 往返、bucket 不可達時 `s3_available()` 正確回報 false、`list_prefixes`/`delete_prefix` 分頁邏輯）與 `archive.py` 在 `backend="s3"` 下的整合行為（`_backup_quotation`/`_mirror_uploads`/`_daily_backup`/`_prune_cloud_backups` 確實透過假 client 寫入而非碰觸本機檔案系統）＋新設定端點的權限/驗證測試
- pytest 429/429 全過（400 既有 + 09-07 稍早的 TOTP 11 題 + 本次雲端備份 18 題）
- 尚未執行：正式機套用（依 §15 流程）；即使套用，預設行為也不會改變，除非之後另外執行上述三步驟主動切換

---

### 2026-09-07（稍晚）— 新增 TOTP 兩步驟驗證，自助啟用（DB v72）

- 架構地圖 §6.2 建議事項：新增 `pyotp`／`qrcode` 依賴，`users` 表新增 `totp_secret`/`totp_enabled`/`totp_recovery_codes`（`db.py::_m072_totp()`）。**刻意做成自助啟用而非強制**——正式機 superadmin 是 jeff/corbin 兩位真人業主，若強制下次登入即進入設定流程，部署當下他們手邊沒先裝好驗證 App 會直接被鎖在系統外面，屬於會中斷真實業務的風險，與使用者確認後定案
- 新端點：`GET/POST /api/auth/totp/status|setup|enable|disable`（需登入自助操作，任何角色）＋ `POST /api/auth/login/totp`（登入第二階段，白名單路徑）。`setup`→`enable` 要求輸入一次正確驗證碼才真正生效，避免掃錯 QR code / 密鑰輸入錯誤卻直接啟用，導致使用者下次登入被鎖在外面；`enable` 成功回傳 10 組一次性救援碼，明文只在該次回應出現一次，DB 只存雜湊
- 登入流程：`POST /api/auth/login` 密碼正確但帳號 `totp_enabled=1` 時不核發 session，改回傳 `{totpRequired, challengeToken}`；`challengeToken` 是短效（5 分鐘）process-global 記憶體狀態，非 DB 持久化；`POST /api/auth/login/totp` 核實 6 位數 TOTP 或 8 碼救援碼後才真正核發 session，每個 challenge 最多 5 次錯誤即作廢（需重新輸入密碼從頭開始）
- 前端：`login.html` 新增第二步驟驗證碼輸入畫面（含返回重新登入）；`change-password.html` 新增「兩步驟驗證」卡片（QR code 設定／確認啟用／一次性顯示救援碼／輸入密碼停用）；`notif.js` 對 admin/superadmin 尚未啟用時顯示提醒 banner（`sessionStorage` 節流每分頁一次，純提醒不阻擋操作，且不在 `change-password.html` 本身顯示避免重複）
- **開發過程中發現並修復一個既有陷阱**：`main.py` 的 `_PUBLIC_API_PATHS` 白名單原本只列 `/api/auth/login`，新端點 `/api/auth/login/totp` 在使用者尚未登入前呼叫會被 `auth_middleware` 攔成 401「未登入」（因為它要求 Bearer token，但登入第二步驟本來就還沒有 token）——這是任何「把登入流程拆成多支端點」都會踩到的通用陷阱，之後若再拆分登入步驟需要同步檢查這份白名單
- 新增測試 `backend/tests/test_totp_2026_09_07.py`（11 題，涵蓋 setup/enable/disable、登入兩步驟完整流程、救援碼一次性使用、per-challenge 鎖定機制），pytest 411/411 全過；另用真實開發機 API（非 pytest 隔離 DB）跑過完整流程二次驗證，確認在真實環境同樣正確。**UI 視覺層級因本次工作環境限制（連接的瀏覽器不在本機、無法連線本機 dev server）未能完成畫面實測**，功能面已用等效 HTTP 呼叫涵蓋全流程，建議之後找機會人工開瀏覽器檢查一次三處新增/修改的頁面
- 尚未執行：正式機套用（依 §15 流程）

---

### 2026-09-07 — 更正 caseRecord.stages 正規化狀態記載＋補齊階段端點測試（DB 無異動）

- 複查 `MOTRIX-ERP-QUICK.md` §11 已知限制清單時發現「caseRecord.stages 正規化進行中」長期記載已過期：核對 `case-management.js`／`quotation-form.html` 程式碼確認 Phase 3b（前端切換）與 Phase 4（`quotation-form.html` 落差修正）其實早在 2026-08-23 當天就已完成——那次是在正式機斷線期間直接於正式機開發、事後用一次大批量回推 commit `2b8e7ad` 拉回開發機，沒有補記錄，導致文件誤記為「進行中」達兩週。已更正 §11 為完成狀態並說明緣由
- 複查過程中發現真缺口：這批 10 個階段 CRUD 端點（新增/更新/刪除/重排/負責人加入移除/前置階段切換/拜訪紀錄新增更新刪除）先前幾乎沒有正面路徑測試，`backend/tests/` 唯一涵蓋 `/stages` 路徑的地方只測「已結案案件鎖定」情境。新增 `test_case_stages_endpoints_2026_09_07.py`（11 題），涵蓋 CRUD 正確性、負責人新增/移除（含重複加入與移除不存在使用者）、前置階段防環偵測（`_would_create_cycle()`）、拜訪紀錄 CRUD 與跨階段/跨案件 id 隔離防護、`_sync_stages_to_json()` 橋樑正確性、鎖定案件擋下
- 同時修正 10 個端點 docstring 裡「尚未接進任何前端頁面（2026-08-23）」的過期字樣，避免下次對話又被誤導成「這批端點還沒上線」
- pytest 400/400 全過

---

### 2026-09-06 — 完整版規劃書拓樸圖第三輪修復：多欄並排＋寬度對齊表格

- 交換器排版改成有多餘寬度就往右並排、排不下才換行（原本第二輪修復只是
  單欄堆疊後整張圖等比縮小塞進一頁），並修正排版改動連帶產生的真實 bug：
  同一列兩台交換器之間的連線標籤原本會直接蓋住左邊交換器的埠位格子
  （改連到面板下緣的空白區域，不再遮擋任何內容）
- 使用者接著要求拓樸圖寬度要跟下方埠位對照表一致：CSS 改用 width:100%
  （強制撐滿容器寬度）取代 max-width；同時發現並縮小原本 160px 的「連線
  標籤防裁切緩衝區」（LABEL_MARGIN，縮到 70），這個固定緩衝在窄版多欄
  排版下占比過大，會讓畫面看起來沒撐滿
- 使用者實測後回報「port 文字無法閱讀」——字體清楚／寬度一致／單頁塞下
  三者互斥（兩欄並排撐滿跟表格一樣寬時，整張圖等比縮到只剩 0.5-0.6 倍，
  port 文字縮到 5-8px）。曾一度改成一列只放 1 台＋拿掉 max-height 換取
  字體放大約 1.35 倍，但拓樸圖跨頁數大增（5 台交換器從 1 頁變 3 頁）；
  使用者實際比較兩版後認為兩欄並排單頁版本比較好——寧可字稍小，也不要
  犧牲頁數，最終定案維持兩欄並排＋max-height:640px＋width:100%
- 已用合成資料＋開發機真實 API 雙重驗證，每次調整都逐版拿 PDF 實測比對；
  全套 pytest 389/389 全過

### 2026-09-06 — 完整版規劃書拓樸圖第二輪修復：一般規模不再跨頁破碎

- 使用者用正式機真實小林機械案（`NP-202608-001`）重新匯出 PDF 後回報「仍然
  一樣」：捲軸 bug／缺埠位對照表確認已修好，但拓樸圖本身還是常跨好幾頁破碎
  （「網路拓樸圖」標題孤伶伶佔一整頁、5 台交換器分散到後面幾頁、中間大片
  空白），追問確認就是指這個問題
- 根因：`build_topology_svg()` 目前只會單欄由上往下堆疊交換器，台數一多整張
  圖遠比一頁高，先前只加 `max-width:100%` 等比縮寬治標不治本（高度完全沒變）
- 修復：`<style>` 的 `svg` 規則加上 `max-height:640px`（A4 橫向可印刷高度扣掉
  表頭/meta/標題後的保守可用空間）——CSS 對有 width/height 屬性的 SVG 這種
  replaced element，`max-width`／`max-height` 同時設定時會自動取兩者中更嚴格
  的縮放比例等比縮小，不是裁切也不是 hack；拓樸圖區塊重新包回
  `page-break-inside:avoid`（這次因為已經保證塞得下一頁，不會再出現孤兒
  標題的矛盾）。一般規模規劃書（幾台到十幾台交換器）拓樸圖現在會完整塞進
  一頁；台數多到縮到很小仍裝不下的極端案例，才會退回自然分頁（不強制切版）
- 已用合成資料（同小林機械案 5 台交換器配置）與開發機真實 API
  （`POST /api/network-plans` → `PUT` 填拓樸資料 → `GET .../export/pdf`）
  雙重驗證：單頁完整顯示交換器面板＋圖例，埠位對照表接續在後，無捲軸
- 全套 pytest 389/389 全過

### 2026-09-06 — 修復完整版「網路架構規劃書」PDF 拓樸圖區塊（原生捲軸誤植入輸出）

- 使用者實際下載完整規劃書 PDF（`NP-202608-001_小林機械廠股份有限公司_網路架構規劃書.pdf`）
  比對後回報格式仍不符，用 PyMuPDF 解析 PDF 向量圖形逐頁複查後找到真正根因：
  `build_plan_html()` 的拓樸圖區塊用 `overflow-x:auto` 包住 SVG——CSS 規範規定
  `overflow-x` 設非 `visible` 值時，未指定的 `overflow-y` 會被瀏覽器一併強制改成
  `auto`；拓樸圖 SVG 常比一整頁還高很多，容器因此變成可垂直捲動，Edge headless
  轉 PDF 時把瀏覽器原生捲軸（含上下箭頭方塊）實際畫進了輸出頁面，肉眼看起來像
  無法辨識的三角形/長條圖案；圖例文字也因此被裁在捲動範圍外看不到
- 修復：拿掉 `overflow-x:auto`，改為完全不設 overflow（回到一般分頁流程，不再
  觸發捲軸）；`<style>` 新增 `svg{max-width:100%;height:auto}` 讓拓樸圖等比縮到
  版面寬度內；比照 b1f_topology.py／快速拓樸圖工具，在圖旁補上
  `build_topology_text_summary_html()` 產生的逐埠文字對照表（完整版規劃書原本
  只有一張圖，沒有文字表）；`.section-label` 統一加上 `break-after:avoid`，讓各
  章節標題盡量跟隨後續內容換頁（不會自己孤伶伶留在前一頁），拓樸圖等大型內容
  在跨頁時仍可能有一頁近乎空白的過場，屬於 A4 分頁報告固有限制，非本次範圍
- 已用合成測試資料（5 台交換器＋24銅埠+4SFP＋交換器間連線）實際產出 PDF、
  用 PyMuPDF 逐頁複查確認捲軸消失、面板正常渲染、圖例與埠位對照表皆正確顯示
- 全套 pytest 389/389 全過

### 2026-09-06 — 品牌文字補漏：全站頁面 `<title>` 與 Email 頁尾（DB 無異動）

- 使用者實際打開網頁後發現分頁標題仍顯示舊字樣：先前那輪「營運系統→專案管理系統」
  只精確比對「營運系統」四字，沒抓到實際散落在全站的「**營運管理系統**」（中間多了
  「管理」二字，不是同一組連續子字串，grep 沒命中）
- 全面掃描 git 已追蹤檔案（`git ls-files`，排除 `rollback_snapshots/` 等備份快照
  目錄，避免誤改歷史備份），共 46 個檔案、53 處字樣：全站 44 個前端頁面的
  `<title>` 分頁標題、2 處動態 `document.title`（`customer-log.html`／
  `supplier-log.html`）、`email_notify.py` 5 處信件頁尾「本郵件由 MOTRIX
  營運管理系統自動發送」、`docs/MOTRIX_ERP_System_Plan.md` 文件標題，全部統一
  改為「MOTRIX 專案管理系統」
- 全套 pytest 389/389 全過（純文字替換，不影響任何邏輯）

### 2026-09-06 — 快速拓樸圖 PDF 格式/分頁改回比照 b1f_topology.py 原始腳本（DB 無異動）

- 使用者要求「輸出的格式跟分頁方式要完全一樣」：`build_topology_only_html()` 版面
  （CSS 變數、放射漸層背景、`.board` 白卡陰影圓角、h1+徽章式標題列、footer 靠右
  對齊）逐項比照原始個案腳本 b1f_topology.py 實際輸出，不再沿用規劃書 PDF 那套
  企業合約書風格
- **分頁方式取捨**（已與使用者確認）：拿掉 2026-09-04 當時因應印表分頁切斷問題
  採用的 A4 直版＋`page-break-inside:avoid`，改回原腳本手法——頁尾 `<script>`
  於 load＋字型 ready 後量測實際渲染尺寸，動態產生剛好等於內容大小的 `@page`
  （永遠一頁、無頁碼）。代價：匯出的 PDF 頁面尺寸不是標準 A4，直接送實體印表機
  可能被印表機驅動縮放或裁切，但數位保存/瀏覽器開啟不受影響——已實測驗證匯出
  PDF 確實只有 1 頁、尺寸為動態值（553.92×1577.04pt）而非 A4 的 595×842pt
- 型號徽章（`.tag.mod`）改為依實際資料動態算：`build_topology_svg()` 新增回傳
  `models`／`uniform_ports`，單一型號且所有交換器銅埠/SFP埠數一致時顯示
  「型號　(N×GbE + M×SFP)」，型號或埠數不一致時只顯示型號、不強加可能失真的
  埠數字樣（原腳本是寫死文字，此為泛化後的必要調整）
- 埠位對照表埠號欄位改用等寬字體＋粗體（比照原腳本 `td.port`，純 CSS 選取器
  達成，未更動 `build_topology_text_summary_html()` 的表格 HTML 結構）
- 「營運系統」→「專案管理系統」品牌文字（見下則）與本次拓樸圖格式調整為
  同一輪對話但互不相關的兩件事

### 2026-09-06 — 品牌顯示文字「營運系統」→「專案管理系統」（DB schema 無異動）

- 頂部列標題（`sidebar.js`）、Email 寄件人預設名稱與測試信標題（`email_notify.py`／`system.py`）、
  Google 行事曆測試事件說明文字（`google_calendar.py`）四處程式碼字樣統一改為「MOTRIX 專案管理系統」
- 一併更新本機 `system_settings.email_notify.from_name` 已持久化的舊值（僅改資料值，非 schema migration）
- 「營運報表」（Reports 模組名稱）不在此次調整範圍內，與本次品牌文字變更無關

### 2026-09-04 — 網路架構規劃書拓樸圖功能上線＋快速拓樸圖工具

- 新模組 `network_plan_topology.py::build_topology_svg()`：讀規劃書「設備清單」（交換器）＋「交換器
  Port 對應」明細自動產生拓樸圖 SVG，取代舊個案腳本 `b1f_topology.py` 手動繪製的方式；埠位顏色依
  `portProfile` 文字雜湊調色盤，連線依新增的 `linkDevice`/`linkPort`/`portMedia` 三欄，命中另一台
  交換器畫真實面板對面板連線，命中不到畫「外部/未列出設備」方塊（處理 ISP 路由器等不在規劃書內的
  上行設備）
- 防呆機制：單一設備埠數欄位打錯不會讓整張圖消失（只跳過該台）；埠號超出實際埠數／設備名稱重複／
  Port 對應表填的設備名稱找不到／`linkDevice` 疑似大小寫或空白打錯四種情況回傳 `warnings` 清單顯示
  在畫面上，不靜默漏資料
- 表單新增「拓樸圖」分頁即時預覽（不落地存檔），PDF 匯出自動內嵌同一張圖；交換器 Port 對應新增
  「依設備清單自動產生缺少的埠列」一鍵按鈕（純新增不覆蓋既有資料）
- 填寫效率優化：10 個明細分頁改成密集網格表格（Tab 鍵可跳下一格）；新增「貼上 Excel 資料」——Excel
  選取範圍複製後貼進文字框，依欄位標題自動比對新增
- 新增獨立無狀態頁面「快速拓樸圖產生器」（`topology-quick.html`＋`routers/network_plans_quick.py`，
  `POST /api/network-plans-quick/preview`／`/pdf`）：完全不寫入 `network_plans` 資料表，資料只存
  瀏覽器 localStorage，對應「不填企劃書、單純產生拓樸圖」的用完即丟情境
- **同日追加修正**（使用者實測後回饋三輪）：①PDF 改 A4 直版＋補逐埠文字對照表＋
  `page-break-inside:avoid` 避免圖被印表分頁切斷，順手修復一個連 SVG 本身都受影響的既有 bug（外部
  設備方塊兩行文字垂直間距太小造成視覺重疊）②新增「拓樸圖埠位排列」欄位（雙排交錯／單排橫向）
  支援不同交換器面板樣式，埠位對照表改固定兩欄 CSS Grid 讓瀏覽器自動兩兩並排③複查真實 PDF 輸出
  又抓到並修復兩個既有繪圖 bug：連線標籤被自己的交換器面板蓋住（改成獨立疊在最上層）、長設備名稱
  在面板邊緣連線上被畫布邊界裁切（加截斷＋160px 緩衝）
- 新增測試 18 題，388 測試全過；已用真實瀏覽器完整驗證（登入→建交換器→Port 對應自動產生+貼上
  Excel→拓樸圖預覽→PDF 匯出）。**這輪連續三次修正都是靠使用者拿真實 PDF 輸出實測回饋才抓到，視覺
  呈現類的 bug（文字重疊/被遮擋/被裁切）難靠程式邏輯測試發現，下次拓樸圖相關改動建議都用真實資料
  產一份 PDF 肉眼複查，不要只信 pytest 綠燈**

---

### 2026-09-02 — 業務開發新增「暫擱置」狀態，180 天自動轉未成案（DB 無異動）

- 案件狀態新增「暫擱置」選項，列表新增對應篩選 chip 與徽章樣式
- 背景排程每日 08:00 一併檢查：暫擱置案件超過 180 天未更新自動轉為「未成案」，避免案件無限期卡在
  暫擱置讓篩選與統計持續失真；轉換動作純系統排程行為，不發 email／站內通知，僅寫入 audit_log 供
  事後追查
- **同日追加修正**：設為暫擱置原本比照「業務主動暫停」不寄送 email 通知，使用者確認後改為與其他
  狀態選項一視同仁照常寄信通知 admin/superadmin；180 天自動轉未成案的排程動作維持不寄信（無負責
  操作者可歸因，屬系統排程行為非人工變更，理由不變）
- `backend/routers/dev_crm.py` + `frontend/pages/dev-crm.html`，pytest 全過

---

### 2026-09-02 — 營運報表模組反派/國稅局視角複查（DB 無異動）

- **安全性/存取控制**：Excel 匯出補上公式注入防護（CWE-1236，`_xl_safe()`）；`GET /api/settings/operating-targets` 補上 admin+ 角色檢查（原本任何登入使用者含 engineer/viewer 皆可讀取年度營收/毛利/業務員配額目標）；營運報表 Excel/PDF、銷項發票清單、銀行對帳單比對四支匯出端點補上稽核記錄
- **財務正確性**：稅額沖銷（taxExempt，內部應收帳款減讓）不再回溯改寫已開立發票的稅務匯出/T100 傳票稅額——過去會讓已產生法定稅捐義務的發票在申報文件上變成稅額=0；改用原始開立金額計算，AR帳齡/收款率邏輯不受影響。稅額計算改用 ROUND_HALF_UP，符合統一發票四捨五入慣例。《月支出》其他支出改用憑證日期(expenseDate)分月，不再用精算完結日期（避免明細跟月度加總對不上月份）。業務員績效/目標達成率改用穩定的 `sales_person_id` 比對，不受業務員改名影響
- **穩健性**：`period` 參數格式錯誤（如 `2026-13`）回 400，不再拋未捕捉例外變 500
- **新增統一發票號碼格式驗證＋跨案件重複偵測**（`helpers/quotations.py::validate_invoice_no()`）：2 碼英文字軌＋8 碼數字，接進 `mark_payment()` 與案件管理財務Tab 整包存檔 `update_case_record()`（實際填發票號碼最常用的路徑）兩處
- **新增統一發票「開立日期」欄位**（`invoiceDate`，直接存 `data_json`，無需 migration）：稅務匯出/T100 傳票的期別歸屬改用這個欄位（法定上決定申報期別的日期），不再用款項收款日期代替；T100 現金基礎傳票日期本身刻意維持用收款日期不變（要跟銀行實際入帳日一致）。案件管理財務Tab 與出納「登錄發票」Modal 都新增對應輸入欄位
- 新增回歸測試共 49 題（`test_reports_review_fixes_2026_09_02.py` 15 題／`test_reports_tax_compliance_2026_09_02.py` 10 題／`test_invoice_date_and_case_record_validation_2026_09_02.py` 9 題，另修正 3 個舊測試裡不符合新規則的假資料），pytest 全過
- **提醒**：若過去曾用銷項發票清單/T100 傳票申報過含「已核准稅額沖銷」的期別，那些期別可能低報了銷項稅額，建議自行跟記帳士確認是否需要補正（系統本身無法判斷是否已實際申報，這部分不會自動處理）
- 安全性/財務正確性/穩健性三批已套用至正式機；發票開立日期功能為同輪追加，尚待套用（依 §15 流程）

---

### 2026-09-01 — T100（鼎新）傳票批次匯出（新模組）＋料件/設備進貨付款狀態追蹤（DB v70）＋匯入確認追蹤（DB v69）

- T100 批次匯出採現金基礎：收款事件（款項明細已開發票且已收款）＋付款事件（承攬商匯款申請已標記已匯款）兩類天生借貸平衡；刻意排除請款單（對客戶要款文件非金流事件）。新檔 `routers/accounting_export.py`，科目代號設定留白供財務自行填入，`reports.html`「資金水位」分頁新增匯出區塊
- 新增料件/設備進貨付款狀態追蹤：新表 `stock_batches`（批次層級表頭，`is_paid`/`paid_by`/`paid_at`，比照承攬商匯款申請模式，既有批次全部回填但預設未付款），並納入 T100 匯出第三個事件來源（借料件設備成本／貸銀行存款）
- 新增已匯入確認追蹤（新表 `t100_export_confirmations`）：財務先 `GET preview` 預覽未確認事件，實際匯入 T100 後 `POST confirm` 整批標記，避免同區間重複匯出/重複匯入；識別碼採資料本身穩定鍵（非流水號）
- 新增測試 `test_t100_export_2026_09_01.py`（6題）／`test_stock_batch_payment_2026_09_01.py`（6題）／已匯入確認追蹤補測 2 題，pytest 全過
- 尚未套用至正式機（依 §15 流程）

---

### 2026-08-31g — 出納整合進營運報表模組（頁籤合併）＋案件管理數字連動稽核

- 獨立的出納模組（2026-08-31e/f 交付）併入 `reports.html` 第 13 個頁籤「出納」（含待付款/待收款/執行歷史/銀行對帳單比對 4 個子頁籤）；`cashier.html` 改為導向 `reports.html?tab=cashier` 的 stub 保留舊書籤，`cashier.js` 內容併入 `reports.js` 後刪除，sidebar 移除獨立出納入口
- 准入權限重新分層：admin+ 維持全部 12 個財務報表頁籤，純 cashier/finance 模組的非管理職使用者只看得到出納頁籤
- 金額連動稽核修復一個真實 bug：`dashboard.py::dashboard_monthly()`（首頁銷售收入趨勢圖表）未比照同檔案其餘 5 處用寬鬆 `COALESCE` 判斷 dealTag，只寫在 data_json 未回填 DB 欄位的舊格式報價單被靜默漏算
- 新增測試 `test_dashboard_monthly_dealtag_fallback_2026_08_31.py`，pytest 294/294 全過
- 尚未套用至正式機

---

### 2026-08-28f — 簽核流程套用範圍：五種文件類型可各自選統一流程或獨立設定

- 報價單／出貨單／發票開立簽核單／請款單／承攬商匯款申請五種文件類型，新增可各自選擇「跟統一流程走」或「獨立設定」；切換到獨立設定時初始值複製目前統一流程內容，不從空白開始
- 核心設計：「編輯」跟「套用」分開——各文件類型自己的 flow key 永遠可直接讀寫，新增 `system_settings.approval_flow_scope` 只決定送審時當下讀哪把 key，避免勾選切換時互相覆蓋
- 後端新增 `helpers/tiered_approval.py::approval_flow_setting_key()` 與相關端點；`approval-settings.html` 整頁改版，五個文件類型的 tiers 編輯 UI 共用同一份元件
- 同時修正文件本身（QUICK.md §5.8/§5.9/§6/§7）多處 2026-08-24 統一簽核上線後未更新的殘留舊描述
- 新增測試 `test_approval_flow_scope.py`，pytest 186/186 全過

---

### 2026-08-28e — 模組逐步檢查（第二輪：主檔資料／業務開發／案件代辦／使用者管理）

- 主檔資料與七大類選型資料庫（switch/monitor/access/gateway/netarch/env/automation）逐一核對：組織架構刪除有子節點保護、客戶/供應商刪除因資料為快照文字本就安全、外包人員/承攬商無硬刪除端點、料號刪除有庫存保護、七大選型資料庫的 fit/products 皆有 `ON DELETE CASCADE`＋全域 `PRAGMA foreign_keys=ON` 保護，確認皆無需修改
- 業務開發（dev_crm.py）：軟刪除（`is_deleted=1`，需 superadmin 核准）後的專案，`get_dev_case()`／`update_dev_case()`／`update_dev_case_status()`／`mark_converted()`／`create_dev_log()` 五個端點原本都沒有檢查 `is_deleted`，知道/猜到 case_id 即可繼續查看/編輯/轉建報價單/新增記錄到一個已核准刪除的專案，且完全不出現在任何列表裡；五處皆補上 `is_deleted=0` 過濾，找不到時回 404
- 案件代辦事項（case_action_items.py）：PUT 編輯內容原本不檢查簽核狀態，已完成兩階段簽核（`status='done'`）的內容仍可被任意改掉，但 `stage1_approver`/`stage2_approver`/時間戳不會跟著重置，變成「顯示已核准，但實際內容沒人審過」；改為內容真的有變動且已進入/完成簽核流程時，一併重置回 `pending` 並清空簽核紀錄，需重新送審；內容沒變時不誤觸重置
- 使用者管理（auth.py）：`delete_user()` 硬刪除時完全沒有關聯資料檢查，但 `users.id` 被多張表以 FK 引用（`quotations.sales_person_id`／`dev_cases.created_by`／`dev_logs` 多欄／`divisions`/`departments.manager_user_id`）且都沒定 `ON DELETE` 行為，實測確認只要有任何一項關聯資料就會拋出未接住的 `sqlite3.IntegrityError`，被全域 exception handler 接成一個不明不白的「伺服器發生內部錯誤」500；接住後改回友善的 409，提示改用既有的「停用」（`toggle_user_active()`）
- 新增測試共 11 題（`test_dev_case_soft_delete_guard`5題／`test_case_action_item_edit_reset`3題／`test_delete_user_referenced_guard`3題）；`pytest` 259/259 全過

---

### 2026-08-28d — 金額同步稽核（模組逐步檢查）

- 營運報表：精算快照過期不再只在案件層級可見，公司彙總新增 `staleSettlementCount`；`_compute_achievement()` 改與 `monthly_trend()` 共用 `wonMonth` date 歸屬邏輯；空付款排程案件新增 `missingPaymentItemsCount`＋清單，避免悄悄消失於金額類報表
- `payment_item_amounts()` 補上 `pretax` 參數，修正已核准稅額沖銷（`taxExempt`）在 12 個呼叫點被忽略、含稅/未稅金額算錯的問題（實測影響 MQ-202608-007，NT$135,660）
- 新增共用 `norm_at()`，修正案件動態時間軸跨來源（`case_updates`/`work_logs`/`daily_task_completions`/`dev_logs`/`audit_log`）時間格式不一致導致排序錯亂
- 承攬商派發 `update_dispatch()` 補上跟 `delete_dispatch()` 一樣的匯款申請已產生鎖，避免已核准匯款申請的凍結快照跟活動中的派發記錄悄悄兜不起來
- 簽核佇列：`get_approval_queue()`／`get_approval_queue_count()` 補上 `myDelegatedFor`，修正簽核代理人設定後在佇列列表／topbar 角標完全看不到任何項目輪到自己的問題
- 勞報單 `update_payslip()`（PUT）補上「已匯出不可修改」鎖，比照既有 `delete_payslip()` 的保護——匯出成 PDF 封存後金額/稅額欄位原本仍可自由修改，封存內容會跟資料庫悄悄兜不起來，且系統無取消匯出的還原機制
- 新增/更新測試共 20 題（`test_reports_logic_fixes`／`test_case_management_logic_fixes`／`test_dispatch_edit_guard`／`test_approval_queue_delegate_visibility`／`test_payslip_edit_guard`）；`pytest` 248/248 全過
- 依「檢查兄弟端點是否有同一道鎖」方法逐一比對報價單/出貨單/請款單/發票憑據/匯款申請等共用簽核系統的文件類型，其餘皆確認已有對等保護，不需修改

---

### 2026-08-28c — 資訊安全＋企業管理優化（四面向優化建議第三批）

- 高權限帳號（superadmin/admin）閒置逾時縮短為 2 小時：既有全域 8 小時閒置登出機制（`main.py::auth_middleware`，DB v17）新增角色分流，其餘角色維持 8 小時
- 新增高權限帳號定期稽查工具 `backend/tools/audit_account_permissions.py`，依 modules 數量與 role 是否不成比例排序標註，供人工複核（不自動判定）
- 區網 HTTPS 現況釐清：2026-08-27 另一 session（commit `d7b8ee9`）已完成基礎設施，只差正式機手動執行 mkcert 產證，已寫成 `HTTPS-DEPLOY-CHECKLIST.md`
- 新增簽核代理人機制（DB 新表 `approval_delegates`）：任何人可自助委託簽核權限，超級管理員可代替他人設定；`helpers/tiered_approval.py::check_approve_permission()`/`check_reject_permission()` 新增可選 `conn` 參數，5 個 router／10 個呼叫點統一更新；新頁面 `frontend/pages/approval-delegates.html`
- 已結案案件半解鎖範圍評估：13 支被排除端點被擋下時原本零紀錄，改在共用守門函式 `_deny_if_case_locked_unsupported()` 補上 `audit_log`（`case.locked_edit_denied`），供之後累積數據決定是否擴大範圍，這輪刻意不擴大
- 新增/更新測試共 24 題；`pytest` 227/227 全過

---

### 2026-08-28b — 視覺化管理優化＋WCAG 對比度修復（四面向優化建議第二批）

- 部門篩選擴大到案件執行看板（`stage_board()`）與月支出報表（`_collect_expenses()`，涵蓋承攬商派發/料件進貨）
- 庫存水位燈號：DB v66 新增 `parts.safety_stock`，`inventory.py::parts_summary()` 新增 `stockLevel` 計算，`inventory.html` 新增水位圓點欄＋快篩；修正 `update_part()` 未帶 `safetyStock` 鍵時悄悄清零安全庫存的 bug
- 跨案件時程視覺化查證後發現不需新開發：專案管理已於 2026-08-26 併入案件管理，既有跨案時間軸已涵蓋此需求
- WCAG 對比度稽核（額外發現）：`--text-dim`/`--success`/`--warning` 三個 CSS 變數對白底對比度不足 WCAG AA 門檻，已加深（沿用站內既有徽章文字色，非新發明），一行 CSS 全站生效
- 新增測試 5 題；`pytest` 203/203 全過（含財務批次）

---

### 2026-08-28 — 財務顧問優化（四面向優化建議第一批）

- 精算快照過期提醒：`settlement.html`／案件管理財務Tab 比對精算完結凍結快照 vs 即時值，承攬商成本異動後提示
- 資金水位總覽：新端點 `GET /api/reports/cash-position`（應收帳齡＋承攬商已核准未匯款），刻意排除請款單（對客戶要款文件非應付支出）與料件/設備進貨（無付款狀態追蹤）；原規劃的現金流預測因無結構化預計收付款日期而改做此回顧性總覽
- 銀行對帳單 CSV 比對：新端點 `POST /api/reports/bank-reconcile`，寬鬆偵測欄位別名，僅依金額比對供人工複核，不自動標記已匯款
- 稅務匯出：新端點 `GET /api/reports/tax-export`，匯出已開發票收款品項為銷項發票清單 Excel
- 新增測試 10 題，另用本機 Ollama qwen3.6 做獨立複查；`pytest` 198/198 全過

---

### 2026-08-17i — 料號主檔新增匯出／匯入 Excel

- 使用者要求料號主檔能匯出跟匯入。比照 `customers.html` 既有匯入/匯出模式（純前端 SheetJS，無新後端端點），`parts.html` 新增 `exportExcel()`（欄位：料號/品名/廠牌/型號/類別/單位/成本(未稅)/定價(含稅)/備注，`brand` 欄位依 `openModal()` 既有的「/」分割慣例拆成廠牌/型號兩欄）與 `handleImport()`（逐列比對料號是否已存在於 `this.items` 決定呼叫既有 `PUT /api/parts/{id}`（更新）或 `POST /api/parts`（新增，料號留空時沿用後端既有依類別前綴自動產生邏輯）），完成後彙總新增/更新/失敗筆數與錯誤明細，樣式與互動邏輯逐一比照 `customers.html` 既有匯入結果 Modal，並新增全域共用的 `@keyframes spin`（`parts.html` 原本沒有）
- **驗證**：已用 demo session 做完整 round-trip——先建立 2 筆測試料號，呼叫 `exportExcel()` 攔截 `XLSX.writeFile` 確認匯出 9 欄資料與畫面顯示完全吻合；再構造 3 列匯入檔（1 筆更新既有料號／1 筆空料號＋類別觸發自動產生新料號／1 筆品名空白故意觸發失敗），呼叫 `handleImport()` 確認回傳 `created:1/updated:1/failed:1` 且錯誤訊息正確，重新查詢資料庫確認三筆料號實際內容與匯入檔一致、失敗列未被寫入；瀏覽器截圖確認匯入結果 Modal 版面正確、console 無錯誤
- 測試資料建立在 demo 隔離 db（下次 demo 登入自動清空，未寫入正式庫）
- 純前端調整，無 DB migration，無新後端端點；`pytest` 106/106 全過

---

### 2026-08-17h — 案件管理動態 Tab 月曆總覽容器字級過小（g 遺漏的另一半）

- 使用者上一版回報過窄看不清後，先修了下方發文列表字級，接著澄清「是月曆總覽內的容器」——實際指的是 `2026-08-17`（第一版月曆比例修正）當時為解決格子被撐成巨大方形而加上的 `max-width:340px` 迷你月曆容器。量測發現該容器內文字從未被放大過，仍維持很小的原始字級（`.feed-cal-wdays` 星期標頭 9px、`.feed-cal-cell` 日期數字 10px、`.feed-cal-cnt` 當日筆數 8px、`.feed-cal-title` 月份標題 12px），縮小容器後更顯侷促
- 調整：`.feed-cal-wdays` 9→11px、`.feed-cal-cell` 10→13px、`.feed-cal-cnt` 8→10px、`.feed-cal-title` 12→14px、`.feed-cal-nav` 按鈕 20→24px（字級 11→13px）、`.feed-cal-toggle-btn`/`.feed-cal-filter-tag` 11→13px；容器 `max-width` 同步由 340px 微幅放寬到 380px 給放大後的文字留呼吸空間（仍遠低於當初撐爆容器的臨界值，不會重現原本的比例錯誤 bug）
- 已用 `javascript_tool` 呼叫 `toggleFeedCalMode()` 展開月曆並截圖確認：日期數字/星期標頭/月份標題清晰可讀，格子仍維持緊湊排列不佔版面，console 無錯誤
- 純前端 CSS 調整，無 DB migration

---

### 2026-08-17g — 案件管理動態 Tab 下方內容/人員顯示字級放大

- 使用者回報「動態」Tab 下方發文列表的文字內容與人員（頭像/名稱）顯示過窄無法閱讀。用 Chrome MCP `javascript_tool` 量測 `.feed-bubble__content` 實際渲染寬度達 1223px（容器完全不窄，問題不在寬度），但字級僅 13px/12px/10px（content/author/time），明顯小於全站預設 15px 基準，在使用者當下套用的 UI 縮放（`motrixSetZoom` 1.15）下仍顯得侷促
- 調整 `case-management.html` 動態 Tab CSS：`.feed-bubble__content` 13→15px（line-height 1.65→1.7）、`.feed-bubble__author` 12→14px、`.feed-bubble__time` 10→12px、`.feed-badge` 9→11px、`.feed-avatar` 30→36px（字級 12→14px）、`.feed-compose__box` 13→14px、`.feed-empty`/`.feed-bubble__del` 13→14px；同步放寬 `.feed-bubble` 內距與 `.feed-item`/`.feed-list` 間距，純視覺尺寸調整不影響互動邏輯
- 已用 `javascript_tool` 直接呼叫頁面內 Alpine 的 `selectCase()`/`loadCaseUpdates()` 選取真實案件（`MQ-202607-137`，8 筆動態）量測調整後渲染尺寸，確認皆放大且無 console 錯誤；本次 Chrome MCP screenshot 工具連續逾時，改以 DOM 尺寸量測＋console 檢查驗證，未取得視覺截圖
- 純前端 CSS 調整，無 DB migration，無需 pytest

---

### 2026-08-17f — 案件管理動態 Tab 月曆比例修正＋業務開發排行改依廠商＋精算完結徽章空白 bug

- **A. 案件管理「動態」Tab 月曆比例錯誤**：使用者回報月曆無法完整顯示內容。根因是 `case-management.html` `.feed-cal-cell` 用 `aspect-ratio:1` 搭配 `grid-template-columns:repeat(7,1fr)`，但父層 `.cm-detail` 是 `flex:1` 可撐到 1000px+ 寬（案件詳情面板佔滿剩餘寬度），每格因此被撐成巨大正方形，6 週月曆總高度遠超過 `.cm-layout`/`.cm-detail` 的固定視窗高度＋`overflow:hidden`，導致下方發文框與動態列表被裁切看不到；格內字級本就是 9-10px 的小尺寸設計，明顯是設計成緊湊迷你月曆而非全寬。修正：`.feed-cal-wdays`/`.feed-cal-grid` 加上 `max-width:340px`，維持原設計的小尺寸樣式，不再隨版面寬度暴衝
- **B. 業務開發接洽成效總覽排行改依廠商**：使用者要求把「業務員接洽排行（近 30 天）」改成「近期聯繫最多廠商」排行。後端 `dev_crm.py` `GET /api/dev-crm/activity-stats`：`case_rows` 查詢補上 `case_name`/`customer_name`，建立 `case_id → (customer_name or case_name)` 對照表，取代原本依 `log_by`（記錄人）分組的邏輯；回傳欄位由 `bySalesperson`（`userId`/`displayName`/`count`）改為 `byVendor`（`name`/`count`），移除不再使用的 `umap` 變數；前端 `dev-crm.html` 同步更新標題文案、`actStats` 初始狀態與 template 綁定欄位
- **C. 精算完結徽章空白 bug**（驗證 A 時意外發現）：瀏覽器 console 出現 `Alpine Expression Error: Invalid or unexpected token`。`case-management.html:1369` 精算完結徽章的 `x-text` 內 `new Date(...).toLocaleString(\'zh-TW\')` 誤加了多餘反斜線跳脫符號（HTML 屬性內的 JS 字串不需跳脫，比對同檔案其餘 25 處 `toLocaleString()` 呼叫皆無此寫法），Alpine 解析整條 expression 失敗直接中止渲染，導致精算完結案件的「精算完結 · 精算日期：...」徽章整段空白；移除多餘反斜線即修復
- **驗證**：三處皆已用 Chrome MCP 在開發機瀏覽器實機操作——A 月曆縮小為緊湊小尺寸、6 週日期完整顯示、下方發文框/動態列表正常顯示；B 業務開發頁右欄排行榜正確顯示廠商名稱與次數（如：壹己商務中心有限公司 2 次）；C 以 `MQ-202607-028`（已結案案件）財務 Tab 確認徽章完整顯示「精算完結 · 精算日期：2026-07-15　完結人：黃玉龍　2026/7/15 下午11:05:22」，`read_console_messages` 確認無殘留 Alpine/JS 錯誤
- 純前端＋單一後端端點欄位調整，無 DB migration；`pytest` 106/106 全過

---

### 2026-08-17e — 移除業務開發接洽成效總覽「近 30 天最活躍」KPI

- 使用者要求拿掉這張卡片；`dev-crm.html` 移除該 `.dc-act-kpi` 區塊，KPI 列由 3 欄改回 2 欄，一併清掉行動裝置媒體查詢裡變成多餘的欄數覆寫
- 後端 `GET /api/dev-crm/activity-stats` 的 `bySalesperson` 欄位不變（業務員排行榜仍在用），純前端調整
- 已用 `node -e new Function()` 語法檢查與 div 標籤數量核對（165→162，減少的 3 個 div 對應被移除區塊的外層+兩個內層元素，數量吻合）

---

### 2026-08-17d — Asana 風格視覺化整合＋財務儀錶板支出項＋業務開發接洽成效總覽

- **背景**：使用者參考 Asana 官方介面截圖（月曆多天橫條視圖、Board 看板視圖），要求把這種視覺語言套用到任務相關介面；同時要求財務儀錶板新增支出項，並在對話過程中追加案件管理「動態」與業務開發模組的整合需求
- **A. 財務儀錶板支出項**：新增 `GET /api/dashboard/expenses-monthly`，彙整承攬商派發（複用 `vendor_contractors._dispatch_row()` 的 grandTotal 公式，避免重複邏輯）、料件/設備進貨成本（依 `parts.category` 分「設備」網通/監控/交換器/伺服器工控 vs「料件」線材配件/其他）、已精算完結案件的額外支出（`settlement.extraItems`，依 `editHistory` 最後一筆 `settlement_finalized` 時間歸月），近 12 個月，權限比照既有 `dashboard_monthly()`。`index.html` 新增「月支出結構」堆疊長條圖，4 類別配色已用 dataviz skill 的 `validate_palette.js` 驗證通過（CVD 檢查全過）
- **B. 每日工作事項 Asana 化**：`daily-tasks.html` 新增「月曆總覽」（全寬月曆，任務以彩色橫條顯示，同週內連續 occurrence 合併成一條橫條、貪婪演算法分配 lane，跨週斷開）與「看板」（依 category 動態分欄，卡片重用既有 `.dt-card` 系列樣式，`sortablejs` 拖曳跨欄，僅 `superadmin && dtUnlocked` 可拖曳，重建完整 payload PUT）
- **C. 案件甘特圖／專案看板加強**：`case-management.js` 甘特圖 bar 改依主要負責人 hash 上色並加 `custom_popup_html`（顯示負責人/日期/依賴階段）；`projects.html` 看板卡片新增成員頭像 chip（真實欄位 `projects.assigned_user_ids`，非新增資料模型）。三處共用同一組色碼＋hash 演算法（`_avatarColor`），讓同一人跨頁面顏色一致
- **D1. 案件管理「動態」Tab**：新增月曆 mini-grid（純前端統計已載入的 `caseUpdates`，不加 API），點日期篩選；`.feed-avatar` 改依發文者上色（沿用 C 的色碼演算法），事件類型徽章保留原本依來源上色
- **D2. 業務開發跨案件接洽成效總覽**：新增 `GET /api/dev-crm/activity-stats`（`dev_crm.py`），僅計入已核准 `dev_logs`，依既有 `_can_access_case()` 過濾權限，回傳近 60 天每日筆數、近 8 週週彙總、近 30 天業務員/通路排行；`dev-crm.html` 右欄「未選案件」空狀態改為接洽成效儀表板（KPI 卡＋純 CSS 長條趨勢圖＋排行榜），未額外引入圖表函式庫
- **驗證**：`node --check`／`new Function()` 語法檢查全數通過；`ast.parse`/`python -m py_compile` 驗證後端語法；對本機實際跑起來的 server 用 demo session 做完整 curl round-trip（`expenses-monthly`／`activity-stats`／每日工作事項 CRUD＋看板分類搬移 PUT 皆確認資料正確寫入讀出，含中文字元 UTF-8 完整性核對）；`pytest` 106/106 全過；`dashboard/expenses-monthly`／`dev-crm/activity-stats` 兩個新端點的聚合邏輯已對照開發機真實資料手算核對（承攬商派發 grandTotal=175,382／近 8 週接洽 7/18/2/3/1/0/0/0 筆），數字完全吻合
- 無 DB migration（全部復用既有欄位：`projects.assigned_user_ids`、`parts.category`、`contractor_dispatches` 既有欄位、`dev_logs` 既有欄位）；瀏覽器實機畫面驗證由使用者自行確認（Chrome MCP 操作時 plan mode 被反覆觸發，已改為純程式碼層級驗證）

---

### 2026-08-17c — 系統通知信全面補齊完整內容（不再截斷/省略）

- **背景**：使用者反映信件內容不完整，以案件留言板為例——收到新增留言通知信，但看不到留言
  實際寫了什麼，還是得登入系統才知道內容，違背「減少人員進入系統時間」的通知本意
- **根因**：`notify_module_activity()`（跨模組共用的通用活動通知，116 處呼叫）原本只有單行
  「項目」欄位，多處呼叫端把自由文字內容硬塞進這個單行欄位時用 `[:30]`/`[:40]` 截斷，或乾脆
  完全不傳，信件只看得到「誰在哪個模組做了什麼」，看不到實際寫的內容
- **修正**：
  1. `email_notify.py` `notify_module_activity()` 新增 `detail` 參數，獨立渲染「內容」區塊，
     完整呈現、保留換行、不截斷；同時補上 HTML escape（`html.escape`，含 `actor`/`item_label`/
     `detail`），避免留言含 `<`/`&` 等字元讓信件排版跑掉
  2. 逐一修正 9 個檔案共 10 處實際遺漏/截斷內容的呼叫端：
     - `quotations.py` 案件留言板新增留言：改傳完整留言全文，項目欄位補上客戶/專案名稱
     - `system.py` 工作日誌建立：改傳完整日誌內容
     - `dev_crm.py` 業務開發新增拜訪記錄：改傳完整記錄內容，並補回原本完全沒傳的聯絡管道與
       下一步待辦
     - `projects.py` 專案新增工作日誌：改傳完整工作內容
     - `customers.py`／`suppliers.py`／`vendor_contractors.py` 新增拜訪/往來紀錄：改傳最新一筆
       紀錄的完整備註內容（三個檔案是同一套「整份陣列覆寫」的往來紀錄模式，一併修正）
     - `vendor_contractors.py` 承攬商派發建立：項目欄位補上承攬商名稱，並傳入完整工作範圍說明
     - `shipping_notes.py` 出貨單回簽/取消回簽：改傳完整備註內容
  3. 已審查其餘 106 處呼叫（選型資料庫 CRUD、帳號/供應商/料號等結構化主檔異動、報價單狀態
     變更等）——這類動作本身沒有另外的自由文字內容欄位，項目欄位已是完整資訊，不需異動；
     23 個既有專屬 `notify_*` 函式（簽核／工作事項／到期提醒等）原本就傳遞完整內容，未受影響
- **驗證**：直接呼叫真正的 `notify_module_activity()` 攔截輸出，確認完整內容有出現、特殊字元
  正確跳脫（`<`/`&`）、換行轉為 `<br>`；對本機實際跑起來的 server 逐一實測案件留言／業務開發
  拜訪記錄／承攬商派發／往來紀錄四條路徑，皆正常回應無錯誤；`pytest` 106/106 全過

---

### 2026-08-17b — 承攬商派發新增發票號碼欄位

- **背景**：使用者要求承攬商發包需要能填寫發票號碼，所有填寫/顯示派發資訊的位置都要同步新增
- **DB v44**（`_m044_dispatch_invoice_no`）：`contractor_dispatches` 新增 `invoice_no TEXT DEFAULT ''`
- 後端 `vendor_contractors.py`：`DispatchIn` 模型、`_dispatch_row()`、`create_dispatch()`／
  `update_dispatch()` 的 INSERT/UPDATE 皆補上 `invoice_no`（JSON 欄位 `invoiceNo`，比照報價單
  收款品項 `invoiceNo` 的自由文字慣例）
- 前端：
  - `case-management.html` 承攬商派發 Modal（填寫）新增「發票號碼」欄位；派發卡片列表（顯示）
    新增發票號碼行
  - `vendor-contractors.html` 承攬商詳情「派發紀錄」區塊（顯示）新增發票號碼行
  - `settlement.html` 精算頁「三、承攬商派發成本」明細（顯示，唯讀即時讀取）承攬商列下方新增
    發票號碼小字
  - `case-management.js`：`dispatchForm` 狀態、`openEditDispatch()`、`saveDispatch()` 皆同步
    帶入/送出 `invoice_no`
- 已全庫搜尋確認派發相關欄位只出現在上述四個檔案，無遺漏位置；`node -e "new Function(...)"`
  驗證四個檔案內嵌 script 語法皆正確；額外用 Node 直接執行 `case-management.js` 真正的
  `_blankDispatchForm()`／`openEditDispatch()`／`saveDispatch()`（stub `fetch` 攔截送出內容）
  驗證欄位正確帶入與送出；後端用 Python `urllib` 對本機實際跑起來的 server 做完整 CRUD
  round-trip（建立含發票號碼→查詢→更新發票號碼→再查詢→列表端點皆正確反映），全部通過；
  `pytest` 106/106 全過

---

### 2026-08-17a — 修正精算「預估 vs 實際」毛利率公式不對稱

- **背景**：使用者要求複查案件金額／毛利率／報表／儀表板是否同步正確且公式正確。追查發現
  `quotation-form.html` 建立報價單時 `directProfit = pretax − totalCost − totalCost×5%`
  （對品項總成本額外扣一筆 5% 非扣抵進項稅才得出直接毛利），但 `settlement.html` 成本精算的
  每個品項預設 `actualCostTaxMode='pretax'`，`grossProfit = quotedPretax − totalActualCost`
  完全沒有這 5% 的扣除；`reports.py`（Excel「毛利分析」差異(pp)欄、`GET /api/reports/*` 的
  `estimatedMarginPct`/`actualMarginPct`）與 `dashboard.py`（`marginComparison`）都是直接拿
  這兩個公式不對稱的數字相減比較，導致即使案件實際成本跟原始報價完全相同，每一筆已精算案件
  都會系統性顯示「真實毛利率」比「預估毛利率」虛高——以典型 30~40% 毛利率的案件試算，落差約
  3 個百分點；已用 Python 模擬兩種公式驗證：修正前 bias=+3.19pp，修正後 bias=0.00pp
- **修正**（`frontend/pages/settlement.html`）：
  1. 精算品項初始化的預設 `actualCostTaxMode` 由 `'pretax'`（未稅，無調整）改為
     `'taxed_gross'`（含稅5%自動加總），與報價單建立時的假設基準一致；品項仍可個別切換回
     「未稅」或「含稅5%」因應該筆成本實際的稅務性質，只是改變沒有動過的品項的預設行為
  2. 精算頁「原始預估」欄位（`origDirectProfit`／`origMarginPct`／`origAdminCost`／
     `origCharity`／`origNetProfit`／`origNetMarginPct`）原本用 `settlement.items` 的
     `origQty`×`origCost` 重新加總計算，不僅同樣漏掉 5% 進項稅，還完全沒把
     `indirectLogistics`／`indirectInstallation`／`indirectTravel`／`indirectWarranty`／
     `indirectOther` 五個間接成本項目算進去；改為直接讀取報價單建立當下已經算好、存在
     `data_json.tot` 裡的對應欄位（沒有才 fallback 舊算法，相容尚未有此欄位形狀的極舊報價單），
     徹底消除「同一組數字兩處分別計算、公式各自漂移」的根本風險
  3. 只影響**尚未儲存過精算資料的新品項**；既有草稿或已完結（`finalized`）精算紀錄裡每個品項
     已存的 `actualCostTaxMode` 一律沿用不受影響，不回溯更動任何歷史精算快照
- 已用 `node -e "new Function(...)"` 驗證 `settlement.html` 兩個內嵌 `<script>` 區塊語法正確；
  `pytest` 106/106 全過（純前端修正，無 DB migration，後端測試本就不涉及此檔案）

---

### 2026-08-17 — 使用者個別 Email 通知偏好（DB v43）＋首頁最新動態彙整

- **背景**：`email_notify.py` 原本 23 個 `notify_*` 事件的收件人（`_admin_emails()` /
  `_superadmin_emails()` / `_lookup_emails()`）全員一體適用，無法讓特定管理員/使用者關閉自己
  不需要的信件類型；同時首頁缺少跨模組（業務開發／報價單／案件留言／出貨單／工作日誌／
  進出物料）彙整排序的「最新動態」總覽，只能逐一進頁面查看各自的更新
- **DB v43**（`_m043_notification_prefs`）：`users` 新增 `notification_muted TEXT DEFAULT '[]'`
  — 存的是「已關閉」事件 key 的**退訂清單**（非白名單），空陣列／NULL＝全部照舊接收，
  故既有使用者與新建帳號皆不受影響，未來新增事件類型也預設對所有人開啟
- **新模組** `helpers/notification_prefs.py`：`EVENT_GROUPS`（23 個事件 key，比照
  `notify_*` 函式名稱去除前綴，分 5 大類）＋ `is_enabled(muted_json, event_key)`
- `email_notify.py`：`_admin_emails()` / `_superadmin_emails()` / `_lookup_emails()` 三個
  收件人查詢函式加上 `event_key` 參數並依 `notification_muted` 過濾；23 個 `notify_*`
  函式呼叫處逐一補上對應 event_key
- **API**：`UserIn` 新增 `notification_muted`，`GET/POST/PUT /api/users` 同步讀寫
  （JSON 欄位 `notificationMuted`）
- `users.html`：新增／編輯使用者 Modal 內「Email 通知偏好」勾選區塊，比照既有「存取模組」
  手風琴分組 UI 樣式（`allNotifyTypes` / `notifyGroups` / `toggleNotifyType()`）
- **新 API** `GET /api/dashboard/activity-feed`（`routers/dashboard.py`）：彙整
  `case_updates`／`work_logs`／`dev_logs`／`stock_items` 直查 + `audit_log` 白名單動作
  （報價單／業務開發案件／出貨單）共 6 個來源，依時間新到舊合併排序；權限沿用既有規則
  （`can_quotation`／`can_dev_crm`／`_can_access_case()`／非 admin 只看自己名下報價單或
  工作日誌）
- `index.html`：首頁新增「最新動態」卡片，六色 `feed-badge` 依來源分類

---

### 2026-08-13 — 業務開發連結報價單改為審核制（可清空，DB v42）

- **背景**：2026-08-05b 開放的「修改連結」直接覆寫既有 `converted_quote_no`，且欄位必填不可清空；
  但案件變更常導致已連結的報價單被取消，此時需要能解除連結，而這類異動應比照案件刪除走審核，
  不該由單一使用者直接覆寫/清空已成立的連結
- **DB v42**（`_m042_dev_cases_relink_review`）：`dev_cases` 新增 `pending_relink` /
  `relink_requested_by` / `relink_requested_at` / `relink_reason` / `relink_target_quote_no`
  （空字串為合法值＝申請解除連結，非單純「未設定」）
- **新 API**：`POST /api/dev-cases/{id}/request-relink-quote`（admin+ 申請，`quote_no` 留空＝
  申請解除連結）／`POST .../cancel-relink-quote`（申請人或 superadmin 取消）／
  `POST .../approve-relink-quote`（僅 superadmin，核准後套用新單號或清空；清空時案件狀態
  一併退回「洽談中」，避免「成案」狀態掛著卻無對應報價單）
- `PATCH /api/dev-cases/{id}/convert` 加上守門：`converted_quote_no` 已有值時回 409，
  提示改走上述審核流程（原端點僅保留給尚未連結的初次轉建報價單使用）
- `dev-crm.html`：「修改連結」鉛筆按鈕改為開啟申請 modal（可留空、可填原因），案件詳情與
  清單卡片新增「待審核連結異動」標記，superadmin 專屬審核 modal（顯示申請人／原因／異動前後對照）
- Email 通知：`notify_dev_case_relink_request()`（新，仿 `notify_dev_case_delete_request`）

---

### 2026-08-05b — 業務開發×案件管理三項聯動（簽核閘門／連結可修改／動態同步）

- **報價單「已成案」需簽核完成**：`PATCH /api/quotations/{no}/deal-tag` 新增檢查，`deal_tag` 欲
  設為「已成案」時報價單 `status` 必須為「已送出」，否則 400；`quotation-form.html` 下拉選單同步
  disable「已成案」選項並在 `onDealTagChange()` 前端擋一次（雙重防呆，FORM_VERSION → V1.2）
- **業務開發案件連結報價單可修改**：原「轉建報價單」（`PATCH /api/dev-cases/{id}/convert`）僅在
  尚未連結時才顯示、且無法回頭修改；`dev-crm.html` 新增「修改連結」鉛筆按鈕 + 對應 modal
  （`openRelinkModal()`/`doRelink()`），沿用同一個既有端點（本來就允許覆寫，只是前端沒開放入口）
- **業務開發進度同步至案件管理「動態」Tab**：`GET /api/quotations/{no}/updates` 新增兩個來源
  （比照既有 work_logs／daily_task_completions 唯讀卡片模式）——① `dev_logs`（依
  `dev_cases.converted_quote_no` 反查 case_id 後列出）② `dev_case.status` 的 `audit_log`
  紀錄（案件狀態變更事件）；僅在該報價單有業務開發案件連結時才出現
- 用 demo 帳號（隔離空白庫）建立測試報價單/案件/開發記錄，以 curl 驗證三項行為皆正確後才收尾

### 2026-08-05 — 報價單簽核永久卡死：兩個共同根因修復 + 正式機 4 張卡死單查證

**緣起**：使用者回報「系統預設申請人不得自己簽核，但這位申請人送出的報價單，簽核流程設定裡把
這位申請人列為簽核人，導致報價單卡在簽核」，正式機當下已有報價單卡死。用使用者提供的正式機帳號
（`jeff`，superadmin）唯讀查證，確認卡死的是 `MQ-202608-003`～`006` 四張、皆由 `jeff` 直接送審。

- **Bug A**：`update_quotation()` 送審時把 `approval_flow` 設定轉成 tiers 快照，完全沒有排除
  送審人自己；`quotation-form.html` 的 `isCurrentTierApprover()` 寫死擋掉送審人自己的按鈕，但
  `approval-queue.html` 的 `canApprove()` 沒擋，兩頁邏輯矛盾；`approve_quotation()` 有 tiers
  分支原本也無自簽檢查
- **Bug B（比對正式機實際卡死單後發現、更根本的成因）**：正式機那 4 張單的 `approval` JSON
  完全沒有 `tiers` 欄位——`quotation-form.html` 的 `confirmSubmit()` 在「新單不先存草稿、直接
  送審」情境下打的是 `POST /api/quotations`（`create_quotation()`），但這個端點完全沒有 tiers
  建構或通知邏輯（該邏輯只存在於 PUT 的 `update_quotation()`），於是完全繞過已設定的兩層流程
  （`jeff→corbin`），也没有通知任何人（`corbin` 從未被告知要簽核）——任何人「新建報價單直接
  送審」都會中招，不限於送審人與簽核人重疊的情況
- 修法：新增共用 helper `_build_approval_tiers_and_notify()`（含 `_exclude_requester()`），
  `create_quotation()`（`body.status=='待審核'` 時）與 `update_quotation()` 都改呼叫同一段邏輯；
  `approve_quotation()` 補上自簽 403 防禦；`approval-queue.html` `canApprove()` 補上與
  `quotation-form.html` 一致的判斷
- 已用正式機唯讀查到的真實 `approval_flow` 設定（`jeff`/`corbin` 兩層）直接呼叫新 helper 驗證：
  `jeff` 正確被排除、只剩 `corbin` 一層、`corbin` 正確收到通知；全檔語法檢查通過。全程只對正式機
  呼叫唯讀 GET 端點，未寫入任何正式機資料
- 附帶修正：正式機 LAN IP 全站記錄錯誤（`172.16.11.211`→`172.16.10.177`，使用者確認為固定 IP），
  含 CORS 白名單與 email 通知連結預設值（若正式機從未手動設定過，過去簽核信件連結可能都是死連結）
- ⚠️ 尚未在瀏覽器實機重現完整送審流程（本機無 server 可測）；正式機 4 張卡死單不手動改資料庫，
  改為部署此修復後由 `jeff` 逐一「收回草稿」再重新送出，會走已修復的 `update_quotation()` 自動解卡

### 2026-08-04 — 報價單「新增品項」／「新增區段標題」按鈕失效修復

**緣起**：使用者回報報價單編輯頁「新增品項」「新增區段標題」兩個按鈕點擊完全沒反應。

- 根因：`addItem()`/`addHeader()` 呼叫 `crypto.randomUUID()` 產生 id，但此 API 只在安全情境
  （HTTPS 或 `localhost`）下才存在；透過區網 IP（`http://172.16.11.211:666`）以純 HTTP 存取時
  屬非安全情境，呼叫直接拋出 `TypeError`，函式中止在 push 進項目陣列之前
- 新增 `genId()` helper（安全情境下用 `crypto.randomUUID()`，否則 fallback 手動產生 id），檔案
  內 4 處呼叫點（`addItem`/`addHeader`/`loadQuote`/`copyToNew`）全數改用
- ⚠️ 尚未在瀏覽器實機驗證，下次有機會時請在非 `localhost` 位址實測確認

### 2026-08-03i — CRM 搜尋殘留 bug／側邊欄角標時區 bug（既有潛藏問題）／出貨單歷史紀錄

**緣起**：業務開發搜尋仍會出現不符搜尋文字的案件；業務開發／報價單側邊欄角標「仍然顯示但未有
其他更新」；要求新增出貨單歷史紀錄頁面。

- CRM 搜尋：`dev-crm.html` 搜尋框同時綁 `x-model.debounce.400ms` 與 `@input` 兩個監聽器互相打架，
  查詢字串永遠落後輸入一拍；改為 `x-model`（即時寫入）+ `@input.debounce.400ms`（延遲觸發查詢）
- 側邊欄角標時區 bug（既有潛藏問題）：`sidebar.js` 用 `toISOString()`（UTC）寫時間戳，後端存
  台灣本地時間，SQL 字串比較幾乎恆判定「有更新」；新增 `_localISOString()` 取代，連帶修好
  `daily-tasks.html` `isNewTask()` 同一套 bug
- 新增「出貨單歷史紀錄」頁面（`shipping-export-history.html` + `GET /api/shipping-notes/export-history`），
  攤平既有 `export_log` 為事件列表，無 DB migration
- 已用瀏覽器實測三項修改，測試資料已清除還原

### 2026-08-03g — 外包名冊新增「參與案件」聯動

**緣起**：使用者要求外包人員參與哪些案件也要跟承攬商管理一樣聯動，方便後續知道哪些人員參與過
哪些案件。

- `contractors.html` 詳情面板比照 `vendor-contractors.html` 承攬商頁的「派發紀錄」區塊，新增
  「參與案件」——沿用既有 `GET /api/contractor-dispatches`，前端用 `personnel_json` 快照篩出
  該人員實際參與的派發，顯示案號連結、狀態、所屬承攬商（純點工顯示無承攬商）、個人金額
- 已用瀏覽器實測驗證，無 console 錯誤

### 2026-08-03f — 承攬商派發改為選填，支援純外包名單人員點工（DB v37）

**緣起**：使用者反映「某些案件有外包人員，就沒有承攬商，單純點工，目前系統綁死要選擇承攬商」——
上一版加入的外包名單人員功能仍要求必選承攬商，無法涵蓋純點工案件。

- `backend/db.py` 新增 DB v37 migration `_m037_dispatch_vendor_optional`：`contractor_dispatches
  .vendor_id` 由 `NOT NULL` 改為可為空（SQLite 需整表重建，沿用既有建新表手法，冪等）
- `vendor_contractors.py`：`DispatchIn.vendor_id` 改選填；驗證改為「承攬商與外包名單人員至少
  擇一」，兩者皆空 → 400；`vendorName`/`import_dispatch_to_quote` 的 `None` fallback 一併修正
- 前端 Modal 拿掉承攬商必填星號，新增「外包人員（點工）」統一 fallback 顯示；派發卡片列表新增
  外包人員明細表格，金額改用 `grandTotal`（原本只算承攬商部分）；`settlement.html` 精算頁「三、
  承攬商派發成本」無承攬商時不再顯示佔位空列
- **零資料流失驗證**：複製開發庫副本跑新版 `db.py` 的 `init_db()`，確認 migration 前後列數不變、
  逐欄比對無跑位、重跑一次確認冪等；瀏覽器實測建立純外包人員點工派發（無承攬商）全流程正確

### 2026-08-03e — 承攬商派發新增外包名單人員個別計費，同步至財務／精算（DB v36）

**緣起**：使用者要求案件管理／承攬商派發新增「外包名單人員」，且承攬商與人員金額都要同步到
財務／精算顯示。

- `backend/db.py` 新增 DB v36：`contractor_dispatches` 加 `personnel_json`（自包含快照
  `[{id,name,amount,note}]`）；`backend/routers/contractors.py` 新增
  `GET /api/contractors/selectable`（比照 `vendor-contractors/selectable`）；
  `vendor_contractors.py` 補上讀寫與 `personnelTotal`/`grandTotal` 計算欄位
- 前端新增派發 Modal 內「外包名單人員」多選＋個別金額欄位；`settlement.html` 新增「三、承攬商
  派發成本」區塊（即時讀取、排除已取消），`calcSummary()` 併入 `dispatchTotal`；案件管理財務
  Tab 同步顯示
- 實測時發現並修正兩個問題：忘記把 `CURRENT_VERSION` 同步改成 36 導致新 migration 會被永久跳過；
  既有的「外包總成本」彙總算法本來就沒算稅金和人員，一併修正
- 已用瀏覽器完整驗證建立→儲存→精算顯示→已取消排除全流程，無 console 錯誤

### 2026-08-03d — 修復 module_versions 表無限增生 bug（DB v35）

**緣起**：使用者詢問正式機每日備份為何每次 300~400MB。查驗當天雲端備份 db 副本（唯讀，未動
正式機）發現 `module_versions` 表實際 626,725 列，但只有 143 組不同的 `(module, version)`，
佔掉備份 db 301MB 中超過 99% 的空間。

- **根因**：`module_versions` 表 `(module, version)` 從未有 UNIQUE 限制，`_sync_module_versions()`
  （`helpers/startup.py`）每次伺服器啟動用 `INSERT OR IGNORE` 想跳過已存在的紀錄，但沒有
  UNIQUE 可判斷衝突，每次重啟都把 143 筆 manifest 整批重複插入一次；crash-restart 迴圈＋
  歷次升級重啟長期累積出約 4,383 倍的重複
- `backend/db.py`：新增 DB v35 migration，補上 `UNIQUE(module, version)` 並重建表去重
  （優先保留使用者手動建立的紀錄），內含 `VACUUM` 釋放磁碟空間；migration 具冪等性
- `backend/routers/module_versions.py`：手動新增版本紀錄撞到重複 (module, version) 時
  回 409 友善錯誤，不再讓原生 IntegrityError 炸到 500
- **零資料流失驗證**：用當天正式機備份 db 副本實測（全程未連線正式機）——確認全部 626,725
  列皆為系統同步產生（無任何使用者手動輸入的紀錄）；用新版 `db.py` 的 `init_db()` 對備份副本
  跑過遷移，1 秒內完成，db 從 301MB 降至 1.71MB，143 列與 143 組相符（真正去重），逐筆比對
  manifest 內容與 db 內容全部一致（1 筆歷史內容差異屬既有現象，下次部署會自動同步修正，
  與本次遷移無關）；並用 `dbstat` 確認 db 內其餘所有表加總不到 1.5MB，沒有其他表有類似問題
- 尚未部署至正式機，需依 §15 流程由使用者在正式機執行 `apply_update.ps1`

### 2026-08-03c — 案件管理介面優化（5 項）

**緣起**：針對案件管理介面提出的 5 點建議，使用者確認後依序落實。

- `frontend/pages/case-management.html`：執行進度／叫料管控／設備登錄／保固備注 四個一級分頁合併為
  「執行管理」+ 二層子分頁（沿用既有但從未使用的 `.cm-subtabs` CSS），一級分頁 9→6 個；`.cm-tabs`/
  `.cm-subtabs` 補上手機版橫向捲動；拿掉與叫料管控分頁重複的「叫料到料」KPI；卡片新增「負責業務」欄位
- `backend/routers/quotations.py` 新增 `POST /api/quotations/case-activity`：彙整 `case_updates`/
  `work_logs`/`daily_task_completions` 三個不會觸發 `quotations.updated_at` 的動態來源，供案件卡片顯示
  「有新動態」未讀提示；`frontend/js/case-management.js` 比照業務開發 CRM 的「未讀游標＋一鍵已讀」設計
- 實測時發現並修正一個 bug：任務 1 一開始誤改到 `case-management.html` 裡的死碼 `__noop_stub()`（見
  2026-08-02c 條目警告），真正邏輯在 `frontend/js/case-management.js`；已修正並重新驗證
- 無 DB migration

### 2026-08-03b — 業務開發 CRM 新增一鍵已讀／只看未讀篩選

**緣起**：使用者反映業務開發模組「有更新」提示會不斷累積、清不完。追查後發現舊機制的已讀基準
是「上一次頁面載入的時間點」而非「離開時間點」，自己剛編輯的案件下次造訪仍會被判定為未讀，且
該提示原本只有 admin+ 看得到。

- `frontend/pages/dev-crm.html`：已讀基準改為模組專屬的 `localStorage` 游標，只能靠手動點擊
  「一鍵已讀」位移；開放給所有可用本模組的角色；新增「只看未讀」篩選與未讀彙總列；卡片欄寬
  300px→340px，新增業務開發／專案規劃人員姓名顯示
- 實測時發現並修正一個 bug：未讀判斷原本用字串比較時間戳，因後端格式（空格分隔）與
  `toISOString()`（`T` 分隔）在 ASCII 排序下不一致，導致同一天的更新恆判定為「未大於」而永遠不會
  顯示未讀；已改用正規化後的 `Date` 物件比較
- 未改動 `sidebar.js`/`notif.js`，其他模組共用的 sidebar 數字徽章機制不受影響
- 已用 demo 帳號實機驗證：未讀標示／一鍵已讀／只看未讀篩選／持久化皆正常運作

### 2026-07-30c — 場域選型導覽新增「簡易／進階」瀏覽切換

**緣起**：網路架構選型導覽上線後，使用者反應場域選型導覽原本的矩陣＋五組篩選＋搜尋太複雜，
希望比照網路架構選型導覽的「先選方塊、再看卡片」介面。討論後決定：不拿掉原本的進階瀏覽
（跨場域比較、風險/品牌篩選仍有價值），改成**新增一個可切換的簡易模式，兩種並存**。

- `frontend/pages/env-guide.html`：
  - 新增 `browseMode`（'simple'｜'advanced'）狀態，`.envg-hd` 新增「簡易／進階」分頁切換，預設 `simple`
  - 簡易模式：場域方塊（依大類分組：一般物流場/冷鏈/戶外/化工石化/延伸/通用）→ 點選後橫向顯示該場域所有分層的建議卡片（入門/建議/高端＋業界慣例＋特別注意＋產品連結＋缺口/關鍵/需外箱 badge），資料直接複用既有 `envRows`/`recRows`/`linkRows`（Alpine reactive），不碰資料庫、不碰原本的 vanilla JS 渲染邏輯
  - 進階模式：原本的矩陣／卡片／表格／搜尋／五組篩選／縮放／深淺色切換，原封不動保留
  - 簡易模式的卡片樣式與配色直接沿用網路架構選型導覽的 `.fam-tile`/`.gen-card`/`.tag-pill` 等 class（MOTRIX 系統配色，不受 ◐ 深色切換影響，因為這些 class 不在 `.envg` 命名空間內）

### 2026-07-30b — 新增「網路架構選型導覽」（選型資料庫第二類別）

**緣起**：場域選型導覽上線後，確立 ERP 要逐步擴充成涵蓋多產品線的「選型資料庫」（無人載具／
網路架構／監控／門禁／自動化系統…）。網路架構是第二個上線的類別，用來驗證：不同類別的內容
形狀可以差很多，不必硬塞進同一張表——這類是「技術族系→世代演進→產品」（如 Wi-Fi 6→6E→7、
4G→5G→5G mmWave），而非場域選型導覽的「情境×分層×三級」。

**後端（DB v30 → v31）**
- `backend/db.py`：新增 `_m031_netarch_guide` migration，建立 `netarch_families` / `netarch_generations`（FK family_code）/ `netarch_products`（FK generation_id）三表
- `backend/netarch_guide_seed.py`（新檔）：第一批資料——Wi-Fi（6/6E/7）、行動網路（4G LTE/5G Sub-6/5G mmWave），以 UniFi／Omada／Peplink／Netgear 實際產品驗證欄位設計
- `backend/routers/netarch_guide.py`（新檔）：`/api/netarch-guide/{families,generations,products}` CRUD，讀取任何登入者皆可，寫入需 superadmin 或 `netarch_guide_edit` 模組
- `backend/main.py`：掛載 `netarch_guide.router`

**前端**
- `frontend/pages/netarch-guide.html`（新檔）：瀏覽模式改用**先選族系方塊、再看世代橫向對照卡片**的簡化互動（不是場域選型導覽那套矩陣/篩選/搜尋），每張世代卡片含核心規格、比上一代進步、典型情境＋標籤、建議售價區間、依賴/相關備註、注意事項、對應產品；從一開始就用 MOTRIX 系統淺色配色（`--accent`/`--text-*`/`--border-light`），不再像場域選型導覽先做深色再改
- `frontend/static/sidebar.js`：新增 `cNetG` 模組旗標、`netg` 圖示、「業務」區塊新增「網路架構選型導覽」nav 項目
- `frontend/pages/users.html`：`allModules` 新增 `netarch_guide`（檢視）／`netarch_guide_edit`（新增修改刪除）

**文件**
- 新增根目錄 `SELECTION-DB-INDEX.md`（選型資料庫總索引：分類邏輯、類別清單、提需求格式）與 `NETARCH-GUIDE-CONTENT.md`（本類別內容維運手冊）

### 2026-07-30a — 新增「場域選型導覽」模組（原單機工具整合進 ERP）

**緣起**：`場域選型導覽.html` 原為 Claude Desktop 本機代理模式產出的獨立參考工具（無人自動化載具 30 個部署場域 × 分層三級設備建議，Sbjlink／Teltonika／iEi／Southco 原廠規格），資料寫死在 JS 陣列裡。今日整合進 MOTRIX ERP，資料庫化並開放後台編輯。

**後端（DB v29 → v30）**
- `backend/db.py`：新增 `_m030_env_guide` migration，建立 `env_guide_environments` / `env_guide_recommendations`（FK env_code, ON DELETE CASCADE）/ `env_guide_links` 三表；種子資料只在表為空時寫入一次（不覆蓋後續編輯）
- `backend/env_guide_seed.py`（新檔）：原工具的 30 筆場域／80 筆建議／44 筆連結，轉存為 JSON 字串常數供 migration 解析
- `backend/routers/env_guide.py`（新檔）：`/api/env-guide/{environments,recommendations,links}` 讀寫 CRUD；讀取任何登入者皆可，寫入需 superadmin 或 `env_guide_edit` 模組（沿用 `parts.py`／`contractors.py` 慣例，`_require_user`/`_audit`）
- `backend/main.py`：掛載 `env_guide.router`

**前端**
- `frontend/pages/env-guide.html`（新檔）：瀏覽模式完整保留原工具的搜尋／篩選／矩陣／卡片／表格／抽屜互動（vanilla JS 原樣搬遷，只把寫死陣列改成 `fetch()` API 資料），套上 MOTRIX topbar/sidebar 殼；新增「管理」模式做場域/建議/連結的新增修改刪除（Alpine + modal）
- 配色：`.envg` CSS 變數改對應 MOTRIX 系統色票（`--accent`/`--text-*`/`--border-light`/`--font-zh` 等），預設（`data-th="light"`）＝系統配色，原本的深色調保留為 `data-th="dark"` 備用切換（點 ◐ 圖示）
- **Excel 匯出／匯入**：僅 superadmin 可見（`session.role==='superadmin'`），3 個工作表（環境/建議/連結），匯入以代碼／ID 比對更新或新增，沿用單筆 CRUD API（做法比照 `customers.html`）
- `frontend/static/sidebar.js`：新增 `cEnvG` 模組旗標、`envg` 圖示、「業務」區塊新增「場域選型導覽」nav 項目（無 badge）、`_FILE_MODULE` 對應
- `frontend/pages/users.html`：`allModules` 新增 `env_guide`（檢視）／`env_guide_edit`（新增修改刪除，含 Excel 匯出入前提）二選項；`ROLE_MODULES.admin`／`.superadmin` 預設含 `env_guide`

### 2026-07-28a — 系統字體全面改為 LINE Seed TW_OTF（自架字型）

**字型自架（`frontend/fonts/`，新增目錄）**
- 複製 4 個字重的 OTF：`LINESeedTW-Thin.otf` / `-Regular.otf` / `-Bold.otf` / `-ExtraBold.otf`
- 由 `backend/main.py` 既有 `StaticFiles(FRONTEND_DIR)` 掛載自動於 `/fonts/*.otf` 提供，區網各台電腦免個別安裝字型即可看到一致外觀

**`frontend/css/style.css`**
- 新增 4 組 `@font-face`（`font-family: 'LINE Seed TW_OTF'`，`font-weight` 依 Thin 100-300 / Regular 400 / Bold 500-700 / ExtraBold 800-900 對應）
- `--font-en` / `--font-zh` 統一改為 `'LINE Seed TW_OTF', system-ui, sans-serif`（原分別為 Google Fonts CDN 的 `Inter` 與 `'Noto Sans TC', 'Inter'`）

**全站頁面／腳本（34 個 `.html` + `js/*.js` + `static/*.js`）**
- 移除所有頁面 `<head>` 內的 Google Fonts `<link>`（`fonts.googleapis.com` / `fonts.gstatic.com`，涵蓋 Inter / Noto Sans TC / Noto Serif TC）
- 所有內嵌 `font-family: Inter, sans-serif`（及各種空白/引號變體）、`'Noto Sans TC', sans-serif`、`'Noto Serif TC', serif` 統一替換為 `LINE Seed TW_OTF`（含 `quotation-form.html` 報價單 PDF 匯出樣式）
- Chart.js 全域字型設定（`index.html` / `js/reports.js` 的 `Chart.defaults.font.family`）同步更新

**批次取代衍生的字串斷裂修正**
- 以正則批次取代 `Inter,sans-serif` 時，凡原本落在**單引號分隔的 JS 字串**內（`static/sidebar.js` 8 處、`static/notif.js`、`index.html`、`pages/sales-orders.html`、`pages/quotation-form.html` 的 `style.cssText = '...'` 與 Alpine `:style="'...'"` 動態綁定），取代字串本身帶的單引號會提前把 JS 字串截斷、造成語法錯誤
- 修正方式：CSS 允許多字詞 `font-family` 值不加引號（`font-family:LINE Seed TW_OTF, sans-serif` 等價於加引號寫法），故在會截斷字串的位置一律改用不加引號形式
- 驗證：4 個獨立 `.js` 檔以 `node --check` 全數通過；全站所有 `.html` 內嵌 `<script>` 區塊以 `new Function()` 逐一語法解析，全數通過；`curl` 確認 `/fonts/LINESeedTW-Regular.otf` 回應 200（5.2MB）

### 2026-07-21g — 品質掃尾批次（Quality Sweep）

**L2 — SortableJS item key 碰撞修復（`frontend/pages/quotation-form.html`）**
- `addItem()` / `addHeader()` 的 `const id = Date.now()` → `crypto.randomUUID()`
- 複製模板路徑：`id: Date.now() + Math.random()` → `id: crypto.randomUUID()`
- API 載入後補 normalize：`this.q.items.forEach(it => { if (!it.id) it.id = crypto.randomUUID() })`（向後相容無 id 的舊報價單）

**L3 — pytest 覆蓋率擴充（`backend/tests/test_core.py`）**
- 新增 4 個測試類別，共 48 tests（原 25）
  - `TestStepsToTiers`（6 cases）：空陣列 / 單步驟 / 順序 / displayName fallback / userId default / 不保留 status
  - `TestActiveTiers`（5 cases）：空 / modern tiers passthrough / 舊 steps backward-compat / 預設 pending / tiers 優先於 steps
  - `TestCurrentTierIdx`（4 cases）：currentTier / currentStep / 預設 0 / 優先順序
  - `TestPasswordHelpers`（8 cases）：PBKDF2 hash+verify / 錯誤密碼 / 不同 salt / 舊 SHA256 相容 / 弱密碼策略

**確認已施作（無需動作）**
- L1：`notif.js:68` 鈴鐺 unread badge 已排除 `type==='approval_request'`，sidebar 角標與通知鈴鐺互不干擾
- E2：Login 速率限制（5 fails → 15 min lockout）在 `routers/auth.py` 已完整實作，含 DB 持久化
- E3：Session 清理（`_cleanup_sessions()`）在啟動時執行，已在 `helpers/startup.py` 實作

---

### 2026-07-21f — 可靠性強化批次（Reliability Patch Batch）

**H3 — 備份失敗 Email 告警（`archive.py`）**
- 新增 `_send_backup_error_email(reason, ts)` 函式
- `_write_backup_alert()` 在 `level=="ERROR"` 且同日尚未發送時呼叫之
- 收件者：`helpers.email_notify._admin_emails()`（所有 admin/superadmin 的 email）
- 發送方式：`_async_send()`（非同步，不阻塞備份流程）；若 Email 未啟用或無收件人則靜默跳過

**H4 — 匯出端點速率限制（`routers/reports.py`）**
- 新增模組級 `_export_times: dict`、`_export_lock: threading.Lock`、常數 `_EXPORT_COOLDOWN = 60`
- 新增 `_check_export_rate(user_id)` — 60 秒冷卻，違反回傳 HTTP 429
- `GET /api/reports/financial/excel` 和 `GET /api/reports/financial/pdf` 均在 auth 後立即呼叫

**M1 — steps→tiers 共用函式（`helpers/quotations.py` + 兩處呼叫端）**
- 新增 `_steps_to_tiers(steps: list) -> list`（無 status 欄位，純格式轉換）
- `helpers/__init__.py` re-export 新函式
- `routers/system.py._normalize_flow()` 改呼叫 `_steps_to_tiers()` 取代原本 inline comprehension
- `routers/quotations._setting_to_active_tiers()` 改呼叫 `_steps_to_tiers()` 取代原本 `[{"order": i, "approvers": [s]}]`
- `_active_tiers()` 維持獨立（需保留 status/approvedAt，不共用）

**M3 — pytest 單元測試（`backend/tests/test_core.py`）**
- 新增 `backend/pytest.ini`（`pythonpath = .`、`testpaths = tests`）
- 新增 `backend/tests/__init__.py`（空白，標記 package）
- 新增 `backend/tests/test_core.py`：25 個測試全部通過（1.31s）
  - `TestParsePeriod`（9 cases）：年度 / 月份 / 季度 / 閏年解析
  - `TestComputeAchievement`（6 cases）：空目標 / 年份不符 / 單案件 / 業務員分解 / 收款率 / 年份過濾
  - `TestCalc`（10 cases）：扣繳稅率 / 二代健保 / 外籍低薪率 / 有工會免補充費

---

### 2026-07-21e — 安全修補批次（Security Patch Batch）

**1. CSP Header（`main.py`）**
- `security_headers` middleware 新增 `Content-Security-Policy` 標頭（常數 `_CSP`）
- script-src 允許 `unsafe-inline`/`unsafe-eval`（Alpine.js 需求）+ `cdn.jsdelivr.net`；object-src `none`；frame-ancestors `self`

**2. Session Idle Timeout 8h（`main.py` + `db.py` + `routers/auth.py`）**
- DB migration v17：sessions 表新增 `last_active TEXT`
- 登入時（`auth.py`）INSERT 帶 `last_active = now`
- `auth_middleware`：若 `last_active` 已設且閒置 > 8h → 刪除 session + 401（`detail: "閒置超過 8 小時，請重新登入"`）
- 閒置 > 5 分鐘才更新 `last_active`（限制 DB 寫頻率）；首次請求（`last_active IS NULL`）直接 stamp 不拒絕

**3. `_PHOTO_SECRET` 持久化（`routers/projects.py`）**
- 原 `_PHOTO_SECRET = secrets.token_bytes(32)` 改為 `_get_photo_secret()` 函式
- 讀 `system_settings.photo_secret`；不存在時生成 32-byte hex 並儲存；以 `_PHOTO_SECRET_CACHE` 模組快取

**4. `PUT /api/settings/operating-targets` Pydantic Schema（`routers/system.py`）**
- 新增 `OperatingTargetsBody` / `_AnnualTarget` / `_SalespersonTarget` Pydantic 模型
- 替換 `body: dict = Body(...)` → 強型別驗證；同時寫入 audit_log（操作人、年度）

**5. HTML 逸出 in PDF 報表（`routers/reports.py:_build_report_html()`）**
- 函式內新增 `esc()` wrapper（`html.escape(str(v))`）
- 所有 period items / outstanding / case / sales / warranty / achievement 行的使用者資料欄位均套用 `esc()`

**6. AR 帳齡端點（`routers/reports.py`）**
- 新增 `GET /api/reports/ar-aging`（admin+ 權限）
- 返回：`{ asOf, note, bands:[{label, key, count, amount, items:[]}], total:{count,amount} }`
- 帳齡以案件報價日為基準分四區間；不含已收款項目

---

### 2026-07-21d — 財務報表：圖表分析 Tab

**新增 CDN（`reports.html`）**
- `<script src="https://cdn.jsdelivr.net/npm/chart.js@4">` 置於 `reports.js` 之前

**新增 Tab「圖表分析」（`reports.html`）**
- Tab 按鈕加於「目標達成率」之後；面板以 `x-show` 渲染（canvas 始終在 DOM，不影響 `x-ref` 解析）
- CSS 新增 `.chart-2col`（2:1 雙欄格線）、`.chart-card`（白底圓角卡）、`.chart-card__title`；RWD ≤800px 自動退為單欄

**`reports.js` 圖表方法**
- `_charts: {}`：chart 實例倉，供 destroy/resize 生命週期管理
- `initCharts()`：銷毀舊實例 → 設定全域字型（Inter/Noto Sans TC）→ 依序呼叫 5 個 `_build*Chart()`
- `_buildTrendChart()`：近 12 月成案趨勢，混合圖（Bar 件數左軸 + Line 合約金額右軸）；資料從 `casesAll.quoteDate` 分月聚合
- `_buildStatusChart()`：案件狀態分佈（Doughnut 65% cutout）；進行中（#F59E0B）vs 已結案（#6B7280）
- `_buildSalesPerfChart()`：業務員績效比較（Horizontal Grouped Bar）；合約總額 vs 已收款；最多顯示 8 人；高度依人數自動計算（max 180, count×52）
- `_buildTargetChart()`：年度目標達成率（Horizontal Bar + 紅虛線 100% 參考線）；6 指標色碼同 KPI Tab（綠/橘/紅）；`hasTargets=false` 時不渲染
- `_buildMarginChart()`：毛利率比較（Grouped Bar）；依業務員分組平均預估 vs 實際精算毛利率；`marginCases` 為空時不渲染
- `$watch('activeTab')`：切回 charts Tab 時，若實例已存在 → `resize()`；若初次進入 → `initCharts()`
- `$watch('data')`：期間切換後資料更新 → 在 charts Tab 時自動重新產圖

---

### 2026-07-21c — 財務報表：營運目標及達成率

**新 API 端點（`routers/system.py`）**
- `GET /api/settings/operating-targets`：讀年度目標（Bearer 即可）
- `PUT /api/settings/operating-targets`：寫年度目標（superadmin；body: `{year, annual:{revenue,newCases,collectionAmount,collectionRate,avgNetMarginPct,grossProfit}, salesperson:[{name,revenue,cases}]}`）

**後端計算（`routers/reports.py`）**
- 新增 `_compute_achievement(year, targets, cases_all)`：計算 6 大年度指標的 YTD 實績 vs 目標（含達成率、按時間比例目標）+ 業務員個人配額達成
- 新增 `_augment_with_targets(data, d0)`：從 `system_settings` 讀 `operating_targets`，計算 `achievement`，注入 `data["targets"]` / `data["achievement"]`（3 個端點統一呼叫）
- `_build_excel()`：新增 Sheet 2「目標達成率」（6 指標表 + 業務員配額表；達標/追趕/落後三色背景）；原 Sheet 2-7 順移為 Sheet 3-8
- `_build_report_html()`：PDF 新增「年度目標達成率」章節（6 格 KPI 卡片 + 進度條 + 業務員表格）；注入 `{acv_html}` 於執行摘要後

**前端（`reports.html` + `reports.js`）**
- `reports.js`：新增 `targets` / `achievement` getters；`acvGrade/acvColor/acvBarPct` 輔助函式；`openTargetModal / addSpTarget / removeSpTarget / saveTargets` 方法；`targetModal / targetForm / targetSaving` 狀態
- `reports.html`：新增 Tab「目標達成率」（6 大指標 KPI 卡片 + 進度條 + 業務員達成率表格）；目標設定 Modal（superadmin only：年度 + 6 大指標 + 動態業務員配額行）；CSS 新增 `.acv-grid / .acv-card / .acv-bar-track / .acv-bar-fill / .btn-set-target / .tgt-2col / .tgt-sp-row`

**達成率計算邏輯**
- YTD 案件：篩選 `casesAll` 中 `quoteDate` 以目標年份（`d0[:4]`）開頭者
- 按時間比例目標：`target × (今日為今年第 N 天 / 全年天數)`；收款率 / 毛利率無按比例
- 平均淨毛利率：基於 `settleStatus=finalized` 的 YTD 精算案件
- `targets.year` 不符合報表期間年份 → `hasTargets: false` → 顯示「尚未設定」提示

---

### 2026-07-21b — 每日工作事項大幅擴充 + Email 商務改版

**常駐任務（週排程折疊）**
- 左面板拆成「常駐任務」（`.recurring-card`，黃底，每週排程去重只顯示一次）和「單次任務」（日期分組）兩區塊
- 常駐任務卡片：本日 N/M 進度 + `monthRate()` 本月完成率 badge + 指派人員 chips
- `filteredWeeklyTasks()` 去重：同 task.id 只取今日 occurrence（或當月首筆）；`weeklyTodayOcc()` 輔助

**跨日逾期通知**
- `_check_overdue_and_notify()` 每日 08:00 掃描昨日所有任務（once + weekly）所有指派人
- 通知對象：被指派人 + 指定主管（若有，嚴格不 fallback 至所有 admin）；主管無 email 時記 warning
- **修復重啟重寄 Bug**：`_set_setting("dt_overdue_last_check", yesterday)` 移至 try block **之前**（guard 先寫），任何例外都不會重置 guard → 重啟不會重寄
- `schedule_overdue_check()`：新增 `if datetime.now().hour >= 8` 條件，深夜重啟不觸發 catch-up

**指派主管 Email 精確路由**
- `daily_tasks` 新增 `supervisors TEXT NOT NULL DEFAULT '[]'`（DB v16 `_m016_daily_task_supervisors`）
- `notify_daily_task_completed` / `notify_daily_task_overdue`：若 `supervisor_usernames` 有值→ 僅通知指定主管（不 fallback 至全體 admin）；主管無 email 時 log warning 並 return

**歷史紀錄功能**
- `GET /api/daily-tasks/{id}/history?page=&per_page=`：所有歷史 occurrence 分頁，軟刪除後仍可讀
- `GET /api/daily-tasks/{id}/history/export`：UTF-8 BOM CSV（7 欄位）
- 右面板 Tab 切換「本次紀錄」/「歷史紀錄」；歷史 timeline 可展開每人狀態 + 回報；「載入更多」分頁；匯出 CSV 以 `Authorization: Bearer` fetch 再 blob download

**回報彙整視圖（全面重設計）**
- 從頂部按鈕切換，佔滿主畫面；分割面板：左 256px 任務列表 + 右詳情
- 回報文字永遠顯示於人員名稱正下方；當前登入人員的行以紫色左側條標記
- 日期選擇：年份/月份 select + ← → 日期導航；全文搜尋：即時搜尋任務名稱/分類/回報內容

**Email 商務文案全面改版（`helpers/email_notify.py`）**
- 所有 9 個 `notify_*` 函式改用 `【MOTRIX】` 主旨前綴，加 `intro` 問候段落，自訂 `button_text`

---

### 2026-07-21a — 每日工作事項全改版

**Req 1 — `pages/daily-tasks.html` 全新設計**
- UI：固定頂部工具列（月份導航）+ 左右雙欄佈局（左面板 300px 搜尋+任務卡片 / 右面板任務詳情）
- 新增/編輯 Modal：日期/優先級/標題/分類/說明 + 排程設定（單次/每週 + 星期幾圓形按鈕）+ 卡片型式人員選取
- 解鎖 Modal：輸入密碼 → POST /api/auth/verify-daily-task-unlock；428=未設定→自動解鎖；403=錯誤

**Req 2 — 管理視角存取控制**
- DB v15：`users.daily_task_pw_hash TEXT NOT NULL DEFAULT ''`
- 後端 `routers/auth.py`：新增 `POST /api/auth/verify-daily-task-unlock`、`PATCH /api/users/{id}/daily-task-password`

**Req 3 — `pages/users.html` 兩項擴充**
- 每列操作區新增「工作事項」按鈕；編輯 superadmin Modal 新增每日工作事項密碼區塊

**後端修復：週排程（DB v14）**
- `_m014_weekly_recurrence`：`daily_tasks` 新增 `recurrence_type/days/end_date`；重建 `daily_task_completions`（UNIQUE 由 (task_id, username) 改為 (task_id, occurrence_date, username)）

---

### 2026-07-20v — 每日工作事項 + 簽核繞過修復

**每日工作事項（`工作內容` 分類下新頁）**
- DB v13：`_m013_daily_tasks` 新增 `daily_tasks` + `daily_task_completions` + 索引
- 後端 `routers/daily_tasks.py`（新）：6 端點（CRUD + PATCH complete）
- 前端 `pages/daily-tasks.html`（新）：左右雙欄；月份導航；superadmin 人員篩選；完成回報 form

**簽核繞過修復（`routers/quotations.py`）**
- `PATCH /api/quotations/{no}/status` 加前置檢查：若 body.status=="已送出" 且尚有未完成簽核層 → 403

---

### 2026-07-20u — 同一層簽核人必須按順序簽核

- 同層內的審核人必須照陣列順序逐一簽核（1號簽完 → 2號才能簽）
- 後端：先確認用戶在當層，再找 `first_pending`；不是第一位 → 403
- 前端 `quotation-form.html` / `approval-queue.html`：改為只看 `firstPending`

---

### 2026-07-20t — 簽核每層加入拒絕結案鎖死功能

- `quotation-form.html` 新增「拒絕結案」Modal（工具列按鈕 + 預覽 Modal 底部）
- 必填原因 textarea；確認後呼叫 `POST /api/quotations/{no}/reject-final`

---

### 2026-07-20s — 退回改版報價單全狀態 returnInfo 顯示

- 移除 `q.status === '草稿'` 限制，改為 `x-show="q.returnInfo"`，所有狀態均顯示退回橫幅
- `reject_quotation()` 中 `previousItems` 快照新增 `type` 和 `brand` 欄位

---

### 2026-07-20r — 案件管理匯入選取功能 + PDF 隱藏欄位修復

- 「從報價單匯入」改為選取式 Modal（checkbox 品項清單，可全選/清除）
- `pdf_gen.py`：修復 `pdfShow` 設定被完全忽略的問題；6 個欄位改為條件式輸出

---

### 2026-07-20p — 專案管理成員分配功能

- DB v12：`projects.assigned_user_ids TEXT DEFAULT '[]'`
- 後端存取控制：非 admin 使用者只看到其 ID 在 `assigned_user_ids` 內的專案
- 新端點 `PATCH /api/projects/{id}/assigned-users`

---

### 2026-07-20o — 使用者管理模組同步修復

- `case_manage` 補入 allModules；ROLE_MODULES 同步更新
- 空 modules 陣列 bug 修復：`hasAccess()` 改用 length 判斷
- equipment 模組 sidebar gating；`dashboard` 模組支援；ntfy icon 補全
- Async session 同步：每頁背景呼叫 `GET /api/auth/me`，有變動立即更新 localStorage 並重建 sidebar

---

### 2026-07-20n — case-management 端點驗證 + §7.1 修正

- 全 9 端點驗證通過（零斷線）
- 移除錯誤標注的 `PATCH /payment/{idx}`（舊版殘留）

---

### 2026-07-20m — case-management 執行 Tab 扁平化

- 移除「執行」父 Tab 及子 Tab 列；4 個原子 Tab 晉升為頂層

---

### 2026-07-20l — case-management 同步 UI/UX 升級

- 左側卡片色條（CSS `:has()` 選擇器）+ Tab 計數 Badge
- Header 3 列化；狀態變更 Popover；日誌卡片視覺強化

---

### 2026-07-20k — projects.html UI/UX 全面重新設計

- 狀態篩選列改 flex-wrap Pill；卡片左色條（CSS `:has()`，7 種狀態色）
- 右側 Header 3 列化；狀態 Popover；日誌卡片 32px 日期 Icon Block
- JavaScript 0 改動

---

### 2026-07-20j — 報價單列表未成案分類

- 「全部」改名「全部(不含未成案)」並排除未成案
- 新增「未成案」Tab

---

### 2026-07-20i — 簽核 bug 修復、狀態手動調整、設備群組匯入

- 移除「自動跳過自身 tier-0 簽核」邏輯（此邏輯在唯一簽核人即申請人時造成 stuck）
- superadmin 狀態手動調整下拉；設備群組區塊式顯示（可折疊，按 qty 建立 N 台）

---

### 2026-07-20h — reject-final 對接、品項標題行、單項毛利欄、拖曳排序

- `approval-queue.html` 前端對接「拒絕結案」（Modal + API）
- `quotation-form.html` 新增 `type:'header'` 品項；`addHeader()`；`real_idx` 跳過標題行
- 單項毛利欄（amount − qty × cost × 1.05）；SortableJS v1.15.3 拖曳排序
- `pdf_gen.py`：識別標題行，輸出藍色全欄標題行

---

### 2026-07-20g — 退回修改完整流程

- `notify_returned()` / `notify_resubmit_requester()`（新）
- `returnInfo` 快照（退回人/時間/原因/前版品項）
- `quotation-form.html`：退回通知橫幅 + 退回修改 Modal + 簽核按鈕重構

---

### 2026-07-20f — 簽核功能完善版

- 收回草稿（`POST /api/quotations/{no}/recall`）
- Email `from_name` 統一為 `"MOTRIX營運系統"`
- Email 靜默丟棄改為 warning log
- Photo token `@error` retry

---

### 2026-07-20e — 修正版

- 死碼清除：刪除 `frontend/js/` 21 個未被載入的 JS 檔
- settlement.html / approval-settings.html / projects.html 補實作與修正

---

### 2026-07-20d — 驗證修正版

- §2/§7/§9/§11/§13 全面修正（死碼標示、幽靈頁面、SQL fallback、雙路徑風險）

---

### 2026-07-20c — 架構梳理交付版

- 全面讀取後端 11 個 router + 6 個 helpers + archive/pdf_gen
- 新增 §5/§6/§7/§15（共用函式庫、API 端點列表、前端→API 對應、資料流呼叫鏈）

---

### 2026-07-20b — UX P3：簽核佇列警示 + 案件執行階段標籤 + 待精算篩選

- 儀表板 Onboarding 引導條；「待精算」篩選 Tab；簽核佇列紅色警示

---

### 2026-07-20 — UX P1/P2：簽核待辦儀表板 + sidebar 角標 + 通知拆分

- 儀表板「等我簽核」KPI；sidebar 簽核佇列角標；`GET /api/approval-queue/count`

---

### 2026-07-19b — Email 通知修復 + 舊代碼清除

- `is_new_submission` 改查 DB 舊狀態；OPTIONS 放行修正；restart.bat 改 PowerShell

---

### 2026-07-19 — Email 通知功能

- `helpers/email_notify.py`（新）：Gmail SMTP 非同步發信；5 事件函式

---

### 2026-07-18a — 全面安全審查 P0–P3（30 項）

**P0 — 安全漏洞**：多個端點補 `_require_user`；deal-tag 補 Auth header；DELETE 僅草稿

**P1 — 業務邏輯**：解鎖 superadmin 驗證；狀態機白名單；deal_tag 已結案不可逆；settlement 回滾；GET /auth/me 驗 expires_at

**P2 — 邊界案例**：mark_payment 樂觀鎖；delegateNote 寫 audit；已成案降級限 admin+；G: fallback；rate limit 持久化；notif.js DOM API；防重複送出 flag

**P3 — 品質**：JSON 原子寫入；Dashboard sparkline 真實資料；audit-log admin+ only；work-log owner 驗證
