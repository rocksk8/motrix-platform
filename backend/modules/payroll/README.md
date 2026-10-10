# M07 薪資獎金（payroll）

勞務報酬單（開立、編號、扣繳與補充保費依法規參數、PDF 與個資分流存檔）與獎金分潤（項目、分組、案件獎金、簽核、送交出納、發放、扣繳與補充保費、傳票草稿）。

## 端點

前綴 `/api/payslips`、`/api/payslip-person-dispatches`、`/api/next-slip-no`、`/api/tax-rules`、`/api/me`（本人收款帳號）、`/api/bank-accounts`（有資格者）（勞報單，權限 key `payslip`＋超級管理員／財務角色，細節見下方「第 46～50 班追加」）、`/api/bonus`（獎金分潤，依角色與簽核名單）。詳細見 `api/`。

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

## 第 46～50 班追加（文件同步 DOCSYNC-T52；細節與版本見 CHANGELOG 1.2.2～1.2.9）

**端點與權限（以伺服器為準，畫面只是呈現）**

| 端點 | 誰 | 說明／稽核動作 |
|---|---|---|
| `POST /api/payslips/{no}/submit｜approve｜reject`（`api/payslip_approval.py`） | **只有真正的最高管理者**（持有勞報單模組的非最高管理者一律 403） | 獨立簽核流程 `payslip_approval_flow`（簽核人只能是最高管理者；沒設簽核層＝送審即核准）；有簽核層時送審人不得自核（Q-S6；全公司只有一位在職最高管理者時例外）；退回原因必填。**第 54 班：當層排序最前的未簽核人就是送審人（或整條鏈唯一的簽核人已停用）而卡住時，另一位最高管理者（且沒在這張單簽過任何一格）可在 `approve` 帶必填 `reason` 代核**（強制稽核 `payslip.approve_bypass`、簽核紀錄留代核人／被代者／原因、通知其他最高管理者；送審人永遠不可自核）。稽核 `payslip.submit／approve／approve_bypass／reject` |
| `GET /api/payslips/{no}/approval-reveal` | 最高管理者、僅待審核單 | 簽核佇列詳情點欄位才取身分證／銀行帳號（單欄）；**每次呼叫寫稽核 `payslip.approval_reveal`（不含值）**、先寫稽核失敗即 500 不回值、每分鐘 30 次、`no-store`；不進清單／計數／信件／通知／日誌 |
| `POST /api/payslips/{no}/void` | 已核准＝最高管理者（Q-S9）；已匯出＝勞報單模組持有者（原規則） | 並發的簽回／付款使 UPDATE 沒中 ⇒ 409 |
| `POST /api/payslips/{no}/mark-paid｜unpay`、簽回檔檢視、出納頁勞報單清單 | **財務角色或最高管理者**（只勾 cashier 模組不再夠） | 付款唯一實作 `mark_payslip_paid`（傳票單號必填）；取消付款允許，已過帳應計產生沖回草稿由會計審。稽核 `payslip.unpay` |
| `GET/POST/DELETE /api/payslips/{no}/dispatch-links` | 看＝能開派發頁的人（單號、狀態、受領人姓名，**無金額**）；連結／解除＝最高管理者 | 稽核 `payslip.dispatch_link／dispatch_unlink`（承攬商端 `dispatch.payslip_link／payslip_unlink`） |
| `GET /api/payslip-person-dispatches?contractor_id=`；`POST /api/payslips/{no}/confirm-contractor` | 勞報單表單使用者（無金額）；確認＝最高管理者 | 依「人」連動：建單可帶 `dispatchIds`（每張派發人員名單必須含此人，否則 400 整張不建）。`contractor_guess_id`（姓名推測）與權威的 `contractor_id` 分開存，金流／總帳／匯款受款人檢查只讀後者。稽核 `payslip.confirm_contractor` |
| `PUT /api/payslips/{no}`、`POST /api/payslips` | 勞報單模組持有者（建立／匯出等既有權限不變） | **不採用前端送來的 `data.status`**（狀態只由專用端點改）；`data.contractorHasUnionInsurance` 只收真布林（`helpers.validation.body_flag`，字串 `"false"` ⇒ 422） |

**狀態與流程**：草稿 → 待審核 → 已核准 → 已匯出 → 已簽回 → 已付款（另有已作廢）。匯出只准核准之後且**不含付款日**；已核准即可付款（簽回檔選填）；既有草稿也走新流程。總帳認列時點維持已簽回／已付款。狀態變更（上傳／刪簽回檔、退回簽回、退回付款、作廢）的 UPDATE 都帶「讀到的狀態」條件，沒中 ⇒ 409。簽核佇列詳情可見度＝該單簽核鏈上的人與送審人（Q-S7 維持現狀：事後加入的代理人仍看得到金額，**看不到身分證與銀行帳號**）。

**獎金分潤（`/api/bonus`）**：獎金基數＝案件精算完結時凍結的**營業利益**（`summary.netProfit`，舊稱淨利；管銷分攤算式見 case 模組 README「利潤規則」）；用語全面改稱營業利益，精算明細表「管銷分攤」列標籤依該案 `formulaVer`／`overheadPct`（新口徑＝「（直接毛利 N%）」，舊＝「（報價稅前 10%）」）。舊版「獎金項目／分潤單」的 8 條寫入端點（`POST /api/bonus/items｜awards｜awards/{id}/submit｜approve｜reject｜mark-paid｜void｜recall`）已於第 49 班整個移除（原本回 410）；舊版唯讀 GET、群組維護與 `module.json` probes 保留。群組 `PATCH /groups/{id}/active` 的 `is_active` 只收真布林。

**資料**：payroll migration 4（`payslips` 加 `approval_json`／`planned_pay_date`／`approved_at`／`approved_by`、新表 `payslip_dispatch_links`）、5（`payslips.contractor_guess_id`）、6（修復早期開發版 migration 5 把推測寫進 `contractor_id` 者）；`payslips` 另有 core migration 117／118 加的作廢與簽回／付款欄位。**回滾缺口**：舊程式不認得「待審核」「已核准」，程式回滾前須先處理這兩種狀態的單。

**串接點（新增）**：提供 IP-112 `payslip.dispatch_links`（含 `payslips_for_contractors`，只回已確認對應、無金額）、`payables.pending`（名稱 `payroll_payslip`，出納待付款）、`approval.queue_items`／`approval.detail`（待我簽核佇列，不含金額與身分資料）、`payslip.payables`、`payslip.remit`；取用 IP-113 `dispatch.brief`、IP-115 `dispatch.by_person`（M04 不在時頁面明說「外包工班模組未安裝」，不影響其他功能）。6 種勞報單信件類型（待審核／輪到下一層／已核准／已退回／已核准待付款／已付款）＋站內通知帶連結，**不含金額與受領人姓名**。

## 本模組不在時

- 四個前綴回 404；側欄入口隱藏（`module.json` 的 `pages`）。
- `/api/system/bonus-module-status` 回 `enabled: false`＋說明（IP-16）⇒ 入口隱藏、頁面顯示暫停。
- M05 出納頁：獎金待發放區、執行歷史與 Excel 顯示「薪資獎金模組未安裝：出納頁不顯示獎金分潤」（IP-8）。
- M08 營運報表與月支出：少了獎金這一類，**不另加提示**（IP-9：本模組不在時沒有應列而未列的支出；⚠ 曾經安裝後停用而資料還在的情況見 INTEGRATION-POINTS IP-9）。

## 尚未處理

- 其他模組與 L1（封存、報表、稽核）仍**直接讀**本模組的表；本模組不在時表仍在（凍結 migration），讀取不會壞。讀取連接器另開題。
- 頁面仍在 `frontend/pages/`（階段 C 由 B 搬）。
