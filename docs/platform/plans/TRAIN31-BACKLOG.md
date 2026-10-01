# 第 31 班待辦（backlog）

## 承攬商收款帳號遮蔽的剩餘範圍（來源：fix/contractor-bank-mask@f69003d0，2026-10-01）

使用者裁示：只有最高管理者看得到完整帳號，其餘一律遮蔽，**無出納例外**。第 30 班已做：承攬商列表／詳情／存簿影本、匯款申請列表／詳情／提供者形狀、簽核佇列、匯款申請 PDF 下載。**刻意留到下一班**：

1. **勞報單（payslip，payroll）乙方帳號**：`GET /api/payslips*` 回傳乙方 `bankAccountNumber`／存簿影本；勞報單 PDF（`pdf_gen._build_payslip_html`／`_payslip_passbook_html`、`generate_payslip_pdf_bytes`）印完整帳號與存簿影本頁。做法比照 `modules/subcontract/bank_mask.py`（`****末四碼`、存簿影本只給最高管理者、編輯時遮蔽值保留原值）。注意勞報單簽回流程與出納付款是否依賴完整帳號。
2. **核准後伺服器端存檔的匯款申請 PDF**：`pdf_gen._generate_contractor_voucher_pdf`（背景產生、寫入 `_get_contractor_voucher_pdf_base()` 資料夾，內含完整帳號與存簿影本，稽核留存副本）。需決定：存檔副本是否也遮蔽，或限制該資料夾的讀取權限（目前非使用者端點可達，但備份會帶走）。
3. 驗收：兩處都加「一般管理員遮蔽／最高管理者完整」測試與反向控制；`test_approval_providers` 類既有正對照改最高管理者。

## 第 31 班主軸（使用者 2026-10-01：以下為主要功能）

| 項目 | 現況 | 前置 |
|---|---|---|
| 固定資產 C6 | `wip/w4-gl-c6`（16af580e）有實作：卡片、折舊、E13a/E13b、對帳、API、頁籤；基底舊、未跑完整閘門 | rebase 到 platform；跑 pre_train_check |
| 建構器分頁掛載 B | 規格 `BUILDER-ATTACH-EXISTING-MODULE-SPEC.md`；需 module.json 掛載點宣告＋權限 | 使用者定先掛哪頁（建議「我的工作」） |
| 401 媒體檔（附件六 112 欄） | 規格已查：`TAX401-RESEARCH-20261001.md`（注意附件五＝進銷項明細、附件七＝縣市代碼，舊文件寫反） | 公司登記資料（稅籍編號等） |
| 401 公式 113–115 | 僅有 403 表轉載推定，**未經會計確認** | 會計師對照 401 實際表單確認＋取整＋108 取 115 或 112 |
| 總帳開帳 | 程式面等期初資料 | 會計師期初試算表 |

## 其他待辦
- 時鐘守門 `wip/clock-gates-2`（596f9ae0）：先修 4 個檔的收集期日期呼叫（analytics test_e2e_ledger_diff_tab、case test_expense_forms／test_expense_void、tests/test_e2e_expense_chain_a2）再收。
- 登入「待簽核」通知：其他單據流程（出貨、付款、發票、承攬、完工、額外支出、自訂模組）簽核後仍未把自己的通知標已讀（彈窗已免疫，僅通知中心未讀數）。
- 時鐘守門、去識別化 prodroot（wip/w3-prodroot-2）、`/api/expenses` 別名（可選）。
- 殘留風險：結算頁信任前端送來的合計；`users.email/phone` 不在個資備份。
- 簽核角標／登入橫幅的「待我簽核」數字只算「當層第一位未簽的人」（A29-B Q6，使用者已接受本班不改）：後端 `routers/approval_queue.py::_counts_for_me`（約 149–160 行）目前算當層**任一**未簽核人，但簽核本身是循序（`approve` 端點與前端 `canApprove`），同層第二位會看到「1 件待您簽核」卻按不下去（探針：tier [x,y]，y 的 `/count`＝1、y 核准＝403「請等待 x 先完成簽核」）。修法＝只算當層第一位未簽者；例外：系統關卡（`tiers[cur].system`）與 `custom_module_def` 同層任一人可簽、且後者排除申請人（對齊前端 `canApprove`）。影響：角標與橫幅數字變小（正確）；測試＝同層雙簽核人兩人各打 `/count`（x=1,y=0）＋核准後 y 變 1＋系統關卡／自訂模組定義例外＋突變（改回 any）。探針檔 `audit/train29-b` 的 `backend/tests/_probes/test_probe_q5_q6.py`。
- 上傳路徑守衛（同類第二階，需 DB 寫入才能利用）：`helpers/uploads.py:215`（delete_document_file）、`modules/case/api/quotations.py:2902`（_cleanup_staged_files）、`:2922-2927`（_move_staged_files src/dest）、`:5290`（案件更新留言刪檔）、`modules/crm/api.py:1011`（開發紀錄刪檔）仍用 `os.path.join(UPLOADS_ROOT, path)`。第 29 班只修 `custom_files._remove_physical` 與 `custom_module_delete`（fix/upload-path-guard）。做法：L1 uploads 加共用 `safe_upload_path`（拒絕空／絕對／`:`／`..`／`\`段、realpath+commonpath 須在 UPLOADS_ROOT 內且非根本身），一次替換全部；每處加「外部檔案不被刪」測試＋反向對照。
- 勞報單後端未驗證帳號欄位（自由 dict）：應拒絕看起來是遮罩值（含 `****`）的銀行帳號，避免遮罩值被存進勞報單（fix/contractor-bank-mask-2 已在前端 payslip-form.html 避免，後端仍待）。
- 既有紅：`tests/test_e2e_pdf_unapproved_more_2026_09_30.py::test_quotation[False]`（點擊逾時）在 platform d4c43792 未改動樹上同樣失敗（a3 驗證）；非第 29 班引入，下班查根因。
- 出貨內容衛生（d7 檢視第29班包）：`docs/platform/plans/HANDOFF-*`、expense-a2 設計文件含本機路徑與簽章金鑰「路徑」字串（無金鑰內容）隨包出貨；`tools/platform/*`（34 檔，第28班起就隨包）也在酬載。下班評估把 plans/HANDOFF-*、expense-a2/ 加入 backend/export_ignore.json，並決定 tools/platform 是否該隨包。
