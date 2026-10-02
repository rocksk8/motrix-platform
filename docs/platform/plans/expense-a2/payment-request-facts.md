# 請款單現況事實表（W2，2026-10-01；基底 origin/platform 37ac3efe）

⚠️ **先講結論**：現有「請款單」(`payment_requests`) 是**對客戶要款的 AR 文件**，不是費用報銷（AP）。核准即為最終文件、**沒有出納付款節點、沒有總帳事件、不進營運報表支出**。使用者想要的「請購／差旅／採購／零用金 → 核准 → 出納付款 → 總帳＋營運報表」是**付出去的錢**；現成的付款管線在另一條：**案件額外支出（`case_extra_expenses`）＋IP-100 `payables.pending`**。兩條方向相反，擴充時要先決定掛哪一條（見 §6）。

## 1. 表與欄位
- `payment_requests`（db.py:1889，V9 凍結 migration v53；stage 欄 db.py:2595 v57）：`id, request_no(UNIQUE,'PR…'), quote_no TEXT NOT NULL, scope('amount'|'items'), stage, status('草稿/待審核/簽核中/已核准'), ratio_pct, amount, terms_json, snapshot_json, data_json(含 approval), export_count, export_log, created_by/at, updated_at`。索引 `idx_pr_quote_no`、`idx_pr_status`。
- `data_json` 存簽核狀態（tiers、currentTier、requestedBy…）；`snapshot_json` 存**建立當下凍結的客戶／案件／品項**（客戶可見文件，故刻意不含成本）。
- 表在 **db.py（L0 凍結）**，arap 模組**沒有自己的 migrations 目錄**（`modules/arap/` 無 `migrations/`；case 有 `modules/case/migrations/0001,0002`）。

## 2. 案件綁定：哪裡要求 quote_no
| 位置 | 事實 |
|---|---|
| 表 | `quote_no TEXT NOT NULL`（db.py:1892）——**SQLite 不能 ALTER 掉 NOT NULL**，要放寬得重建表 |
| 建立 API | `create_payment_request`（payment_requests.py:364）：查 `quotations`，找不到 404；`_quote_remaining()`（:177）算**剩餘可請款額度**並擋超收（409） |
| 單據守門 | `_guard_voucher`（:53）用 `guard_case_access(quote_no…)`；報價單不存在則退回 `require_any_module(case_manage/finance/cashier/quotation)` |
| 建立權限 | `_require_admin`（:139）＝admin／superadmin；金額可視另看 `can_see_financial`＋是否本單簽核人 |
| 表單 | `frontend/pages/payment-request-form.html`：無 `quoteNo` 整頁不渲染（:96 `x-if="quoteNo"`），返回連結回 case-management；合約總額／剩餘額度欄（:240） |
| 簽核佇列 | `queue_items`（:923）`linkedQuoteNo=quote_no`、`projectName=… 關聯案件 {quote_no}` |
| 案件頁 | `quotations.py:4396–4458` 只回唯讀子清單 `paymentRequests`，**不併進應收合計**；`:1983` 案件相關單據清單 |
| 不依賴案件的部分 | L1 簽核佇列只用 `type` 標籤（`routers/approval_queue.py:201`）；信件只帶單號＋客戶名 |

## 3. 簽核流程與信件
- 共用 `unified_approval_flow`（system_settings；與報價單／開票憑據／出貨單共一組）；tiers 依序簽、`cascade_self_tiers`、不可自簽（`check_no_tier_self_approval`）、退回必填原因（`require_reject_reason`）。端點：`submit :578`、`approve :639`（核准 ⇒ `status='已核准'`，:~720）、`revoke-approval :747`、`reject :788`。
- 信件類型（`helpers/mail_types.py:98–121`）：`payment_request_submitted／_next_tier／_approved／_returned`（`helpers/email_notify.py:768–825`）；另有站內通知 `payment_request_approval_request／_approved`。
- 佇列提供者：`modules/arap/__init__.py:23–27`（`approval.queue_items／reassign／detail`，type=`payment_request`）。

## 4. 出納付款路徑（現況）
- **請款單本身：沒有。** 核准即終點；文件檔頭明講「不像承攬商匯款申請多一個『已匯款』節點」。出納頁不列它。
- 現成的**付款管線**（都是 AP）：
  - IP-100 `payables.pending`（`docs/platform/INTEGRATION-POINTS.md:702`）：M01 提供者 `modules/case/payables.py::_Payables`（`pending :57 / paid :65 / mark_paid :77`）＝核准而未付款的**案件額外支出**；出納 `GET /api/cashier/pending-payables`、`POST /api/cashier/pending-payables/{名稱}/{key}/pay`（`modules/arap/api/cashier.py:82/102`）。**多提供者、以名稱區分**——新款項可登記同一名稱空間。
  - 承攬商匯款（IP-14）、獎金（IP-8）、勞報單各有自己的發放路徑。

## 5. 若一張「無案件」請款走各消費端
| 消費端 | 現況對無案件資料的行為 |
|---|---|
| **營運報表支出** | 經 IP-9 `expense.entries` 提供者（arap `receipt_fee`、case `remit_fee_case`、payroll `bonus/payslip`…）。`quoteNo` 可空字串；`reports.py:3418` 部門篩選 `bool(quote_no) and …` ⇒ **選了部門就被排除，「全部部門」才出現**。請款單**目前刻意不進**（`reports.py:2514` 註解：避免 AR 又算 AP） |
| **應收帳齡** | `reports.py:2512` 請款單屬 AR，金額在報價單應收帳齡內；新 AP 類型不可進這裡 |
| **總帳 E 事件** | 請款單**無** gl_events。額外支出有 E11（應付）／E11b（付款）（`modules/case/gl_events.py:30–70`，`case_no=quote_no or ""`，科目 COST_PROJECT/AP/BANK）；無案件 ⇒ `case_no=""`、仍可入帳，但 **COST_PROJECT（專案成本）對非案件費用語意不對**，要新增角色／科目映射（差旅、零用金、採購各自的費用科目）＋事件碼 |
| **案件成本／結案報表** | 只聚合 `case_extra_expenses.quote_no`；無案件的不會進任何案件成本（合理），但需要另一個「非案件費用」彙總才看得到 |
| **稽核／附件** | `helpers/audit.py` 已有 `payment_request` 為單據類（ref_no＝單號）；附件目錄綁案件資料夾規則（W3 路徑綁單據）需新增資料夾類型 |

## 6. 遷移與設計限制（正式機有真實資料）
1. **不動既有 AR 請款單的語意與資料**：正式機 `payment_requests` 有活資料（已核准的客戶請款單＋PDF 匯出紀錄）。把 AP 類型塞進同表會讓 `_quote_remaining`（SUM(amount) 防超收）、案件頁 `paymentRequests`、PDF 客戶文件、AR 帳齡全都得加 `type` 分支，任何漏掉的消費端都會把 AP 算成 AR（或反之）——**風險最高的方案**。
2. `quote_no NOT NULL` 在 L0 凍結表：放寬要重建表（L0 變更，主版號級）；替代是**新表**（arap 或新模組的 migration）。
3. 模組 migration 規則：`modules/<m>/migrations/000N_*.py`、`up(conn)` 回 None／原因字串、冪等、不 commit、不 import 會演進的程式碼（守門 `tests/platform/test_module_migrations.py`）；回退相容＝只新增表／欄。
4. 建議（供 W1 設計參考，非決定）：**新增獨立單據（如 `expense_requests`，`type`＝請購／差旅／採購／零用金／一般，`quote_no` 可空，`fields_json` 由超管設定各類型欄位）**，簽核沿用 `unified_approval_flow` 與 tiered_approval，付款登記為 IP-100 的新提供者名稱（出納頁「請款待付款」頁籤自動出現），GL 新事件碼＋費用科目映射，營運報表經 `expense.entries` 新提供者（付款日列支出；無案件照列、部門篩選的行為要明訂），並在 MONEY-FLOWS §9 加一列。既有請款單原封不動（必要時 UI 上並列入口）。
5. 新增欄位可由超管編輯 ⇒ 需 `fields_json` schema 驗證（型別／必填／長度上限），不可信任前端；稽核 detail 有 2000 字上限（`helpers/audit.py` `_DETAIL_MAX`）。
6. 列車分類：新表＋API＋頁＝L2；出納頁籤沿用 IP-100 無需 L1 變更；GL 事件碼屬 W4（accounting）；若要新 mail type／核心簽核欄位＝L1（train 29 之後）。
