# 已知個資缺口（尚未處理，待使用者裁示）

> 2026-10-01（W3）。員工收款帳號（`user_bank_accounts`，payroll 0003）已做遮蔽與稽核；下列是**既有**的另一處收款帳號資料，
> 目前**未**遮蔽。遮蔽會改變現有「承攬商管理」使用者的可見資料，屬行為變更，第 29 班不做，待使用者裁示。

## 承攬商收款帳號（`vendor_contractors`，M04 subcontract）

資料位置：`vendor_contractors.data_json` 的 `bankAccountName`／`bankAccountNumber`／`bankPassbookImage`，
另有欄位 `bank_code`／`bank_name`／`bank_branch`／`bank_account_name`／`bank_account_number`。

回傳完整值（未遮蔽）的端點（權限＝`procurement`／`case_manage`／`contractor_list` 任一；付款類另含 `finance`／`cashier`／`quotation`）：

| 端點 | 檔案:行 | 內容 |
|---|---|---|
| `GET /api/vendor-contractors` | `modules/subcontract/api/vendor_contractors.py:181` | 每列含戶名／帳號（`_vendor_row`，存簿影本除外） |
| `GET /api/vendor-contractors/{vid}` | 同檔 :223 | 同上 |
| `GET /api/vendor-contractors/{vid}/passbook` | 同檔 :361 | 存簿影本（base64） |
| `GET /api/contractor-vouchers`、`GET /api/contractor-vouchers/{voucher_no}` | `modules/subcontract/api/contractor_vouchers.py:228`、:254 | 匯款單快照 `bankAccountName`／`bankAccountNumber`／`bankPassbookImage`（:162） |
| `POST /api/contractor-vouchers/{voucher_no}/export` | 同檔 :707 | 匯出檔含帳號 |
| 承攬商匯出（Excel 欄位表） | `vendor_contractors.py:219` | 戶名、帳號欄 |

已涵蓋：每日備份的個資分流（`archive._F2_FIELDS["協力廠商"]`）。未涵蓋：上列讀取端點的遮蔽與「顯示完整」稽核。

建議做法（比照員工帳號）：列表只回末四碼；完整值須明確「顯示」並寫稽核（不記全碼）；出納／財務維持可見。
員工收款帳號的做法見 `modules/payroll/bank_account.py`（`mask_number`、`may_see_full`、`audit_reveal`）。
