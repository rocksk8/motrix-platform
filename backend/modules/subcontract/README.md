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
