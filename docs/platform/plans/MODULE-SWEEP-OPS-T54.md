# 模組框架化盤點 — 營運類：subcontract／supply／crm／lodging（第 54 班；盤點，不含實作）

> 規則來源與格式同 `MODULE-SWEEP-FINANCE-T54.md`（使用者 2026-10-10：每個模組都要盤點①功能與規則②決策點③頁面顯示）。基準：`wip/t54-n39-settings-s0s2`；少數行號標「~」為由合併列表推得，引用前須再核對。
> 機制縮寫：SR＝設定中心、M＝權限矩陣(F3)、S＝狀態／標籤(F5)、FP＝欄位政策(F7，僅設計)、D1＝顯示偏好(新)、locked＝法令／會計完整性鎖定。
> 路徑：`SC/`＝`backend/modules/subcontract/`、`SU/`＝`.../supply/`、`CRM/`＝`.../crm/`、`LG/`＝`.../lodging/`、`FP/`＝`frontend/pages/`（此處 FP 指資料夾，不是欄位政策）。
> 已在設定機制內、不重列：上傳大小（`uploads.max_file_mb`）、`remit_require_payslip`（`system_settings`，`SC/api/contractor_vouchers.py:977`）、`contractor_voucher_approval_flow`、`unified_approval_flow` 簽核層、款別（`remit_kinds`，已是可發布的定義文件）。

## 1. subcontract（承攬商／匯款）

### 1a. 規則、門檻、編號、稅
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| SC-01 | 派發單號 | `DP-YYYYMMDD-NNNN` 日序 4 位 | `SC/dispatch_flow.py:82-88` | 前綴＋位數（歸 F5 編號框架） | ops | F5 | S |
| SC-02 | 匯款申請單號 | `next_entity_code(..., "PV")` | `SC/api/contractor_vouchers.py:456` | 前綴 | ops | F5 | S |
| SC-03 | 派發預設稅率 | 0.05 多處 fallback | `SC/api/vendor_contractors.py:85,175,599,649,673`；`dispatch_flow.py:101` | 新單預設值＝讀 `legal_params`，不開自由欄位 | legal | locked（預設值連動法定） | M |
| SC-04 | 匯款稅率回退 | 派發無稅率時 0.05 | `contractor_vouchers.py:400`；`remit_create.py:92` | 同 SC-03 | legal | locked | S |
| SC-05 | 稅額進位 | `round_half_up` 到元 | `remit_split.py`；`gl_events.py`；`contractor_vouchers.py:401` | — | legal | locked | - |
| SC-06 | GL 進項稅碼 | `IN-5`／`IN-EX` | `SC/gl_events.py:60-63,83` | — | legal | locked | - |
| SC-07 | 分期末期補稅尾差 | 末期＝總稅減前期稅 | `SC/remit_split.py:20` | — | legal | locked | - |
| SC-08 | 分期輸入方式 | 比例 0<p≤1 或固定金額（整數元≥1） | `remit_split.py` | 開關「允許固定金額」，預設開 | money | SR | S |
| SC-09 | 個人點工只掛末期 | `keep_personnel = is_last` | `SC/remit_create.py:120-123` | 末期／首期／按比例，預設末期 | money | SR | M |
| SC-10 | 完工／驗收款前期未付 | 僅警示不擋 | `remit_create.py:104` | 警示／擋／關，預設警示 | money | SR | S |
| SC-11 | 整筆與分期互斥 | 有舊整筆單或已有發票日則擋 | `remit_create.py:84,89` | — | money | locked（防重複認列成本） | - |
| SC-12 | 分期作廢 LIFO | 只能作廢最新一期 | `remit_create.py:55-67` | — | money | locked（稅額凍結） | - |
| SC-13 | 實付≠應付→待審 | 四捨五入至分後有差即待審 | `SC/remit.py:61` | 容差金額，預設 0 | money | SR（`requires_pending`） | S |
| SC-14 | 手續費 | 公司吸收、不自受款人扣；類別「匯款手續費」 | `SC/remit.py:25,42-58` | 類別標籤走 S；規則 locked | money | S | S |
| SC-15 | 自標匯款不得自審 | `paid_by`＝本人則 403 | `remit.py:136-140` | 開關「強制職責分離」，預設開 | security | M | S |
| SC-16 | 驗收人≠建立人 | 自己驗收自己的派發被擋；superadmin 例外（留稽核） | `dispatch_flow.py:127-131` | 開關預設開；例外可設 | security | M | S |
| SC-17 | 取消需理由 | 已核准或驗收中狀態須理由，最多 500 字 | `dispatch_flow.py:136-140` | 狀態集合＋字數 | ops | SR＋S | S |
| SC-18 | 已有匯款申請僅 superadmin 可取消 | 否則 403 | `dispatch_flow.py:141-143` | 角色集合 | money | M | S |
| SC-19 | 作業狀態轉換表 | TRANSITIONS 僅向前 | `dispatch_flow.py:68-76` | 每公司可調的允許表 | ops | S | L |
| SC-20 | 須先核准才可前進的狀態 | GATED＝sent／confirmed／pending_acceptance／accepted | `dispatch_flow.py:78,121` | 狀態集合 | ops | S | M |
| SC-21 | completed 只經完工審核 | `via_completion` | `dispatch_flow.py:118` | — | ops | locked（系統不變式） | - |
| SC-22 | 狀態／審核標籤 | 草稿／已送出…；完工審核中 | `dispatch_flow.py:11-14,31-49` | 標籤覆寫 | none | S | S |
| SC-23 | 實質欄位 hash | vendor、items、personnel、稅率；備註日期不計 | `dispatch_flow.py:91-105` | 觸發重審的欄位集合 | money | FP | M |
| SC-24 | 核准後實質編輯→回草稿 | 只對「已核准」；舊單豁免 | `vendor_contractors.py:675-694` | 回草稿／僅警示，預設回草稿 | money | SR | S |
| SC-25 | 審核中鎖編輯、核准／審核中不可刪 | PENDING／IN_PROGRESS 鎖 | `vendor_contractors.py:657,735` | — | ops | locked | - |
| SC-26 | 同人連任多層一次簽 | `cascade=true` 才連簽 | `SC/api/dispatch_approval.py:158,182`；`contractor_vouchers.py:716` | cascade 預設值，預設 false | security | SR | S |
| SC-27 | 退回必填原因 | `require_reject_reason` | `dispatch_approval.py:220`；`contractor_vouchers.py:44` | 開關預設開 | ops | SR | S |
| SC-28 | 簽核人角色限制 | 設定頁可選任何人，程式要求 admin／superadmin | `contractor_vouchers.py:679`；`dispatch_approval.py:82` | 角色集合 | security | M | S |
| SC-29 | 沒設簽核層→直接核准 | 無層級即自動核准 | `dispatch_approval.py:~120-124` | 自動核准／擋，預設自動 | money | SR | S |
| SC-30 | 同層簽核人不得自簽 | `check_no_tier_self_approval` | `dispatch_approval.py:175`；`contractor_vouchers.py:749` | 共用 helper；開關 | security | M | S |
| SC-31 | 預定付款日提醒 | 前 3 天、當天、逾期；用工作日 | `SC/payable_due.py:86-98` | 天數清單＋各類開關 | ops | SR | M |
| SC-32 | 提醒收件人 | `to_group=True`（財務群） | `payable_due.py:~88-98` | 收件群組 | ops | SR | S |
| SC-33 | 提醒不含金額與姓名 | 只有單號、標籤、案件、到期日 | `payable_due.py:54-57` | — | security | locked（隱私設計） | - |
| SC-34 | 行事曆付款待辦 | 核准、未付、未作廢、有效日期時建立 | `payable_due.py:40-44` | 開關預設開 | none | SR | S |
| SC-35 | 派發審核通知 8 種 | 已註冊 mail_types，信內無金額 | `SC/dispatch_notify.py:17-35` | 個人通知偏好已處理 | none | 現有 | - |
| SC-36 | 派發審核對象角色 | admin／superadmin＋模組 procurement／case_manage／contractor_list | `dispatch_approval.py:79-84`；`vendor_contractors.py:27-33,241,291` | 角色／模組矩陣 | security | M | M |
| SC-37 | 財務動作角色 | 建立、送審、作廢＝財務；標記已付＝出納；連結勞報＝出納 | `contractor_vouchers.py:150,275,1007,1041,1104` | 角色對應 | money | M | M |
| SC-38 | 款別設定只 superadmin | 款別定義頁 | `SC/api/remit_kinds.py:32` | 角色 | security | M | S |
| SC-39 | 款別預設與限制 | 預設 4 個；最多 30 種、名稱 20、備註 200 | `SC/remit_kinds.py:21-37` | 限制數字走 SR | none | SR | S |
| SC-40 | 銀行帳號遮蔽 | 僅 superadmin 見完整；其他 `****`＋末四碼；存摺影本隱藏 | `SC/bank_mask.py:12-45`；`contractors.py:145-263` | 可看完整帳號的角色集合 | security | M | S |
| SC-41 | 外包名冊只限 superadmin | 全 CRUD `require_superadmin` | `SC/api/contractors.py:176-488` | 角色 | security | M | S |
| SC-42 | 身分證影本浮水印 | 「僅供申報扣繳使用」30°；最大寬 1800 | `SC/api/contractors.py:30-97` | 文字 locked（法遵）；寬度 SR | legal | locked＋SR | S |
| SC-43 | 附件讀取模組 | procurement／case_manage／contractor_list／quotation | `SC/attachments.py:117` | 模組集合 | security | M | S |
| SC-44 | 派發／勞報單連結只回無金額欄位 | 不含金額、扣繳、銀行 | `SC/api/dispatch_payslip_links.py:4,20` | — | security | locked（Q9 裁示） | - |
| SC-45 | 取消派發關閉在審階段→已退回 | 強制 RETURNED | `dispatch_flow.py:146-161` | — | ops | locked | - |
| SC-46 | GL 認列條件 | E04 僅驗收／完成且有發票日與核准；E05 依付款日 | `SC/gl_events.py:~34-46` | — | legal | locked | - |
| SC-47 | 清單上限 | `LIMIT 200` | `contractor_vouchers.py:313`；`vendor_contractors.py:545`；`dispatch_payslip_links.py:128` | 整數 | none | D1 | S |
| SC-48 | 發票號／原因長度 | 發票號 40、作廢原因 500 且必填 | `contractor_vouchers.py:551,586-588` | 整數 | none | SR | S |

### 1b. 頁面顯示
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| SC-D1 | 外包人員名冊欄位 | 姓名／證件號碼／電話／Email／國籍／分行／狀態 | `FP/contractors.html:119-127` | 欄位集合與順序 | none | D1 | M |
| SC-D2 | 承攬商欄位 | 名稱／統編／聯絡人／電話／Email／狀態 | `FP/vendor-contractors.html:118-125` | 欄位集合 | none | D1 | M |
| SC-D3 | 預設只顯示啟用 | 「顯示停用」預設關 | `contractors.html:109`；`vendor-contractors.html:103` | 預設篩選 | none | D1 | S |
| SC-D4 | 國籍選項 | 本國籍／外國籍（滿183天）／外國籍（未滿183天） | `contractors.html:334-336` | locked（連動扣繳率與183天規則） | legal | locked | - |
| SC-D5 | 承攬商類別選項 | 機電／弱電／消防／空調／裝修／水電／IT／土木／其他 | `vendor-contractors.html:387-395` | 公司可編輯清單 | none | S（選項清單） | S |
| SC-D6 | 統編查詢 | 8 碼；名稱搜尋至少 2 字 | `vendor-contractors.html:318,335` | locked | none | locked | - |
| SC-D7 | 搜尋 debounce | 300 ms | `contractors.html:106`；`vendor-contractors.html:100` | — | none | locked | - |
| SC-D8 | 配色 | 外包人員綠 #059669、承攬商紫 #7C3AED、停用灰 | `contractors.html:134,141`；`vendor-contractors.html:132,139` | 主題 | none | D1 | S |
| SC-D9 | 款別設定頁長度 | 名稱 20、代碼 40、備註 200 | `FP/remit-kinds-settings.html:80-101` | 同 SC-39 | none | SR | S |
| SC-D10 | 金額顯示 | `NT$ `＋toLocaleString | `contractors.html:287`；`vendor-contractors.html:251` | 數字格式（D2） | none | D1 | S |
| SC-D11 | 派發主 UI | 在 `frontend/js/case-management-dispatch.js`（屬 case 模組），本表未盤點 | — | — | — | — | - |

## 2. supply（採購、庫存、出貨）

### 2a. 規則
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| SU-01 | 庫存水位燈號 | 安全量≤0 綠；<安全量 紅；<安全量×1.5 黃 | `SU/api/inventory.py:42,74-87` | 倍數 1.5（1.0–5.0） | ops | SR | S |
| SU-02 | 採購建議補貨目標 | `ceil(安全量 × 1.5)` | `inventory.py:219,273` | 跟 SU-01 或獨立倍數 | ops | SR | S |
| SU-03 | 採購建議循環 | suggested→ordered→received 僅向前；到貨仍低於門檻則新循環 | `helpers/procurement.py:36-47,100-155` | — | ops | locked | - |
| SU-04 | 前置時間優先序 | 零件優先於供應商；0＝有庫存；None＝未知 | `helpers/procurement.py:71-86` | — | ops | locked | - |
| SU-05 | 入庫批次單號 | `next_entity_code(..., "PO", code_col="batch_no")` | `inventory.py:449` | 前綴 | ops | F5 | S |
| SU-06 | 出貨單號 | `next_entity_code(..., "DN")` | `SU/api/shipping_notes.py:305` | 前綴 | ops | F5 | S |
| SU-07 | 序號必填且不重複 | 空白、批內重複、既有序號皆拒 | `inventory.py:426-447` | — | ops | locked | - |
| SU-08 | 序號狀態集合 | in_stock／shipped／installed／void；void 終態 | `inventory.py:630-660` | 標籤；轉移 locked | ops | S | M |
| SU-09 | 庫存直接刪除 | 僅 in_stock 可刪 | `inventory.py:679-681` | 狀態集合 | ops | S | S |
| SU-10 | 庫存寫入需 admin | 批次建立、調整、刪除 | `inventory.py:45-47,415,531,616,673` | 角色 | security | M | S |
| SU-11 | 標記批次付款＝出納 | `has_cashier_access` | `inventory.py:570` | 角色 | money | M | S |
| SU-12 | 庫存讀取模組集 | inventory／procurement／case_manage／netplan_edit | `inventory.py:55,158,295,362,395,414` | 模組集合 | security | M | S |
| SU-13 | 供應商模組集／管理員 | customer／procurement／inventory＋admin | `SU/api/suppliers.py:36-37` | 角色／模組 | security | M | S |
| SU-14 | 進項稅估計 | `_RATE = 0.05` | `SU/gl_events.py:19` | locked（會計估計，可被補登覆蓋） | legal | locked | - |
| SU-15 | GL 事件認列日 | E08／E08b 批次日、E09 付款日、E10 出貨／入帳／作廢日 | `SU/gl_events.py:52-118` | — | legal | locked | - |
| SU-16 | 出貨單編輯／刪除／送審限草稿 | 非草稿 409 | `shipping_notes.py:337,363,391` | 狀態集合 | ops | S | S |
| SU-17 | 送審至少 1 項品項 | 否則拒 | `shipping_notes.py:397` | 開關 | ops | SR | S |
| SU-18 | 出貨單簽核 | 層級讀 `unified_approval_flow`；無層即自動核准；cascade | `shipping_notes.py:408-431,474-535` | 既有簽核設定；cascade 預設同 SC-26 | money | SR | S |
| SU-19 | 核准時序號鎖定 | 序號仍須 in_stock 否則 409，核准後轉 shipped | `shipping_notes.py:553-561,577` | — | ops | locked | - |
| SU-20 | 撤銷核准 | admin；已回簽則擋；序號回 in_stock | `shipping_notes.py:618-652` | 角色＋開關 | ops | M | S |
| SU-21 | 回簽 toggle | 僅已核准；簽與取消皆留紀錄 | `shipping_notes.py:~776-830` | 角色 | ops | M | S |
| SU-22 | 刪除回簽附件限 admin | 否則 403 | `shipping_notes.py:~867-869` | 角色 | security | M | S |
| SU-23 | 出貨單讀取 | `guard_case_access(allow_module="case_manage")`；歷史需 `shipping_export_log` | `shipping_notes.py:104-110,148-149` | 模組 | security | M | S |
| SU-24 | 材料申請占用狀態 | 預留＝待審核／簽核中；已出＝已核准；草稿與退回不計 | `SU/material_link.py:18-19` | 狀態集合 | ops | S | S |
| SU-25 | 超過到料量擋出貨 | `reserved + shipped + qty > arrivedQty + eps` → 400 | `material_link.py:152-156` | 擋／警示，預設擋 | ops | SR | S |
| SU-26 | 同列序號與材料連結互斥 | `ship_link_serial_exclusive` | `material_link.py:63-64` | — | ops | locked | - |
| SU-27 | 未連結剩餘料警示 | `unlinked_warnings` 僅提示 | `material_link.py:159-177` | 開關 | none | SR | S |
| SU-28 | 出貨單清單上限 | LIMIT 200 | `shipping_notes.py:118` | 整數 | none | D1 | S |

### 2b. 頁面顯示
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| SU-D1 | 庫存主表欄位 | 料號／品名／廠牌型號／類別／水位／在庫／在庫金額／最近入庫／已出貨／已登載／報廢／操作 | `FP/inventory.html:115-126` | 欄位集合 | none | D1 | M |
| SU-D2 | 序號明細欄位 | 序號／MAC／狀態／批次／入庫時間／關聯／操作 | `inventory.html:250` | 欄位集合 | none | D1 | S |
| SU-D3 | 批次表欄位 | 批次號／料號／數量／金額／供應商／發票號／付款狀態／操作 | `inventory.html:290-291` | 欄位集合 | none | D1 | S |
| SU-D4 | 水位顏色 | red #DC2626、yellow #D97706、green #D1D5DB | `inventory.html:49-51` | 主題 | none | D1 | S |
| SU-D5 | 序號狀態標籤與色 | 在庫綠、已出貨藍、已登載紫、報廢灰 | `inventory.html:54-57,241-244` | 標籤 | none | S | S |
| SU-D6 | 只看低庫存 | `lowStockOnly` 顯示紅＋黃 | `inventory.html:486,496` | 預設篩選 | none | D1 | S |
| SU-D7 | 採購建議排序 | 紅燈優先、估算成本降冪 | `inventory.py:92` | 排序偏好 | none | D1 | S |
| SU-D8 | 供應商欄位 | 公司名稱／簡稱／統編／類型／聯絡人／電話／幣別／付款條件／狀態 | `FP/suppliers.html:176-184` | 欄位集合 | none | D1 | M |
| SU-D9 | 供應商下拉選項 | 類型（原廠…其他）、幣別（NTD/USD/JPY/EUR/CNY）、付款條件（月結30天…） | `suppliers.html:606-644` | 公司可編輯清單 | none | S（選項清單） | M |
| SU-D10 | 詳情顯示最近 3 筆拜訪 | `.slice(0,3)` | `suppliers.html:351` | 整數 | none | D1 | S |
| SU-D11 | 供應商紀錄頁排序與類型 | 預設最新在前；類型 5 種 | `FP/supplier-log.html:361-362,492-496` | 預設排序＋選項清單 | none | D1／S | S |
| SU-D12 | 出貨匯出歷史篩選 | 年／月下拉，無頁大小 | `FP/shipping-export-history.html:87-93` | 預設篩選 | none | D1 | S |

## 3. crm（業務開發）

### 3a. 規則
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| CRM-01 | 案件狀態集合 | 洽談中／成案／未成案／暫擱置 | `CRM/api.py:26,556` | 標籤與集合 | ops | S | M |
| CRM-02 | 洽談中逾 30 天視為停滯 | `_STALE_DAYS = 30`；前端另寫 30 | `CRM/api.py:1083`；`dev-crm.html:480,571,1412,1551` | 整數 30（前後端同源；與 ANA-05 共用） | ops | SR | S |
| CRM-03 | 停滯重複通知 | 每 14 天，每分組 | `api.py:1084,1114` | 整數 14 | ops | SR | S |
| CRM-04 | 停滯通知對象 | 業務與規劃，否則建立者，加全部 admin／superadmin | `api.py:1099,1138-1148` | 收件集合 | ops | SR | S |
| CRM-05 | 停滯行事曆事件 | 每案每個 `updated_at` 一筆 | `api.py:~1150-1156` | 開關 | none | SR | S |
| CRM-06 | 暫擱置逾 180 天自動轉未成案 | 只寫稽核，使用者「系統自動」 | `api.py:1085,1169-1190` | 天數 180；0＝關 | ops | SR | S |
| CRM-07 | 排程時間 | 啟動後每日 08:00 | `api.py:1232` | 整數時點 8 | none | SR | S |
| CRM-08 | 業務開發權限 | admin／superadmin 或模組 `dev_crm` | `api.py:94-103,129` | 模組＋角色 | security | M | S |
| CRM-09 | 案件可見性 | admin＋見全部；其他限建立者／業務／規劃 | `api.py:110-115,~339` | 擁有權規則 | security | M（row_access） | M |
| CRM-10 | 刪除案件 | admin 申請、superadmin 核准；僅可撤自己申請 | `api.py:441,475,486,508` | 角色／簽核 | security | M | M |
| CRM-11 | 報價連結異動 | admin 申請、superadmin 核准；已有連結則不可直連 | `api.py:597,627,705` | 角色 | security | M | M |
| CRM-12 | 連結報價單被刪 | 狀態回洽談中並清除連結 | `api.py:~1120-1135` | — | ops | locked | - |
| CRM-13 | 開發記錄審核 | 代他人填的記錄需審；僅 admin 可核 | `api.py:~903,1059` | 開關，預設開 | ops | SR | S |
| CRM-14 | 記錄修改／刪除限本人 | 403 | `api.py:975,1006` | 角色／擁有權 | ops | M | S |
| CRM-15 | 附件刪除限 admin+ | 403 | `api.py:1038` | 角色 | security | M | S |
| CRM-16 | 介紹人上限 | 60 字，超過 400 不截斷 | `api.py:217-228` | 整數 | none | SR | S |
| CRM-17 | 樂觀鎖 | 他人已更新則 409 | `api.py:407` | — | none | locked | - |
| CRM-18 | 接洽統計窗 | 日 60 天、週 8 週（週一起）、廠商／管道 30 天；僅計已核准記錄 | `api.py:789-825` | 整數 60/8/30 | none | SR | S |
| CRM-19 | 案件列表排序 | `ORDER BY updated_at DESC`，不分頁 | `api.py:~331` | 排序偏好 | none | D1 | S |
| CRM-20 | 通知類型 | 停滯、刪除／換連結申請、狀態變更 | `api.py:367,574,612` | 個人通知偏好已處理 | none | 現有 | - |

### 3b. 頁面顯示（`FP/dev-crm.html`）
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| CRM-D1 | 漏斗卡 | 四狀態卡含計數，點擊篩選 | `dev-crm.html:476-497` | 順序與顯示 | none | D1 | S |
| CRM-D2 | 預設不顯示未成案 | 無篩選時 `status !== '未成案'` | `dev-crm.html:1487,1546` | 預設篩選 | none | D1 | S |
| CRM-D3 | 溫度條門檻 | >7 天警示、>30 天紅，上限 60 天；僅洽談中／暫擱置 | `dev-crm.html:1408-1425` | 整數 7／30／60（連動 CRM-02） | none | SR＋D1 | S |
| CRM-D4 | 狀態徽章色 | 洽談黃、成案綠、未成案紅、暫擱灰 | `dev-crm.html:171-174` | 色票 | none | S | S |
| CRM-D5 | 排序選項 | 最後更新／建立日期／案件名稱／客戶名稱 | `dev-crm.html:536-539` | 預設排序 | none | D1 | S |
| CRM-D6 | 人員篩選 | 所有人員／只看我負責／指定姓名；存 localStorage | `dev-crm.html:526-529,1380` | 預設 | none | D1 | S |
| CRM-D7 | 年份月份篩選 | 依 `createdAt` | `dev-crm.html:547-553,1488-1489` | 預設 | none | D1 | S |
| CRM-D8 | 聯絡管道選項 | 電話／Line／Email／面訪／視訊／其他 | `dev-crm.html:912-914` | 公司可編輯清單 | none | S | S |
| CRM-D9 | 記錄狀態快照選項 | 不記錄＋四狀態 | `dev-crm.html:934-935,1088` | 跟 CRM-01 | none | S | S |
| CRM-D10 | 排行與建議筆數 | 廠商前 6、近期案件 8、客戶建議 20／25 | `dev-crm.html:689,1757,1764,1771` | 整數 | none | D1 | S |
| CRM-D11 | 時間顯示 | 日期 slice(0,10)、時間 slice(0,16) | `dev-crm.html:630,873,1015` | 日期格式（D2） | none | D1 | S |
| CRM-D12 | 管道徽章與審核徽章色 | 管道靛、已核准綠、待審琥珀 | `dev-crm.html:329-353` | 主題 | none | D1 | S |

## 4. lodging（附近旅宿）

### 4a. 規則
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| LG-01 | 對外抓取開關 | 出貨時關；`MOTRIX_LODGING_FETCH=1` 開 | `LG/source.py:44-46,89-91` | 開關預設關（環境變數保留為覆寫） | security | SR | S |
| LG-02 | 資料來源 | 觀光署 Hotel-json.zip URL、UA、資料集名稱、標準 V2.1 | `source.py:37-42` | locked（授權標示依賴） | legal | locked | - |
| LG-03 | 手動更新最短間隔 | 成功後 24 小時 | `source.py:48` | 小時數 24 | ops | SR | S |
| LG-04 | 失敗冷卻 | 1 小時 | `source.py:49` | 小時數 1 | ops | SR | S |
| LG-05 | 每日自動更新時點 | 03:00 後，一天一次 | `source.py:51,338` | 時點 3 | ops | SR | S |
| LG-06 | 自動更新間隔／當日失敗上限 | 20 小時／3 次 | `source.py:53,55` | 整數 | ops | SR | S |
| LG-07 | 下載逾時、總時、大小 | 每請求 60s、總 180s、下載 50MB、解壓 200MB | `source.py:58-62` | 整數（程式內保留上下限） | security | SR | S |
| LG-08 | zip 白名單 | 僅 HotelList.json、manifest.csv 與兩個 schema csv | `source.py:64-65` | — | security | locked | - |
| LG-09 | 資料過舊天數 | 30 天顯示「可能過時」 | `source.py:67,133` | 整數 30 | none | SR | S |
| LG-10 | 旅宿類別 | 1 國際觀光、2 一般觀光、3 一般旅館→hotel；4 民宿→homestay；9 其他 | `source.py:72-74` | 標籤 | none | S | S |
| LG-11 | 座標合理範圍 | 緯度 21.0–27.0、經度 116.0–123.5 | `source.py:77-78` | — | none | locked | - |
| LG-12 | 新快照辨識率 | 辨識率 <90% 則拒絕 | `source.py:80,266` | 小數 0.9 | ops | SR | S |
| LG-13 | 半徑選項 | 1／3／5／10 km，預設 3 | `LG/search.py:17-18`；`api_records.py:56-58` | 整數清單＋預設 | none | SR／D1 | S |
| LG-14 | 房價異常門檻 | <300 或 >100,000 標 `price_suspect`，排序排除 | `search.py:15-16,38-40` | 整數 300／100000 | none | SR | S |
| LG-15 | 計價單位／詢價管道 | 每晚／每人；電話／官網／現場／其他 | `search.py:20-21` | 選項清單 | none | S | S |
| LG-16 | 排序 | 距離（預設）或價格 | `api_records.py:62-64`；`search.py:113-117` | 預設 | none | D1 | S |
| LG-17 | 地址與備註長度 | 地址 200、備註 500、房型 100、含 100 | `api_records.py:31-32,307` | 整數 | none | SR | S |
| LG-18 | 詢價日期／金額驗證 | YYYY-MM-DD 且不晚於今天；整數元為正 | `api_records.py:276,297-300` | — | none | locked | - |
| LG-19 | 紀錄可見性 | 建立者與 admin／superadmin；admin 見全部 | `api_records.py:33,123,163` | 角色 | security | M | S |
| LG-20 | 重新抓取權限 | 僅 superadmin | `LG/api.py:~58-60` | 角色 | security | M | S |
| LG-21 | 紀錄刪除 | 能看到者即可刪（建立者或 admin） | `api_records.py:195-208` | 角色 | ops | M | S |
| LG-22 | 紀錄保存期限 | 無（永久） | `api_records.py`（無保存邏輯） | 保存天數，0＝永久 | none | SR（併 retention 類） | M |
| LG-23 | CSV 公式注入防護 | 開頭 `= + - @ \t \r` 加前綴 | `api_records.py:213-219` | — | security | locked | - |
| LG-24 | 匯出欄位與格式 | csv 或 json；固定欄位 | `api_records.py:224-233` | 欄位集合 | none | D1 | S |
| LG-25 | 授權標示文字 | 政府資料開放授權文字＋資料年 | `LG/attribution.py:13-32` | — | legal | locked | - |
| LG-26 | 地圖底圖 | 允許則 google，否則 osm | `api_records.py:91` | 選項 | none | SR | S |

### 4b. 頁面顯示
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| LG-D1 | 紀錄清單欄位 | 時間／建立者／中心點／半徑／筆數／備註 | `FP/lodging-records.html:80` | 欄位集合 | none | D1 | S |
| LG-D2 | 結果欄位 | 名稱／類別／登記證號／地址／直線距離／官方參考房價 | `lodging-records.html:119` | 欄位集合 | none | D1 | S |
| LG-D3 | 比較固定兩筆 | `selected.slice(-2)`，剛好選 2 筆才可比較 | `lodging-records.html:257,71` | — | none | locked | - |
| LG-D4 | 距離格式 | ≥1000 m 顯示 km，否則 m | `lodging-records.html:339`；`LG/pages/lodging-overlay.js:32` | 單位偏好 | none | D1 | S |
| LG-D5 | 日期時間格式 | 日期 slice(0,10)、時間 slice(0,16) | `lodging-records.html:334-336` | 格式（D2） | none | D1 | S |
| LG-D6 | 中心點來源標籤 | 目前位置／Google／OSM／OSM行政區／TGOS／人工座標 | `lodging-records.html:357` | 標籤 | none | S | S |
| LG-D7 | 疊圖預設 | 半徑預設 3 km；兩類都勾；依距離／依參考房價；備註 500 | `LG/pages/lodging-overlay.js:181-210` | 預設查詢條件 | none | D1 | S |
| LG-D8 | 詢價表單預設 | 單位每晚、管道電話；長度 100／100／500 | `lodging-records.html:142-148` | 預設 | none | D1 | S |

## 5. 風險提醒與限制

1. 前後端重複的常數須一起改：CRM 停滯 30 天（`api.py:1083` 與 `dev-crm.html` 四處）及 7／60 溫度條；改成 SR 時前端改讀伺服器下發值。分期預覽直接呼叫同一支 Python `remit_split.plan`，沒有重複。
2. 5% 稅是法定值，但「新派發的預設值」是業務預設：建議由 `legal_params` 通讀取得，不開自由欄位。資金路徑項目（SC-09、SC-10、SC-13、SC-24、SC-29、SU-25）若開放，須 `requires_pending`＋`config_ledger` 留痕。SC-07、SC-11、SC-12 維持 locked（防重複認列成本、稅額總和恆等）。
3. 角色檢查有三種寫法：硬編碼 `role in ("superadmin","admin")`（大宗）、`has_finance_access`／`has_cashier_access`（第 42 班裁示）、`require_any_module`。搬進權限矩陣是一件協調作業（約 3 pd）；最敏感為 SC-40／41（銀行帳號）與 SC-15／16（職責分離）。兩處 superadmin 例外都是使用者明確裁示，應保留為選項，不移除。
4. 未涵蓋：`frontend/js/case-management-dispatch.js` 等派發 UI、`customers.html`／`customer-log.html`（不在 crm 的 module.json）、`procurement.html`、`parts.html`、`helpers/tiered_approval.py`。帶「~」的行號為近似值；`SC/payable_due.py`、`SC/remit.py` 行號由合併列表推得，引用前須再核對。
5. `settings_registry` 目前型別只有 int／float／bool／str（`_TYPES`）。SC-D5、SU-D9、CRM-D8、LG-15 等「可編輯選項清單」須走 S 框架或定義文件，不是 SR。已註冊的兩組（`helpers/settings_groups.py`）可當樣板。
