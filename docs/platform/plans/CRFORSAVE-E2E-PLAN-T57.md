# `_crForSave` 瀏覽器行為測試計畫（僅文件；0.5 pd）

> 來源：M2.1 熱修的 0d S4／`FOLLOWUPS-T57-HOTFIX.md`。對象：`frontend/js/case-management-core.js::_crForSave()`、`case-management-exec.js::moSave()`、`mlPickCandidate()`。
> 目前只有靜態字串守門（`backend/modules/case/tests/test_material_import_t57.py`），沒有瀏覽器行為測試。本文列出要驗的行為、做法、種子資料與風險；實作等機器空檔（e2e 需要 Edge、一次一個程序）。

## 1. 要驗的行為（一題一件事）

| # | 情境 | 預期 |
|---|---|---|
| 1 | 案件有一張已核准採購單涵蓋的品項；材料卡片名稱與其相符；使用者在卡片下拉選「帶入並連結」 | 材料申請多一列草稿（`_saved=false`）；卡片 `orderItemId` 指向它；畫面上連結可見 |
| 2 | 緊接著等自動存檔（1.5 秒）跑完 | `PATCH /case-record` 的請求本文中，該卡片的 `orderItemId` 是空字串（連結被扣住）；回應沒有 `rejected`；畫面連結仍在；存檔訊息含「連結將在材料申請儲存後送出」 |
| 3 | 未選供應商就按材料申請「儲存」（設定＝一律要選） | 不送請求，顯示「還沒選供應商」 |
| 4 | 選供應商、儲存成功 | `PATCH /material-orders` 成功；隨後自動補送一次 `case-record`，這次卡片 `orderItemId` 是新列的編號；伺服器資料庫的卡片已連結 |
| 5 | 設定改成『帶入採購單的免選』（直接設定註冊表）、帶入列免選供應商儲存 | 前端不擋；`PATCH` 成功；`GET material-orders` 的 `supplierRequiredAlways=false` |
| 6 | 伺服器擋下一列（例如採購單連結失效） | 訊息格式為「部分項目沒有儲存：「品名」：原因（另有 N 項被擋下：…）」，原因是第一個項目的 |
| 7 | 手動新增的材料列（沒有 PO）未選供應商 | 不論設定，前端都擋 |
| 8 | 切換案件後再回來 | `_mlHeldLink` 不殘留（沒有多餘的補送） |

## 2. 做法

- 檔名：`backend/tests/test_e2e_crforsave_t57.py`（`@pytest.mark.e2e`；`live_server`、`e2e_browser`、`inject_login`、`make_user`——與 `test_e2e_completion_form_2026_09_12.py` 同款）。
- 觀察請求：`page.on("request")` 收 `PATCH …/case-record` 與 `PATCH …/material-orders` 的本文（`request.post_data_json`），逐一斷言本文；用 `page.expect_request`／計數取代固定等待；自動存檔等待以 `page.wait_for_function` 看 `saveStatus === 'saved'`，不寫死 sleep。
- 種子：一張 `已送出` 報價單（含一個有 `id` 的品項），一張 `已核准` 採購單（`case_extra_expenses`，`kind` 採購單，`lines_json` 指向該品項，行數量與金額固定）、`caseRecord.materials` 一張名稱相符的卡片、設定註冊表預設。種子函式沿用 `test_mat_candidates_t51.py` 與 `test_e2e_material_po_ui_2026_10_03.py` 的作法（先讀，不重寫）。
- 登入角色 `superadmin`（材料申請編輯需要財務檢視權）。
- #5 改設定：在測試內直接呼叫 `settings_registry.publish`，或 monkeypatch `material_guard.supplier_policy`（live_server 與測試同一個程序時可行；若是子程序則走設定中心 API）。
- #8 不另開頁面：以 `page.evaluate` 呼叫 `selectCase` 的公開入口切換，再斷言 `_mlHeldLink === false`。

## 3. 風險與取捨

- 1.5 秒的自動存檔去抖動：用 `saveStatus` 等待，不依賴時間；仍要把單題逾時放到 45 秒（機器負載時 Alpine 初始化慢，參見既有 e2e）。
- `case-management.html` 很大，初始化慢：每題共用一個登入的頁面會互相影響狀態（`moDirty`、`_mlHeldLink`），所以**一題一個頁面**，成本約 8 × 10 秒；可把 #1/#2/#4 合成一題連續劇本（同一個流程的三個斷點），其餘獨立。
- 這批題目依賴 `data-testid` 少：優先用既有的 `ml-p-<單號>-<列>` 勾選與 `x-model` 選擇器；若真的找不到穩定錨點，先在頁面補 `data-testid`（屬頁面變更，要同一個 commit 帶 CHANGELOG）。
- 與 M3 的案件頁 e2e（golden、theme）共用 `case-management.html`：本檔不可改全域狀態（字級、主題）。

## 4. 不做的事

- 不測採購單審核流程本身（已有 `test_e2e_material_po_ui_2026_10_03.py`）。
- 不用 mock 取代 `PATCH`：要看真的請求本文與真的資料庫結果。

## 5. 驗收

- 8 題（或 6 題＋1 個連續劇本）全綠，連跑 3 次不偶發；`regen` 後 `test_map.json` 把它歸在 `e2e` 類；單檔執行時間 < 120 秒。
