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
| Demo 帳號 | 不支援（`auth_login()` 的 demo 分支在檢查 totp 之前就已回傳，設計上就不會走到） |

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
