# 第 31 班待辦（backlog）

## 承攬商收款帳號遮蔽的剩餘範圍（來源：fix/contractor-bank-mask@f69003d0，2026-10-01）

使用者裁示：只有最高管理者看得到完整帳號，其餘一律遮蔽，**無出納例外**。第 30 班已做：承攬商列表／詳情／存簿影本、匯款申請列表／詳情／提供者形狀、簽核佇列、匯款申請 PDF 下載。**刻意留到下一班**：

1. **勞報單（payslip，payroll）乙方帳號**：`GET /api/payslips*` 回傳乙方 `bankAccountNumber`／存簿影本；勞報單 PDF（`pdf_gen._build_payslip_html`／`_payslip_passbook_html`、`generate_payslip_pdf_bytes`）印完整帳號與存簿影本頁。做法比照 `modules/subcontract/bank_mask.py`（`****末四碼`、存簿影本只給最高管理者、編輯時遮蔽值保留原值）。注意勞報單簽回流程與出納付款是否依賴完整帳號。
2. **核准後伺服器端存檔的匯款申請 PDF**：`pdf_gen._generate_contractor_voucher_pdf`（背景產生、寫入 `_get_contractor_voucher_pdf_base()` 資料夾，內含完整帳號與存簿影本，稽核留存副本）。需決定：存檔副本是否也遮蔽，或限制該資料夾的讀取權限（目前非使用者端點可達，但備份會帶走）。
3. 驗收：兩處都加「一般管理員遮蔽／最高管理者完整」測試與反向控制；`test_approval_providers` 類既有正對照改最高管理者。
