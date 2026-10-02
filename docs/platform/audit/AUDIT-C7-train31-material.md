# 第 31 包稽核（c7）：31-C 叫料審核／叫料匯款申請（作者 d7）

稽核者 hichan-c7（**不是** 31-C 作者；我是設計器與第 30 班之後數個修補的作者，不在本稽核範圍）。被稽核：`packages\20261002_134219_a5dea50c_full`（commit a5dea50c4710ba3c7c9034067b23ad95a6332b51）。
方法：讀碼＋獨立探針（`backend/modules/case/tests/test_probe_t31c_material_c7.py`，單程序、不用 `-n`）＋**真基底庫升級**（`docs/platform/audit/train31-probes/t31c_mig_probe.py`：prod/6b5d2865 的程式建庫 → a5dea50c 升級兩次）。不重跑作者的 material_* 測試，不跑全量。

## 判定：PASS — 無必修（must-fix 0）。2 項建議（should-fix）、4 項待裁示／觀察。

## PASS（有證據）
| 項目 | 證據 |
|---|---|
| **migration 0004／0005（真基底庫）** | prod/6b5d2865 建庫（155 張表；放舊叫料 3 筆〔含 1 筆已付 4,000〕、物流列、舊派發）→ 現行程式升級兩次：**155 張舊表中唯一有變動的是 `module_schema_versions`（版本記錄，預期）**；其餘逐列雜湊相同；新增 `case_material_approvals／payments／payment_lines` 三表皆空（＝全部舊單）；舊叫料 JSON 與升級前相同；`integrity_check` ok、FK 違規 0；第二次升級零變更。 |
| **收款人個資告知（伺服端強制）** | 開申請時 `payeeNoticeAcked` 缺、`false`、`"true"`（字串）、`1`、`null`、`"yes"` 六種變體 ⇒ 一律 400，**資料庫 0 列**。帶 `True` ⇒ 建立；紀錄由伺服器蓋章（`at`、`by`、`byUsername`、`noticeHash`），客戶端偽造 `ackedBy/ackedAt/ack` 全被忽略；稽核 `material_payment.privacy_notice_ack` 有。 |
| **ack 讀／補記權限** | `GET …/privacy-notice`：sa／admin 200、非案件成員 404、無財務權者 404；`POST …/ack`：admin 200、一般案件成員 403、外人 404；補記冪等（已記錄的不覆蓋，重讀紀錄逐位相同）。 |
| **個資全庫掃描** | 完整付款流程（建立→核准→出納兩次付款）後，掃整個資料庫所有文字欄位找收款帳號全碼：**只出現在 `case_material_payments.snapshot_json`**；稽核表不含帳號前段。 |
| **個資備份拆分** | `archive._daily_backup_tables()` 含 `模組-case-case_material_payments`；`_general_row` 之後一般份**不含帳號全碼、也不含戶名**；個資份（完整列）含全碼；付款明細表不含帳戶。 |
| **金額 half-up** | `material_payment.r2`：0.145→0.15、2.675→2.68、1.005→1.01、0.005→0.01、0.004→0.0、−0.145→−0.15、1234567.895→1234567.9；經出納 API 實付 2.675 ⇒ 明細存 2.68、待付剩餘 7.32。 |
| **簽核佇列與紅點** | 一般使用者（sales）簽核人：叫料單＋叫料匯款各一張待簽 ⇒ `/api/approval-queue/count`＝2、佇列兩種 type（`material_order`／`material_payment`）都在；非簽核人／外人＝0；核准一張後降為 1。 |
| **額度鎖** | 同一叫料單兩個同時建立（各 7,000／小計 10,000）：一個 200、一個 409，有效合計 7,000；退回釋出的額度被別張用掉後，原申請**重送審 ⇒ 409**（合計不超過小計）。 |
| **has_payments 守門** | 有有效申請的叫料單：實質編輯（`has_payments`）、刪除（`delete_blocked`）、取消（409）都被擋且資料不變；有付款明細的申請不可作廢（409）。 |
| **舊單基線** | 舊單（無疊加列）可開匯款申請（舊單例外）；歷史已付 4,000 凍結並計入額度：6,000 成功、再 1 元 ⇒ 409，`legacyPaid=4000`。 |
| **出納輸入驗證** | 實付負數、非數字、壞日期、負手續費 ⇒ 400 且 0 列明細。 |
| **自審禁止（多付）** | **最高管理者**自己登錄的多付，自己核可 ⇒ 403（「差額需由其他管理員審核」）；非 admin 也 403（作者測試已有）。 |
| **登記已付已關閉** | 專屬端點與 `PATCH /case-record` 直接帶 `paidStatus=paid/10000` ⇒ 叫料單維持 `pending/0`。 |

## 建議修（should-fix）
**S-1 告知紀錄寫入失敗時，申請仍被建立（伺服端強制可被靜默繞過）**。`material_payments.py` 的 `_record_payee_ack` 把例外吞成 `None`；探針把 `privacy_notice.record_purpose_ack` 換成丟例外：建立端點仍回 **200，資料庫有 1 列申請，但沒有告知紀錄**。（紀錄壞掉時，`get_ack` 讀取端會讓畫面顯示「尚未告知」，與已建立的申請矛盾。）機率低（`AcksCorrupted`／寫入失敗）但違反「每張申請都有告知紀錄」的承諾。建議 fail-closed：記錄不成功就在同一交易回滾並回 5xx／409，或建立後驗證紀錄存在。探針：`test_ack_recording_failure_must_not_leave_a_payment_without_an_ack`（刻意紅，稽核分支用）。
**S-2 出納手續費沒有上限也不進審核**。出納登錄 `fee=1e12`（實付 100）⇒ **200**，付款明細 `remit_review=''`（不進多付審核），手續費列會進營運報表的支出（`expense.entries / remit_fee_case_material`）。實付超額（1e15）會進「待審核」，手續費卻沒有同等控制；多打幾個 0 的手續費就直接變成報表支出。建議手續費設合理上限（例如不超過該筆實付或固定金額）或超過門檻進差額審核。（此為既有出納手續費機制，我沒驗證其他來源是否同樣無上限；31-C 繼承了它。）

## 待裁示／觀察
- **O-1（待裁示，同第 30 班 S-1 的叫料版）** 舊單被實質編輯回草稿：探針把「已全額付清（已付 10,000）」的舊叫料單單價改成 5,100 ⇒ 該單審核狀態變 **草稿**，同時 `paidStatus=paid／paidAmount=10000` 保留；成本口徑依 CHANGELOG（草稿不計權責成本）會少計，直到重送審核准。CHANGELOG 已預告「上線時報表數字可能變動，需公告」。建議裁示：已付清／已有付款的舊單改實質欄位是否直接禁止（改走作廢再開），而不是退回草稿。
- **O-2（待裁示）完整收款帳號端點 `payee-bank` 的角色**：`sa／admin／admin2／cashier` 皆 200；一般案件成員、外人、無財務權者 403。使用者對「承攬商帳號」的裁示是「只有最高管理者看完整」；叫料匯款需要出納付款，所以放行出納是合理的，但**任何 admin（不必有出納模組）**也 200。是否要收斂到 superadmin／持 `cashier` 模組者？
- **O-3** 唯一簽核人是申請人本人時可自簽（`self-approve as only approver → 已核准`）：與第 30 班派發同一引擎、屬流程設定責任；沒設簽核層＝送審即核准（設計如此）。
- **O-4** `GET /api/material-payments/{id}/privacy-notice` 對有財務檢視權的案件成員都 200（回 `by／at／noticeHash`，不含敏感內容）；僅供知悉。
- **O-5（未驗證）** 手續費、實付的上限是否在其他來源（額外支出、承攬匯款）有控制——我只驗了叫料來源。

## 未涵蓋
通知信與 PDF 的文字（作者測試涵蓋、未獨立重做）；案件頁畫面（`case-management.html`／`-exec.js`）的操作與版面；寫入閘在**所有**使用者可達路徑的完整性（我讀碼確認叫料相關的直接 `UPDATE quotations SET data_json` 都不接受使用者的 `caseRecord`，並實測專屬端點與 `case-record`；整份存檔／已結案變更／匯入未逐一打）；第 30 班派發審核 S-2 是否已修（不在本題範圍）。

## 執行紀錄
探針檔 36 題（含刻意紅 1 題）；單程序、不用 `-n`、跑完刪暫存。第一輪我自己的 SQL 欄位名寫錯（`amount` ⇒ `amount_approved`）與佇列回應形狀誤判，已修正後重跑，非產品問題。
