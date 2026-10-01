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
- 【A29-B F1，使用者裁示延到第31班】勞報單詳情 `GET /api/payslips/{slip_no}` 與 `/pdf-download`（payroll/api/payslips.py ~l.326／~l.539）對有勞報單模組的 admin 顯示個人完整銀行帳號（正式機現況，非迴歸）。做法：admin 顯示 ****末四碼，遮罩值回傳視為保留原值，仍只有最高管理者看全號。
- 【A29-B G1】`test_bank_account_mask_2026_10_01` 抓不到憑據 PDF 未遮罩（突變 mask_bank=False 仍綠）→ 加 pypdf 文字斷言。【G2】`bank_mask.keep_if_masked` 是死碼（突變仍綠；真正的守門在 vendor_contractors 內聯 is_masked_value）→ 刪或接上並加測試。
- 【使用者新需求 2026-10-01 21:4x】承攬商派發管理的新增派發要有審核機制：目前派發後手動選狀態，沒有審核就能完結。設計中：docs/platform/plans/DISPATCH-APPROVAL-DESIGN.md（wip/dispatch-approval-2e）。第 31 班主軸之一。
- 【派發審核 使用者裁示 2026-10-01】審核鏈＝既有分層簽核；完工也要簽核（兩段：新增派發、完工申請）；既有進行中派發不溯及既往（舊單標記）；報表成本：草稿與被退回不算、待審核算並標註。預設（主持代決）：送審＝建立人／報價單擁有者與協作者／admin+；核准後實質欄位修改需重送審；取消已核准派發＝admin+ 必填原因（有憑據則 superadmin）；單號 DP-。
- 【使用者新需求 2026-10-01】叫料管控也需要審核（比照派發審核）。設計中：wip/material-order-approval-d7，docs/platform/plans/MATERIAL-ORDER-APPROVAL-DESIGN.md；考慮與派發審核共用「審核閘」機制。第 31 班。
- 【第31班拆班 2026-10-01】31-A 派發審核（兩段審、G-D1、_set_status、佇列／信件／稽核、報表規則、舊單徽章；不動表）約 2.5–3 班；31-B 匯款款別（訂金／進度／完工／驗收款、比例＋稅金自動算、累計上限、移除 dispatch_id UNIQUE 需正式機資料副本演練、E04 逐張、每期發票）約 2.5–3 班；31-C 叫料審核（疊加表、四路徑閘、匯款申請＋出納、收貨記人不簽核、$0叫料單）約 5 班；另：固定資產 C6、建構器 B、401 媒體檔、勞報單帳號遮罩。
- 【401 研究更正 2026-10-01 23:0x】a3 取官方附件六 PDF（law-out.mof.gov.tw FileID=51326）逐列轉錄：32–46 欄寬度為混合（32/34/36/38/40 銷售 S9(12)＋33/35/37/39/41 稅額 S9(10)；42 僅銷售；43–46…），72 欄是 9(3)，93–95＝代號113/114/115；先前研究摘要的「交錯寬度」是猜的、會被對方系統拒收。產生器已按 PDF（modules/accounting/ledger/tax401_media.py，分支 wip/t31-payslip-mask-a3）。待會計確認：正數末位是否用 overpunch（{ABCDEFGHI）、最後一筆是否有結尾 CRLF、C(n) 以字元計。
- 【使用者新需求 2026-10-01 23:1x】輪到我簽核時，側欄「我的工作」要有紅點（目前沒有）。c7：wip/t31-approval-dot-c7（沿用簽核佇列計數端點，不另輪詢）。
- 【上線公告 紅點／橫幅】非 admin 使用者（一般簽核人、業務、檢視者）過去完全沒有導覽徽章、每日工作事項徽章與登入「待簽核」橫幅（notifStore 只掛在 admin 才有的通知鈴裡）；wip/t31-approval-dot-c7 起改掛不可見的 notifStore，非 admin 也會看到簽核紅點與數字、每日工作徽章、登入橫幅（一次／分頁）。鈴鐺、模組計數徽章與 TOTP 提醒維持僅 admin。
- 【使用者新需求 2026-10-01】檔案中心「開啟原單據」點選後直接開啟上傳檔案（a3：wip/t31-filecenter-open-a3；預設：主要動作改「開啟檔案」，保留次要連結「前往原單據」）。
- 【使用者新需求 2026-10-01 23:47】模組建構器與請款類型編輯頁 UX 重設計：正中間為真實表單預覽、左右兩側加欄位與設定；國中程度看得懂的頁面／圖示／選單；固定值選項改成可 Enter 連續新增的項目清單；使用者可自行設計版面（區塊、拖拉）。c7 主導共用元件（wip/t31-form-designer-c7，先出可點擊原型與設計文件），a3 整合請款類型端。需使用者審原型後才實作。
- 【使用者新需求 2026-10-02 01:5x】新增請款的採購單／請購單要連線到案件品項（例：品項 A 直接點選請購），這類支出算案件的實際支出，不再是額外支出。設計：wip/t32-prpo-item-link-2e（docs/platform/plans/PR-PO-CASE-ITEM-LINK-DESIGN.md）；重點風險：與叫料（31-C）重複認列。

## 第30班派發審核稽核（c7，audit/train30-dispatch-c7@c8e68d7b，PASS 無 must-fix）
- S-1（需使用者裁示）：已驗收/完成的舊列（approval_status=''）實質編輯會重設為草稿 → 掉出成本檢視與 GL E04，直到重送核准。選項：舊列編輯維持 ''，或 UI 明確警示。
- S-2（should-fix，31班）：待審核中取消 → approval_status 仍 待審核、紅點不消、/approve 對已取消回 200。修：取消時同交易關閉待審階段；/approve 對 cancelled 回 409。
- O-1 自核准屬流程設定；O-2 approved_hash 只寫不驗；O-3 PUT 鎖序理論競態；O-4 結案閘不看派發核准狀態。
- 報告：docs/platform/audit/AUDIT-C7-train30-dispatch.md（探針檔含刻意紅的 F2，不進列車）。

## 進度 2026-10-02（主持核對 ls-remote）
- 2e：wip/t31-prefill-sources-2e@0bf4ccc6（合併時 l1 snapshot 衝突→取 platform 版再 core_bump --pending）；wip/t32-prpo-s1-2e@80c3532d（Q6 額外支出合計對齊 + purchase-items picker；公告：有 PR/草稿/退回列的案件合計會變）。待做 S2（itemId 驗證／上限／overPlanReason）、S3（入帳）、額外支出頁 uncountedAmount 提示。
- c7：wip/t31-form-designer-c7@d9569b3a（切片1–3；預設關閉；真滑鼠拖放需人工驗）。
- a3：wip/t31-expense-designer-a3@99e14769（請款類型接線；預設改關閉）。
- d7：wip/t31-material-d7@73e82a57（31-C 叫料付款/匯款切片完成，含 merge 第30班；PAID_VIA_REMITTANCE_ONLY=True；M1–M18 突變全紅）。整合注意：case CHANGELOG「(next)」需編號、analytics changelog 守門紅（非 d7）。poDocCode/poLine seam 待 2e 設計。
- a3：wip/t31-expense-designer-a3@fc610fb3（預設舊 UI，?designer=1 開新）；c7：wip/t31-form-designer-c7@3268466c（fixedOptions；待補 modules.json 登記 3 檔）。
- 請款類型預覽截圖（a3 e0d830c1，docs/platform/plans/expense-types-designer-shots/）發現：(2) 出貨定義 applicant 欄位 help 含術語「把 locked 改成 false」→ 動 helpers/expense_type_defs/*.json 影響 def_version，待使用者裁示措辭；(3) 深色面板標題低對比（頁面原有樣式）。(1) 簽核單據類型「undefined（未登記）」僅顯示修正，a3 處理。
- 真滑鼠拖放（設計器）需人工瀏覽器驗，列入使用者預覽清單。
- 2e：wip/t32-prpo-s1-2e@167f208b（S2 完成：itemId／累計上限／overPlanReason／fromPr；14 題＋16 突變 15 殺，1 等價）；S3 入帳進行中（GL E11、結算欄、itemLinkedAmount）。
- 使用者裁示 2026-10-02：連案件品項的 PO 明細，營運報表算「料件」欄（recognition.ITEM_COST_BUCKET；不新增第5欄）。
- 2e：wip/t32-prpo-s1-2e@d9c38a97（S1+S2+S3）。S3 保留 totalAmount 含連品項列（新欄 itemLinkedAmount/extraOnlyAmount）；結算頁改用 extraOnlyAmount+品項系統帶入屬 S5，**S3 與 S5 必須同班出**（S3 單獨出安全）。S4（叫料連結）等 31-C 併入。
- d7：wip/build-opt2-d7@82844b9b（failfast 外掛，opt-in，未改 build script；實測單靠停損只省 2–9 分，主力是 failure-first 排序與 item 3 依賴增量）。3 日複查：cron `17 9 */3 * *`。
- a3：wip/t31-expense-designer-a3@67ac7c65（docType 顯示、深色面板修）；c7 須查設計器深色主題是否被全域 invert filter 反轉成淺灰。
- a3：wip/t31-expense-designer-a3@83da4b4a（併入 c7 f9958ab5 深色修；8 張截圖重拍）；wip/t31-expense-prefill-a3@3aa22930（請款側 prefill 驗證，registry 未到前行為不變，stub 對齊 2e 簽名）。整合順序：2e registry 先，a3 prefill 後。
- 2e S5：wip/t32-prpo-s1-2e@1245cd27（前端選擇器＋結算採用）。待修：①PO 送審被拒時草稿殘留、再按產生第二份；②結算 PDF/匯出的分項加總與 totalActualCost 差 itemPoUnadopted。S3+S5 同班出。
