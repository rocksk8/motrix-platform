# M07 薪資獎金（payroll）

勞務報酬單（開立、編號、扣繳與補充保費依法規參數、PDF 與個資分流存檔）與獎金分潤（項目、分組、案件獎金、簽核、送交出納、發放、扣繳與補充保費、傳票草稿）。

## 端點

前綴 `/api/payslips`、`/api/next-slip-no`、`/api/tax-rules`（勞報單，權限 key `payslip`＋超級管理員）、`/api/bonus`（獎金分潤，依角色與簽核名單）。詳細見 `api/`。

## 資料（依 MODULE-GUIDE §3 分類）

| 名稱 | 類別 | 說明 |
|---|---|---|
| `payslips`、`payslip_seq` | T1 | 勞報單與編號；身分證號、地址等屬 F2 欄位（`archive._F2_FIELDS`） |
| `bonus_items`、`bonus_item_people`、`bonus_groups`、`bonus_group_members` | T1 | 獎金項目與分組 |
| `bonus_awards`、`bonus_award_lines`、`bonus_award_edit_log` | T1 | 獎金分潤單 |
| `bonus_case_awards`、`bonus_case_award_lines`、`bonus_case_award_edit_log` | T1 | 案件獎金 |
| 勞報單存檔（`payslip_archive_path`） | F2 | 個資，雲端走獨立的個資資料夾（`archive._mirror_pii_archives`） |

## 串接點

| 方向 | 串接點 | 說明 |
|---|---|---|
| 提供 | IP-8 `bonus.payouts` | M05 出納的獎金待發放與發放紀錄 |
| 提供 | IP-9 `expense.entries`（名稱 `bonus`） | 已發放的獎金列入營運報表與月支出（M08） |
| 提供 | IP-16 `bonus.module_status` | L1 `/api/system/bonus-module-status`（側欄、獎金頁、結案頁問「入口該不該出現」） |
| 取用 | IP-2／IP-3／IP-4（M06） | 獎金傳票草稿、會計設定、作廢草稿；M06 不在時獎金照常，頁面明說不產生傳票 |
| 取用 | IP-7 `helpers.legal_params`（L1） | 扣繳與補充保費依撥付日選版 |

## 本模組不在時

- 四個前綴回 404；側欄入口隱藏（`module.json` 的 `pages`）。
- `/api/system/bonus-module-status` 回 `enabled: false`＋說明（IP-16）⇒ 入口隱藏、頁面顯示暫停。
- M05 出納頁：獎金待發放區、執行歷史與 Excel 顯示「薪資獎金模組未安裝：出納頁不顯示獎金分潤」（IP-8）。
- M08 營運報表與月支出：少了獎金這一類，**不另加提示**（IP-9：本模組不在時沒有應列而未列的支出；⚠ 曾經安裝後停用而資料還在的情況見 INTEGRATION-POINTS IP-9）。

## 尚未處理

- 其他模組與 L1（封存、報表、稽核）仍**直接讀**本模組的表；本模組不在時表仍在（凍結 migration），讀取不會壞。讀取連接器另開題。
- 頁面仍在 `frontend/pages/`（階段 C 由 B 搬）。
