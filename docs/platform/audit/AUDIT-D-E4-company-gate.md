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
