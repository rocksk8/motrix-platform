# 薪資獎金 更新紀錄

## 1.2.12 — 2026-10-10（wip/t50-int；第 50 班）
- 層外核准通知信：客戶／核准人／原簽核人／原因（自由文字）寫進信件前先 HTML 跳脫（信件模板不跳脫列值）；站內通知不變。

## 1.2.11 — 2026-10-10（wip/t51-1d-payslip-prefill；勞報單預設選取已派工、一鍵帶入）
- **勞報單表單（`payslip-form.html`）**：選了外包名冊人員後，他的派工清單**預設勾選『還沒連過這位人員勞報單』的**（連過的標『已有勞報單』不勾），每列顯示狀態色塊、單號、案件／客戶名稱（僅通過案件讀取守門者）、工作範圍、品項摘要、日期；新增『帶入勾選的派工』按鈕：只填**目前是空的**欄位——工作內容（案件名稱＋範圍）、服務起訖日（派發日期）、備註（派工單號／案號），不覆蓋已打的字、**不帶金額**。從派發頁『新增勞報單』（`?dispatchId=`）進來，若該派發名單剛好只有一位外包名冊人員 ⇒ 預選他。清單仍只在新增勞報單時出現。
- API（加法）：`GET /api/payslip-person-dispatches` 每列多 `scope`、`itemsSummary`、`projectName`、`customerName`、`caseVisible`、`linkedForThisPerson`（本人有未作廢勞報單連到該派發）；不含草稿與已取消的派發；仍不含金額。新端點 `GET /api/payslip-person-dispatches/by-dispatch?dispatch_id=`（最高管理者／勞報單模組）：派發名單裡的外包名冊人員（id、姓名）。沒有 migration、沒有權限放寬、派發頁不動。測試：`modules/payroll/tests/test_payslip_prefill_t51.py`、`tests/test_e2e_payslip_person_link_t48.py`。

## 1.2.10 — 2026-10-10（wip/t52-b5-s6-worklog）：獎金分潤『只有一位簽核人』時層外最高管理者可代核；強制稽核自行推導欄位
- `POST /api/bonus/cases/{quote_no}/approve` 多收選填 `reason`：整條簽核鏈（所有層合計）**只有一位簽核人**、操作者是最高管理者但不在簽核層內、且不是送審人 ⇒ 帶 `reason` 即可代核；沒帶 ⇒ 403 並說明要填原因。其他情況（鏈上不只一位、送審人自核、非最高管理者）維持原本的 403。
- 代核一定留痕：簽核紀錄（`approval_json.bypass`＋該簽核人格內 `bypass`）、編修紀錄（`approve_bypass`）、**稽核 `bonus.case.approve_bypass`（誰、哪張、略過哪位簽核人、原因；與核准同一個交易，寫不進去整個核准回滾）**。
- 代核後通知其他在職最高管理者（含原簽核人，不含操作者）：站內通知＋信（新信件類型 `bonus_approver_bypass`，owner payroll，預設不寄、依個人偏好）。獎金頁：核准被擋且訊息要求原因時，跳出輸入原因的視窗再送。
- 測試：`test_bonus_sole_approver_bypass_t52.py`（7 題）。

## 1.2.9 — 2026-10-09（wip/t50b-05-roundfix）：`bonus.py` 檔頭註解更正（營業利益算式的唯一來源已是 profit_rules）
- `bonus.py` 模組說明的過時註解（還寫「算式只在 settlement.html」）改為第 48 班起的實況；只改註解，行為不變。

## 1.2.8 — 2026-10-10（wip/t50-int 整合修正）
- `module.json`：`api_prefixes` 補登記 `/api/payslip-person-dispatches`（勞報單人員⇄派發連動，48c；路由歸屬守門 dep_scan --check-modules）。行為不變。

## 1.2.7 — 2026-10-10（wip/t50-int；48b 獎金用語跟進營業利益（s6））
- **（併入）(next) — 2026-10-09（wip/t48-oh25-s6／s3）：獎金用語跟進營業利益；bonus_case 註解改管銷分攤**
- 獎金分潤的「淨利」字樣（精算明細表、PDF、獎金頁、錯誤訊息）改稱「營業利益」；基數鍵 `netProfit` 與算式不變（仍讀精算已存值）。
- 精算明細表「管銷分攤」列標籤依該案 `summary.formulaVer`／`overheadPct` 組：無戳記＝「（報價稅前 10%）」，口徑 2＝「（直接毛利 N%）」（N 為該案存值，非寫死）。
- **（併入）(next) — 2026-10-09（wip/t49-05-bonus-cleanup）：移除舊版獎金分潤的 8 條 410 墓碑寫入端點（端點稽核 W1a，使用者裁示）；併第49班 strict-bool（W1c-P2）；併 wip/t48-oh25-s3b（s6／s3 用語跟進）；併 2026-10-09(wip/t48-payslip-person-link)**
- **（併入）(next) — 2026-10-09（wip/t48-payslip-person-link）：勞報單人員 ⇄ 派工連動；獨立稽核#3 修補（推測另存 contractor_guess_id）；migration 6 修復早期版本、確認鈕修正**
- 依「人」連動（設計 `docs/platform/plans/PAYSLIP-PERSON-LINK-T48.md`）：建立勞報單可帶 `dispatchIds`（需 `contractor_id`＝外包名冊人員；每張派發的人員名單必須含此人，否則 400 且整張不建），與勞報單同一個交易連結；手動新增／解除仍只有最高管理者。
- payroll migration 5：`payslips.contractor_guess_id`（舊單靠姓名**推測**的名冊對應，**與權威的 `contractor_id` 分開存**；金流／總帳 `gl_events`、`remit_link`、匯款受款人檢查只看 `contractor_id`，永遠讀不到推測）。回填只對「姓名恰好對到一位名冊人員、尚無 `contractor_id`、非已作廢」的舊單寫 guess；同名多位或對不到不動；**不碰 `contractor_id`、不建任何連結**；冪等；名冊表不在回 None。回滾（先做 DB 備份）：`UPDATE payslips SET contractor_guess_id=NULL`（確認過的 `contractor_id` 是人工決定，不還原）。
- payroll migration 6（修復）：早期開發版本的 migration 5 曾把推測寫進 `contractor_id`（只在開發／演練庫跑過）；本支補欄位並把 `contractor_match='unconfirmed'` 的列搬回 `contractor_guess_id`、`contractor_id` 還原 NULL（冪等；全新庫不動）。
- 新端點：`GET /api/payslip-person-dispatches?contractor_id=`（勞報單表單勾選用，無金額）、`POST /api/payslips/{slip_no}/confirm-contractor`（最高管理者把 guess 升格成 `contractor_id`；已簽回／已付款／已作廢的單不給確認，單一條件式 UPDATE＋稽核）；`PUT`：同名重存保留推測、改受領人姓名或人工選名冊（＝確認）即清除推測；單一 `?dispatchId=` 建立路徑與 `dispatchIds` 同樣檢查人員名單；清單多回 `contractor_guess_id`。
- 提供者 `payslip.dispatch_links` 加 `payslips_for_contractors`（只回已確認對應，無金額）。頁面：`payslip-form.html` 勾選派發、`payslips.html`「身分待確認」標籤＋確認鈕。
- **（併入）(next) — 2026-10-09（wip/t49-05-bonus-cleanup）：移除舊版獎金分潤的 8 條 410 墓碑寫入端點（端點稽核 W1a，使用者裁示）；併第49班 strict-bool（W1c-P2）；併 wip/t48-oh25-s3b（s6／s3 用語跟進）；併 2026-10-09(wip/t48-payslip-person-link)；併 2026-10-09(wip/t49-strict-bool；W1c-P2 旗標嚴格解析)**

## 1.2.6 — 2026-10-09（wip/t49-05-bonus-cleanup）：移除舊版獎金分潤的 8 條 410 墓碑寫入端點（端點稽核 W1a，使用者裁示）；併第49班 strict-bool（W1c-P2）
- `api/bonus.py`：移除 `POST /api/bonus/items`、`POST /api/bonus/awards`、`POST /api/bonus/awards/{id}/submit｜approve｜reject｜mark-paid｜void｜recall`（原本一律回 410「舊的獎金分潤流程已停用」，函式本體是被 `dependencies=_GONE` 擋掉的死碼，共約 450 行）與 `_legacy_write_gone`／`_GONE`、不再用到的匯入。現在對這些路徑的 POST 回 404／405；前端沒有任何呼叫（`bonus.js` 只打 `/api/bonus/cases`）。
- 保留：舊版唯讀端點（`GET /api/bonus/items｜base/{q}｜awards｜awards/{id}｜awards/plan/{q}｜awards/candidates｜awards/{id}/preview｜pdf-download`）、群組維護、`module.json` probes（皆 GET）。
- 測試：`test_bonus_legacy_retired_2026_09_24.py` 改驗「POST 已無路由（404／405，不寫任何東西）」＋路由表層級反向控制；`modules/case/tests/route_table_golden.json` 刪去那 8 筆（使用者裁示的刻意移除，其餘逐筆不變）。
- **（併入）(next) — 2026-10-09（wip/t49-strict-bool；W1c-P2 旗標嚴格解析）**
- 套用點：勞報單建立／更新 `data.contractorHasUnionInsurance`（影響扣繳／二代健保試算，字串 `"false"` 以前會被當成有工會保險）、獎金群組 `PATCH /groups/{id}/active` 的 `is_active`。旗標只收真布林（`helpers.validation.body_flag`）；JSON 字串 `"false"`／`"0"`／`""` 以前會被當成 true，現在回 422、什麼都不寫。前端本來就送真布林，行為不變。測試：`tests/test_strict_bool_sites_t49.py`。
## 1.2.5 — 2026-10-08（wip/t47-audit-fixes）：勞報單政策收緊（Q-S6 自核、Q-S9 作廢已核准；Q-S7 維持現狀）與並發防護補強（S1／S2／S3 本體已在 1.2.4）
- **Q-S6（A）**：有簽核層時，送審人也不得自行核准自己送的勞報單（`check_no_tier_self_approval`，與沒有簽核層的路徑一致）；**例外**：全公司只有這一位在職最高管理者。簽核層裡只列了送審人自己、且還有別的在職最高管理者時，這張單無法被簽過——送審人可以退回（回草稿）再改由他人簽。
- **Q-S9（A）**：作廢「已核准」的勞報單需要真正的最高管理者（持有勞報單模組但不是最高管理者者 403）；作廢「已匯出」維持原規則（模組持有者可作廢）。
- **Q-S7（B，維持現狀）**：簽核佇列詳情的可見度＝這張單簽核鏈上的人與送審人；**後來才加入的代理人、以及送審後被降級的人，仍可開啟詳情看到受領人姓名與各金額欄位**（身分證與收款帳號不在內，仍須最高管理者逐欄點擊顯示並留稽核）。這是使用者裁示的現狀，不是漏洞；若要改成每次重驗最高管理者，見 `docs/platform/plans/T47-POLICY-QUESTIONS.md`。
- 作廢：UPDATE 條件沒中（並發的簽回／付款）⇒ 409，不再回「已作廢」。
- `_SLIP_NO_RE` 結尾改 `\Z`（`$` 會放過結尾換行）；退回通知信內的原因與站內通知同樣截斷 100 字。

## 1.2.4 — 2026-10-08（wip/t46-fix-payslip-races）：勞報單狀態變更並發防護（第 46 班獨立稽核 S1／S2／S3）
- **並發防護（獨立稽核 S1／S2／S3）**：上傳簽回檔、刪簽回檔、退回簽回、退回付款的 UPDATE 都帶「讀到的狀態」條件（上傳／刪檔再帶讀到的簽回檔清單），rowcount≠1 ⇒ 409，不再把剛被付款的單蓋回已簽回／已匯出、不洗掉重新付款後的付款欄位；刪除草稿先 `BEGIN IMMEDIATE` 再讀狀態且 DELETE 帶狀態條件；建立／修改剔除前端送來的 `data.paid_via_remit`（只准匯款連結寫入）。

## 1.2.3 — 2026-10-07（wip/t46-payslip-impl）：勞報單送審流程（P1）＋出納整合（P2）＋派發連結（P3）（含 Q0 守門、複核修正、簽核佇列詳情、reveal 加固）
- 狀態新增 `待審核`、`已核准`：草稿 → 送審 → 簽核（獨立流程 `payslip_approval_flow`，簽核人只能是最高管理者）→ 已核准；退回（原因必填）回草稿；**沒設簽核層＝送審即核准**。匯出只准核准之後（草稿／待審核 409），**匯出不需要付款日**；`待審核`、`已核准` 鎖定（不可改、不可刪）；已核准（未匯出）也可作廢（原因必填）。
- 新端點 `POST /api/payslips/{no}/submit｜approve｜reject`（`api/payslip_approval.py`）；新提供者 `approval.queue_items`／`payroll_payslip`（待我簽核佇列，不含金額、受領人、身分資料）；單據類型 `payslip` 登記（簽核設定頁多一列，不併統一流程）。
- 通知（`payslip_notify.py`，6 種信件類型、站內通知帶連結）：待審核／輪到您審核／已核准（送審人）／已退回／已核准待付款（財務，站內＋群組信）／已付款；主旨寫結果；**不含金額與受領人姓名**；自核不寄給自己。
- **安全修正**：`POST /api/payslips`、`PUT /api/payslips/{no}` 不再採用前端送來的 `data.status`（原本可把單據直接寫成已付款）；狀態只由專用端點改。
- migration v4：`payslips` 加 `approval_json`／`planned_pay_date`／`approved_at`／`approved_by`、新表 `payslip_dispatch_links`（P3 使用）。舊列不變。**回滾缺口**（Q11 已裁示接受）：舊碼不認得 `待審核／已核准`，回滾前先處理這兩種狀態的勞報單。
- 行為變更：既有 `草稿` 要多按一次「送審」才能匯出（沒設簽核層＝一鍵核准）。
- **P2 出納整合**：新提供者 `payables.pending`／`payroll_payslip`（`payslip_payables.py`）——已核准／已匯出／已簽回且未付款的勞報單進出納「待付款申請」；**已核准即可付款**（Q4：簽回檔與匯出都變選填；舊的已簽回列行為不變）；付款唯一實作 `mark_payslip_paid`（勞報單 `mark-paid` 與出納 IP-100 共用；傳票單號必填並驗證）；`unpay` 改為退回付款前最近的狀態（有簽回檔＝已簽回；匯出過＝已匯出；否則已核准）；預定付款日 `planned_pay_date`（出納可改，不進行事曆）；清單不含身分證／地址／電話／銀行帳號。付款後通知送審人（不含金額）。
- **權限變更（Q1，使用者裁示）**：勞報單 `mark-paid`／`unpay`、簽回檔檢視、出納頁勞報單清單由「最高管理者或具 cashier 模組勾選」改為「**財務角色或最高管理者**」；只勾 cashier 模組的一般帳號不再能付款或看簽回檔。
- **簽核佇列詳情（使用者 2026-10-07 裁示：詳情顯示完整內容含身分證字號與收款帳號）**：新提供者 `approval.detail`／`payslip`；身分證與帳號**不在提供者內容、清單、角標、信件、站內通知裡**，詳情由使用者**點欄位旁的「顯示」才取該欄位**：`GET /api/payslips/{no}/approval-reveal?field=idNumber|bank|bankAccountNumber`（真正的最高管理者＋`can_see_full`＋能開該詳情；只限待審核；**稽核先寫、寫不進去 ⇒ 500 不回值**；每次點擊一筆稽核 `payslip.approval_reveal`，不含值；每人每分鐘 30 次；`Cache-Control: no-store`；關閉抽屜即清除）取值。**複核 H1**：`_require_user(module=…)` 會放行持有勞報單模組的非最高管理者，reveal 與簽核／退回改為明確要求 `role==superadmin`；詳情存取＝簽核鏈上的人、送審人、最高管理者（`caseless`）。
- **總帳（使用者裁示 B）**：認列時點維持已簽回／已付款（不改程式）；取消付款允許，已過帳應計會產生沖回草稿，由會計審。
- **既有草稿**：上線時已存在的草稿也走新流程（送審 → 核准後才能匯出）。
- **權限（使用者裁示）**：`POST /api/payslips/{no}/submit` 只准真正的最高管理者；持有勞報單模組的非最高管理者送審一律 403（建立／匯出等既有端點不變）。代理人規則不變。測試：`test_module_holder_cannot_submit_approve_or_reject_only_true_superadmin`。
- 複核修正：送審即核准只在送審人是最高管理者且沒設簽核層時成立（否則待審核，無層簽核路徑不可自核）；簽核當下再確認操作者是最高管理者；刪除草稿時一併刪派發連結。總帳（E06）影響的選項與建議見 `docs/platform/plans/PAYSLIP-LEDGER-OPTIONS-T46.md`（**待裁示，程式未改**；現況由 `test_ledger_payslip_approval_pin_t46` 釘住）。
- **P3 派發 ⇄ 勞報單雙向連結**：新表 `payslip_dispatch_links`（一派發對多勞報單、一勞報單對多派發）；勞報單頁「來源派發」區塊（`GET/POST/DELETE /api/payslips/{no}/dispatch-links`，建立勞報單時可選填 `dispatchId` 與勞報單同一交易）；提供者 `payslip.dispatch_links`（派發頁用，**只回單號、狀態、受領人姓名、開單日期，無金額**）；已付款（含經匯款單付款）不可解除；作廢保留並標已作廢。
- **Q13**：`remit_link`（匯款單關聯勞報單）由「須已簽回」放寬為已核准／已匯出／已簽回；取消匯款退回付款前最近的狀態。

## 1.2.2 — 2026-10-08（fix/t45-audit-followups）：勞報單 data_json 不留前端送來的 status（第 45 班稽核 S5）
- 建立與修改都把請求 `data.status` 移除後才存 `data_json`；狀態欄位本來就只由專用端點改，這裡讓 `GET` 的 `data.status` 也不會顯示被偽造的值。

## 1.2.1 — 2026-10-07（wip/t45-payslip-status-fix）：勞報單狀態不再由前端指定（快修）
- `POST /api/payslips` 一律建成草稿；`PUT /api/payslips/{no}` 不採用請求裡的 `data.status`（沿用資料庫現值）。原本最高管理者可在請求中直接把狀態寫成已簽回／已付款，繞過匯出→簽回→出納付款的流程（已簽回的單據會進出納待付款與總帳應付分錄）。狀態只由匯出／簽回／付款／作廢等專用端點改變。
- 測試：`modules/payroll/tests/test_payslip_status_not_client_controlled_2026_10_07.py`（含反向控制：還原修正即紅）。

## 1.2.0 — 2026-10-06（wip/t44-bonus-mail）：獎金分潤核准／退回通知送審人（信＋站內）
- 新 `bonus_notify.py`：信件類型 `bonus_approved`（「獎金分潤核准（送審人）」，簽核類、owner＝payroll，自動併入個人通知偏好）；簽核完成進入「待發放」時寄給送審人（`approval_json.requestedBy`），主旨與事由同一句「獎金分潤 {單號} 已核准」。**信內不放金額**（只有單號與客戶）。送審人就是簽核的人（唯一最高管理者自簽）⇒ 不寄給自己；寄信例外只記 log，不影響簽核。
- `api/bonus.py`：`_notify_after(quote_no, status, by)` 在待發放時呼叫 `fire_approved`（之前送審人收不到任何結果）。
- 新信件類型 `bonus_returned`（「獎金分潤退回（送審人）」）：駁回（待審核）與退回（待發放等）都回草稿，原本沒人收到信；現在送審人收到「獎金分潤 {單號} 已退回」（附原因、不含金額）＋站內通知。`_back_to_draft` 回傳（送審人, 客戶）供 commit 後通知用。連結改用 `urllib.parse.quote` 編碼單號；信的連結組法同 `case/material_notify._page`。
- 站內通知（`type=bonus_approved`，含單號＋連結 `bonus.html?q=`，不含金額；以 `_approved` 結尾 ⇒ L1 去重）：與信互不依賴；`link=` 參數由 t44-inapp-bell 提供（同班整合後必有）。
- 測試：`tests/test_bonus_approved_mail_2026_10_06.py`（9 題；信的突變 4/4 轉紅，站內通知＋退回信突變待補）。

## 1.1.24 — 2026-10-06（wip/t44-settle-terms）：`bank-account.html` 提示「請款或報銷」→「支出申請或報銷」（只改畫面文字）

## 1.1.23 — 2026-10-05（wip/t42-finance-role）：財務角色
- 獎金金額讀取端點（基數、預覽、分潤單預覽、PDF）改由「財務」角色決定；「產生」維持現狀；發放通知收件人改為財務角色＋superadmin。

## 1.1.22 — 2026-10-04（wip/t38-case-be）：獎金分潤 PDF 精算明細的派發併入列
- 精算明細表在 `summary.dispatchAbsorbedTotal > 0`（承攬商派發被採用的品項吸收）時，於「承攬商派發成本」下多印一列「已併入品項實際成本（承攬商派發，不重複計）」，分項加總＝實際總成本；`SETTLEMENT_ROWS` 11 列與標籤不動，沒有這個鍵／為 0 的歷史精算完全不變。

## 1.1.21 — 2026-10-02 09:14（wip/t32-prpo-s1-2e）：獎金分潤 PDF 精算明細的採購單列（32-S5 追補）
- 精算明細表（固定 11 列，規格 BN11）在 `summary.itemPoUnadopted > 0` 時於「品項實際成本」下多印一列「採購單（品項尚未採用）」，分項加總＝實際總成本；沒有該鍵或為 0 的歷史精算輸出逐字不變。

## 1.1.20 — 2026-10-01（wip/t31-payslip-mask-a3：勞報單收款帳號遮蔽，稽核 F1）
- ⚠️ 行為變更（使用者裁示：只有最高管理者看得到完整帳號，沒有例外）：`GET /api/payslips/{no}` 對非最高管理者（持 payslip 模組）回 `data.bankAccountNumber`＝`****末四碼`＋`bankMasked=true`；`pdf-download` 的 PDF 文字只有末四碼、不帶存簿影本；匯出存檔（F2 法定紀錄）仍是完整版（不論誰按匯出），存檔讀取（`/archive/{idx}`）對非最高管理者改回傳遮蔽的重新產生版。
- 寫入：遮蔽值原樣送回 ⇒ 沿用舊單的帳號；沒有舊值可沿用 ⇒ 400；非最高管理者建單／改單沒有帳號時，伺服器從外包名冊取值填入（真值不經過前端）。新增 `payslip_bank.py`（規則同 subcontract/bank_mask.py，模組之間不互相 import，測試逐案對照）；勞報單表單在帳號為遮蔽值時顯示「僅最高管理者可見完整帳號」。

## 1.1.19 — 2026-10-01（暫用號，列車取號；fix/t29-w2）員工收款帳號：寫入端點的稽核改由端點本體呼叫
- `PUT /api/me/bank-account`、`PUT /api/bank-accounts/{user_id}`：稽核（`user.bank_account.update`）原本藏在內部 helper `_save` 裡，寫入端點稽核守門（`test_write_endpoints_are_audited`，只認端點本體直接呼叫 `_audit`）判為沒稽核而擋下全量測試；改成端點自己呼叫 `_audit`。稽核內容照舊（欄位、前後**末四碼**、byAdmin），另加 `userId`、`changedBy`；**不含帳號全碼與戶名**；沒有變更（noop）不寫稽核。下游效應（R1）：只多兩個稽核欄位，API 回應與資料不變。

## 1.1.18 — 2026-10-01（暫用號，列車取號；fix/contractor-bank-mask-2）
- 勞報單頁（`payslip-form.html`）從外包名冊挑人時不再帶入遮蔽的帳號（`****末四碼`，非最高管理者從名冊拿到的值），避免存成假帳號；留空由有權限者補。勞報單 API／PDF 的帳號遮蔽仍在 TRAIN31 backlog。

## 1.1.17 — 2026-10-01（wip/w1-attach-p3-a3：附件目錄 P3）
- 附件目錄 P3：`_PayrollCatalog` 加 `search`／`count`（勞報單簽回檔；權限＝最高管理者或出納模組，不符一筆都不列）。

## 1.1.16 — 2026-10-01（暫用號，列車取號；wip/w3-bank-profile）
- 員工收款帳號（A2 收款人，使用者 2026-10-01）：migration 0003 新增 `user_bank_accounts`（每人一個有效帳戶、舊的留歷史）；`/api/me/bank-account`（本人）、`/api/bank-accounts*`（超級管理員／財務維護；出納查看）；頁面 `bank-account.html`；遮蔽：本人完整、有資格者要 `reveal=1` 才回完整並寫稽核、其他人只見末四碼；提供者 `payee.bank_profile`（IP-BK1）。只新增表，舊程式碼不讀它（回滾相容）。

## 1.1.15 — 2026-10-01（暫用號，列車取號；wip/w2-bonus-correction-3：列車 28 紅燈修正）
- 獎金更正單：寫入交易改用 `core.txn.begin_write`（不再自己 `BEGIN IMMEDIATE`）；沖轉傳票呼叫 `voucher.draft` 改明列關鍵字（不用 `**`）；更正單頁的狀態篩選標 `class="filter"`。
- 文件：`case_read_scope.json` 歸類更正單的兩條讀取路徑（`list_corrections`、`current_amounts`＝own_rule）；`money_flows.json`／MONEY-FLOWS.md 登記 E8b（IP-9 `bonus_correction`）；三種信件類型加進個人通知設定（`notification_prefs`）。行為不變。

## 1.1.14 — 2026-10-01（列車 28 整合：獎金更正單頁防重複初始化）
- 內部：`bonus-corrections.html` 補 `_initDone` 守衛（Alpine 會自動呼叫 `init()`，`<body>` 又寫 `x-init`，不守衛會重複打 API）；行為不變。

## 1.1.13 — 2026-09-30（暫用號，列車取號；wip/w2-bonus-correction：獎金更正單）
沖轉改用總帳 `voucher.draft(reverses_voucher_id=…)`（連續更正時沖轉前一次的重開傳票；總帳拒絕時沖轉與重開都不開、畫面寫原因）；追回＝「其他應收款」傳票（設定鍵 bonus_corr_clawback_receivable_code，預設 1213），標「追回處理方式待確認」。
新增獎金更正單（已發放獎金的事後更正）：migration 0002（bonus_corrections／bonus_correction_log）、/api/bonus/corrections、bonus-corrections.html、簽核佇列項目、IP-9 expense.entries（bonus_correction）、IP-8 補發列；核准開沖轉＋重開應付傳票草稿、出納補發。

## 1.1.12 — 2026-09-30（暫用號，列車取號；wip/w2-money-guards：金流寫入連動修補（MONEY-FLOWS §9 L5/L11/L12））
- L5：經承攬商匯款單付款（`paid_via_remit`）的勞報單，營運報表支出只列代扣部分（gross − net），匯款單實付已由承攬商支出計入，不再雙計。

## 1.1.11 — 2026-09-30（暫用號，列車取號；W4 寫入串接缺口 L1／L2／L6／L8／L9／L10）
- L6：已付款勞報單的付款事件 E06b——出納填的傳票號指向有效的手工傳票（存在、未作廢、不是系統產生）時不再重複產生（notice 說明）；應付事件 E06 照常。

## 1.1.10 — 2026-09-30（暫用號，列車取號；wip/w2-open-bind：安全審查 W3 sibling gap）
- 勞報單簽回檔 metadata 的 `ext` 必須在允許集合（.pdf／.jpg／.jpeg／.png），不合法 ⇒ 不拼進路徑（讀取端點 400、附件目錄 404）。

## 1.1.9 — 2026-09-30（暫用號，列車取號；wip/w1-menu-split 選單拆分）
- 選單：獎金分潤在「財務會計」群組 order 50→90（排在報表設定之後，避開與會計期間與結帳同為 50）；perm 不變。

## 1.1.8 — 2026-09-30（暫用號，列車取號；wip/w2-upload-magic：上傳檔頭檢查）
- 勞報單簽回檔上傳（`POST /api/payslips/{no}/signed-files`）在副檔名檢查之後呼叫 L1 `_check_upload_magic`（檔頭與副檔名不符 ⇒ 400＋稽核）；單據狀態、大小、空檔檢查不變。

## 1.1.7 — 2026-09-30（暫用號，列車取號；wip/w2-attach-p2：附件目錄 P2）
- 新增 `attachments.py::_PayrollCatalog`（`attachments.catalog`／`payroll`，IP-105）：勞報單簽回檔開檔（實體檔在封存目錄，宣告 `ROOTS`）；權限＝superadmin 或出納（同簽回檔讀取端點）。

## 1.1.6 — 2026-09-30（暫用號，列車取號；W4 總帳 C6／扣繳補齊）
- 獎金發放事件 E07b（native）多帶 `meta.withholding`／`wh_prefix`（發放當下的每人代扣所得稅與補充保費快照），供總帳扣繳清單；作廢的發放傳票也照送，讓總帳移除未繳庫的列。無 migration。

## 1.1.5 — 2026-09-30（暫用號，列車取號；W4 總帳 R12 畫面）
- `payslip.remit`（IP-105，原暫用 IP-104 與 sec-p0 撞號）新增 `candidates(conn, contractor_id)`：列出該受款人已簽回、未付款的勞報單供匯款單挑選。

## 1.1.4 — 2026-09-30（暫用號，列車取號；W4 總帳 R12）
- 新增提供者 `payslip.remit`（IP-105）：承攬商匯款單驗證、標記、退回勞報單付款；由匯款單付款的勞報單不可單獨 unpay（409，請到匯款單取消），總帳不再另產生其 E06b。無 migration（沿用 data_json.paid_via_remit）。

## 1.1.3 — 2026-09-30（暫用號，列車取號；W4 總帳 C3b）
- 獎金核准應付／發放傳票開立時帶 `origin`（bonus_accrual／bonus_payment，經 `voucher.draft` 可選參數）；`gl.events` 新增獎金事件 E07a／E07b（mode=native，登記既有傳票，不重複產生）。無 migration、無新欄位。

## 1.1.2 — 2026-09-30（暫用號，列車取號；W4 總帳 C3）
- 新增提供者 `gl.events`（IP-GL1）：勞報單應付（E06，已簽回／已付款，依勞報日或簽回日）與付款（E06b，依付款日）事件，供 M06 總帳引擎產生傳票草稿；唯讀、不寫資料、不改欄位；不帶身分證字號。

## 1.1.1 — 2026-09-30（暫用號，列車取號；wip/w1-file-preview 共用檔案預覽 P1）
- 勞報單頁簽回檔改用 L1 共用預覽元件（頁內預覽，同一張勞報單的簽回檔可 ◀ ▶ 切換），不再 `window.open(blob)`。

## 1.1.0 — 2026-09-29（暫用號，列車取號；wip/payslip-void-signed）
- 勞報單作廢（新功能）：`POST /api/payslips/{單號}/void`，只准從「已匯出」、原因必填，終結狀態（不可改／刪／再匯出）；PDF 對已作廢單加斜向「已作廢」浮水印與頂端紅色橫幅（作廢時間、人、原因；`pdf_gen._payslip_apply_void_mark`，版型沒有 <body> 也不漏）。
- 勞報單簽回（新功能）：上傳對方簽回檔 `POST /api/payslips/{單號}/signed-files`（已匯出 → 已簽回；pdf／jpg／png、單檔 20MB），實體檔放勞報單存檔目錄（F2，鏡像流程照走）；讀取 `GET …/signed-files/{id}`（最高管理者或出納）；`DELETE` 只准已簽回、刪光退回已匯出；`POST …/unsign` 退回簽回（才可作廢）。
- 出納付款（新功能）：`POST /api/payslips/{單號}/mark-paid`（最高管理者或 cashier 模組；已簽回 → 已付款；付款日期 YYYY-MM-DD、傳票單號經 M06 `voucher.by_no` 驗證存在且未作廢；會計模組不在 ⇒ 拒絕並說明），`POST …/unpay` 退回付款。
- 新增提供者 IP-103 `payslip.payables`（出納頁待付款，只回付款需要的欄位、不含 F2 個資）與 IP-9 `expense.entries`（名稱 `payslip`：已付款者依付款日期歸月、取應付總額，類別「勞報單」）。
- 狀態鎖：已匯出／已簽回／已付款／已作廢一律不可修改、刪除；補印（再匯出）不會把已簽回／已付款洗回已匯出。
- 首個模組自有 migration：`migrations/0001_payslip_void_signed_paid.py`（payslips 加 10 欄，只新增、冪等、表不在回原因字串）。⚠ 模組更新包（P7）拒收帶 migrations 的模組 ⇒ 這一版走完整部署包。

## 1.0.8 — 2026-09-28（暫用號，列車取號；E4 wip/e-company-gate-impl 第三段）
- 本公司資料設定閘門第二道（COMPANY-SETUP-GATE §5；D CG5-M1）：勞報單 PDF 下載端點：`except Exception` 前先 `except HTTPException: raise`；勞報單視圖（L1）先驗本公司已設定（Q4：單據上手改的公司欄位保留）

## 1.0.7 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`payslips.html`、`payslip-form.html`、`bonus.html`

## 1.0.6 — 2026-09-27（c-approval-l1-4，稽核 D QJ-M1；列車取號）
- 待簽佇列提供者：簽核 JSON 存在獨立欄位的單（`approval_json`／`change_approval_json`）改經 L1 `approval_raw_of`：解析不了 ⇒ 跳過那一筆＋ERROR（原本 `tier_fields` 把壞 JSON 吞成 {} ⇒ 列給每個 superadmin、計角標，核准時才丟例外；稽核 D QJ-M1）

## 1.0.5 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.3，列車取號）
- 待我簽核（M01-PLAN §3-7）：新增 `bonus_queue.py`，提供 `approval.queue_items`（獎金分潤單 `bonus_award`、案件獎金分潤 `bonus_case_award`，欄位同原 M01 佇列）；M01 佇列與角標不再直讀 `bonus_awards`／`bonus_case_awards`。案件獎金的客戶與案名不再 JOIN M01 的 `quotations`，改由 M01 彙整端依 `linkedQuoteNo` 補

## 1.0.4 — 2026-09-26〔稽核 X C4-S5：c-probes 先上第八班、用了 1.0.3 ⇒ 本段改 1.0.4〕
- D7 演練：`module.json` 宣告 `provides.probes`（`/api/payslips`、`/api/tax-rules`、`/api/bonus/awards`、`/api/bonus/items`）——純讀的 GET、在本模組前綴下、模組在時回 200（守門 `tests/platform/test_product_drill_probes.py`、`test_probe_side_effects.py`：不寫表、不寄信、不排程、不把回應值寫進 log）
- 選單宣告搬進本模組：`payslips.html`、`bonus.html` 的 `pages[].menu`（原寫在 L1 的 `core/menu_l1.json`；group／order／perm／badge 原值照搬）。階段 C／C4（主持裁示 A）：本模組不在時它的入口隨宣告一起消失，不再靠前端寫死的頁面⇒模組對照表；版號與 c-probes／h-probes 交會，列車取號

## 1.0.2 — 2026-09-26
- 規格編號隨模組走：`BN1`～`BN18`、`QS1a` 的條件（原在 STATE.md）與 `BN1`～`BN19`、`QS1a` 的範圍（原在 SCOPE.md）移進本模組 `SPEC.md`；`AC1`／`BN17` 的撞名登記改在本模組 `## 登記`（反向控制：模組不在時這些編號變成「沒有題」與「未宣告」）
- 勞報單稅額純函式題（`TestCalc`，9 題）自 `tests/test_core.py` 拆進本模組 `tests/test_payslip_calc.py`：模組層 import 讓本模組不在時整檔收集中斷（不帶 --continue-on-collection-errors 的反向控制抓到）
- 勞報單的個資告知端點登記 `api_module: payroll`（`docs/platform/pii_forms.json`）：本模組不在時不比對端點，告知區塊照驗

## 1.0.1 — 2026-09-26
- 反向控制（刪掉 modules/payroll）抓到 204 題綁著本模組 ⇒ 需要本模組的題搬進 `modules/payroll/tests/`（整檔 41、從 9 個混合檔拆出）；`payslip_seq` 分類改 T3（編號計數，本來就在備份排除清單）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/payslips.py`、`routers/bonus.py`、`helpers/bonus*.py`（6 支）搬入 `modules/payroll/`（PLAYBOOK §B；兩支 router 放 `api/`，CORE-SPEC §3）；由載入器掛載
- 提供者改由 `ModuleSpec.providers` 宣告：IP-8 `bonus.payouts`、IP-9 `expense.entries`、IP-16 `bonus.module_status`
- 不再依賴 M06：獎金分潤單的版面元件改用 L1（簽核格顯示名稱、公司抬頭、HTML→PDF、金額格式）——會計模組不在時照樣能預覽與匯出
