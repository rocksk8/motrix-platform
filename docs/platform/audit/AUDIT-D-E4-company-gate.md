# 稽核：E4 本公司設定閘門設計（wip/e-company-gate 82ee8480，COMPANY-SETUP-GATE.md）（D，2026-09-28）

> 範圍：設計文件（df0091ed＋§9 裁示 82ee8480）。依據 CORE-SPEC 0f8b16bf、99702431、裁示 d27ce2dc。
> 只讀文件與 origin/platform 的現行程式碼（main.py auth_middleware、notif.js、licensing.machine_fingerprint、apply_update.ps1 健檢），沒有跑題。

## 0. 結論

- **必修 2、建議 5、觀察 3。**
- 方向正確：判準用「有人做過決定」（確認紀錄＋欄位雜湊），不用「欄位非空」；預設擋、白名單放行；兩道（中介層＋輸出端）
- 最大的風險在 ②③：**這是第一個在正式機上依機器指紋擋住全部功能的機制**（`licensing.LICENSE_GATE_ENABLED = False`，指紋從沒在正式機上擋過任何東西），而設計裡失敗時沒有現場可用的出口，現行健檢也看不到它 ⇒ CG-M1

## 1. 必修

**CG-M1（必修）　backfill 或指紋出狀況時，全公司停擺，而且健檢看不到、現場沒有出口**

- **健檢看不到**：`apply_update.ps1` 套用後只輪詢 `/api/ping`（:86-88）。`/api/ping` 在白名單內、不需登入 ⇒ 閘門把所有業務 API 都擋住時，健檢仍判健康、不會自動回滾。§6-3「升級後健檢加一項 status、不是則立即回滾」寫的是「正式機 Claude 指示回報」＝人工；而 `/api/settings/company-setup/status` 在登入之後，ps1 沒有 token 打不到
- **指紋會自己漂**（讀 `licensing._windows_hardware`）：
  - 指紋＝主機板 UUID＋「PCI／USB 網卡中最小的 MAC」。插上 USB 網卡、手機 USB 網路分享（RNDIS 是 `USB\`）等，只要 MAC 比較小，指紋就變
  - 讀硬體靠一次 PowerShell 呼叫：被群組原則擋、逾時 ⇒ 兩個來源都空 ⇒ 改用 `MachineGuid` ⇒ **換成另一個指紋而不丟例外**，而且整個行程都快取這個值
  - 因此 §3.4「讀不到硬體 ⇒ 退用 `.install_identity`」幾乎不會發生：先發生的是換成 MachineGuid 指紋 ⇒ 綁定不符 ⇒ 被擋
- **現場沒有出口**：
  - 一般客戶：最高管理員重新確認一次即可（前提是最高管理員在）
  - 開發者自己的正式機：資料命中開發者指紋 ⇒ 需要「登記機器」或「簽章確認檔」。簽章檔也綁機器指紋 ⇒ 指紋一漂，兩條都失效 ⇒ 要等開發者在自己的機器（私鑰在 D:\MOTRIX-KEYS）簽一份新檔送過去。在那之前**全公司不能用**，也沒有其他出口
- **修法（設計要補，全部都要）**：
  1. **套用前預檢**：ps1 在停服之前，以新版程式碼乾跑一次 status（讀正式庫＋本機指紋＋簽章檔）。套用後會是「未設定」⇒ **拒絕升級**，不要等升級完再回滾。`::RESULT::` 要說出原因
  2. **套用後自動健檢**：ps1 取得 status 的方式不能靠登入。可以選 localhost 限定、不需登入、只回 `{configured, reason}` 的端點，或用 python CLI 直接讀庫。未設定 ⇒ 自動回滾（與 ping 失敗同級）
  3. **現場安全閥**：本機限定、有期限（例如 72 小時）、會記稽核的暫時放行。例如最高管理員從 localhost 按「暫時放行」，或在安裝目錄放一個含到期時間的檔（F3、不進包、不進備份）。期間所有頁面顯示橫幅、每日告警一次（〈告警必須有速率上限〉）、到期自動失效。它**不寫確認紀錄**，所以複製庫的情境仍然擋得住（到期即恢復）
  4. **先量再開**：正式機回報連續幾次重啟的 `machine_fingerprint()`（含 PowerShell 失敗時的退路值），確認穩定後才登記；§6 的演練加「插拔 USB 網卡」「PowerShell 被擋」兩種情境，並驗證安全閥可用
  5. status() 本身丟例外時的行為要寫明（建議：當作未設定並記 ERROR＋告警，安全閥仍有效）

**CG-M2（必修）　白名單要逐條精確列舉（方法＋完整路徑），不可以有萬用字元或描述性條目**

- §4.1 的白名單有三類寫法，§7-① 的「每條存在」守門驗不了：
  - 萬用字元：`/api/system/branding*`。前綴比對會讓以後任何 `/api/system/branding…` 新端點自動放行，等於「預設擋」在這個前綴下失效
  - 描述性條目：「健康檢查」「使用者管理的『自己』端點」「TOTP 與 Passkey 設定」「上傳品牌圖」。沒有路徑，守門無從比對，實作者自己決定範圍
  - 只列路徑、不列方法：`/api/settings/company-profile`（GET／PUT）要寫明方法，其他方法（DELETE 等）要擋
- 修法：比照 `_MUST_CHANGE_PW_ALLOWED`（精確字串集合），改成 `{(方法, 路由樣板)}`，每條附理由；中介層以路由樣板比對（有路徑參數的端點）。§7-① 的「存在性」以 app 路由表為準
- 範圍判斷（① 的回答）：
  - **應該在**：登入／登出／me、改密碼（`_MUST_CHANGE_PW_ALLOWED` 全部）、ping、version、branding（GET，登入頁用）、company-profile GET／PUT、company-setup/status、menu
  - **應該補上**：`license_core.LICENSE_EXEMPT_PATHS`（授權啟用與自救；目前授權閘門關著，但兩道閘門同時生效時，未授權又未設定的安裝會連授權都無法啟用）；品牌圖上傳要寫出確切路徑
  - **不應在**：備份還原、模組管理、使用者管理（除了「自己」那幾條要逐條寫出）、部署與更新頁 API。這些在未設定時不需要，就算要，也該經安全閥
  - 非 /api 路由：閘門只管 `/api/`，而 `/pages`、`/static`、`/map-overlays` 都不含資料（E3-S2 白名單已登記），不需要動

## 2. 建議

- **CG-S1　不要跟既有的 409 撞在一起**：產品碼有 19 處 `status_code=409`（版本衝突等）。notif.js 以 `code` 分辨可以運作，但頁面自己的 fetch 流程在導頁前可能先把 409 顯示成「資料衝突」。建議比照 `must_change_password` 用 403，或改用 428（Precondition Required），並在 notif.js 以 `code` 為準
- **CG-S2　backfill 不可以丟例外**：它在核心 migration 裡。丟例外 ⇒ 啟動失敗 ⇒ 整包回滾，範圍大於閘門本身。要做到「算不出來 ⇒ 不寫紀錄、記 ERROR、交給 CG-M1 的預檢與安全閥」，並寫一題
- **CG-S3　簽章確認檔要做網域分隔**：它與交付包共用同一把 Ed25519 金鑰。被簽的內容要帶用途前綴（例如 `motrix-company-confirm-v1\n`），驗證端也只認這個前綴，不讓一份簽章能被當成另一種用途。另外建議加到期日或「可換機一次」的欄位，給 CG-M1 的換機情境用
- **CG-S4（④ 的回答：可接受）　把威脅模型寫明**：
  - 加鹽雜湊防的是「程式碼與文件裡多一處字面值」，不防還原。統編是公開登記資料，而且已以字面值存在於凍結的 db.py／core/upgrade.py ⇒ 可以還原不構成新的風險
  - 機器指紋的雜湊是 16 碼 hex（64 位元），不可能暴力還原
  - 整個閘門防的是「沿用預設」與「疏忽」，不防會改 Python 的客戶（程式碼在客戶機器上）。請在 §3.3 寫一句，免得之後有人把它當成授權或防盜機制來加強
- **CG-S5　復原路徑寫進 DR-SOP 並演練**：還原到新機器（指紋不同、`.install_identity` 不在備份裡）⇒ 必然「未設定」。DR 步驟要寫「最高管理員重新確認」；開發者正式機要寫「簽章檔或安全閥」。另外，只有一位最高管理員而他不在時，其他人只看得到說明頁、沒有人能按 ⇒ 說明頁要寫明聯絡誰，或允許第二位最高管理員

## 3. 觀察

- **CG-O1**：§3.4 對指紋退路的描述與現行程式不符（先退到 MachineGuid，最後才丟 RuntimeError）。實作前改寫；這也是 CG-M1「會自己漂」的根據
- **CG-O2**：`/api/uploads/…?pt=` 在 auth_middleware 的登入檢查之前就放行（簽名 token，1 小時），不會經過閘門。token 只能由已受閘門保護的端點簽發 ⇒ 只剩閘門生效前已簽發、1 小時內的尾巴，可忽略；§1.4「已存檔的輸出一樣被第一道擋」要加這個但書
- **CG-O3**：§1 的盤點（34＋1＋6、繞過 3 處）我沒有逐點重查。§7-② 掃描器的正對照（已知點全部要亮）就是用來驗這份盤點的，實作時以它為準

---

## 4. 複審 CG-M1／CG-M2：wip/e-company-gate 32d7c056（ede87d61＋Q7 C）（D，2026-09-28）

> 依據主持裁示：綁定改 `backend/.install_identity`（不綁硬體；威脅模型＝防沿用預設與疏忽，不防改碼或整包複製）；Q7＝C。
> 只讀文件＋現行程式碼；另做一個 FastAPI 探針（見 CG2-S1）。

### 4.0 結論

- ✅ CG-M1 關閉（32d7c056）
- ✅ CG-M2 關閉（32d7c056）
- **新必修 1（CG2-M1）、建議 4。**

### 4.1 主持指定

**① 兩階段漏做時，預檢會不會「拒絕升級、不停服」：成立，但有四個前提要寫進設計（CG2-S3）。**
- 執行的是**包裡的新版** ps1：UPDATE-DELIVERY §3.4 步驟 2 先把 `staging\<包>\backend\tools\*` 複製到安裝目錄，再執行 apply_update.ps1 ⇒ 預檢與 `ensure-install-id` 會在第一次含閘門的升級就生效
- 漏了第一階段（沒有識別檔、沒有簽章檔）：同一次執行裡 `ensure-install-id` 先產生識別檔，接著預檢得到 `developer_identity_unsigned` ⇒ 拒絕，這時服務還沒停
- 簽章檔是對另一個識別簽的（例如識別檔被重建）：`install_mismatch` ⇒ 同樣拒絕
- 還缺的前提：
  - 預檢**自己**當掉、逾時、輸出看不懂 ⇒ 要視為拒絕（不可以當成通過）
  - 預檢得到 `status_error`（configured:null）⇒ 也要拒絕：§3.6 說「會丟例外的新版在停服前就被擋下」，但 §6.3-1 只寫「未設定 ⇒ 拒絕」
  - `-Force`（版本比對用）**不可以**略過預檢；要略過就另開一個旗標，並寫進 `::RESULT::`
  - 套用後 CLI 得到 `configured:null` ⇒ 與「未設定」同樣自動回滾（新版上線即全公司停止輸出文件，等同故障）
  - 手動套用（不經儀表板）時也要先複製包裡的 tools；正式機 Claude 指示要寫明

**② 暫時放行：72 小時與「只能用 CLI」在檔案層面擋不住，要改成以伺服器記下的時間為準（CG2-S4）。**
- 放行檔是本機檔案：任何能寫安裝目錄的人都可以不經 CLI 直接寫它，也可以同時改 `created` 與 `until` 來延長。在威脅模型（防疏忽，不防改碼）下可以接受，但「≤72h、不可延長」要由伺服器來保證：
  - 伺服器第一次看到某份放行檔（以內容雜湊為鍵）時，記下 `first_seen`（寫進 DB 稽核）；有效期＝min(`until`, `first_seen`＋72h)
  - `created` 晚於現在（容許幾分鐘誤差）⇒ 無效
  - 檔案內容一改就是「新的一份」⇒ 新的稽核與告警。這讓「重建」看得見，但不禁止（設計本來就允許重建，每次都有紀錄）
- 放行在 `status()` **丟例外**時讀不到（放行是在 status() 裡判斷的）：Q7 C 的中介層本來就放行，所以不影響功能；但 §3.6 表格的「§4.3 暫時放行對輸出端同樣有效」在 status_error 時不成立。這句要改寫，或把放行判斷放在 status() 之外

**③ 428：成立。** 產品碼 0 處使用；`required` 與 `undetermined` 分開，後者不導設定頁，正確。殘留見 CG2-S2。

**④ 精確白名單＋LICENSE_EXEMPT_PATHS：內容成立，比對方式不可行（CG2-S1）。**
- `LICENSE_EXEMPT_PATHS`＝ping、login、logout、`/api/license/status`，都無害，而且前三個已在改密碼白名單內
- 白名單內容：不含萬用字元與描述性條目，方法都寫了。備份還原、模組管理、使用者管理、部署頁都不在，正確

### 4.2 新必修

**CG2-M1（必修）　三個 F3 檔沒有登記為「安裝設定」⇒ 完整包升級、V9 轉換、回滾時可能被當成程式處理或清掉**

- 新設計讓 `backend/.install_identity` 成為開發者正式機唯一的綁定依據（丟了 ⇒ `install_mismatch` ⇒ 要重簽或暫時放行）
- 現行 `core.upgrade.CONFIG_FILES`（:74-83）列的是 license.key、`.deployed_commit.json` 等「安裝本身的設定」；沒列的檔在 `classify` 裡預設是「程式」。刪除計畫、cleanup-snapshot、兩種回滾都依這個分類決定動不動它
- 設計 §7-⑧ 只要求「`.gitignore`、verify_package 拒絕帶入、不進備份」，沒有要求登記為設定
- 修法：
  - `.install_identity`、`company_confirmation.sig`、`company_setup_grace.json` 進 `_paths` 常數＋`core.upgrade.CONFIG_FILES`（同 DB-O1 對 `.deployed_modules.json` 的做法）
  - §7-⑧ 加一題：刪除計畫、cleanup-snapshot、apply／rollback 之後三檔逐位元組不變
  - 啟動時「識別檔不存在 ⇒ 產生並記 WARN」：若庫裡**已有**確認紀錄，重建就等於改掉綁定 ⇒ 至少要記 ERROR＋告警（寫明「識別檔遺失，已重建；確認紀錄失效」），不可只記 WARN

### 4.3 建議

- **CG2-S1　中介層拿不到路由樣板**：§4.1 寫「以 `request.scope["route"].path` 比對」。D 探針（FastAPI，本 repo venv）：`@app.middleware("http")` 在 `call_next` **之前** `scope["route"]` 是 **None**，之後才是 `/api/settings/branding/{kind}`（路由在 call_next 裡才解析）。改成中介層自己比對：對白名單中的每條路由呼叫 `route.matches(scope)`（Starlette `Match.FULL`），或啟動時由白名單的 (方法, 樣板) 編成正規式。§7-① 要有一題：有路徑參數的白名單條目（branding/{kind}）真的放行、同前綴的非白名單路徑真的擋
- **CG2-S2　409 殘留**：§5（`CompanySetupRequired` ⇒「端點轉 409」）、§7-①（「必須 409」「不再 409」）、§7-③（「所有 identity 輸出 409」）還寫 409。守門照文件寫會跟 428 矛盾，實作前改掉
- **CG2-S3**：見 4.1-①（預檢當掉＝拒絕、status_error＝拒絕、-Force 不略過、套用後 null＝回滾、手動套用先複製 tools）
- **CG2-S4**：見 4.1-②（first_seen 由伺服器記、`created` 在未來＝無效、status_error 時放行讀不到）

---

## 5. 複審 CG2-M1＋CG2-S1～S4：wip/e-company-gate 5560ba84（D，2026-09-28）

- ✅ CG2-M1 關閉（5560ba84）
- CG2-S1～S4 都已採納：`route.matches(scope)`（白名單條目在路由表找不到 ⇒ 啟動 ERROR＋守門紅）、409 全改 428、預檢的例外／非零／逾時 60 秒／輸出壞／`configured:null` 一律拒絕、`-Force` 不略過、套用後 null 或 CLI 當掉 ⇒ 自動回滾、放行期限＝min(until, first_seen＋72h)，first_seen 以內容雜湊為鍵存 DB、`created` 在未來＝無效
- **新必修 1（CG3-M1）。**

**CG3-M1（必修）　`-SkipCompanySetupPreflight` 從正式機的 apply_update.ps1 拿掉**

主持問：需不需要、是否只該存在演練副本、正式機使用算不算重要參數。D 的判斷：**不需要，正式機腳本不留**。
- 預檢正確地判「未設定」時跳過它：套用後的 status 檢查（6.3-2）一樣判未設定 ⇒ 自動回滾。旗標只換來「停服、套用、再回滾」一輪，沒有效果
- 確實需要先升級、之後再補設定（例如急修而簽章檔還沒到）：§4.3 暫時放行已經涵蓋。有有效放行時預檢本來就通過（「未設定**且無有效放行** ⇒ 拒絕」），而且放行有稽核、有期限、有橫幅
- 剩下唯一的情況是「預檢工具自己壞了、閘門其實沒問題」：正確的處置是修工具、重出包；正式機上跳過一個壞掉的檢查，就是〈降級之後它還是會動〉
- 「只准人工使用」擋不住：儀表板以 `-Yes` 呼叫 ps1，參數由呼叫端決定；`::RESULT::` 多一個 skipped 欄位，也要動到出口值域 1:1 的儀表板
- 同 U-M2 原則（演練繞過分支只在演練副本）：若演練要測「預檢失敗時的後續」，把預檢結果注入寫在演練副本；正式機腳本裡不出現這個旗標。§7-⑨ 的題改成「正式機 ps1 沒有任何略過預檢的參數」（AST／文字掃描），放行路徑的題保留

## 6. 複核 CG3-M1：wip/e-company-gate 6387eb87（D，2026-09-28）

- §6.3-1 拿掉 `-SkipCompanySetupPreflight`（原句以刪除線保留＋更正說明）；§7-⑨ 改為「正式機 ps1 沒有任何略過預檢的參數」的掃描題＋正對照；演練以副本注入。比對條件（skip／bypass＋preflight／company）不會誤中既有的 `-SkipAutoRollback`
- ✅ CG3-M1 關閉（6387eb87）

---

## 7. 完整稽核實作段①（正式機段）：wip/e-company-gate-impl db551e01（D，2026-09-28）

> 範圍：d6f196d7..db551e01 的產品碼：`helpers/company_setup.py`、`tools/company_setup_cli.py`、`apply_update.ps1`（2026-09-28h）、`main.py` 啟動、`core.paths`／`CONFIG_FILES`／`verify_package`。本段不擋任何 API。
> 拋棄式 worktree：相關題 49 過（core＋cli＋D 探針）；探針不提交、跑完刪、暫存已清。

### 7.0 結論

- **必修 1（CGI-M1）、建議 3、觀察 1。**
- 最壞情況的回答：**本段不會造成全公司停擺**。中介層還沒有擋任何 API，任何漏做都只會讓「升級被拒」（服務還沒停），或在套用後檢查失敗時自動回滾（連資料庫快照一起還原）
- 但有一條正式機實際會走的路（用暫時放行先升級）會卡死 backfill，見 CGI-M1

### 7.1 主持指定

**① 正式機第一次升到含本段版本的完整路徑**

| 情境 | 結果 |
|---|---|
| 照順序：ensure-install-id → 開發者簽 `company_confirmation.sig` → 升級 | 預檢通過 → 啟動時 backfill 寫確認紀錄 → 套用後檢查通過 ✔ |
| 漏了第一、二步，直接升級 | ps1 先建識別檔，預檢得 `developer_identity_unsigned` ⇒ `refused_company_setup`，**停服之前**就中止，正式機沒被動 ✔。但拒絕時**沒有印出安裝識別雜湊**，開發者簽不了（CGI-S1） |
| 簽章檔是對另一個識別簽的 | `install_mismatch` ⇒ 預檢拒絕 ✔ |
| 升級後因任何原因未設定（backfill 出錯等） | 套用後 CLI 檢查不過 ⇒ `company_setup_rolled_back`，程式與資料庫快照一起還原 ⇒ `BACKFILL_DONE` 旗標也回到套用前 ✔；`-SkipAutoRollback` 不適用 ✔ |
| 升級後識別檔被刪 | 啟動重建＋ERROR＋告警 ✔；本段不擋 API ⇒ 不停擺；下一次升級會被預檢拒絕，直到重簽 |
| **簽章檔還沒到，先用 72h 放行升級** | 預檢因放行而通過 → 啟動 backfill 因為沒有簽章檔回 `skipped`，**卻照樣寫下 `BACKFILL_DONE`** → 之後簽章檔到位也不會再補（見 CGI-M1） |

- 第一步的 CLI 在第一次升級之前**只存在於包裡**（正式機還沒有這支檔）。§6.2 要寫明從 staging 執行：`python <staging>\payload\backend\tools\company_setup_cli.py ensure-install-id --root <ROOT>`；或者直接讓第一次升級被拒，由拒絕訊息帶出雜湊（CGI-S1）
- 第二步由使用者以交付金鑰簽（Claude 不讀私鑰）

**② backfill_once 在啟動時不丟例外；失敗時的狀態：成立，只有一個缺口。**
- 整支包在 try/except 裡；出錯回 `"error"`，而且例外發生在寫 `BACKFILL_DONE` 之前 ⇒ **不會**寫旗標，下次啟動會重試 ✔
- `main._startup_company_setup` 再包一層，閘門的問題不會讓服務起不來 ✔
- 缺口：`skipped` 也寫旗標（CGI-M1）

**③ ps1 的兩個新呼叫點要逐字複製到 A 的 `apply_module_update.ps1`**
- `Invoke-CompanySetupCli` 放在 apply_update.ps1「逐字相同的區段」標記（:268）**之後**，也不在 `test_apply_plan` 的 `_SYNCED_FUNCS` 裡 ⇒ 目前沒有守門會要求兩支 ps1 的這個函式相同
- A 的 DB-S1 逐字比對清單要加入 `Invoke-CompanySetupCli`（CGI-S2）
- 單模組包不帶 tools ⇒ 模組 ps1 的預檢與套用後檢查應呼叫**已安裝**的 `backend\tools\company_setup_cli.py`（core 沒換，已安裝版即新版），而不是 `$PackagePath\backend\tools\…`

### 7.2 必修

**CGI-M1（必修）　backfill 在 `skipped` 時不可以寫「已完成」**
- D 探針（`test_company_setup_core` 的 `devco` fixture＋放行檔）：
  1. 放行中 ⇒ 預檢判定 allows＝True
  2. 啟動 backfill ⇒ `skipped`，`BACKFILL_DONE={result: skipped}`
  3. 簽章檔到位（`signed_file_state`＝valid）、放行移除
  4. 再跑 backfill ⇒ `already_done`
  5. status ⇒ `configured False / no_record`，allows False
- 而本段**沒有**寫確認紀錄的入口（設定頁的 confirm API 在之後的段）⇒ 之後每一次升級，預檢都拒絕；唯一出路是一再重建 72h 放行。這正是 §6.5 寫的「開發者正式機 ⇒ 用暫時放行撐到新簽章檔到位」那條路
- 修法（擇一）：
  - 只有 `backfilled`，或確認紀錄已存在時，才寫 `BACKFILL_DONE`；`skipped` 不寫（每次啟動多讀幾個設定，成本可忽略）
  - 或保留旗標，但在 status 端讓「開發者身分＋有效簽章檔＋無紀錄」在啟動時補寫（等於 backfill 可重跑）
- 題：探針的五步 ⇒ 第 4 步回 `backfilled`、第 5 步 configured

### 7.3 建議

- **CGI-S1　拒絕時要帶出安裝識別雜湊**：`ensure-install-id` 的輸出只在失敗時 `Write-Host`；預檢拒絕的訊息沒有 `install`。開發者要簽檔就需要它 ⇒ 預檢拒絕時印出（並寫進 result.json 的一個欄位），正式機回報就有了。同時在 §6.2 寫明第一次要從 staging 執行 CLI
- **CGI-S2　逐字比對清單加 `Invoke-CompanySetupCli`**：見 7.1-③
- **CGI-S3　ps1 的 robocopy 排除清單與 `CONFIG_FILES` 對齊**：:768（程式快照）、:885（複製包）的 `/XF` 明列 `license.key`、`.deployed_commit.json` 等設定檔，新的三個 F3 檔沒有列。現在不會出事（包裡沒有這三檔；快照在 ensure 之後才拍），但 CG2-M1 要的是「升級與回滾不當程式處理」。建議列入 `/XF`，並加一題「ps1 的 `/XF` ⊇ `CONFIG_FILES` 裡位於 backend 的檔」

### 7.4 觀察

- **CGI-O1**：本段上線之後，開發者正式機的**每一次**升級（含急修）都要先有有效簽章檔或放行。§6.2 的兩階段要在本段出貨**之前**完成，否則第一個急修就要走放行（而放行正是 CGI-M1 的路）

## 8. 複核 CGI-M1＋S1／S3：wip/e-company-gate-impl 3a49c1b5（D，2026-09-28）

- ✅ CGI-M1 關閉（3a49c1b5）
- CGI-S1（預檢輸出帶安裝識別雜湊，拒絕訊息指明交給開發者簽；§6.2 staging）、CGI-S3（`/XF` 補三檔＋兩個初始帳密檔）都已採納；CGI-S2 依主持裁示由 A 的模組 ps1 逐字守門負責
- **偏離（skipped_fields 照記、waiting_signature 不記）：同意。** E 的理由成立：一律不記，全新安裝在管理員存好欄位後重啟就會被自動確認，跳過了「有人決定過」
- **但同一個理由在 `waiting_signature` 上沒有守住 ⇒ 新必修 CGI2-M1**

D 探針（拋棄式 worktree，3a49c1b5；題目 54 過，探針不提交、已刪）：

| 探針 | 步驟 | 結果 |
|---|---|---|
| 五步（CGI-M1） | 放行中升級 → backfill → 簽章檔到位、放行移除 → 再 backfill → status | `waiting_signature`（不記）→ `backfilled` → configured ✔ |
| 全新安裝 | 空欄位 backfill → 管理員存好欄位 → 重啟 backfill | `skipped_fields` → `already_done`、`no_record` ✔（E 的反向控制成立） |
| **複製的開發者庫** | 開發者資料、沒有簽章檔 → backfill → 有人把名稱與統編改成別家、**沒按確認** → 重啟 backfill | `waiting_signature` → **`backfilled`，via `upgrade_backfill`，configured** |

**CGI2-M1（必修）　`waiting_signature` 之後的重試，只能補「開發者身分＋有效簽章檔」這一種情況**
- 開發者資料的庫出現在沒有簽章檔的安裝，正是閘門要防的情境（§3.1）。它停在 waiting；之後有人改了欄位但沒有按確認，下一次啟動 backfill 就把它當成「既有安裝的合格資料」自動確認 ⇒ 與 E 為全新安裝所擋的是同一件事
- 修法：上一次結果是 `waiting_signature` 的庫，重試時
  - 仍是開發者身分，且簽章檔有效 ⇒ `backfilled`
  - 仍是開發者身分，簽章檔未到 ⇒ 繼續 `waiting_signature`（不記）
  - **已不是開發者身分** ⇒ 記下做過（例：`skipped_identity_changed`），**不寫確認紀錄** ⇒ 由最高管理員在設定頁確認
  - 做法：waiting 時也記一筆「狀態」（例如 `BACKFILL_DONE={result: waiting_signature}`，但 backfill 對這個結果值照樣重試），這樣重試時才分得出「上次是 waiting」
- 題：上表第三列 ⇒ 不自動確認，status `no_record`；五步那一列照舊 configured（正對照）

## 9. 複核 CGI2-M1：wip/e-company-gate-impl 6ee28810（D，2026-09-28）

- ✅ CGI2-M1 關閉（6ee28810）
- 探針重跑（拋棄式 worktree；題目 56 過，探針不提交、已刪）：

| 探針 | 結果 |
|---|---|
| 五步（放行升級 → 簽章檔到位） | `waiting_signature` → `backfilled` → configured ✔ |
| 複製的開發者庫、改成別家、沒按確認 | `waiting_signature` → `skipped_identity_changed` → status `no_record` → 之後 `already_done` ✔ |
| 等簽章期間把聯絡欄位清空 | `skipped_fields`、`fields_invalid` ✔ |

---

## 10. 完整稽核實作段②（中介層＋確認＋428）：wip/e-company-gate-impl e71e904d（D，2026-09-28）

> 範圍：段①（6ee28810）之後 E 的改動：`main.py` 中介層與白名單、`company_setup.gate／compile_allowed／is_allowed`、`routers/system.py` 確認與狀態端點、`notif.js` 導頁與橫幅、設定頁與說明頁。只讀碼＋grep。

### 10.0 結論

- **必修 1（CG5-M1）、建議 2。**
- 白名單偏離（多 `GET /api/settings/branding`、`DELETE /api/settings/branding/{kind}`）：**同意**。兩條都限最高管理員、端點自己驗權限，只動品牌圖、不動確認紀錄與公司資料；設定頁在未設定時本來就要能用它們。不算過寬

### 10.1 主持指定

**① 白名單以外的 /api 真的全擋：成立。**
- `test_every_other_api_route_is_blocked_when_unconfigured`：走訪路由表，白名單與公開路徑以外的每一條（路徑參數填假值）逐一打，未設定時都必須 428
- 比對用 Starlette 的 `compile_path`（與路由同一套編譯規則），HEAD 視同 GET；`test_allowlist_is_exact_and_exists` 驗每條存在、方法相符；`test_allowlist_reverse_controls` 驗萬用字元／描述性條目會紅
- 中介層位置：登入檢查、改密碼閘門之後，`call_next` 之前 ✔；`/api/uploads?pt=` 在登入檢查前放行（CG-O2 已記），不受影響

**② 正式機（已 backfill 為 configured）行為不變：成立。**
- `gate()` ⇒ `GATE_OK` ⇒ 中介層不擋、不加標頭；`test_reverse_control_configured_has_no_header` 驗「已設定 ⇒ 200 且沒有標頭」
- 判定有行程內快取（鍵＝三個設定的 updated_at＋三個檔的 mtime＋分鐘），Ed25519 驗章只在快取失效時做，每個請求只多一次讀設定的查詢
- demo token 段② 視同已設定（段③ 種示範公司後拿掉），正式帳號不受影響

**③ status 例外（Q7＝C）：一般 API 放行＋標頭＋橫幅成立；「輸出拒絕」沒有實作 ⇒ CG5-M1。**
- 中介層：`gate()` 丟例外 ⇒ `GATE_UNDETERMINED` ⇒ 放行並加 `X-Motrix-Company-Setup: status_error`；告警每日一次；有題 ✔
- 但 `gate()` 的呼叫點只有 `main._company_setup_gate_kind` 與 `routers/system.company_setup_status`（grep）；沒有任何輸出路徑（報價單等 PDF、財報、自訂模組輸出、排程報表信）呼叫它，也沒有 `company_setup_undetermined` 的回應

### 10.2 必修

**CG5-M1（必修）　判定失敗時，橫幅說「對外文件暫停輸出」，但輸出照常**
- Q7 裁示 C 的兩半是一起的：放行一般功能（避免停擺）**＋** 含本公司資料的輸出拒絕（保護面不降級）。段② 只做了前一半
- 結果：status 出錯時，中介層放行所有 API，**包括 PDF／匯出**；而 notif.js 的橫幅與 status 端點的訊息都寫「本公司設定狀態無法判定，對外文件暫停輸出」⇒ 畫面告訴使用者的與系統實際做的不同
- 修法（擇一）：
  1. 在本段補上輸出端第二道：共用路徑 `identity_for_output`（§5）遇 `GATE_UNDETERMINED` ⇒ 428 `company_setup_undetermined`；至少報價單 PDF、財報匯出、自訂模組輸出三條路徑，加上排程報表信（不寄＋告警）
  2. 或者本段先**不**宣稱：橫幅與 status 訊息改成不提「暫停輸出」，並在文件寫明輸出端在段③；等段③ 補上再改回
- 無論哪一種，都要在正式機升到本段之前完成；題：`status()` 丟例外 ⇒ 報價單 PDF 428 `company_setup_undetermined`（或採 2 時：訊息不含「暫停輸出」）

### 10.3 建議

- **CG5-S1　一般存檔改到必要欄位 ⇒ 全公司立即 428**：`fields_hash` 含名稱、統編、電話、email。最高管理員在設定頁只改了電話、按「儲存」（沒按確認）⇒ 確認紀錄失效 ⇒ 其他人全部 428，直到他按確認。設計如此，但很容易發生。建議設定頁在必要欄位有變動時，把「儲存」換成「儲存並確認」（或存檔前提示「這會暫停其他人的使用，直到確認」）；後端不變
- **CG5-S2　判定失敗時每個請求都重算**：`gate()` 失敗時清快取，所以 status 出錯期間每個 /api 請求都重跑一次判定並呼叫 `alert()`（有每日節流，但每次都讀寫一次節流設定）。建議失敗結果也快取一分鐘（同鍵）

---

## 11. 完整稽核實作段③（含 CG5-M1 修正）：wip/e-company-gate-impl 6797b053（D，2026-09-28）

> 只讀碼＋grep＋一個統編檢查碼小實驗。

### 11.0 結論

- ✅ CG5-M1 關閉（6797b053）
- **必修 0、建議 2（其中 E4S3-S1 要在上正式機之前處理）。**

### 11.1 CG5-M1：輸出端第二道

- 檢查放在「組輸出文字」的 helper 本身：`company_identity.company_name／company_heading／contact_line／name_pair／footer_line` 與 `pdf_gen._identity_head／_identity_foot／_identity_foot_short` 一進來就 `require_for_output()`；`location_identity()`／`identity_from_profile()` 不擋（畫面、稽核、閘門自己用）
- **這些 helper 的所有呼叫點都是輸出**（grep 6797b053）：T100 傳票匯出、傳票 PDF、營運報表／年度目標／銷項發票清單、月報、網路規劃書匯出、獎金分潤單 PDF、個資告知列印端點。沒有通知信或一般畫面資料 ⇒ 判定失敗時「一般功能照常」（Q7=C）不會被這一道誤傷 ✔
- `CompanySetupRequired` 繼承 HTTPException（428），`main.py` 有專用的 exception handler 帶出 `code`；五個端點補了 `except HTTPException: raise`，避免被 `except Exception` 吞成 500 ✔
- 月報：不寄＋告警（每日一次）＋`monthly_report_last_sent` 不前進（設定完成後下一輪補寄）✔
- 題：`status()` 丟例外 ⇒ 報價單 PDF 下載 428 `company_setup_undetermined`（D 指定的題）✔
- CG5-S1（已確認後改必要欄位 ⇒ 409 `company_setup_reconfirm`、設定頁「儲存並確認」）、CG5-S2（失敗快取 60 秒）已採納

### 11.2 主持指定

**① 請款單缺匯款三欄 ⇒ 428 `company_bank_required`（原本照印、少一段）**
- 行為本身合理：請款單沒有匯款資料等於沒用。凍結快照的空欄位會退回即時值（`apply_snapshot` 的規則），舊單不會因快照沒存銀行欄而被擋
- 但這是**正式機可見的行為變更**：正式機的「公司資料設定」若銀行欄沒填，上線後請款單 PDF 一張都印不出來 ⇒ **E4S3-S1**

**② 「00000000 不過檢查碼」寫錯：要擋。** D 以 `ubn_valid` 實測：`00000000` ⇒ True（加權和 0）、`55555555` ⇒ True、`12345675` ⇒ True；`11111111`、`99999999` ⇒ False。
- demo 示範公司用 `00000000`，原本的前提是「不可能是真公司」；而正式安裝上輸入 `00000000` 會被當成合格統編、可以確認 ⇒ 等於用一串 0 就跳過「必要欄位」
- ⇒ **E4S3-S2**

**③ CG5-S1 的 409 與既有 409 衝突嗎：不衝突。** 它只出現在設定頁自己的 `PUT /api/settings/company-profile`，回應帶 `code: company_setup_reconfirm`，由設定頁處理（改成「儲存並確認」）；語意是「與目前狀態（已確認）衝突，要重新確認」，正是 409 的用法。D 先前建議改 428 的是**中介層閘門**（任何頁都會收到），那個已經是 428

### 11.3 建議

- **E4S3-S1（上正式機前）　先確認正式機的匯款欄位有填**：
  - 在套用前預檢（`company_setup_cli preflight`）或正式機回報裡加一項「請款單匯款欄位是否齊全」，只報不擋；或在安裝指示裡請正式機 Claude 以唯讀查詢回報
  - 欄位缺 ⇒ 先請使用者在舊版設定頁補齊，再升級。否則上線當天請款單就印不出來
- **E4S3-S2　擋保留統編**：`required_problems` 對非 demo 庫拒收 `00000000`（demo 保留值），訊息「這是系統保留的示範統編」；題：正式庫存 `00000000` ⇒ `fields_invalid`、demo 庫照常。§4.1 的錯句用更正保留（已有）

## 12. 抽查 E4S3-S1／S2：wip/e-company-gate-impl 13a2fbfd（D，2026-09-28）

- 兩條建議都已採納，**無新必修**
- **E4S3-S1**：CLI preflight／status 回 `payment_bank_missing`（主要據點解析後的三欄）；apply_update 在預檢之後、停服之前印 `[WARN]`＋`::NOTE:: company_bank_missing=<欄位>`（齊全 `company_bank=ok`、讀不到 `unknown`），只報不擋；函式不丟例外 ✔
  - **偏離（不進 `::RESULT::`）：同意。** `::RESULT::` 的欄位順序與值域是儀表板與結果檔的固定契約，結果檔寫入函式又與 rollback 逐字相同；另起一行 `::NOTE::` 不動契約，是對的做法
  - 代價：寫回開發機的 result.json 不帶這個註記 ⇒ **正式機安裝指示要請正式機 Claude 把 `::NOTE::` 那一行照抄進回報**（下一班指示範本加一句）
- **E4S3-S2**：非 demo 庫拒收 `00000000`（`RESERVED_DEMO_UBN`；確認回 422、直接寫庫的 status 判 `fields_invalid`）；demo 由 `db.is_demo_mode()` 判定（中介層依 token），CLI 對正式庫預設非 demo ✔
- 版本撞號見 AUDIT-D-A-switch-warn.md SW-O1（已補）

## 13. 抽查正式機形狀的匯款欄位回退：wip/e-company-gate-impl bee605e0（只加題）（D，2026-09-28）

- **回退鏈成立。** `identity_from_profile`：每個欄位取「該據點 → 主要據點 → 頂層別名（`_PROFILE_ALIASES`）→ 聯絡方式 → 預設」第一個有值的
  - `bank_name`／`bank_branch`／`bank_account_name`／`bank_account_number` 四個都在 `DEFAULT_IDENTITY` 的鍵裡，`_PROFILE_ALIASES` 也對應到頂層同名欄位（另收 camelCase）⇒ 據點沒有任何 bank 鍵時，逐欄落回公司層級
  - `_require_payment_bank` 與 `payment_bank_missing` 都走這一支；舊單的凍結快照空欄位也會退回即時值（§11.2）
- 新題 `test_prod_shape_company_level_bank_with_locations_without_bank_keys`：正式機實況形狀（公司層級四欄有值、兩個據點無 bank 鍵）⇒ 主要據點與兩個據點都取公司層級、不 428；預檢 CLI 子行程 `payment_bank_missing == []`；反向控制（清空公司層級帳號）⇒ 428、缺「帳號」✔
- D 在拋棄式 worktree 跑 `test_company_setup_output_gate_2026_09_28.py`：21 passed
- ⇒ 依主持的正式機只讀實況，**E4S3-S1 的風險在正式機不成立**（請款單不會被擋）
- **觀察 E4-O1**：這個題檔是一般 in-process 的 `client` 題，跑完樹裡卻多了 `backend/.initial_admin_credentials.txt`、`.initial_demo_credentials.txt` ⇒ `client` fixture 的 `import main` 本身就會寫這兩個檔（範圍比 AB-S1 的子行程題更廣，可能是既有狀況）。共用主樹上這兩個檔會一直被測試改寫；建議 conftest 在 import main 前把兩個帳密檔路徑導到暫存（同 A46-S1 的位置）

## 14. 抽查 E4-O1 的修正：wip/a-conftest-creds ae27088f（A，基底 0af16ad1）（D，2026-09-28）

- **放行。** conftest `_app` 在 import main 之前，把 `helpers.auth._CREDENTIALS_FILE`、`helpers.startup._DEMO_CREDENTIALS_FILE` 導到 session 暫存
- 寫入端都在呼叫時讀模組變數（`auth.py:130`、`startup.py:262`）⇒ 導向對 import main 與之後每個 client 題都有效；`helpers/__init__.py` 另有一份重新匯出的 `_CREDENTIALS_FILE`，只供讀取，不影響
- BK19 的存量清單移除這兩列 ⇒ 之後有人把帳密檔寫回樹上，守門會紅（有人做過決定）
- D 在拋棄式 worktree 跑新題＋`test_archive_isolation`＋`test_api_docs_off`：32 passed；**跑完樹上沒有任何帳密檔**（對照：§13 在 E4 樹上跑 client 題會留下兩個）
- E4 分支合流時：E4 也改了 conftest（閘門預設、FILES_OVERRIDE），兩邊都在 `_app` 的同一段 ⇒ 合流那一班要確認兩組導向都在

## 15. 抽查 sign 子指令＋§6.7：wip/e-company-gate-impl 303d6f70（D，2026-09-29）

> 只讀碼（未碰真的私鑰）。作者測試：`pytest -n 3`（company_setup_{sign,core,cli,gate,output_gate}＋unit_cards＋l1 快照＋no_our_company_literals＋wording_guards）165 過／1 skip／3 xfail，依裁示 8c34f08a 採信，未重跑。

### 15.0 結論

- **必修 2（SG-M1、SG-M2），都與使用者授權的「有效期 30 天」有關；建議 1。**
- 主持指定的三點中，私鑰不外洩、用途前綴不可互換兩點成立；`--days` 上限不符授權 ⇒ SG-M1

### 15.1 主持指定

**私鑰不外洩：成立。**
- 私鑰只以路徑讀進記憶體、交給 `sign_confirmation`；讀取或簽章丟例外 ⇒ 只回例外**型別名**（註解寫明：例外內容可能含檔案片段）
- 成功的輸出只有 `out／install／issued／expires`；不寫 log；確認檔內容只有 payload＋簽章
- 外層 `main()` 的通用 except 會印例外訊息，但 `cmd_sign` 內讀私鑰的那一段已自己攔下，外層只可能碰到寫出檔案的錯誤（訊息只含路徑）

**用途前綴不可互換：成立。**
- 確認檔簽的是 `b"motrix-company-confirm-v1\n"`＋標準化 JSON；驗證端只接受這個前綴，而且 `purpose` 要相符
- 交付簽章簽的是 `delivery.json 原始位元組 + b"\0" + package.sha256`（`delivery.signed_bytes`），開頭必定是 `{` ⇒ 交付包的簽章不可能被當成確認檔；反過來，確認檔的簽章內容以 `motrix-…` 開頭，不是 JSON，不可能通過交付驗證（delivery.json 還要解析成 dict）
- 簽完以內嵌的交付公鑰自驗，不過不寫檔 ⇒ 拿錯金鑰（例如測試金鑰）簽不出檔 ✔

**`--days` 上限：不符授權 ⇒ SG-M1。**

### 15.2 必修

**SG-M1（必修）　`--days` 的預設與上限要照使用者授權的 30 天**
- 現況：`--days` 預設 **365**、上限 `SIGN_MAX_DAYS = 400`；§6.7 (b) 的範例指令也寫 `--days 365`
- 使用者授權的確認檔有效期是 30 天（主持 2026-09-29）⇒ 照說明操作會簽出超過授權的檔
- 修法：預設 30、上限 30（授權變更時一起改常數與題）；§6.7 (b) 範例改 `--days 30`；題：`--days 31` 被拒、不帶 `--days` 簽出的 `expires − issued == 30`

**SG-M2（必修）　有效期 30 天，但到期前「30 天起每日告警」**
- `SIGNED_EXPIRY_WARN_DAYS = 30` ⇒ 30 天的檔**從簽發當天起每天告警**（每日一次），真正快到期時的告警淹沒在其中（〈告警必須有速率上限〉的另一面：一直響的警報等於沒有）
- 到期的後果不只是「升級被拒」：開發者正式機的簽章檔過期 ⇒ status `signed_file_expired` ⇒ 段② 中介層對**全公司** 428（只能靠 72 小時放行撐住）⇒ 30 天有效期讓「每月重簽」成為可用性的依賴
- 修法：
  - 提醒視窗改成與有效期相稱（例：剩 ≤ 7 天才開始每日告警）
  - §6.5／§6.7 寫明「到期＝全公司暫停，直到放入新簽章檔或啟用暫時放行」，並寫出每月重簽的步驟與負責人（(a) 不必重做，install 不變；只做 (b)(c)）
  - 題：`expires` 在 20 天後 ⇒ 不告警；在 5 天後 ⇒ 告警一次／日

### 15.3 建議

- **SG-S1　確認檔經雲端交付之後要移除**：§3.3 對 F3 檔寫「不上雲」，§6.7 (b) 卻把確認檔輸出到 Google 雲端硬碟的交付資料夾。確認檔不是秘密（公開可驗、綁定單一安裝識別），走交付資料夾可以接受；但請在 (c) 加一步「放進正式機並預檢通過之後，刪除交付資料夾裡的那一份」，§3.3 的「不上雲」改成「只經交付資料夾傳遞、用完刪除」
- §6.7 (a)-4（套用前不要用舊版腳本套別的包）：舊版 apply／rollback 用的是 robocopy `/E`（不是 `/MIR`），不會刪除快照裡沒有的檔；這一條偏保守，但無害，保留

## 16. 複核 SG-M1／SG-M2（使用者改裁示：有效期 365 天、提前 30 天提醒，CORE-SPEC 9a4ec755）：wip/e-company-gate-impl e4b7be5d（D，2026-09-29）

> 作者測試：`pytest -n 3` company_setup_{sign,output_gate,core,cli}＋unit_cards＋l1 快照 135 過、1 skip（依裁示 8c34f08a 採信）。

- ✅ SG-M1 關閉（e4b7be5d）
- ✅ SG-M2 關閉（e4b7be5d）
- SG-M1：`SIGN_MAX_DAYS = 365`＝`--days` 預設＝上限（366 拒絕且不寫檔；預設簽出 expires−issued＝365），與新的授權一致；兩次變更以刪除線保留
- SG-M2：`SIGNED_EXPIRY_WARN_DAYS = 30`，有效期 365 天 ⇒ 只在最後 1/12 期間告警，不再從第一天起每日響（剩 200／31 天不告警、29 天告警一次，有題）；§3.3／§6.5／§6.7(b)／DR-SOP 寫明「到期＝全公司暫停」、年度重簽負責人（主持）、install 不變只做 (b)(c)、在告警期內完成
- SG-S1：§6.7(c) 加「預檢通過後刪除交付資料夾那一份」✔
- **殘留更正（非必修）**：COMPANY-SETUP-GATE.md §6.7 (b) 說明列（約第 333 行）仍寫「`--days` 1～400」，與上限 365 不符 ⇒ 改成「1～365」

## 17. 抽查 sign --permanent：38c5156d（origin/train/0929-train21）（D，2026-09-29）

- **放行，無必修。** 依據：使用者原話「正式機為永久授權」（主持轉達，CORE-SPEC 已記）
- `permanent: true` 寫在簽章範圍內，且**必須沒有** `expires` 才算永久（`is_permanent_doc`）⇒ 無法把一份有到期日的檔改成永久，也無法把永久檔加上到期日；沒有 `expires` 又沒有 `permanent` ⇒ 不算永久、判 expired（反向控制有題）
- 只准開發者身分（與一般簽發同一道指紋檢查）；`--permanent` 與 `--days` 擇一；一般 `--days` 上限仍 365
- 永久檔：只驗簽發日 ≤ 今天；`observe_expiry` 不提醒 ✔
- 文件（train21 分支 c10f625f）：§6.7 (b) 改用 `--permanent`；「年度重簽」以刪除線保留，改為「僅在安裝識別變更時重簽（負責人主持）」；DR-SOP 同步 ✔
- 相容性：這個判定規則與 E4 閘門同一班首次出貨，正式機不存在「認得閘門但不認得永久檔」的舊版本 ⇒ 回滾到目前正式機版本（沒有閘門）也不會把永久檔判成過期
- 提醒：永久檔無法「撤銷」，只能刪檔或改變安裝識別；這與威脅模型（防沿用預設與疏忽）一致，不是缺陷

## 18. 更正（2026-09-29，B 演練發現）

〔更正：§4.1-① 與 §7.1 表格中「漏了第一、二步直接升級 ⇒ 預檢得 `developer_identity_unsigned`」——**原因碼寫錯**。`status()` 在沒有確認紀錄時先回 `no_record`（此時 `developer: true`）；`developer_identity_unsigned` 只在「已有紀錄、但簽章檔不在或無效」時出現。結論（停服之前拒絕、正式機不動）不變。原句保留在原處。〕
