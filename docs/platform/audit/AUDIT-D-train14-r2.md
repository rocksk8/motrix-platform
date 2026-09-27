# 稽核：第十四班第二輪新包（D，2026-09-28）

> 範圍：主持第二輪派工第 4 項，含兩次追加。只讀碼；針對疑點在拋棄式 worktree 跑題目與突變，暫存已刪，worktree 已移除。
> 第二輪的複核（H12、B41、H13、a-mustfix-scan）寫在各自原本的稽核檔。

## 0. 總表

| 包 | commit | 必修 | 建議 | 觀察 | 結論 |
|---|---|---|---|---|---|
| A43 a-storage-settings | ddcb2025 | **1** | 0 | 0 | 設定讀取失敗會退回自動判斷，見 SL-M1；其餘成立 |
| A38 a-update-delivery | 44b2d8d8 | 0 | 1 | 0 | US1 已處理；US2 未處理；judge 注入可接受 |
| A41 a-builder-sink-guard | cbcdff1d | 0 | 0 | 0 | BS1、BO1 已處理（只改題目與文件）；10 過 |
| B47 b-l1-coverage-restore | 5ddb52af（主持給的是 461ad3e7，origin 已前進） | 0 | 0 | 0 | RM-S1 以參數化處理；131 過 |
| B48 b-build-by-license | 4f549cfe | 0 | 0 | 0 | machine_mismatch 放行安全；13 過 |
| A34 a-cr-network-errors | 90f05d06 | 0 | 0 | 0 | NS1 已處理（突變由主持跑過：approve 重送 ⇒ 紅） |
| H12 h-apply-platform | d046f206（只補題） | 0 | 0 | 0 | D2-S1、D2-S2、D2-O1 已補；先前存活的 M3、M9、R4、R10 重跑全紅；146 過 |

## 1. 必修

**SL-M1（必修，A43）　設定讀不到時退回「全部自動」並快取 30 秒，與模組自己的不變式相反，個資可能寫到使用者已經不用的資料夾**
- 證據：
  - `_read_main_db` 讀 system_settings 發生任何例外 ⇒ `return {}`（helpers/storage_locations.py:54）
  - `configured()` 把它當成「全部留空」快取 30 秒（:84）
  - 於是 `resolve("archive_root")` 走 `_auto_archive_base()` 掃磁碟，`resolve("pii_root")` 落在自動找到的根目錄旁的「系統存檔_個資」
- 與檔頭不變式的衝突：「有設定 ⇒ 用設定（不存在就回 ""，**不退回自動判斷**：寫到別的地方比寫不進去更糟）」
- 觸發情境：主庫被鎖超過 30 秒（連線 timeout＝30）或損毀；而最高管理員把個資資料夾從預設位置改到了別處、舊的預設資料夾還在
  - ⇒ 這 30 秒內的個資鏡像（勞報單、個資欄位）會寫進舊的預設資料夾
  - `_pii_ensure_dir` 只擋「根目錄不在」，舊資料夾在就照寫
- 修法：
  - 讀取失敗 ⇒ **不快取**，回「無法判定」（三個位置的 path 都回 ""，source 回 "unknown"）
  - 寫入端照「找不到」處理（告警、不寫）
  - 只有「讀到了、而且鍵不存在或為空」才算留空＝自動
  - 補題：`_read_main_db` 丟例外 ⇒ `resolve` 三種都回空、不是自動路徑、下一次讀取會重試（反向控制：真的留空 ⇒ 自動）
- 登記：列車合回時，`mustfix_open.json` 加上 SL-M1（owner A，wip/a-storage-settings）

**其餘逐項（A43）**：
- 背景程式不自動建資料夾：`_pii_ensure_dir` 逐層 mkdir，根目錄不在就丟例外
- `create` 只建最後一層、已存在就拒絕、只限最高管理員、寫稽核
- 個資資料夾與雲端存檔根目錄、更新交付資料夾不可以互相包含（含留空時自動算出來的那一個）
- PUT 用 `extra=forbid`；一律寫主庫（demo 模式不寫 demo 庫）；變更寫稽核（from → to）

以上都成立。

## 2. 建議

**US2（A38，第一輪提出，仍未處理）　儀表板用 `import delivery` 取它，而沒有任何題確認取到的是安裝目錄 backend\tools 那一份**
- 現在儀表板在正式機的 backend\tools 執行，sys.path[0] 就是那裡，所以取到的是對的
- 但信任鏈（用已安裝版本的公鑰驗章）完全靠這件事成立，日後改啟動方式時不會有任何題紅
- 建議補一題：`delivery.__file__` 的上一層＝儀表板所在的 tools 目錄，而且不在 staging 底下

**A38 其餘**：
- US1：`/api/delivery/apply` 在套用前，對同一個 staging 重跑 `verify_staged`（跳過 verify_package），被改過就回 409；題 `test_rc_staging_changed_after_prepare_is_refused`
- A 問的做法：delivery.py 不再 import 儀表板，改由儀表板傳入自己的 `(decide_outcome, parse_result_line)`；題目以 importlib 依路徑載入儀表板取這兩支。判定的唯一來源仍在儀表板，而 HC1c（儀表板的路由只掛在只限本機的 app）沒有被繞過 ⇒ **可以接受**

## 3. B48：machine_mismatch 放行（主持指定）

- `licensing._verify_blob` 的順序固定是 malformed → missing → **bad_signature** → machine_mismatch → expired：簽章驗過之前不讀 payload 的任何欄位；簽章沒過一律 `_unverified`（env＝None）
- 建包端第一道就是 `env is None ⇒ 拒絕`；4f549cfe 補了「未驗過卻帶模組清單 ⇒ 仍拒絕」的題（突變 L2 原本存活）
  - ⇒ 會走到 machine_mismatch 的，必定是簽章成立的授權，模組清單可信
- 到期判定改看 `days_left`，因為 machine_mismatch 會蓋過 expired：非永久、已過期 ⇒ 拒絕；看不懂的 reason ⇒ 拒絕
- 建包端只決定包裡放哪些檔。正式機的載入器照樣以授權（含機器指紋）決定載入哪些模組，所以即使放行錯了，也只是包裡多了檔，不會讓未授權的模組執行
- **判定：放行是安全的。**

## 4. 其他

- A41：寫入點守門的掃描對象加上 form-preview.js（白名單 3 處，附理由）與 custom-layout.js（0 處）；上限按檔分開計；補 setHTMLUnsafe、createContextualFragment；新檔各有正對照
- B47：feed_attachment_serving 的附件來源參數化——`crm`（參數層標 needs_crm）與 `l1`（直接呼叫 helpers.uploads.save_document_files，不標）；地圖與定位題照同樣的方式，以 suppliers 當 L1 資料來源。CRM／標案雷達不在的樹上，L1 行為仍然有題在驗
- A34：核准、退回、流程轉換網路失敗時，改成「重新載入單據」；只有儲存（PUT）直接重試
- H12 d046f206：
  - trap 四格：applied／not_applied＋down ⇒ 重啟；restoring、up ⇒ 不重啟
  - plan_refused 排在 plan_failed 之前
  - M3 改驗 Copy-Item、M9 改驗 cleanup 失敗的判定與 Fail
  - D2-O1：執行期寫入位置的 classify 不可以是 program

## 5. 複核 SL-M1：wip/a-storage-settings bb01c764（範圍 ddcb2025...bb01c764）（D，2026-09-28）

- 修正內容：
  - 讀不到 ⇒ `_read_main_db` 回 None；「庫檔不存在」與「還沒有 system_settings 表」仍算沒設定；設定值不是 dict 也算讀不到
  - `_load` 不快取未知
  - `resolve` 三個位置都回 `{"path": "", "source": "unknown"}`，不退回自動判斷
  - `configured()` 丟 Unreadable；GET、PUT 回 503，PUT 在寫入之前就停
  - `status` 標 unknown
- 題 23 過。突變：
  - 讀不到仍快取成空 ⇒ 2 紅
  - **只把 `sqlite3.OperationalError`（庫被鎖）那一支改回 `{}` ⇒ 存活**：題目模擬讀不到用的是一般例外，沒有走到「庫被鎖」那一支，而那正是 SL-M1 的主要觸發情境
- 探針（拋棄式 worktree，臨時庫）：讓 `sqlite3.connect` 丟 `OperationalError("database is locked")` ⇒ 三個位置都回 unknown、空路徑；恢復之後的下一次讀取回到 `source=setting` ⇒ **程式碼行為正確**
- **D3-S1（建議）**：補一題以 `OperationalError("database is locked")` 模擬被鎖（與探針同一種做法），把主要情境釘住；反向控制：`no such table` ⇒ 仍算沒設定

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ SL-M1 關閉（bb01c764）——讀不到儲存位置設定時三個位置回未知、不退回自動判斷、不快取，設定頁回 503 不寫

## 6. 複核 US2：wip/b-delivery-us2 eb953b23（範圍 44b2d8d8...eb953b23）（D，2026-09-28）

- 修正：`_trusted_delivery()` 比對已載入 delivery 模組的 `__file__` realpath（normcase）與 `<TOOLS_DIR>/delivery.py`；`TOOLS_DIR` 取自儀表板自己的 `__file__`。不同 ⇒ prepare、apply 回 409，背景套用記 failed。涵蓋所有會驗章或套用的入口
- 題（三檔）41 過。突變：
  - 拿掉比對 ⇒ 2 紅
  - 把「載入的路徑」換成「期望的路徑」（自己比自己的假綠）⇒ 2 紅
  - 反向控制：staging 放一份位元組相同的 delivery.py、排在 sys.path 前面 ⇒ 被擋。證明比的是位置，不是內容
- **D4-O1（觀察）**：overview、status、開發機的 prod-status 這三處仍然直接 `import delivery`，但只做顯示（讀鎖、讀結果、列包），不驗章、不套用。模組快取是同一個物件，之後的 `_trusted_delivery` 仍會依 `__file__` 攔下 ⇒ 可以接受
- **US2 成立**（它是建議，沒有關閉紀錄的格式要求）

## 7. 第十四班列車修正：wip/a-train14-fix 12fb2e27＋9c689477（父 76bf91e3）（D，2026-09-28）

- 12fb2e27：apply_plan.py 把 `"frontend/pages"` 抽成 `PAGES_REL`，3 處改用它，字串值相同 ⇒ **行為不變**（讀碼逐處比對）；page_path 基線登記 2 筆
- 9c689477：payment-request、storage-settings 兩頁的 favicon 改讀品牌端點（與其他頁一致，是建構器預覽唯一的 API 豁免）；test_module_rc_scope 的正對照題逐題標 requires_module accounting＋case。成立
- 題：test_apply_plan＋test_module_rc_scope 54 過
- **D5-S1（建議）　題目失去錨點**：題目裡 27 處字面值全部改成 `PG = ap.PAGES_REL`，整檔不再有 `"frontend/pages"` ⇒ 用程式自己的值驗程式自己
  - 突變：把 `PAGES_REL` 改成 `"frontend/page"` ⇒ 54 題**全綠**
  - 而正式機的安裝目錄仍是 `frontend/pages`：
    - lock 的 removed_pages 會全部被判不合法 ⇒ 拒絕套用
    - DO3 保護「未授權模組的頁面不刪」的 `protected_pages` 會對不到真實路徑 ⇒ baseline 來源會刪掉客戶付費模組的頁面
  - 目前的值是對的，所以不擋上車
  - 建議補一題：`ap.PAGES_REL == os.path.relpath(core.paths.FRONTEND_PAGES_DIR, core.paths.INSTALL_ROOT).replace("\\", "/")`——期望值取自獨立來源（core.paths），不是字面、也不是被測物本身
- 必修 0

- D5-S1 已處理（34e2cbef）：`test_pages_rel_matches_the_real_install_layout` 以 core.paths 為期望值。D 重跑突變「PAGES_REL 改成 \"frontend/page\"」⇒ 只有這一題紅、其餘 51 題綠；還原後 worktree 乾淨（D，2026-09-28）
