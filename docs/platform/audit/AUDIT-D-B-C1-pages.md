# 稽核：B 的階段 C／C1＋C2a——/pages 由 core.pages 提供（合回後稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。只審新版（CORE-SPEC 35014aaa）。
> 對象：origin/platform `8235c8ed`（C1＋C2a）、`97192db6`（頁面路徑守門補正）。規格：STAGE-C-DESIGN §3、裁示 D2（選項 A：HTTP 404＋伺服器提示頁）、STATES-PLATFORM P-LD-07（衝突比照路由衝突）。
> 稽核樹 `D:\MOTRIX-PLATFORM-D2`（detached，origin/platform `193e29e4`），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：`PG`＝`backend/core/pages.py`。

## 0. 結論

- 主持點名的四項都成立，也都有題目：
  - 停用或未授權模組的頁面回 **404＋提示頁**：單元題＋e2e。D 的突變 G04（改成 200）在單元題存活，但 e2e `test_direct_url_to_unloaded_module_shows_notice` 斷言 `status == 404`，補跑之後轉紅 ⇒ 有守到。
  - 名稱比對不分大小寫（查詢與衝突兩處）。
  - 撞名時整個模組標 failed，被拒模組的頁面不會落到 L1 以 200 提供。
  - `/pages` 路由在 StaticFiles 之前。
- 基準：`test_core_pages`＋`test_page_paths_centralized` **42 passed**。D 自做突變 8 項＋e2e 補跑 1 項：**全部轉紅**（§2）。
- **必修 1 項**：
  - P-M1：模組的 `pages[]` 可以宣告 L1 頁面（例如 `login.html`）。那個模組一停用或未授權，**登入頁就回 404 提示頁**，沒有任何守門擋得到。
- 建議 1 項、觀察 2 項。O5 的分析見 §4：目前沒有證據顯示與 `/pages` 路由有關。

## 1. 逐項驗收

| 項目 | 驗收 | 證據 |
|---|---|---|
| 未載入模組的頁面 ⇒ HTTP 404＋提示頁（停用／未授權／失敗／未安裝） | ✅ | PG:142-157；`main.py` 的 `/pages/{name:path}` 回 `HTMLResponse(..., 404)`；突變 G03 紅、G04 由 e2e 紅 |
| 名稱不分大小寫（查詢） | ✅ | PG:101-105；突變 G01 紅（`Tender-Radar.html` 不會讀到舊檔） |
| 名稱不分大小寫（衝突） | ✅ | PG:69；突變 G02 紅 |
| 撞名 ⇒ 整個模組 failed、不掛；其他模組照常 | ✅ | PG:174-191（在 `mount_modules` 之前）；突變 G05、G08 紅 |
| 同一頁在模組資料夾與 frontend/pages 各有一份 ⇒ 衝突 | ✅ | PG:75-77；突變 G07 紅 |
| 檔名只准單層、擋 `..` | ✅ | PG:28、43-44；突變 G06 紅 |
| 路由順序：`/pages` 在 StaticFiles 之前 | ✅ | `test_main_serves_pages_before_static_files` |
| L1 行為改變寫 CHANGELOG | ✅ | `backend/core/CHANGELOG.md`（8235c8ed） |

## 2. 突變（D 自做；在 `D:\MOTRIX-PLATFORM-D2`，每項都用 `git checkout` 還原並核對內容）

| 突變 | 結果 | 轉紅的題 |
|---|---|---|
| G01 查詢分大小寫 | 🔴 | `test_rc_case_variant_of_a_disabled_page_is_not_served` 等 2 |
| G02 衝突比對分大小寫 | 🔴 | `test_rc_two_modules_declaring_the_same_page_fail` 等 2 |
| G03 未載入也給檔案 | 🔴 | `test_unloaded_module_page_gets_the_notice[…]` 等 6 |
| G04 提示頁回 200 | 單元題 🟢 ／ **e2e 🔴** | `test_direct_url_to_unloaded_module_shows_notice[…]` 4 題 |
| G05 衝突模組不卸載 | 🔴 | `test_check_and_register_marks_conflicting_module_failed` |
| G06 不擋路徑穿越 | 🔴 | `test_rc_unsafe_names_are_rejected[../secret.html]` 等 3 |
| G07 兩份不算衝突 | 🔴 | `test_rc_page_in_both_places_fails` |
| G08 被拒模組的頁面落到 L1 | 🔴 | `test_collect_refuses_the_later_module_whole` |

探針（直接呼叫 `core.pages`）：合成模組 `zz_mod` 的 manifest 寫 `pages: [{"path": "login.html"}]`，L1 目錄用 repo 的 `frontend/pages`：
- `collect()` ⇒ `login.html` 的擁有者變成 `zz_mod`，而且**不算衝突**（`refused` 是空的）。
- `page_response("login.html", …)`，當 `zz_mod` 停用 ⇒ `("notice", …, "disabled")`，也就是 **HTTP 404＋「此模組目前已停用」**。

## 3. 發現

### 必修

**P-M1　模組可以把 L1 頁面宣告成自己的頁面；那個模組一停用，L1 頁面就回 404**
- 位置：PG:64-83。`legacy.is_file()` 就接受；PG 不知道哪些頁面屬於 L1（「不屬於任何模組」＝L1，是推論出來的）。G2 守門只檢查宣告的頁面**存在**，而 `frontend/pages/login.html` 確實存在。
- 後果：模組停用、未授權或載入失敗時，登入頁、首頁、使用者管理、模組管理這類頁面都會變成提示頁。登入頁被佔掉的話，連管理者都無法登入去把模組重新啟用。能讓這件事發生的，是一個寫錯的 module.json，或是一個 P7 模組更新包。
- 為什麼是必修：這是階段 C 新開的一條路，而影響的是整個系統能不能進得去。依 MODULE-GUIDE 的原則，模組拿掉時「只能少一個功能」，現在卻會少掉 L1。
- 建議修法：
  - L1 頁面要有明確的清單。STAGE-C 已經規劃 `core/menu_l1.json`；或者另設 `core/pages_l1.json`。
  - `collect()` 遇到模組宣告 L1 頁面 ⇒ 列為衝突，拒絕那個模組（比照 P-LD-07），L1 頁面照常提供。
  - 補反向控制題（可以直接用上面的探針），並用突變證明它會紅。

### 建議

- **P-S1　`/pages` 每一個請求都走執行緒池，而且每次都重查狀態**：路由是同步函式（`def module_page`）。命中未載入模組時，`_module_state` 會把 `module_states()` 整份掃一遍。頁面流量不大，影響有限；但 e2e 全量時執行緒池也被 API 共用。建議：已載入的模組直接回檔案（現在已經是這樣）；提示頁那條路徑可以用 `registry` 的單筆查詢取代整份掃描。這一點**沒有**觀察到實際的延遲，列為建議。

### 觀察

- **P-O1　「未安裝」的提示頁實際上只有在模組資料夾還在時才會出現**：`read_manifests` 只讀安裝目錄裡的 module.json。模組沒有裝、頁面檔卻留在 `frontend/pages` 時，那一頁照樣 200（由前端 `sidebar.js` 後備蓋提示框）。說明文字已寫明是後備；而部署包的選配會移除被排除模組的頁面（`removed_pages`），所以正常的安裝包不會有這種情況。
- **P-O2　`PAGE_NAME` 只接受 `.html`**：`/pages/` 底下如果有其他檔案（圖片、js），現在一律 404。D 查過 `frontend/pages/` 目前只有 `.html`，沒有影響；之後模組頁面要附圖時，需要另外的位置或放寬規則。

## 4. O5（登入導向偶發逾時）與 `/pages` 路由的關係

主持請 D 順便看 O5：`test_e2e_login_enter_submits::test_enter_logs_in[after_failed_attempt-webauthn]` 在 C1 全量裡紅 1 次，等 `/index.html` 等了 8 秒逾時。D 的判定：**目前沒有證據顯示與 `/pages` 有關**。依據：
1. 逾時的等待點是 `wait_for_url(… endswith("/index.html"))`。`/index.html` 由 `/` 的 StaticFiles 提供，不經過 core.pages。`/pages/login.html` 是在情境開始之前載入的（`_goto_login` 已經等到 `webauthn-config-status` 回應與 Alpine 渲染完成）。
2. 從按下 Enter 到導向，頁面只打 `/api/auth/login`（`login.html:612` 在回應 ok 之後才 `location.href`）。這個情境登入兩次：一次故意打錯、一次正確，都要計算密碼雜湊，在滿載的全量裡是最慢的那一段。
3. 登入鎖定：以 IP 計算，連續 5 次失敗鎖 15 分鐘。conftest 每一題都把 `routers.auth._rl_state` 換成新的 dict（`backend/conftest.py:552-554`），live_server 同一個行程讀的是模組屬性，所以不會跨題累積。這一題本身只失敗 1 次。⇒ 排除「被鎖」這個解釋。

建議下次出現時照 RUN-PLAN 的說明抓兩樣東西，再判斷是不是 CPU 飽和造成登入 API 太慢：
- `/api/auth/login` 兩次請求的開始時間與耗時（`page.on("request")`／`page.on("response")`）；
- 伺服器端 `auth.login` 的耗時紀錄。

D 沒有重現 O5，以上是排除法的結論，不是成因。

## 5. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| P-M1 | 修正：L1 頁面明確清單 `core/l1_pages.json`（20 頁，＝modules.json L1 群組的 `page:pages/*`；`index.html` 在 frontend 根、不經 /pages，不列），守門 `test_l1_pages_file_matches_modules_json`。`collect()` 遇到模組宣告 L1 頁面（不分大小寫）⇒ 衝突、整個模組拒絕（已載入 ⇒ unload 成 failed，比照 P-LD-07）；L1 頁面不進 page_map，照常由 L1 提供。探針：D 的情境（模組宣告 login.html）與後果題（模組未載入時 /pages/login.html 仍回 L1 檔）；另加「現有模組都沒宣告 L1 頁面」。突變（拿掉檢查）⇒ 3 紅 | 5e661035 | |
| P-S1 | 不修（理由）：整份掃描只發生在「未載入模組的提示頁」這條路徑，已載入的模組與 L1 頁直接回檔；D 也沒有觀察到延遲。要改成單筆查詢得在 registry 加公開介面（L0 次版號）——代價大於效益。改成 async 的效益同理。若之後量到延遲再處理 | — | |
| P-O1～O2 | 收到。O1 與 sidebar.js 後備的說明一致（C1 已寫明），正常安裝包由選配移除頁面，不會出現。O2 記入 STAGE-C C5 注意事項：模組頁面要附圖時另訂位置或放寬 PAGE_NAME（屆時一併補規則與守門） | — | |
