# `_crForSave` 與材料認列的瀏覽器行為測試計畫（僅文件；0.5 pd）

> 版本：以 **MS1c 之後的行為**為準（讀 `origin/train/ms1c-int-b` b06d7c92a 的 `case-management-mlink.js`／`-core.js`／`-exec.js`）；MS1d 的「立即存檔」依 PM 描述，**實作到位前不寫死該部分斷言**，先讀 MS1d 程式再補。
> 目前只有靜態字串守門（`backend/modules/case/tests/test_material_import_t57.py`），沒有瀏覽器行為測試。本文列出要驗的行為、做法、種子資料與風險；實作等機器空檔（e2e 需要 Edge、一次一個程序）。

## 0. 現況（MS1c）——哪些函式還會產生「扣住的連結」

MS1c 之前，卡片的「帶入並連結」會建立一列未儲存的材料申請草稿，再把卡片的 `orderItemId` 指向它，所以自動存檔必須把這個連結扣住（`_crForSave`）。**MS1c 起這條路徑不再如此**：

| 函式 | MS1c 行為 | 會不會產生扣住的連結 |
|---|---|---|
| `mlPickCandidate(mat, groupKey)` | `mat.orderItemId=''`；`mat.poLink={key, poDocCode, docCodes, name, vendor}`（只有 `key` 是前端的主張，其餘由伺服器驗證後重填）；`mat.ordered=true`；供應商文字取自採購單廠商；**不建立材料申請列、不走審核**；`setDirty()` ⇒ 隨一般 `PATCH /case-record` 立即落地 | **否** |
| `mlImport()`（面板勾選「從採購單帶入」） | 呼叫 `_mlPush` 建立 `_saved:false` 的材料申請草稿列；**不**改任何材料卡片 | 否（沒有卡片指向它） |
| 卡片下拉直接選一筆**尚未儲存**的材料申請列（`x-model` 手選 → `mlOnLinkChange` → `setDirty()`） | `mat.orderItemId=<未儲存列>` | **是**——`_crForSave` 仍會把它扣住並顯示「連結將在材料申請儲存後送出」，`moSave()` 成功後 `_mlHeldLink` 補送一次 |
| `mlAutoLinkMaterials()` | 只連**已儲存且已核准**的材料申請（`o._saved !== false`） | 否 |
| `mlUnrecognize(mat)` | 清 `poLink`；無 `orderItemId` 時取消已申購／已到料；`setDirty()` | 否 |

⇒ `_crForSave`／`_mlHeldLink` 現在只服務「手選連到未儲存草稿列」這一條，測試要證明：①這條仍被扣住且補送；②**認列（poLink）完全不經過它**（請求本文含 `poLink`、`orderItemId` 為空，且沒有 `PATCH material-orders`）。

## 1. 要驗的行為（一題一件事）

| # | 情境 | 預期 |
|---|---|---|
| 1 | 案件有一張已核准採購單涵蓋的品項；材料卡片名稱與其相符；在卡片下拉選候選（`mlPickCandidate`） | 材料申請清單**沒有**多出草稿列；卡片顯示「已認列採購單 …（廠商：…）」；「已申購」自動勾上 |
| 2 | 緊接著等自動存檔完成 | `PATCH /case-record` 本文：該卡片 `poLink.key` 有值、`orderItemId` 為空；回應沒有 `rejected`；重新載入後 `poLink` 的 `docCodes`／`vendor` 是伺服器重填的值（不是前端送的）；**沒有** `PATCH /material-orders` 請求 |
| 3 | 偽造 `poLink.key`（測試內改 `mat.poLink.key` 為不存在的值再存） | 伺服器擋下（`rejected`），畫面顯示原因，卡片換回伺服器現值 |
| 4 | 面板「從採購單帶入」勾選一組、按帶入（`mlImport`） | 清單多一列 `_saved:false` 草稿；沒有任何卡片被連結；未選供應商按「儲存」⇒ 前端擋下並顯示「還沒選供應商」（設定＝一律要選） |
| 5 | 選供應商後儲存 | `PATCH /material-orders` 成功；**沒有**補送的 `case-record`（`_mlHeldLink` 為 false） |
| 6 | 設定改成「帶入採購單的免選」後，帶入列免選供應商儲存 | 前端不擋；`GET material-orders` 的 `supplierRequiredAlways=false`；手動新增（無 PO）的列仍被擋 |
| 7 | 伺服器擋下一列（例如採購單連結失效） | 訊息「部分項目沒有儲存：「品名」：原因（另有 N 項被擋下：…）」，原因是第一個項目的 |
| 8 | **仍會扣住的路徑**：先 `mlImport` 建一列未儲存草稿，再在某張卡片下拉手選這一列 | 自動存檔的 `case-record` 本文中該卡片 `orderItemId` 為空；存檔訊息含「連結將在材料申請儲存後送出」；畫面連結仍在 |
| 9 | 接著選供應商、儲存材料申請 | `PATCH /material-orders` 成功後自動補送一次 `case-record`，本文 `orderItemId` 為新列編號；資料庫的卡片已連結；之後 `_mlHeldLink===false` |
| 10 | 取消認列（最高管理者）`mlUnrecognize` | `poLink` 清除，已申購／已到料取消（除非另有已核准申請支撐）；非最高管理者被伺服器擋下 |
| 11 | 切換案件再回來 | `_mlHeldLink` 不殘留（沒有多餘補送） |

> MS1d 到位後：若 #9 的補送變成「儲存當下立即送出」，把 #9 改成斷言「`moSave` 成功回應之後、同一事件迴圈內已發出 `case-record`」，並保留「請求本文的 `orderItemId` 是新列編號」；其餘題不受影響。

## 2. 做法

- 檔名：`backend/tests/test_e2e_crforsave_t57.py`（`@pytest.mark.e2e`；`live_server`、`e2e_browser`、`inject_login`、`make_user`——與 `test_e2e_completion_form_2026_09_12.py` 同款）。
- 觀察請求：`page.on("request")` 收 `PATCH …/case-record` 與 `PATCH …/material-orders` 的本文（`request.post_data_json`）；用 `page.expect_request`／計數取代固定等待；自動存檔以 `page.wait_for_function` 看 `saveStatus === 'saved'`，不寫死 sleep。
- 種子：一張 `已送出` 報價單（含一個有 `id` 的品項），一張 `已核准` 採購單（`case_extra_expenses`，`kind` 採購單，`lines_json` 指向該品項，含廠商名稱以便驗證 `vendor` 重填）、`caseRecord.materials` 一張名稱相符的卡片、設定註冊表預設。種子函式沿用 `test_mat_candidates_t51.py` 與 `test_e2e_material_po_ui_2026_10_03.py` 的作法（先讀，不重寫）。
- 登入角色 `superadmin`（材料申請編輯與取消認列需要）；#10 另加一個非最高管理者帳號驗證被擋。
- #6 改設定：測試內呼叫 `settings_registry.publish`，或 monkeypatch `material_guard.supplier_policy`（live_server 與測試同一程序時可行；若是子程序則走設定中心 API）。
- #3 偽造：以 `page.evaluate` 直接改 Alpine 資料（`Alpine.$data(...)`），不要靠 UI。
- #11 以 `page.evaluate` 呼叫 `selectCase` 的公開入口切換，再斷言 `_mlHeldLink === false`。

## 3. 風險與取捨

- 1.5 秒自動存檔去抖動：用 `saveStatus` 等待，不依賴時間；單題逾時放到 45 秒（負載時 Alpine 初始化慢，參見既有 e2e）。
- `case-management.html` 很大、初始化慢：每題共用同一頁會互相影響狀態（`moDirty`、`_mlHeldLink`、`poLink`），所以**一題一個頁面**，約 11 × 10 秒；可把 #1/#2、#4/#5、#8/#9 各合成一個連續劇本（同一流程的斷點），共 6～7 個測試。
- 錨點：優先用既有的 `ml-p-<單號>-<列>` 勾選與 `x-model` 選擇器；找不到穩定錨點就先在頁面補 `data-testid`（頁面變更，需同一個 commit 帶 CHANGELOG）。
- 與案件頁 golden／theme 共用 `case-management.html`：本檔不可改全域狀態（字級、主題）。
- #1～#3 屬 MS1c 的認列機制，與本計畫原本的 `_crForSave` 目標分開寫在同一檔，是因為兩者共用同一種子與同一頁面；若 MS1c 另有自己的 e2e，先讀它並避免重複（`grep -l poLink backend/tests/test_e2e_*`）。

## 4. 不做的事

- 不測採購單審核流程本身（已有 `test_e2e_material_po_ui_2026_10_03.py`）。
- 不用 mock 取代 `PATCH`：要看真的請求本文與真的資料庫結果。

## 5. 驗收

- 題目全綠，連跑 3 次不偶發；`regen` 後 `test_map.json` 把它歸在 `e2e` 類；單檔執行時間 < 150 秒。
