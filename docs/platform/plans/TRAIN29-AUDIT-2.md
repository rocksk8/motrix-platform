# 第 29 班第二稽核者清單（audit/train29-b，2026-10-01）

第二稽核者（W2 視窗，hichan 名下，以下稱 A29-B）稽核 **c7（A29）為作者** 的五條線；對應 `TRAIN29-AUDIT.md`（origin/audit/train29@af0d4280）§0／§6「待他人稽核」。A29-B 不是這五條線的作者（W2 作者是 A2 額外支出，不在本檔範圍）。
基準：正式機 0bb4834e；被稽核＝`wip/train-29-int1` 建出的包。**不跑全量**；只做探針（單檔或單題）、突變（自己的 worktree、突變前先 commit、只 `git checkout -- <單一檔>` 還原）、獨立重算。**執行時機：包存在之後**（先讀 TRAIN29-AUDIT P1～P5 對包的驗證，才執行本檔）。一次最多 1 個 pytest 行程（`-n 2` 以下），暫存放 `D:\開發測試檔\`、用完刪。
斷言一律打在**伺服器回應／資料庫／產出檔**，不打畫面文字；每條探針先找一個**正對照**（會命中的已知案例）證明比對器有效。

## 0. 先驗的疑點（讀程式時已看到、尚未證實；每條都要先用探針判成立與否，成立＝必修）
| # | 疑點 | 依據 | 判定方式 |
|---|---|---|---|
| Q1 | **外包人員（`contractors`，個人）清單／詳情是否遮蔽帳號？** `contractors.py` 沒有 import `bank_mask`；`_LIST_COLS` 與 `SELECT *` 回完整 `bank_account_number`；只有證件號碼 `_mask_id` | `grep bank_mask` 只有 contractor_vouchers／vendor_contractors | 以 admin＋`contractor_list` 模組帳號打 `GET /api/contractors`、`/{cid}`；`require_superadmin=True, module='contractor_list'` 的語意（是否「superadmin **或** 有該模組」）一併查 `helpers/auth.py::_require_user`。裁示原文＝「承攬商：只有最高管理者看完整」 |
| Q2 | `contractor_vouchers._mask_snapshot` 以 `mask_record(None, …)` 遮蔽；建立憑據時快照（約 line 342–367）寫入的是完整帳號，且 PDF（`pdf_gen.py` 約 1398／1462）與簽核佇列 `personnelBanks`（`approval_queue.py` 約 205）各有自己的遮蔽點 | 多處各自遮蔽＝漏一處即洩漏 | §1 角色矩陣逐面探針 |
| Q3 | 匯款申請／出納側（arap cashier 的承攬商匯款佇列、`payables`）是否帶出收款帳號 | 本線只改 subcontract／pdf_gen／approval_queue | grep `arap` 對 `bankAccountNumber`／`bank_account` 的讀取；探針 cashier 角色 |
| Q4 | `delete_module` 刪實體檔：`os.path.join(UPLOADS_ROOT, p)`，`p` 取自 DB `custom_record_files.path`——若 `p` 是絕對路徑或含 `..`，`join` 會跑出 UPLOADS_ROOT | `custom_module_delete.py` 檔尾 | 在拋棄式 DB 種一列 `path`＝絕對路徑／`..\x`（指向拋棄式暫存檔），`with_records=1` 刪除 ⇒ 暫存檔**不可**被刪（正對照：正常相對路徑檔會被刪） |
| Q5 | `_mark_notifications_read(quote_no, ["approval_request"])` 以 `ref_id`＝報價單號比對：同單號其他文件類型／其他人的通知是否被誤標 | `audit.py` 新函式 | 探針 §3 |
| Q6 | `/api/approval-queue/count` 與簽核佇列頁「待我簽核」是否同一份（代理、連簽、superadmin 無簽核層、費用單據無案件項目） | 橫幅改用該數字 | 探針 §3 |

## 1. 線 A：承攬商／匯款申請帳號遮蔽（`fix/contractor-bank-mask`，`modules/subcontract/bank_mask.py`）
**規則（使用者 2026-10-01）**：只有 superadmin 看完整；其餘 `****末四碼`（≤4 碼＝`****`）；存摺影像只回旗標；無「本人／出納／財務」例外；寫入時遮蔽值原樣送回＝保留舊值；稽核不寫全碼。
**角色矩陣**（固定）：superadmin｜admin（無額外模組）｜admin＋cashier｜admin＋finance｜持 `contractor_list` 模組的非 admin｜簽核鏈成員（匯款申請簽核人）｜申請／派工人本人｜無關 user｜停用帳號（應 401/403）。
**輸出面 × 角色**（每格一個斷言：回應文字不含全碼的連續數字串；含 `****NNNN`；`bankPassbookImage`／`bank_passbook_image` 為 `''`；`hasPassbook` 旗標仍在）：
1. vendor-contractors：`GET` 清單／`/{id}`／`/selectable`（不含銀行欄）／匯出（若有）／`PUT` 帶遮蔽值（DB `data_json.bankAccountNumber` 不變）／`PUT` superadmin 改新值（變）／`PUT` admin 帶**新的明碼**（是否允許非 superadmin 寫入新帳號？裁示只講「看」；若允許列待裁示）。
2. contractors（個人，Q1）：`GET` 清單／`/{cid}`／`/export`／`POST /import`（匯入含帳號欄的檔，回應與稽核不回顯全碼）／`PUT /{cid}`。
3. contractor-vouchers：`GET` 清單／`/{no}`（`include_snapshot` 兩種）／`snapshot.personnel[]`／建立憑據時的回應／PDF 下載（`mask_bank` 預設 True；只有 superadmin 傳 False——以 admin 與 cashier 下載，解析 PDF 文字不含全碼）。
4. 簽核佇列：`GET /api/approval-queue` 的 `personnelBanks`（`_BANK_NUMBER_KEYS`）對 admin／簽核鏈成員（簽核人若不是 superadmin 就看不到要匯的帳號——列「業務影響」給主持，不是洩漏）。
5. 出納（Q3）：承攬商匯款相關的 `/api/cashier/*` 項目；W3 員工帳號 `payee-bank` 端點（規則不同——只確認兩套規則沒被混用）。
6. 稽核與信件：`audit_log.detail`／`target_label` 對上述寫入動作（`PUT`／匯入／建立憑據）全文不含全碼；通知／信件文字不含帳號。
7. 備份：每日 JSON 一般份不含全碼（`_F2_FIELDS`：承攬人員、承攬付款憑據、協力廠商）；個資份才有——只驗宣告與 `_general_row` 的結果，不跑備份。
**突變**（每條都必須有測試轉紅，否則＝假綠燈，必修）：
- M-A1 `bank_mask.can_see_full` 永遠 True。
- M-A2 `mask_number` 回原值。
- M-A3 `vendor_contractors` 序列化略過 `_bm.mask_record`（約 line 96）。
- M-A4 `contractor_vouchers` 的 `if not _bm.can_see_full(viewer)` 區塊整段略過（include_snapshot 兩種都測）。
- M-A5 `_mask_snapshot` 不遮 `personnel`。
- M-A6 `pdf_gen` 遮蔽函式（約 line 1398）改回傳原值。
- M-A7 `approval_queue._BANK_NUMBER_KEYS` 改成空 tuple。
- M-A8 `keep_if_masked` 改成直接回 `new_value`（遮蔽值覆蓋真帳號）→「PUT 帶遮蔽值後 DB 不變」題紅。
- M-A9（Q1 成立並修好後）`contractors` 的遮蔽拿掉。

## 2. 線 B：部門跟業務負責人（`fix/dept-follows-sales-owner` ＋ `wip/w3-dept-dim-c7` 合併；`reports.py::_case_dept`、`recognition.extra_entries`）
**規則**：案件部門＝`caseRecord.roles.sales` 的帳號部門；只有名字／查無帳號／同名無法唯一＝「未分類」（不退回開單者）；`roles.sales` 沒填＝退回開單者（`_case_sales_owner` 既有）。費用單據無案件列用 `departmentId`；有案件列跟案件部門。
**對帳探針（核心）**：造一組案件（業務為帳號 A（部門 D1）、帳號 B（D2）、純名字、同名兩人、`roles.sales` 空＋開單者 C（D3）、已停用業務、業務換部門後），各含收款／支出／額外支出（舊版＋有案件費用單據＋無案件費用單據）：
- 「全部部門」合計＝Σ 各部門（含「未分類」）——逐端點各驗：部門績效、未收款項、收款異常、支出彙總（`_collect_expenses`）、月趨勢、首頁 stats／月趨勢（`dashboard.py`）、`expenses-monthly?department_id=`（當月／本季／今年度三範圍）。
- 與業務員績效表並排：同一業務的金額在「部門」與「業務員」兩表一致——**獨立重算**（直接從 `quotations.data_json` 用 SQL／Python 算，不呼叫 `_case_dept`）。
- 無案件費用單據選部門：出現在該部門、不出現在其他部門、「全部部門」只算一次（舊行為＝無案件＋選部門整筆消失；**正對照＝在 0bb4834e 的程式上同題為紅**）。
- 現金／權責兩口徑各驗；金額＝`total_cost`（現金口徑＝實付）。
- 邊界：部門被刪／停用、使用者無部門（`deptId` None）、同名帳號大小寫、`roles.sales` 為整數 id 與字串 id。
**突變**：M-B1 `_case_dept` 改回開單者部門；M-B2 查無帳號時退回開單者；M-B3 `_quote_in_department` 對 `quoteNo==''` 回 False（舊 bug 復活）；M-B4 `dashboard.py` 其中一處仍用舊 `_row_dept`；M-B5 `extra_entries` 的 `departmentId` 設成 None。

## 3. 線 C：登入「待簽核」橫幅（`fix/login-approval-popup`；`notif.js`、`audit._mark_notifications_read`、`quotations.py` 三個呼叫點）
**規則**：橫幅數字＝`/api/approval-queue/count`（與角標、簽核佇列同一份）；0 件不彈；每分頁最多彈一次；核准只標自己的通知、退回／拒絕標所有人的；不刪列。
**探針**：
- 數字對帳：同一帳號同一時刻，`/api/approval-queue/count` ＝ `/api/approval-queue`「待我簽核」筆數；情境＝一般簽核人／**代理人**（approval_delegates）／連簽（同人兩層）／superadmin 且無簽核層／**費用單據（無案件，A2）**／已簽過／被退回／其他人先簽掉（同層另一人）。不等＝列「橫幅與佇列不一致」。
- 已簽過不再跳：簽核人核准 → 該人的 `approval_request` 通知 `is_read=1`、`/count` 遞減；同層**下一位**的通知仍 `is_read=0`（Q5：不可被誤標）；退回後所有人的待簽核通知已讀、申請人的「被退回」通知**不**被標（類型不同）。
- `ref_id` 碰撞：另一單據類型使用同一字串 `ref_id`（例如費用單據 id 與報價單號）時，只有 `type IN ('approval_request')` 被標。
- 前端（單題 e2e）：有待簽核登入 ⇒ 彈一次；關掉後同分頁換頁不再彈（`sessionStorage`）；`sessionStorage` 被禁（拋例外）時不壞（`try/catch`）；count 請求失敗時**不彈、不報錯**。
**突變**：M-C1 `notif.js` 橫幅改回用未讀通知數；M-C2 `_mark_notifications_read` 不帶 `username` 條件（核准標到所有人）；M-C3 退回路徑不呼叫標已讀；M-C4 `type IN (...)` 條件拿掉；M-C5 `_maybeShowApprovalBanner` 略過 `_popupShown` 檢查（每次換頁都彈）。

## 4. 線 D：刪除模組＋選單位置清單（`fix/module-delete-ownership`；`helpers/custom_module_delete.py`、`routers/definitions.py::delete_custom_module`、`module-builder-core.js`、`window.MOTRIX_MENU.groups`）
**探針**：
- 權限：未登入 401、一般 user／admin 403、superadmin 200；`key` 帶路徑字元（`../`、`%00`、超長）⇒ 404／400，不丟 500。
- 狀態：有送審中版本 ⇒ 409；有單據且未帶 `with_records` ⇒ 409＋`records` 數；`with_records=1` 且有金流 outbox ⇒ 409（**已入帳不可刪**；正對照＝無 outbox 的測試模組可刪）；刪第二次 ⇒ 404；稽核 `definitions.delete_module` 一筆、detail 有版本與單據數。
- 刪乾淨（正對照＝刪前各表有列）：`ui_definitions`、`custom_records`、`custom_record_values／snapshots／revisions／files／log／counters` 皆 0；**孤兒檢查**：`notifications`、簽核相關、`gl_source_events`（來源＝自訂模組）、`audit_log`（應保留）、使用者版面／選單設定裡指向該模組的項目、`module_versions`；列出仍引用該 `module_key` 的任何表。
- Q4 實體檔路徑（見 §0）；檔案刪除在 commit 之後（DB 例外時不刪檔）——以 monkeypatch `conn.commit` 拋例外驗。
- 選單位置：`window.MOTRIX_MENU.groups` 只含伺服器宣告的分組名稱（不夾帶使用者沒權限頁面的標題）；建構器僅 superadmin 可用（既有）；已存分組不在清單時保留並提醒（`groupMissing`）。
**突變**：M-D1 `require_superadmin` 拿掉；M-D2 outbox 檢查拿掉；M-D3 `open_sub`（送審中）檢查拿掉；M-D4 刪檔迴圈改成在 `commit` 之前；M-D5 少刪 `custom_record_counters`。

## 5. 線 E：manifest VR3（`backend/version_manifest.json`）
**探針**：`test_version_manifest_shipped_is_immutable`（對 `prod/0bb4834e` 的 manifest：已出貨條目逐字相同——**自己重算**：`git show 0bb4834e:backend/version_manifest.json` 與工作樹逐條比對，不信測試）；一模組一筆（VR3，未出貨區）；合併後的「模組建構器」條目**內容包含兩個原條目的全部變更**（沒有為過守門而刪內容）；JSON 合法、日期時間遞減、版本字串不重複、模組名稱沿用既有名；`docs/quick/changelog.md` 與各模組 CHANGELOG 對應條目沒被連帶改寫（只增不改）。
**突變**：M-E1 改一個已出貨條目的 content 一個字 ⇒ `shipped_is_immutable` 紅；M-E2 同模組新增第二筆 ⇒ VR3 紅；M-E3 把合併條目少一段內容 ⇒ 人工比對差異（無自動測試＝列「守門缺口」）。

## 6. 執行順序、記錄與關閉
1. 包存在後：先讀 TRAIN29-AUDIT 的 P1～P5 結果（不重做）；從 §0 疑點開始（成立者立即回報主持，不等全部做完）。
2. 每條探針：指令＋回應節錄＋判定（✅／❌／待裁示）；每條突變：改動 diff、跑的單一測試檔、紅的測試名（沒紅＝假綠燈＝必修）。
3. 產出 `docs/platform/audit/AUDIT-A29B-train29.md`（判定：可上／有條件／不可；§0 疑點結果、四條線的探針表、突變表、必修／待裁示清單）。必修以單行 `✅ <編號> 關閉（<commit>）` 關閉，A29-B 不關自己提以外的必修；未關登記 `docs/platform/mustfix_open.json`。
4. 不覆蓋：W1／W3／W4 的線（A29 負責）、W2 A2（作者自審＋A29 抽查）、全量與演練（列車長）。
5. 判定前提：Q1～Q6 已逐條判定；各線突變全紅；無未關必修。
