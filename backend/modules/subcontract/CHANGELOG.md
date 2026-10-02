# 外包工班 更新紀錄

## (next) — 2026-10-02 11:41（fix/t32-dispatch-s1-2e）：舊單實質編輯維持舊單（使用者裁示 S-1）
- ⚠️ 行為變更：舊單（`approval_status=''`）的**實質欄位**（承攬商、品項、人員、稅率）被編輯後，**不再**回草稿重新送審——維持舊單，成本（營運報表應計）、總帳 E04、匯款申請照舊不掉；改為①`approval_json` 記 `legacyModified`（修改人、最後時間、次數、第一次時間）②獨立稽核 `vendor.dispatch.legacy_edit`（前後金額）③`dispatch.row` 新增 `legacyModified`／`legacyModifiedAt`，畫面出現「舊單已修改」警示徽章與存檔提示。已核准的派發實質編輯仍回草稿重審（不變）；非實質欄位（備註、日期、發票）不受影響。

## 1.1.4 — 2026-10-02 07:27（fix/t32-dispatch-cancel-2e）：審核中取消派發同交易關閉待審階段（稽核 S-2）
- 修正：派發在**待審核／簽核中**（派發審核或完工審核）被取消時，`dispatch_flow.set_status` 在同一個交易內把還在審的階段關閉（`已退回`＋歷程記一筆 `cancelled`、`closedByCancel`）；已核准／已退回的階段不動；沒有在審的（草稿、舊單、已核准）取消行為不變。`/approve`、`/reject` 對已取消的派發回 409；簽核佇列提供者不列已取消的派發，待簽紅點／計數隨之消失；稽核 `vendor.dispatch.cancelled` 的 detail 帶 `closedStages`，並通知送審人（不含金額）。

## 1.1.3 — 2026-10-02 01:08（fix/t31-build2-2e）：派發佇列提供者的 type 寫成字面值
- `dispatch_approval.queue_items` 呼叫 `_queue_for` 時直接寫 `"contractor_dispatch"`／`"contractor_dispatch_completion"`（原本用常數）：佇列覆蓋檢查是靜態讀提供者原始碼找 type 字面值，用常數會在「模組已載入」的測試順序下紅（單獨跑因為類型尚未登記而假綠）；行為不變。

## 1.1.2 — 2026-10-02 00:59（fix/t31-build-2e）：派發審核的稽核包裝函式改名
- 內部：兩段審核端點共用的 `do_*` 改名 `dispatch_review_submit／approve／reject／withdraw`、`_apply_status` 改名 `dispatch_status_audited`（名稱登記進寫入端點稽核掃描器的 AUDIT_WRAPPERS，需全域唯一）；行為不變。

## 1.1.1 — 2026-10-01（wip/t31-payslip-mask-a3：稽核 G1／G2）
- `bank_mask.keep_if_masked` 刪除（死碼：各端點直接用 `is_masked_value`，沒有呼叫者）；匯款申請 PDF 補「PDF 文字層級」遮蔽測試（pypdf 抽文字；突變 `mask_bank=False` 會紅）。

## 1.1.0 — 2026-10-01 23:40（wip/t31-dispatch-approval-2e）：承攬商派發兩段審核（31-A）
- 新增：派發審核（第一段）與完工審核（第二段）——`POST /api/contractor-dispatches/{id}/submit|approve|reject|withdraw` 與 `.../completion/request|approve|reject|withdraw`；分層簽核重用 `helpers/tiered_approval`，簽核類型 `contractor_dispatch`（預設跟統一流程），沒設簽核層＝送審即核准；核准當下釘住實質欄位雜湊（`approved_hash`），之後改承攬商／品項／人員／稅率要重新送審。
- 新增：作業狀態唯一寫入口 `dispatch_flow.set_status`（靜態守門 G-D1：模組內只准它寫 `contractor_dispatches.status`）；建立一律 draft（忽略 body.status）、編輯不能改狀態、`completed` 只能由完工審核通過設定（舊單也要）、確認驗收人≠建立者（最高管理者例外並標註）、取消已核准或已進入驗收者要理由、已有匯款申請者只有最高管理者可取消、審核中不可編輯／刪除。新端點 `POST /api/contractor-dispatches/{id}/status`（卡片操作按鈕）。
- 新增：migration 0003（只加不改：15 欄與 `idx_dispatch_doc_code`／`idx_dispatch_approval`；既有列 `approval_status=''`＝舊單，不補審、行為照舊）；派發單號 `DP-YYYYMMDD-NNNN`。
- 新增：簽核佇列（`contractor_dispatch`／`contractor_dispatch_completion` 兩種 type，單號＝doc_code）、詳情、轉簽提供者；八種信件類型（`dispatch_*`，owner＝subcontract，信內不放金額）；稽核 `vendor.dispatch.<submit|approve|reject|withdraw|…>`。
- 修正（下游閘）：匯款申請另要求派發已核准（舊單照舊；既有「已驗收／完工」閘不變）；總帳 E04 只取已核准與舊單；成本檢視 `dispatch.cost_for_case` 與營運報表同一條規則（已取消／草稿／已退回不計，待審核／簽核中計入並標 `approvalPending`）。
- `dispatch.row`（IP-1）只新增鍵：`approvalStatus`／`completionStatus`／`docCode`／`legacy`／`displayStatus` 等。

## 1.0.39 — 2026-10-01（暫用號，列車取號；fix/contractor-bank-mask-2：外包名冊帳號遮蔽更正）
- 見下方前一筆的「更正」：外包名冊（`/api/contractors*`）列表／詳情／存簿影本端點（`/id-card`）／匯出一律對非最高管理者遮蔽 `****末四碼`；編輯（PUT）與匯入遇遮蔽值保留原帳號。測試 `test_contractor_roster_bank_mask_2026_10_01.py`、`test_e2e_bank_mask_roster_page_2026_10_01.py`（含反向控制）。

## 1.0.38 — 2026-10-01（暫用號，列車取號；fix/contractor-bank-mask）
- 承攬商／匯款申請收款帳號遮蔽（使用者裁示 2026-10-01：只有最高管理者看得到完整帳號）：新增 `bank_mask.py`；承攬商列表／詳情、存簿影本端點、匯款申請列表／詳情（含快照與外包人員）、IP-14 提供者形狀（無檢視者＝遮蔽）、匯款申請 PDF 下載一律 `****末四碼`、存簿影本拿掉；承攬商編輯時遮蔽值原樣送回＝保留原帳號。**更正（2026-10-01）**：外包名冊（`/api/contractors*`）守門其實放行「持 contractor_list 模組的非最高管理者」，原先判斷為「僅最高管理者」是錯的——列表／詳情／存簿影本／匯出一併改為非最高管理者遮蔽 `****末四碼`，編輯與匯入遇遮蔽值保留原帳號（`test_contractor_roster_bank_mask_2026_10_01.py`）。勞報單頁從名冊挑人不再帶入遮蔽帳號。

## 1.0.37 — 2026-10-01（wip/w1-attach-p3-a3：附件目錄 P3）
- 附件目錄 P3：`_SubcontractCatalog` 加 `search`／`count`（派工單附件、承攬商發票；權限＝`_SubcontractPathAccess.readable` 逐派工單）。

## 1.0.36 — 2026-10-01（wip/w4-acceptance-2）
- 承攬商發票進項稅額的提示統一寫『估計稅額』，並說明派工沒填稅率時以 5% 估算。⚠ 提示字串若寫壞（例：格式字串裡的裸 `%`），整個事件提供者會丟 TypeError、所有承攬商事件靜默消失（引擎只在 notices 寫『讀取失敗』）；驗收測試 `test_ledger_acceptance` 斷言每個事件來源都讀取成功。

## 1.0.35 — 2026-10-01（暫用號，列車取號；wip/w3-local-date）
- 本地日期（使用者 2026-10-01：凌晨建的單日期變前一天）：外包名冊／承攬商頁的匯出檔名日期與「今天」改用本地日期。

## 1.0.34 — 2026-09-30（wip/w1-t27fix2）
- 承攬商匯款申請的退回與撤銷核准：原因改在狀態與權限檢查之後才驗（409 不再被 400 蓋掉）。

## 1.0.33 — 2026-09-30（暫用號，列車取號；wip/w3-t27fix2）
- 匯出 PDF 姊妹的歸屬區改用常數 `_EXPORT_AREA`（不寫 module 等號字串字面量：test_module_keys_consistency 的後端掃描器會把它當權限 key）；只動寫法，行為與稽核內容不變。

## 1.0.32 — 2026-09-30（暫用號，列車取號；wip/w2-glwarn-doc：提示要說得出是哪一筆（W1 複核））
- 已入帳提示帶單號：派工改發票日「此筆（派工單 N／案件）…」、取消已匯款「此筆（匯款單 …）…」。

## 1.0.31 — 2026-09-30（暫用號，列車取號；wip/w2-open-bind：附件開檔路徑綁單據（安全審查 W3））
- 附件目錄提供者 `open()` 加路徑綁單據檢查（`helpers.uploads.upload_path_key`）：檔案路徑不在這張單據自己的資料夾 ⇒ 當作沒有這個檔。

## 1.0.30 — 2026-09-30（暫用號，列車取號；wip/w3-export-pdf）
- 匯出規則（使用者 2026-09-30）：外包名冊匯出加 PDF 姊妹（`/api/contractors/export/pdf`），每次匯出寫稽核。

## 1.0.29 — 2026-09-30（暫用號，列車取號；W4 R1 跨模組寫入註解）
- 匯款標記／取消時改動薪資模組勞報單（IP-105）的兩處寫入點加上『跨模組寫入連結』註解並登記於 MONEY-FLOWS §9（W-1）。僅註解，行為不變。

## 1.0.28 — 2026-09-30（暫用號，列車取號；wip/w2-gl-warn：已入帳來源的修改提示（MONEY-FLOWS §9 L3））
- 派工改發票日（已入帳 E04）與取消已匯款（已入帳 E05）時，回應帶 `glWarning`（非阻擋）；前端 toast。

## 1.0.27 — 2026-09-30（暫用號，列車取號；wip/w1-pdf-unapproved）
- 承攬商匯款申請：退回與撤銷核准一律要填原因；PDF 預覽未核准時有紅色警示、預覽可「退回修改」。

## 1.0.26 — 2026-09-30（暫用號，列車取號；W4 總帳 列車修補）
- 匯款單關聯勞報單的金額比對改為到分的差值比對（不用 round()，符合金額進位守門）；行為不變。

## 1.0.25 — 2026-09-30（暫用號，列車取號；W4 總帳 R12 畫面）
- R12 畫面與預設：出納頁、案件頁的『標記已匯款』視窗可為每位個人外包人員挑選勞報單（`GET /api/contractor-vouchers/{單號}/personnel-links`），顯示勞報單實付與匯款金額差異；`system_settings.remit_require_payslip` 預設改為**開啟**（緊急開關 `PUT …/settings/remit-require-payslip`，僅最高管理者、寫稽核）；連接器編號改為 IP-105。

## 1.0.24 — 2026-09-30（暫用號，列車取號；W4 總帳 R12）
- 個人外包人員 ↔ 勞報單（使用者裁示 R12）：新增 `POST /api/contractor-vouchers/{單號}/personnel-link`（快照 personnel[].payslipNo，additive、無 migration）；標記已匯款前驗證已關聯者（勞報單已簽回、受款人相符、匯款金額＝勞報單實付），`system_settings.remit_require_payslip`＝"1" 時每位個人都必須已關聯（預設關閉）；匯款成功一併把勞報單記為已付款（同一個交易），取消匯款一併退回。總帳 E05：已關聯者借『其他應付款』而非應付帳款，不再產生 E05b。

## 1.0.23 — 2026-09-30（暫用號，列車取號；wip/w2-attach-p2：附件目錄 P2）
- 新增 `attachments.py::_SubcontractCatalog`（`attachments.catalog`／`subcontract`，IP-105）：派工單附件與承攬商發票開檔；權限＝派工單單筆端點規則（同 `_SubcontractPathAccess`）。

## 1.0.22 — 2026-09-30（暫用號，列車取號；wip/cal-toggle 行事曆推送可選）
- 行事曆「包商撥款」（預設關，事件種類開關在 L1）：`paid-toggle` 標記已匯款 commit 之後推 `push_event_for_module('contractor_payout', …)`，事件日期＝匯款日期，說明含應付／實付／手續費；取消匯款不刪事件。題 `modules/subcontract/tests/test_payout_calendar_2026_09_30.py`
## 1.0.21 — 2026-09-30（暫用號，列車取號；W4 總帳 C2）
- 新增提供者 `gl.events`（IP-GL1）：承攬商發票（E04，依發票日、稅額依派工稅率估算並標 tax_estimated，會計可在總帳補登實際稅額）、匯款（E05，含手續費；實付≠應付且已核可才入帳，待審核不產生並 notice）、個人點工未關聯勞報單（E05b，標未扣繳）。唯讀、不寫資料、不改欄位。
## 1.0.20 — 2026-09-30（暫用號，列車取號；wip/sec-p0 安全修正 P0）
- 安全修正 P0：新增提供者 `uploads.path_access`／`subcontract`（IP-104，`attachments._SubcontractPathAccess`）：`contractor_dispatches/`、`contractor_dispatch_invoices/` 的附件只簽給派工單單筆端點的模組（procurement／case_manage／contractor_list／quotation）或看得到該案單據的人。原本任何登入者都拿得到簽章。

## 1.0.19 — 2026-09-30（暫用號，列車取號；N1 承攬商派工，接在 W1 之後）
- N1 稽核補修：刪除申請進簽核佇列（`approval.queue_items` 名稱 `subcontract_dispatch_file`、`approval.detail` `dispatch_file_delete`；佇列頁可直接核可／退回）；申請人不能核可／退回自己的申請；核可端點簽核人防呆
- W1 稽核補修：`paid-toggle` 標記已匯款不帶 `paid_at` ⇒ 400（不再默認今天）；待審核差額（實付≠應付）標記匯款者不能自己核可／退回（403）；手續費 `expense.entries` 帶 `pending`；`_voucher_public` 帶 remitReview
- N1 承攬商派工（暫用號，列車取號）：承攬商報價單附件刪除改為「申請刪除、要審核」（`DELETE …/files/{id}` 帶原因；簽核走案件既有簽核層級＝報價單的流程設定（預設統一流程；申請人沒有部門主管解析不出來時退回由最高管理者核可），沒設層級時由最高管理者核可，最高管理者自己申請且沒設層級才直接刪）；新增 `POST …/files/{id}/delete-approve`／`delete-reject`；核可前檔案保留、檔案帶 `deleteRequest`（畫面標「刪除待審」）；派工視窗：派工內容改大輸入框、視窗加寬置中、品項說明改多行、單位改可自行輸入（datalist）

## 1.0.18 — 2026-09-30（暫用號，列車取號；W1 wip/w1-remit-fee）
- 稽核補修（見 1.0.19 段）：日期必填 400、自己標記不能自己核可、待審核差額標示
- W1 出納匯款手續費（暫用號，列車取號）：`contractor_payment_vouchers` 加實付／手續費／差額審核欄位（本模組首支 migration v1 `0001_remit_fee`）；`paid-toggle` 收 `actualAmount`／`hasFee`／`fee`，實付≠應付 ⇒ `remit_review='pending'`（差額待審核，通知管理員），取消匯款一併清空；匯款日期不帶仍退回今天（舊契約）；提供 IP-102 `remit.reviews`（名稱 `contractor_voucher`：清單、核可／退回）、IP-9 `expense.entries`（名稱 `remit_fee_contractor`：手續費以匯款日列營運報表支出）；`GET /api/contractor-vouchers/remit-fee-total`（案件成本用）；匯款單公開形狀加 payableAmount／remitActual／remitFee／remitDiff／remitReview*（IP-14 加欄位、相容）。⚠ 帶 migrations/ 的模組目前不能用單模組更新包出貨（P7b）

## 1.0.17 — 2026-09-28（暫用號，列車取號；E4 wip/e-company-gate-impl 第三段）
- 本公司資料設定閘門第二道（COMPANY-SETUP-GATE §5；D CG5-M1）：承攬匯款申請 PDF 下載端點：`except Exception` 前先 `except HTTPException: raise`（第二道的 428 不被吞成 500）

## 1.0.16 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`contractors.html`、`vendor-contractors.html`、`contractor-voucher-approval-settings.html`

## 1.0.15 — 2026-09-27（第十三班列車取號，原暫用 1.0.12；c-queue-json，主持指派）
- 待簽佇列提供者：簽核 JSON 改用 L1 `helpers.approval_queue.approval_json_of` 在 Python 逐筆解析（原本 SQL `json_extract(data_json,'$.approval')` 遇到一筆 malformed JSON ⇒ 整個查詢丟例外 ⇒ 這一類待簽全部靜默消失）；壞的那一筆跳過並記 ERROR（寫單號、不寫內容）

## 1.0.14 — 2026-09-27（第十三班列車取號，原暫用 1.0.13；稽核 D 建議，wip/b-drill-absent404-2）
- `pages` 補 `contractor-voucher-approval-settings.html`（不帶 menu，不進側欄）：modules.json 把它歸 M04，原本沒列入 pages ⇒ 模組缺席時不會被移除、D7 前哨也不會驗它回 404。守門 `tests/platform/test_module_pages_match_units.py`

## 1.0.13 — 2026-09-27（第十二班列車取號，原暫用 1.0.12）
- IP-15 追加成本檢視 `dispatch.cost_for_case`（主持派工，B 實作；M06 傳票摘要改走它）：放行 finance／cashier（＋原本看得到派工的三個模組）；只回金額、日期、案件、廠商名稱、派工描述（scope）、發票號、品項描述＋金額、外包人數與人員金額合計，**不回外包人員姓名、personnel、派工細節**；`dispatch.list_for_case` 不動〔rebase 到第十班 8151bdc6：列車已取 1.0.8～1.0.11 ⇒ 本段暫用 1.0.12；第十二班列車 rebase 到第十一班之後與附件來源說明句撞號，改取 1.0.13〕

## 1.0.12 — 2026-09-26（第十一班列車取號，原暫用 1.0.8）
- 附件來源看不到時說出沒列出幾個附件（`AttachmentNotVisible(hidden=N)`，只有數字；主持裁示：因權限沒列出要明說，不可以帶出單號與內容）

## 1.0.11 — 2026-09-26（第十班列車取號，原暫用 1.0.7）
- 附件來源提供者加權限（稽核 D AT-M1，主持裁示 (b)）：`files`／`doc_nos_for_case` 多帶 `user`，看不到派工單所屬案件的人 ⇒ `AttachmentNotVisible`（同派工單清單的讀取規則）

## 1.0.10 — 2026-09-26（第十班列車取號，原暫用 1.0.6）
- 提供 `attachments.for_document`（IP-21 暫定號，主持裁示 M06-b）：派工單與承攬商發票的已上傳檔案（`attachments.py`）；M06 傳票帶入附件不再直讀 `contractor_dispatches`。本模組不在時，傳票頁明說「外包工班模組未安裝：派工單、承攬商發票的附件沒有列出」、帶入 400 並說明

## 1.0.9 — 2026-09-26（第十班列車取號，原暫用 1.0.5）
- IP-14 加第二個能力 `contractor_voucher.paid_between(start, end)`：區間內已付款的承攬商匯款申請（形狀同 `contractor_voucher.public`）；M06 會計匯出的 T100 付款傳票改走它，不再自己讀本模組的表（主持派工，A 的 M06 搬遷前置）。M04 不在 ⇒ 會計匯出沒有承攬付款、預覽 notice 照舊明說

## 1.0.8 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.6，列車取號）
- 簽核佇列詳情（M01-PLAN §3-7，c-approval-2）：單據內容改由本模組提供 `approval.detail`（共同段用 L1 `helpers/approval_queue.snapshot_doc_detail`）；M01 詳情端點不再直讀本模組的表，只做每案權限、案件抬頭、金額遮蔽。本模組不在 ⇒ 詳情 400 並明說

## 1.0.7 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.5，列車取號）
- 待我簽核與轉簽（M01-PLAN §3-7）：本模組提供 `approval.queue_items`（承攬商匯款申請的待簽項目，欄位同原 M01 佇列）與 `approval.reassign`（`contractor_voucher`：`contractor_payment_vouchers.data_json.$.approval` 的讀寫）；M01 佇列、角標、轉簽不再直讀直寫本模組的表。本模組不在 ⇒ 佇列不列、不給轉簽

## 1.0.6 — 2026-09-26〔稽核 X C4-S5：c-probes 先上第八班、用了 1.0.5 ⇒ 本段改 1.0.6〕
- D7 演練：`module.json` 宣告 `provides.probes`（`/api/contractors`、`/api/vendor-contractors`、`/api/contractor-dispatches`、`/api/contractor-vouchers`）——純讀的 GET、在本模組前綴下、模組在時回 200（守門 `tests/platform/test_product_drill_probes.py`、`test_probe_side_effects.py`：不寫表、不寄信、不排程、不把回應值寫進 log）
- 選單宣告搬進本模組：`contractors.html`、`vendor-contractors.html` 的 `pages[].menu`（原寫在 L1 的 `core/menu_l1.json`；group／order／perm／badge 原值照搬）。階段 C／C4（主持裁示 A）：本模組不在時它的入口隨宣告一起消失，不再靠前端寫死的頁面⇒模組對照表；版號與 c-probes／h-probes 交會，列車取號
## 1.0.4 — 2026-09-26
- 第六班列車：IP 定號（`dispatch.list_for_case` IP-12→IP-15、`quotation.append_items` IP-13→IP-17；origin 已用 IP-12 `case.access`、IP-13 `crm.quote_deleted`；`contractor_voucher.public` 維持 IP-14）；只改註解與文件

## 1.0.3 — 2026-09-26
- 稽核 D M04-M1（§B-11 反向控制：刪掉本模組跑 tests/platform＋提到 M04 的所有題）：需要本模組的題搬進本模組 `tests/`（整檔 9、從 19 個混合檔拆出 36 題，同檔名）；留在外面的守門改以 `core.source_tree.module_installed` 判斷本模組在不在（連簽 helper、EM1 訊息、module_history 前例、案件單據端點、案件頁黃金錄製）；兩個模組層 import 改在題目裡 import
- 承攬人員名冊、承攬商的個資告知端點登記 `api_module: subcontract`（`docs/platform/pii_forms.json`）：本模組不在時不比對端點，告知區塊照驗
- M04-S1：`INTEGRATION-POINTS.md` 提供方路徑補 `api/`，並加守門「模組在時提供方檔案必須存在」；M04-S2：README 的 M01 不在判準改 `case.access`（IP-12）；M04-S3：SPEC.md 指向本模組 tests/；O-1：`privacy_notice_acks` 維持 L1 共用（主持裁示），README 劃掉並加〔更正〕

## 1.0.2 — 2026-09-26
- `module.json` 補 `customization`（P3：目前沒有宣告可自訂點，寫出空的類別＝有人決定過）

## 1.0.1 — 2026-09-26
- 搬遷後續：已廢棄的匯款簽核設定頁（AS4）不列入 `pages`；IP-1 的契約與正對照題搬進本模組的 tests/（本模組不在時跟著消失）；測試不用規格編號樣式的名稱
- 出納頁在本模組不在時說出原因（e2e）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/contractors.py`、`routers/vendor_contractors.py`、`routers/contractor_vouchers.py` 搬入 `modules/subcontract/`（PLAYBOOK §B）；由載入器掛載
- 提供者改由 `ModuleSpec.providers` 宣告：IP-1 `dispatch.row`、IP-12 `dispatch.list_for_case`、IP-14 `contractor_voucher.public`
- 派工品項匯入報價單改用 M01 的 IP-13 `quotation.append_items`（不再自己讀寫報價單）
- 日期欄驗證改用 L1 `helpers.dates.normalize_date`；案件存取守門改用 L1 `helpers.case_access`
