# MOTRIX ERP — 安全（§3）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

---

## §3 · 安全（2026-07-18 強化後）

---

### §3.1 · 帳號與密碼

| 規則 | 說明 |
|------|------|
| **禁止明文密碼寫入文件／UI** | 歷史預設已移除 |
| 密碼長度 | ≥ **8**；拒絕已知弱密碼 |
| 雜湊 | PBKDF2-SHA256（260k）；舊 sha256 登入時升級 |
| 新建使用者 | 一律 PBKDF2；`must_change_password=1` |
| 管理員重設密碼 | 同樣標記強制改密 |
| 全新安裝 `jeff` | 隨機臨時密碼 → `backend/.initial_admin_credentials.txt`（用後刪） |
| 既有弱密碼 | 啟動 `flag_weak_passwords()` 標記；登入後強制改密 |

**強制改密流程**

```
登入 → mustChangePassword=true
  → 前端導向 change-password.html?forced=1
  → middleware 僅放行：/api/auth/me · change-password · logout · ping
  → 改密成功 → must_change_password=0 → 重新登入
```

### §3.1b · 登入失敗稽核與鎖定告警（2026-11-12）

**稽核**：四種登入失敗來源都寫 `audit_log`（`action='auth.login_failed'`、`result='fail'`、`status_code=401`），以 `reason_code` 區分；同帳號＋同 IP＋同來源 60 秒內合併成一列（累加 `detail.repeat`）。**不記密碼、驗證碼、token。**

| 來源 | `reason_code` | `detail` | 寫入點 |
|---|---|---|---|
| 密碼錯誤 | `login_failed`（歷史值，不變） | `{ip, repeat}` | `routers/auth.py` 登入 |
| TOTP 驗證碼／救援碼錯誤 | `totp_failed` | `{ip, repeat, method:"totp"}` | `/api/auth/login/totp` |
| QR 核准（密碼）錯誤 | `qr_failed` | `{..., method:"qr"}` | `/api/auth/login/qr-approve` |
| Passkey 失敗 | `passkey_failed` | `{..., method:"passkey"}` | `/api/auth/webauthn/login/complete`（六個失敗點） |

四種都統一由 `_rl_fail(ip, username, source)` 寫稽核＋計入鎖定計數（以前只有密碼會寫稽核）。標籤對照在 `helpers.audit._FAIL_REASON_LABELS`／`LOGIN_FAIL_REASONS`。

**鎖定告警**（`helpers/auth_alert.py`，信件類型 `auth_lockout`＝系統技術類、預設只給最高管理者、信件關閉被鎖住）：
- **觸發**：`_rl_fail` 達到鎖定（5 次失敗／15 分鐘，以 IP；IPv6 取 /64）的那一刻發**一次**，不是每次失敗。內容：來源 IP、嘗試過的帳號（最多 5 個，**遮蔽**：存在的帳號原樣、不存在的只留前 2 字＋字數、像密碼的整個遮掉）、失敗次數、鎖定到幾點。
- **節流**：同一個鎖定範圍在鎖定期間只發一次；全系統每個滾動 1 小時最多 10 則（`HOURLY_CAP`）、每個滾動 24 小時最多 20 則（`DAILY_CAP`，摘要也算），超過的合併成**一則摘要**（件數＋最多 5 個 IP），等兩個視窗都有空位才送。節流狀態在記憶體，重啟後清空（鎖定本身存 DB，仍有效）。**兩個上限可調**：`system_settings.auth_alert_limits = {"hourly_cap": n, "daily_cap": n}`（各 1～1000；設定頁沒有欄位，維運寫資料庫）。
- **不拖慢登入**：只做記憶體判斷，發送在背景執行緒；任何例外只記 log，不影響登入回應（仍回 401／429）。
- **收件人**：沿用「信件與通知收件設定」（預設最高管理者；可覆寫）。**Email 與 LINE 是獨立通道**：Email 只寄有 Email 且未退訂的人；LINE 不看 Email，依同一份收件設定解析帳號 ⇒ LINE「可收的角色」⇒ 本人 LINE 勾選 ⇒ 已綁定。同一個人兩邊都有就兩邊都發。
- **LINE 條件**：LINE 公司層事件開關**預設關**（LINE 設定頁勾選「登入失敗鎖定告警」才發）；等級是 critical，**額度保留（用量 ≥ 90%）時照發**，推播後額度告警照常。**每月累計上限**：本事件 LINE 每月累計不超過月額度的 25%（`LINE_EVENTS["auth_lockout"]["month_cap_percent"]`；月額度用 LINE 回報值；**LINE 回報無上限（付費方案）時沒有每月上限**；本月用量讀不到時保守用 200＝免費方案），超過只寄 Email；可用 `system_settings.line_notify.month_cap_percent = {"auth_lockout": n}` 調（0＝不發 LINE）。只有收件人才會在「我要收的 LINE 通知」看到這一項（`audience="group"`）。
- **已知限制**：⓪稽核表 `audit_log.username` 仍記嘗試帳號原文（可能是誤填的密碼；server log 與告警內容已遮蔽）；①LINE 開關預設關，上線後要有人勾；②節流與未送出的摘要在重啟時遺失；③被灌爆時（超過每小時上限）細節只留在稽核與 log，通知只有摘要；④每則通知給 N 位收件人耗 N 則 LINE 額度（最壞每天 20×N，且受每月 25% 上限約束）。
- **上線步驟（F10，缺一則 LINE 告警是靜默的）**：套用步驟檔要加：①到「通知設定」→「LINE 通知」勾選「登入失敗鎖定告警」；②確認至少一位最高管理者（或「信件與通知收件設定」指定的收件人）已綁定 LINE；③（可選）確認 `auth_alert_limits`／`month_cap_percent` 的數字符合預期。Email 不受①②影響。
- 通用規則（LINE 獨立通道、額度保留、已推播記號、事件字典）見 `helpers/line_notify.py`（`LINE_EVENTS`／`deliver_event`）與 `helpers/event_audience.py`。

---

### §3.2 · 解鎖密碼（報價單解鎖編輯）

- 僅 superadmin；與登入密碼獨立
- **不再自動寫入共用預設**
- 啟動若偵測歷史弱預設 → **清空 hash**，需至使用者管理重新設定
- 未設定：`POST /api/auth/verify-unlock` 回錯誤提示先設定
- 解鎖成功後：顯示「取消解鎖」按鈕（`cancelUnlock()`），防止意外觸發重送審

---

### §3.3 · Session 與 API 保護

| 項目 | 值 |
|------|-----|
| Session | `sessions` 表，預設 30 天；`expires_at` 中介層 + `/auth/me` 雙重驗證 |
| 白名單 | `/api/ping` · `/api/auth/login` · `/api/auth/login/totp` · `/api/auth/logout` · `/api/system/version` |
| 其餘 `/api/**` | 需 `Authorization: Bearer {token}` |
| 回應標頭 | `X-Content-Type-Options` · `X-Frame-Options` · `Referrer-Policy` |
| **登入暴力破解** | per-IP rate limiting；5 次失敗鎖 15 分鐘；HTTP 429 含倒數；**鎖定狀態持久化** `login_rate_limit` 表（DB v11），重啟不失效 |

---

### §3.3b · TOTP 兩步驟驗證（自助啟用，DB v72，2026-09-07）

架構地圖 §6.2 建議事項——`users` 目前只有密碼＋Bearer token 單因子。採**自助啟用而非強制**：正式機 superadmin 是 jeff/corbin 兩位真人業主，若做成下次登入強制進入設定流程，部署當下他們手邊沒先裝好驗證 App 會直接被鎖在外面，屬於會中斷真實業務的風險（決策見 db.py `_m072_totp()` docstring）。任何角色皆可自助到「修改密碼」頁（`change-password.html`）啟用；`notif.js` 對 admin/superadmin 未啟用時顯示提醒 banner（`sessionStorage` 節流每分頁一次，純提醒不阻擋操作）。

```
setup（POST /api/auth/totp/setup）→ 產生密鑰，totp_enabled 仍是 0
  → enable（POST /api/auth/totp/enable，需輸入一次正確驗證碼）→ totp_enabled=1
    → 產生 10 組一次性救援碼，明文只在這次回應出現，DB 只存雜湊
登入：/api/auth/login 密碼正確但 totp_enabled=1 時不核發 session，
      回傳 {totpRequired, challengeToken}（process-global 記憶體，5分鐘過期，非 DB）
  → /api/auth/login/totp 送驗證碼或救援碼核實後才真正核發 session
      （6 位數字視為 TOTP code；其餘視為救援碼，比對雜湊後即時作廢）
```

| 項目 | 說明 |
|------|------|
| `users.totp_secret`/`totp_enabled`/`totp_recovery_codes` | DB v72，見 `_m072_totp()` |
| 停用 | 需重新輸入目前密碼確認（比照既有敏感操作慣例），不需再帶驗證碼 |
| 登入第二階段防暴力破解 | 每個 challenge 最多 5 次錯誤即作廢（需重新輸入密碼），錯誤同時也計入既有 per-IP 登入鎖定 |
| 手機掃 QR 核准（2026-11-12 起） | **只接受「這支手機已登入同一個帳號」（`session_token` 分支）**；原本的「輸入密碼核准」已移除——它讓只知道密碼的人能自己核准自己的登入、繞過 TOTP（hichan-1 審查 F1）。手機沒登入時頁面顯示「請在手機上先登入同一個帳號再掃碼」；`qr-status`（發 session 的最後一步）也套帳號鎖與外網強制 TOTP |
| Demo 帳號 | 不支援（`auth_login()` 的 demo 分支在檢查 totp 之前就已回傳，設計上就不會走到） |

---

### §3.3d · 外網登入防護：外網強制 TOTP＋單一帳號鎖定（2026-11-12，外網登入強化票）

背景：`motrix-platform.miactw.com` 經 Cloudflare Tunnel（→ `https://localhost:666`）對外開放後，風險評估（`正式機回報/20261112_外網開放風險評估.md`）指出登入保護只有「每來源 IP 5 次／15 分鐘」，換很多 IP 就能持續猜同一個帳號的密碼；TOTP 當時只有 2 位最高管理者啟用。設定在設定中心群組「外網登入防護」（`external_login`），程式 `helpers/external_access.py`（判定＋強制規則）、`helpers/account_lock.py`（帳號鎖）、`routers/auth.py`（接線）。內網登入行為不變。

**① 「外網」怎麼判定**（`external_access.classify`，**判斷不出來一律當外網**；任何一條成立＝外網）

| 順序 | 條件 | 理由 |
|---|---|---|
| a | 帶 Cloudflare 標頭（`CF-Connecting-IP`／`CF-Ray`／`CF-Visitor`／`CF-IPCountry`） | 經隧道進來的請求一定有；區網直連不會有 |
| b | `Host` 是設定的外網網域（預設空；要加第二層就在設定中心填網域，正式機填 Tunnel 的網域） | 設定可調（`external_hosts`） |
| c | 帶 `X-Forwarded-*`／`Forwarded`／`X-Real-IP` | 有代理介入就不當內網 |
| d | 來源 IP（`helpers.client_ip.client_ip`，T80 的可信判斷，**不讀 XFF**）解析不出來、是 loopback（127.x／::1），或不在內網網段 | 內網網段預設＝私有網段（10/8、172.16/12、192.168/16、169.254/16、fc00::/7、fe80::/10），設定可調（`internal_networks`）但**只收私有網段**，公網網段、0.0.0.0/0 與 loopback 會被忽略 |
| e | 其餘（無代理痕跡且 IP 在內網網段） | ＝內網 |

偽造只會往「更嚴」：區網自己加 CF 標頭／改 Host／塞 XFF ⇒ 被當外網；外網使用者無法把自己變內網（標頭由 Cloudflare 加、IP 由 T80 可信判斷）。
**本機直連（loopback）預設不算內網**（F2）：同一台電腦上的非 Cloudflare 代理（netsh portproxy、frp、同機 nginx 去掉標頭）會讓外部使用者看起來像本機，若算內網就會免除 TOTP 與帳號鎖定。影響：直接在正式機上開 `https://localhost:666` 登入時適用外網規則——被要求 TOTP 的角色必須已啟用（最高管理者已啟用；管理員／財務未啟用者本機也登入不了，請從區網登入）；`tools/deploy_dashboard.py` 等本機工具的登入同理（它支援輸入 TOTP 碼）。真的需要本機免 TOTP：設定中心「本機直連算內網」（`loopback_is_internal`，放寬方向、走確認期間＋第二位最高管理者核准）。
注意：同事在辦公室用外網網址（`https://motrix-platform.miactw.com`）登入，對系統來說就是外網（走 Cloudflare），適用外網規則；用內網位址登入才是內網。

**② 外網強制 TOTP**：總開關 `ext_totp_enabled`（預設開）＋每個角色一個開關（預設 superadmin／admin／finance 開；sales／engineer／viewer 關，可在設定中心調整）。外網登入、該角色被要求、帳號 `totp_enabled=0` ⇒ **403** 並提示「請先在公司內網登入並啟用兩步驟驗證」；**密碼要先正確**才會看到這個訊息（錯密碼仍是通用的 401，不洩漏帳號資訊），拒絕不算密碼失敗、不計入鎖定、寫稽核 `auth.login_refused_external_totp`（`reason_code=ext_totp_required`）。已啟用 TOTP 的人走原本的挑戰流程。Passkey 登入（目前暫緩）同樣套用。`demo` 帳號不適用。只管「登入」；已發出的 session 不綁來源。放寬方向（關總開關、取消某角色、調高門檻…）一律走設定中心的確認期間＋第二位最高管理者核准，收緊立即生效。

**③ 單一帳號鎖定**（不分 IP；預設 10 次／30 分鐘窗 → 鎖 30 分鐘）

| 取捨 | 內容 |
|---|---|
| 經典做法的問題 | 任何人故意輸錯就能把別人鎖在門外（DoS），包含在公司內網的本人 |
| **預設（模式 1，只鎖外網）** | 只計**外網來源**的失敗；鎖住時只擋外網登入，**內網照常能登入**；內網成功登入會解除該帳號的鎖；超級管理員可手動解鎖（`GET /api/auth/account-locks`、`POST /api/auth/account-locks/unlock`）；30 分鐘自動解除。攻擊者最多讓「該帳號暫時不能從外網登入」，不能讓人進不了系統 |
| 模式 2（設定 `lock_scope=2`） | 不分來源計數、被鎖時連內網也擋；最嚴但有 DoS 風險，只建議遭受持續攻擊時暫用 |
| 不被延長 | 鎖定期間的嘗試被直接擋、**不計數也不延長鎖定**，攻擊者無法靠持續送請求把鎖拉長 |
| 不洩漏帳號是否存在 | 任何帳號名（含不存在的）一視同仁計數、同樣回 429 |
| 預占計數（F4） | 登入入口（密碼、TOTP 步驟、Passkey）一進來就在**同一把鎖裡**檢查鎖＋把這次嘗試先算進去；窗口內放行滿門檻次後，第「門檻＋1」次當場鎖並拒絕 ⇒ 併發的猜測最多放行門檻次（以前是驗完才計數，40 個併發都能通過）。密碼正確時退回預占，成功登入清計數 |
| 清表（F5） | 計數表上限 10,000 列；超過先丟整窗沒再嘗試的，再依（窗內次數少 → 最近一次舊）丟前半，**保留接近門檻的列**，塞滿一次性帳號名擠不掉已累積的受害帳號 |
| 帳號名是攻擊者可控字串（F6） | 記憶體與資料庫的鍵都是雜湊（`acct:`＋SHA-256 前 20 碼），**資料庫不存帳號明文**；稽核／告警／log 只顯示「已存在的帳號」名稱（去控制字元、限長），不存在的帳號名（可能是被貼進帳號欄的密碼）只顯示雜湊前 8 碼與長度，明文不進鎖定稽核、告警、log。注意：既有的「登入失敗」稽核（`auth.login_failed`，helpers/audit.py）原本就記嘗試的帳號名，本票沒改它 |
| 持久化 | 鎖定寫進 `login_rate_limit`（鍵 `acct:<小寫帳號>`），重啟後仍有效；失敗計數只在記憶體（重啟歸零，最壞情況是少算） |
| 稽核／告警 | 鎖定那一刻寫 `auth.account_locked`（帳號、來源 IP、次數、門檻，不含密碼）；呼叫 `helpers.auth_alert.on_lockout(scope="account")`（與 IP 鎖定共用 auth_lockout 事件與每小時上限）；解鎖寫 `auth.account_unlocked` |

**④ Cloudflare 限流**（使用者自己在後台設）：見 `docs/platform/guides/CLOUDFLARE-RATE-LIMIT-GUIDE.md`（免費方案 1 條規則、10 秒窗、依 IP；擋瞬間狂打，慢慢猜靠程式的 IP／帳號鎖定與 TOTP）。

**⑤ 已知限制與交使用者決定的風險**（hichan-1 審查，維持原取捨）：
- **F3 外網持續 DoS**：外網攻擊者可反覆讓某帳號「無法從外網登入」（鎖到期後立刻續鎖）。內網登入不受影響、內網成功登入會解鎖、超管可手動解鎖；若要連這個也消除，只能放棄帳號鎖（改靠 TOTP＋Cloudflare 限流）或改成「帳號鎖只在密碼驗證成功後才套」——都有更大代價，交使用者決定。模式 2 會把這個 DoS 擴大到內網。
- **F8 403 當密碼探針**：外網、角色被要求 TOTP 而帳號未啟用時，密碼正確回 403（白話訊息）、錯誤回 401，攻擊者可據此得知密碼是否正確（不會拿到 session）。該拒絕刻意不計入鎖定（否則本人被鎖）；緩解：被要求 TOTP 的角色都盡快在內網啟用 TOTP（啟用後外網只會看到 TOTP 挑戰）。
- **F7 合併順序**：帳號鎖定告警呼叫 `helpers.auth_alert.on_lockout(scope="account")`（hichan-3 的 auth_lockout 告警）；本分支必須在它**之後**合併，缺它時鎖定與稽核仍有效，但告警不會發出，並記 `logger.error`。
- 同公司同事共用對外 IP 時，IP 鎖定仍是「一人輸錯 5 次鎖全辦公室外網」（既有行為，T80 起）——帳號鎖不影響這點；TOTP 啟用要在內網先做（外網沒啟用的角色進不來）。測試：`backend/tests/test_external_login_hardening_2026_11_12.py`。

---

### §3.3c · Passkey／WebAuthn 與 HTTPS 憑證（2026-09-11 起實際可用；**Passkey 已於 2026-09-16 暫緩**）

> 🔴 **2026-09-16 起 Passkey 功能暫緩使用（使用者裁示）**，本節以下描述的是
> **功能開著時**的行為規格，不是現在的畫面。總開關
> `backend/helpers/auth.py::PASSKEY_ENABLED = False`：所有 `/api/auth/webauthn/*`
> 與 `/api/settings/webauthn-config` 回 404，三個前端頁面的 Passkey 區塊都不顯示。
> **是暫停不是移除**——程式碼、`webauthn_credentials` 資料表、既有憑證列全部原樣
> 保留，改回 `True` 就整組回來（含 55 題被 skip 的測試）。細節見 §12 2026-09-16。
>
> 本節的 HTTPS／mkcert CA 部分**不受影響**，那是整站 HTTPS 的基礎，跟 Passkey 無關。

> 兩份專門文件：`PASSKEY-CA-ROLLOUT.md`（自簽 CA 那條路，**已執行完畢**）／
> `LETSENCRYPT-PUBLIC-CERT-PLAN.md`（公開憑證那條路，**規劃完成、尚未執行，是下一個決策點**）。
> 本節只寫「現在是什麼狀態」與「碰它之前要知道的事」，步驟細節看那兩份。

**目前狀態（2026-09-11 01:20 實測）**

| 項目 | 值 |
|------|-----|
| 憑證 | mkcert 自簽，SAN = `DNS:localhost, DNS:motrix.internal, IP:172.16.10.177, IP:127.0.0.1`，有效期至 2028-12-10；舊憑證備份在正式機 `backend\certs\backup_20260910_144802\` |
| 根 CA 指紋 | `A9AF974F0BD6CE35B47CDB95CAA5E2B324DAE61C`（正式機 `%LOCALAPPDATA%\mkcert\`；**`rootCA-key.pem` 絕對不能離開正式機**） |
| 已裝 CA 的機器 | **只有正式機與開發機兩台**。其他同事的電腦要用 Passkey，每台都得做兩件事：①`certutil -addstore -f Root rootCA.pem` ②能解析 `motrix.internal`（兩台的主網卡 DNS 都是 8.8.8.8，不是 Peplink，所以是加 hosts 解決的） |
| RP ID / Origin | `motrix.internal` / `https://motrix.internal:666`（存 `system_settings`，**不在 git 裡**） |
| 用戶端一鍵設定 | `backend/tools/setup_passkey_client.ps1`（裝 CA＋加 hosts，需系統管理員）；`fetch_root_ca.ps1` 從正式機取回 CA |
| 實測 | 使用者已可註冊 Passkey **並用 Passkey 登入**；自動化 e2e `backend/tests/test_e2e_passkey_2026_09_11.py`（CDP 虛擬認證器）覆蓋整條路 |
| **到期告警** | ✅ 2026-09-11 新增 `daily_tasks.py::_check_cert_expiry()`——**在那之前完全沒有任何監控**。門檻依憑證總效期自動切換（>180 天視為手動簽發 → 60/21/7 天；否則視為 ACME → 21/7/1 天），過期後每 7 天重寄。以目前這張算，第一次告警是 **2028-10-11**（到期前 60 天） |

> **2026-09-13 使用者回報的「Passkey 又失效」＝網址問題**（不是憑證、不是 RP ID、
> 也不是 Windows Hello）。當天逐項驗過開發機：mkcert 根 CA 在 LocalMachine\Root 且
> 指紋相符、hosts 有 `172.16.10.177 motrix.internal`、正式機憑證 SAN 含
> `motrix.internal` 有效到 2028、`webauthn-config-status` 為 `configured:true`、
> 正式機為該帳號存了 2 張憑證且都在現行 RP ID 下，而**本機 Windows Hello 裡那張
> `motrix.internal / jeff` 的 credentialId 與伺服器手上的第 2 張完全相同**。
> 也就是說兩邊都好好的，失敗的是入口——**只有 `https://motrix.internal:666` 這個
> origin 能用**；用 IP、`localhost` 或 `http://` 進去，瀏覽器在
> `navigator.credentials.get()` 就會擋。下次再遇到「Passkey 失效」，**先確認網址**，
> 那是成本最低也最常中的一項（通知信的 `base_url` 目前仍是 `http://172.16.10.177:666`，
> 從信裡點連結進去就會踩到）。

**❌ 已排除的替代方案（2026-09-11 決定，不要再重新評估）**

| 方案 | 為什麼不做 |
|---|---|
| **Cloudflare Origin CA 憑證** | 它的根 CA **不在任何瀏覽器／OS 信任清單裡**（設計如此，是給 Cloudflare proxy ↔ 主機那一段用的）。要用就得每台裝 Cloudflare 的根 CA，等於回到現在 mkcert 的處境、一台都沒少，還改成信任一個不是自己控制的第三方根。**解決不了原本的問題** |
| **Cloudflare Tunnel + Access** | 唯一的獨門好處是「從公司外面能用 ERP」，代價是①對外網路一斷，坐在辦公室也連不上②全部 ERP 流量在 Cloudflare 邊緣解密③正式機多一個不在 git 的常駐服務④Access 會在 ERP 登入頁之前再插一層登入。而**使用者規劃中的 VPN 解的是同一個問題**且沒有這四項代價。錢不是因素（該用的方案都在免費額度內） |

> 若之後真的要重開這個討論，前提是「VPN 確定不做」。另外注意：改走 Tunnel **不需要再換一次 RP ID**（RP ID 只認主機名、不含 port），只要改 Origin 設定，既有 Passkey 不會失效。

**⏳ 動 RP ID 之前必讀——這是本模組唯一不可逆的操作**

**一旦改動 RP ID，所有既有 Passkey 全部失效且無法救回**——綁定在瀏覽器端，不在我們手上，
沒有補救、沒有遷移，只能請每個人重新註冊。

**2026-09-11（DB v74）補上 `webauthn_credentials.rp_id`**：v73 建表時沒存這個欄位，代價是系統
**查不出哪張憑證屬於哪個 RP**——只能對使用者說「全部都可能不能用了」，而使用者在裝置清單看到
的是一張外觀完全正常、實際上永遠驗不過的殭屍憑證，登入失敗也只回一句概括的「認證失敗」。
補上之後：

| 位置 | 行為 |
|------|------|
| `login/begin` | 不把舊 RP ID 的憑證交給瀏覽器；**但對外錯誤訊息與「帳號不存在」完全相同**（照實說會洩漏帳號存在＋有註冊過 Passkey，正是 `0527524` 修掉的用戶枚舉），真相寫進 server.log |
| `login/complete` | 回**明確原因**（「此 Passkey 是在舊的系統網域下註冊的…請重新註冊」），不再是籠統的「認證失敗」。走到這一步代表對方握有真實 credential_id，不是枚舉探測 |
| 裝置清單 | 標 `stale`，`change-password.html` 顯示紅色「已失效」徽章與說明；全部失效時卡片徽章顯示「已失效」而非「已設定」 |
| `PATCH /api/settings/webauthn-config` | 回報**精準張數與人數**（原本是回報全表張數，只有一種 RP ID 時剛好等於正確答案） |

> ⚠️ **這個欄位救不回任何憑證**，它讓失效變成「可見、可通知、可清理」。別把這兩件事搞混。
>
> `rp_id=''`（v74 之前的舊資料，來源不明）的取捨是**刻意不對稱**的，兩邊都是「不確定時選傷害較小的那邊」：
> 登入路徑當成「相符」（不確定時不要把人鎖在門外）、失效張數統計則排除（不要謊報「已失效、無法復原」，
> 那句話會讓人去刪掉可能還能用的憑證）。正式環境不會有這種列——v74 回填會填好，而 RP ID 沒設定時根本註冊不了。

**❌ 「新舊網域並行過渡期」做不到——查證後放棄**

原本規劃的進階做法是：驗證時逐張比對憑證自己的 rp_id，開一段新舊網址並行的窗口，讓大家慢慢遷移。
**但這對即將要做的這次切換沒有用**：切到 Let's Encrypt 之後，憑證只涵蓋 `erp.miactw.com` 一個名字
（LE 不可能為 `motrix.internal` 這種私有名稱簽發），而 uvicorn 只能載入一張憑證——**舊網址在切換的
同一瞬間就失去有效憑證**，Passkey 在那個 origin 下本來就不會運作。換句話說並行窗口的前提不成立。

要真的並行，得讓兩個名字**同時**各有一張有效憑證（例如另起一個 port 用舊憑證服務），那是為了
1～2 張 Passkey 而增加的常駐複雜度，不划算。**結論：這次切換就是「所有人重新註冊一次」，
而 v74 讓這件事至少是說得清楚、看得見、清得掉的。**

> ~~**結論：越晚換越貴。** 現在全公司只有 1～2 張 Passkey，這是換 RP ID 成本最低的時刻。~~
> 使用者先前提過「未來會有 VPN、主機可能變更網路環境」——而 `motrix.internal` 是一個
> 只在內網有意義的名字，那個未來一到就會被迫換。
>
> **2026-09-16 修正**：Passkey 已暫緩使用，沒有人在用，**換 RP ID 的失效成本歸零**，
> 「越晚換越貴」不再成立。憑證路線現在可以純粹按 HTTPS 需求決定。
> ⚠️ 但順序有講究：**要恢復 Passkey 的話，先把 RP ID 定案再開功能**，
> 否則又會回到「開了之後不敢換」的局面。

**下一個決策點：要不要改用 Let's Encrypt 公開憑證（`LETSENCRYPT-PUBLIC-CERT-PLAN.md`）**

| | 現況（自簽 CA） | 改用 `erp.miactw.com` |
|---|---|---|
| 每台使用者要做的事 | 裝 CA＋管理員密碼＋要解析得到 `motrix.internal`（macOS 沒有對應腳本） | **什麼都不用做**，Windows/macOS/iOS/Android/Firefox 全部開箱即用 |
| 換網段／加 VPN／換辦公室 | RP ID 被迫換 → 既有 Passkey 全滅 | 不受影響（RP ID 綁主機名，不綁 IP） |
| 代價 | — | ①內網 IP `172.16.10.177` 會出現在公開 DNS ②**所有人必須改用新網址**，舊的 IP／`motrix.internal` 位址會跳憑證主機名不符 ③憑證 90 天到期，續期失敗＝全站 HTTPS 壞掉＝Passkey 全部不能用 |

技術前提都已實測確認：`miactw.com` 的 DNS 在 Cloudflare（有 API）、`erp.miactw.com` 未被佔用、
用 **DNS-01** 驗證所以正式機**不需要對外開放任何連接埠**。續期腳本 `backend/tools/letsencrypt_renew.ps1`
已寫好（比對憑證有變動才動作、用 fullchain、覆蓋前備份、`-InstallSchedule` 建每日排程）
但**尚未執行**——步驟 1、2（Cloudflare 加 A 記錄、建 API Token）與步驟 3（正式機簽憑證）都需要人操作。

> 順序不可顛倒：**先把憑證弄乾淨，最後才改 RP ID**。反過來做只會得到一個「看起來啟用了
> 但不能用」的 Passkey，比誠實地回 503 更難查。

**踩過的坑（四個根因，每一個都讓 Passkey「功能上線但從來沒真的能用」）**

| 根因 | 為什麼拖這麼久才發現 |
|------|-------------------|
| `base64.b64decode()` 解 base64url（`a1f56e9`） | 前端送的是去 padding 的 base64url，每次都丟 `Incorrect padding`，被上層 `except Exception` 收斂成籠統的「認證器驗證失敗」 |
| credential 缺 `type` 欄位（`4ffe190`） | py_webauthn 驗 `type` 必須是 `"public-key"`，前端沒送、後端模型也沒宣告，**兩邊都要改** |
| `login.html` 有兩個 `init()`（`34e0ce1`） | JS 物件實字重複鍵後者勝出且**無任何警告**，`checkWebauthnConfig()` 從來沒被呼叫，Passkey 按鈕永遠不顯示——註冊得起來卻永遠登不進去 |
| `verified.sign_count` 屬性不存在（`34e0ce1`） | py_webauthn 3.0.0 的認證結果叫 `new_sign_count`，只有註冊結果才叫 `sign_count`；每次登入丟 AttributeError 被收斂成 401 |

**共同教訓**：這四個 bug 能一路存活，是因為 Passkey 一直卡在更前面的環節（RP ID 未設、憑證未生效），
**從來沒有人真的走到那一步**——功能上線但從未被端到端驗證過的典型代價。最後是靠 CDP 虛擬認證器
把整條路自動走完才當場抓到後兩個。另外 `34e0ce1` 同時補上 W3C 7.2 的前提：只有新舊簽章計數
至少一邊不為 0 時，計數沒前進才算複製徵兆——Windows Hello 與 iCloud/Google 同步的 passkey
都不實作計數器、永遠回 0，少了這個前提它們每次登入都會被誤判成重放攻擊。

---

### §3.4 · 角色與模組

> **2026-09-13 全面盤點：[`MODULE-AUDIT-2026-09-13.md`](../../MODULE-AUDIT-2026-09-13.md)**
> ——三方（權限目錄／側欄／後端）逐 key 對照、七項已修、五項待決策。動模組機制前先看那份。

```
superadmin > admin > sales > engineer > viewer
```

**先記住這一句**：模組決定「**看得到什麼**」，角色與端點內的檢查決定「**能做什麼**」。
35 個可授權模組裡後端真的會擋的只有 19 個（含 7 個 `*_guide_edit`），其餘只影響側欄顯示；
前端沒有任何頁面層守門（`auth-guard.js` 只驗 session），**任何登入者手打網址都開得了任何頁**，
所以不該被看到的資料一定要在端點上擋。新增模組時三邊（`users.html` 目錄／`sidebar.js`／
後端檢查）要一起補，`test_module_keys_consistency_2026_09_13.py` 會擋下只補一邊的情況。

| 角色重點 | 說明 |
|----------|------|
| `engineer` | 預設無 `financial_view`，不可看金額／財務（**注意：這是前端顯示偏好，API 照樣回金額**，見稽核 §4） |
| 模組例 | `project_manage`（＝案件叫料－修改，2026-09-13 補回目錄） · `project_approve_eng` · `project_approve_biz` · `financial_view` · `reports` · `work_log` · `daily_task` |
| 報價列表過濾 | 非 admin+ 用 `sales_person_id=自己id OR (sales_person_id IS NULL AND sales_person=display_name)` |
| **稽核記錄** | `GET /api/audit-log` 限 **admin+**；viewer/sales/engineer 呼叫回 403 |
| **工作日誌** | `PUT/DELETE /api/work-logs/{id}`：非 admin 只能修改/刪除**自己**的日誌 |
| **業務開發 CRM** | 非 admin 只能查看自己建立、或列於 `sales_persons`/`planners` 欄位的案件（`_can_access_case()` helper）；admin+ 無限制 |
| **自訂角色** | superadmin 可建立自訂角色（名稱 + 基礎角色層 + 模組清單）；儲存於 `system_settings`；使用者 Modal 快速套用 chips 顯示 |
| **角色名稱** | superadmin 可在「角色名稱設定」自訂各層顯示名稱（`GET/PUT /api/settings/role-labels`）；DB 內 `role` 欄位仍儲存系統名稱 |

---

### §3.5 · Demo 展示帳號（隔離空白資料庫）

給客戶展示用；帳號 `demo` / 密碼 `60575481`，role=superadmin（所有模組全開，頁面/效果完整可見）。

```
db.py:      DB_PATH（正式）+ DEMO_DB_PATH（motrix_erp_demo.db，獨立檔案，同一套 schema/migrations）
            contextvars 依 request 切換 get_db() 指向哪個檔案（伺服器啟動/排程觸發的背景工作，
            如每日逾期通知、月報寄送，不掛在任何 request 上，contextvar 本來就該是預設值 False，永遠打正式庫，
            這是正確行為）
routers/auth.py auth_login()：
  帳號名為 demo → reset_demo_db()（整檔刪除 + 重新 init_db，回到全空白）
             → 核發 DEMO_ 前綴 token，session/user 只寫入 demo db（不進正式 sessions 表）
main.py auth_middleware：token.startswith('DEMO_') → set_demo_mode(True)，
             此後本次 request 內所有 get_db()（含 _require_user()/_audit()）都自動轉向 demo db
```

- **每次登入 demo 帳號＝整個 demo db 重置為全新空白**（客戶怎麼操作、寫入什麼測試資料，下次登入一律清空，正式庫完全不受影響）
- 正式庫 `users` 表僅存一筆 `demo` 守門帳號（`init_demo_account()`，供登入時驗證密碼用），實際瀏覽/操作全在隔離 db 進行
- 新增任何會直接 `sqlite3.connect(db.DB_PATH, ...)` 而非透過 `get_db()` 的程式碼，會繞過此隔離機制 — 一律使用 `get_db()`
- **檔案儲存也要隔離**：專案照片（`photos.py _photo_root()`）、勞報單 PDF 存檔（`payslips.py _archive_path()`）、報價單里程碑自動匯出 PDF（`pdf_gen.py _get_pdf_base()`）三處是直接寫實體檔案，不經過 `get_db()`；已改為 `is_demo_mode()` 時導向 `uploads/_demo_projects`／`backend/_demo_pdf_archive`／`backend/_demo_payslip_archive`，`reset_demo_db()` 一併清空。**新增任何寫檔案到磁碟的功能，都要檢查 `is_demo_mode()` 並比照辦理**，否則 demo 帳號會把檔案寫進正式共用目錄，且 project_id/slip_no/quote_no 在 demo db 都從 1 重新編號，可能撞名蓋掉正式檔案
- **路由 handler 內用 `threading.Thread(...)` 起的背景工作，一律要用 `db.spawn_bg_thread()` 取代直接呼叫 `threading.Thread`**（2026-08-01i 修復，見 §12）：`contextvars.ContextVar`（`_demo_mode`）只在建立當下的 context 裡有效，一般 `threading.Thread(...).start()` 起的新執行緒拿到的是全新、空白 context，裡面的 `is_demo_mode()`/`get_db()` 會誤判成正式環境——即使觸發的 request 其實是 demo session。`spawn_bg_thread()` 用 `contextvars.copy_context()` 把呼叫當下的 context 原封不動帶進新執行緒，修正後 demo 帳號核准出貨單/報價單不會再把 PDF 寫進正式共用資料夾、每日工作事項通知也不會再誤連正式庫寄信給真實同仁。**例外**（不需要、也不該用 `spawn_bg_thread()`）：(a) 伺服器啟動/排程觸發、不掛在任何 request 上的背景工作（如 `daily_tasks.py` 的 `_startup_catchup`、`reports.py` 的 `_catchup_monthly_reports`），本來就該永遠連正式庫；(b) 只吃呼叫端已解析好的純值參數、本身不呼叫 `get_db()`/`is_demo_mode()` 的葉節點執行緒（如 `email_notify.py` 的 `_async_send()`/`_send()`）
- `reset_demo_db()` 用 SQL `DELETE`+`VACUUM`（同一連線內完成），不刪 `.db/-wal/-shm` 檔案本身 — 避免 Windows 掃毒/索引服務短暫鎖住剛建立的 WAL 檔案導致 `os.remove()` 失敗
- `db.demo_reset_lock`（`threading.Lock`）包住整個「reset + 建立 demo 使用者/session」流程 — 兩個 demo 登入同時到達會搶跑同一個共用 db，造成 `IntegrityError`/database-is-locked；已用併發壓力測試驗證修正
