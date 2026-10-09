# M04 外包工班（subcontract）

承攬人員（個人外包）、協力廠商（承攬商）與派工、派工驗收與發票、承攬商匯款申請（簽核、匯款標記、PDF）。

## 端點

前綴 `/api/contractors`、`/api/vendor-contractors`、`/api/contractor-dispatches`、`/api/contractor-vouchers`。
權限：承攬人員 `contractor_list`（＋超級管理員）；協力廠商與派工 `procurement`／`case_manage`／`contractor_list` 任一；匯款申請另依案件存取（L1 `helpers.case_access`）與簽核名單。詳細見各檔。

## 資料（依 MODULE-GUIDE §3 分類）

| 名稱 | 類別 | 說明 |
|---|---|---|
| `contractors` | T1 | 承攬人員；身分證號、地址、聯絡方式、銀行帳戶屬 F2 欄位（`archive._F2_FIELDS`「承攬人員」） |
| `vendor_contractors` | T1 | 協力廠商；銀行帳戶一律當 F2（MODULE-GUIDE §3.2） |
| `contractor_dispatches` | T1 | 派工（品項、人員、驗收、發票） |
| `contractor_payment_vouchers` | T1 | 匯款申請；`snapshot_json` 凍結的帳戶屬 F2（`archive._F2_FIELDS`「承攬付款憑據」） |

身分證件與存摺影像存在 L1 uploads（`helpers.uploads`），不在本模組資料夾。

## 串接點

| 方向 | 串接點 | 說明 |
|---|---|---|
| 提供 | IP-1 `dispatch.row` | 派工單列序列化（M01 應計派工成本、M06 傳票摘要來源） |
| 提供 | IP-15 `dispatch.list_for_case` | M01 案件整包的承攬派工段 |
| 提供 | IP-14 `contractor_voucher.public` | M05 出納（待付、執行歷史）、M06 T100 匯出讀匯款申請 |
| 取用 | IP-17 `quotation.append_items`（M01） | 派工品項匯入草稿報價單 |

## 第 46～51 班追加（文件同步 DOCSYNC-T52；細節與版本見 CHANGELOG）

- **派發 ⇄ 勞報單連結**（1.1.23、1.1.28）：`GET/POST/DELETE /api/contractor-dispatches/{id}/payslip-links`（資料來自 M07 提供者 `payslip.dispatch_links`，M07 不在 ⇒ 明說「薪資獎金模組未安裝」）；派發頁使用者只看單號、狀態、受領人，**無金額**；連結／解除只有最高管理者（稽核 `dispatch.payslip_link／payslip_unlink`）。依「人」連動：`GET …/payslip-links` 多回 `byPerson`（派發人員名單內人員、**且連到同一案件派發**的已確認勞報單，扣掉已手動連結的；不跨案揭露）與 `unconfirmedCount`；新提供者 `dispatch.by_person`（IP-115）、`dispatch.brief`（IP-113）加 `personnelIds`／`dispatchDate`。個人外包匯款關聯勞報單時，勞報單狀態放寬為已核准／已匯出／已簽回（Q13）。
- **承攬商匯款預定付款日**（1.1.24～1.1.25）：提供者 `set_planned_pay_date` 先拿寫鎖，「沒變」的比較與寫入同一個寫交易（日期沒變 ⇒ `unchanged`，出納端點不稽核不通知）；提醒信／站內通知（`daily.check` 提供者 `subcontract_payable_due`，規則在 L1 `payable_due_core`）與行事曆「付款待辦」事件 `subcontract_voucher:<單號>` 在核准、退回、撤銷、作廢、標記匯款時 commit 之後對齊（IP-114）。
- **可見範圍（端點稽核 W1b／第 49 班）**：`GET /api/contractor-vouchers/last-paid-bank-account` 限財務角色／最高管理者（其他 403）；`GET /api/contractors/selectable` 限最高管理者、財務角色，或持有 procurement／case_manage／contractor_list／payslip 任一模組者（其他 403）。
- **旗標嚴格解析**（1.1.26～1.1.27）：`PUT /api/contractor-vouchers/settings/remit-require-payslip` 的 `enabled`（個人外包匯款強制關聯勞報單的緊急開關）與三個 `approve` 端點的 `cascade`、匯款 `hasFee` 只收真布林（字串 ⇒ 422、不寫入）。
- 守門：`tests/test_endpoint_auth_w1b_t48.py`——case／subcontract／supply 宣告前綴下的每條路由無憑證呼叫一律不得 2xx／5xx（報告 `plans/ENDPOINT-AUDIT-W1B-T48.md`）。

## 本模組不在時

- 四個前綴回 404；側欄入口隱藏（`module.json` 的 `pages`）。
- M01：案件整包的承攬派工段回 404 說明；應計派工成本少了承攬商一類並記 WARNING（IP-1）。
- M05 出納：待付款回 404 說明、頁面顯示原因；執行歷史的已匯款明細空、`contractorNotice` 與 Excel 第一列明說。
- M06：T100 預覽 `notice` 明說不含承攬商付款；傳票摘要來源只剩額外支出（IP-1）。

## 案件模組（M01）不在時

- 派工品項匯入報價單回 409：「案件模組未安裝：無法把派工品項匯入報價單」，派工本身不動。
- 匯款申請的案件存取守門：M01 沒有提供 `case.access`（IP-12）⇒ 404，表與資料在也一樣（L1 `helpers.case_access`，稽核 D CA-M1）。

## 尚未處理

- 其他模組與 L1（M01 報價單、M05／M06、M08 報表、封存、PDF、傳票附件）仍**直接讀**本模組的四張表；本模組不在時表仍在（凍結 migration），讀取不會壞。讀取連接器另開題。
- 頁面仍在 `frontend/pages/`（階段 C 由 B 搬）。
- ~~承攬人員的個資告知紀錄仍存在 L1 設定鍵 `privacy_notice_acks`……另開題。~~〔更正（主持裁示 2026-09-26，稽核 D O-1）：個資告知跨報價、網規、外包多個模組，是共用能力 ⇒ **維持 L1 共用**（`helpers/privacy_notice.py`、設定鍵 `privacy_notice_acks`），不改成本模組的表〕
