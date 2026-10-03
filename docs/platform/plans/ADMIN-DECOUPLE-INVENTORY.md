# admin 直通盤點（附錄；唯讀盤點，未改程式）

來源：基底 origin/wip/train-34-int1（2f027536）。三個區各一份，分類 F＝金額可見／出納／財務相關（脫鉤要改）、M＝一般管理（不動）、?＝模糊（待裁示）。筆數為估算。主文件見 USER-PERMISSIONS-PROPOSAL.md。

## 一、案件／分析／CRM

# 盤點 case／analytics／crm（admin 角色判斷）

輔助函式定義（本區所依賴）：
- helpers/auth.py::can_see_financial(user) = role in (superadmin, admin, **sales**) 或 financial_view。連 sales 也直通；函式在區外，需連同改（建議新增 has_finance_access）。
- case_extra_expenses._can_view_row／_amount_viewer：admin 直通，或 cashier／finance（另含申請人、簽核人例外）。
- material_guard.can_edit_orders = (admin+ 或 project_manage) 且 money_visible(actor)。
- quotations._invoice_no_change_allowed：admin 或 cashier／finance。

| 檔案:行 | 函式/端點 | 判斷原文 | 用途 | 分類 | F 改法建議 |
|---|---|---|---|---|---|
| modules/case/api/case_extra_expenses.py:250,252 | _can_view_row | role in (superadmin,admin) or created_by==username；L252 cashier/finance | 額外支出列可見性 | F | 去掉 admin；改 superadmin 或 cashier 或 finance；保留建立者／簽核人例外 |
| modules/case/api/case_extra_expenses.py:262 | _amount_viewer | role in (superadmin,admin) or cashier or finance | 費用單據金額可見 | F | 同上；申請人、簽核人例外維持。attachments.py:92、expense_form_pdf.py:85、quotations.py:4522 經它自動連動 |
| modules/case/api/case_extra_expenses.py:285 | 費用單可用判斷 | role in (superadmin,admin) or expense_forms | 能否開費用單 | ? | A：功能入口＝M；B：費用單即請款付款流程＝F。建議 M（持 expense_forms 即可） |
| modules/case/api/case_extra_expenses.py:305 | _can_modify | role in (superadmin,admin) | 編輯／刪除／送審：本人或 admin+ | ? | A：一般管理 M；B：admin 可改別人填的請款金額＝F。需裁示 admin 是否仍可改別人的費用單 |
| modules/case/api/case_extra_expenses.py:362,371 | list 端點 | can_see_financial(user)／_amount_viewer | 清單金額遮蔽 | F | 改 has_finance_access；確認 sales 是否保留；簽核人例外 |
| modules/case/api/case_extra_expenses.py:428 | picker | show_cost=can_see_financial(user) | 品項選擇器顯示成本 | F | 隨 can_see_financial |
| modules/case/api/case_extra_expenses.py:652,654,658 | 設／改付款日 | _can_modify or cashier；is_admin=role in (superadmin,admin)；not (is_admin or cashier) | 付款日（出納登付款） | F | L654 is_admin 改為 is_superadmin；L658 改 superadmin 或 has_cashier_access；L663 已僅 superadmin。L652 依 L305 |
| modules/case/api/case_extra_expenses.py:1037 | 核准後修改 | _can_modify or cashier | 已核准後改付款相關 | F | 隨 _can_modify；cashier 部分已合規 |
| modules/case/api/case_extra_expenses.py:719 | 作廢 | role != superadmin | 僅 superadmin | M（已合規） | 不動 |
| modules/case/api/case_extra_expenses.py:851 附近 | approve／reject | 純簽核人判斷 | 簽核 | M | 不動 |
| modules/case/attachments.py:92 | 附件遮蔽 | not _xe._amount_viewer | 費用單附件 | F（間接） | 隨 _amount_viewer |
| modules/case/api/expense_form_pdf.py:85 | 費用單 PDF | _amount_viewer | PDF 可見性 | F（間接） | 隨 _amount_viewer |
| modules/case/api/quotations.py:356-362,4293,4319,4410 | _require_financial_view（成本精算／應收應付總覽／銷售訂單） | can_see_financial(user) | 案件財務總覽讀寫 | F（間接） | 改 superadmin／finance；L4325 finalized 已僅 superadmin |
| modules/case/api/quotations.py:6543,6545 | 財務彙總清單 | role not in (superadmin,admin) and not finance；can_see_financial | 財務清單 | F | superadmin 或 finance；第二道隨 can_see_financial |
| modules/case/api/quotations.py:1137 | mark_payment | role not in (superadmin,admin) and not cashier | 標記收款 | F | superadmin 或 has_cashier_access |
| modules/case/api/quotations.py:2836 | 款項明細編輯（收款欄位） | 同上 | 收款欄位寫入 | F | 同上 |
| modules/case/api/quotations.py:3837 | 發票／收據欄位 | 同上 | 開票收款 | F | 同上 |
| modules/case/api/quotations.py:2686 | _invoice_no_change_allowed（用於 L3879） | role in (superadmin,admin) or cashier or finance | 更換發票號碼 | F | superadmin 或 cashier 或 finance |
| modules/case/api/quotations.py:2690,2776 | _payment_items_lock_violation／cashier_payment_only | 註解非 admin 非出納；L2776 cashier | 款項整包存檔鎖 | F（間接） | 與 L2836 同批確認呼叫處 admin 放行 |
| modules/case/api/quotations.py:4174 | request_payment_writeoff | role not in (superadmin,admin) | 申請稅額沖銷 | F | superadmin 或 finance／cashier；需裁示出納可否申請 |
| modules/case/api/quotations.py:4206 | 取消沖銷申請 | role not in (superadmin,admin) | 取消申請 | F | 同 L4174 |
| modules/case/api/quotations.py:4216,4235 | 沖銷核准 | != superadmin | 僅 superadmin | M（已合規） | 不動 |
| modules/case/api/quotations.py:436 | 案件成員判斷 | role in (superadmin,admin) | 案件擁有者直通 | ? | A：一般存取 M；B：admin 直通可進含金額案件（金額欄另由 can_see_financial 擋）。建議 M |
| modules/case/api/quotations.py:1089 | 批次 lookup | role not in (superadmin,admin) 才套 row_access | 案件批次讀取過濾 | ? | 同 L436；需確認回傳是否含金額，建議 M |
| modules/case/api/quotations.py:6163 | 簽核歷史 scope=all | not in (superadmin,admin) | 全公司簽核歷史 | ? | A：M；B：若含請款金額摘要＝F。需看回傳欄位 |
| modules/case/api/quotations.py:6270 | admin+ 端點（未細讀） | not in (superadmin,admin) | 疑為簽核管理 | ? | 請抽驗內容是否涉金額 |
| modules/case/api/quotations.py:1296,1320 | 批次設成員／回簽 toggle | not in (superadmin,admin) | 人員指派／回簽 | M | 不動 |
| modules/case/api/quotations.py:1437 | 刪回簽單 | is_admin=role in (admin,superadmin) | 刪檔 | M | 不動 |
| modules/case/api/quotations.py:2355,2398 | deal_tag 成案切換 | not in (superadmin,admin) | 成案狀態 | M | 不動 |
| modules/case/api/quotations.py:5144,5346,5377 | 動態留言刪／編輯／附件 | role in (superadmin,admin) | 留言管理 | M | 不動 |
| modules/case/api/quotations.py:1700,1900,3133,3177,4897,5061,5065 | 多處 | != superadmin | 僅 superadmin | M（已合規） | 不動 |
| modules/case/api/case_action_items.py:176 | delete_case_action_item | not in (superadmin,admin) | 刪待辦 | M | 不動 |
| modules/case/api/case_action_items.py:61,93,205,210 | 待辦權限 | == superadmin／模組 | 已 superadmin | M | 不動 |
| modules/case/api/completion_notes.py:116 | _require_admin（L273,315,362,389,608,654,673,704,831） | role not in (superadmin,admin) | 完工單管理 | M（待抽驗是否含金額） | 預設不動 |
| modules/case/api/completion_notes.py:649,790 | 核准判斷／刪回簽附件 | role in (admin,superadmin)… | 簽核／刪檔 | M | 不動 |
| modules/case/api/material_orders.py:121,123 | 叫料編輯 | not in (superadmin,admin) and not project_manage；L123 money_visible | 叫料（採購成本）編輯 | ? | A：專案管理 M；B：含成本單價＝F（金額另由 money_visible 擋）。建議 M |
| modules/case/api/material_orders.py:204 | 叫料讀取 | not in (superadmin,admin) and not any(project_manage,cashier,finance) | 叫料讀取（含出納／財務） | F | superadmin 或 project_manage 或 cashier 或 finance |
| modules/case/material_guard.py:106 | can_edit_orders（material_payments.py:58,180 呼叫） | (role in (superadmin,admin) or project_manage) and money_visible | 叫料／匯款申請編輯 gate | F | (superadmin 或 project_manage) 且 money_visible；money_visible 在區外（helpers/financial_mask）需併改 |
| modules/case/api/material_payments.py:58,180 | 匯款申請建立／供應商選單 | MG.can_edit_orders | 匯款申請 | F（間接） | 隨 material_guard |
| modules/case/material_payment.py:436 | 匯款申請撤回 | requestedBy!=user and role not in (admin,superadmin) | 匯款撤回 | F | superadmin 或 has_cashier_access；建單人本人例外 |
| modules/case/material_payment.py:456 | 匯款申請作廢 | role not in (admin,superadmin) and not (草稿且本人) | 額度釋出 | F | 同上 |
| modules/case/material_payment.py:232,236 | 超額覆寫 | == superadmin | 僅 superadmin | M（已合規） | 不動 |
| modules/case/material_approval.py:304 | 叫料單撤回 | requestedBy!=user and role not in (admin,superadmin) | 叫料審核撤回 | ? | A：流程動作 M；B：叫料為成本憑證 F。建議 M |
| modules/case/material_approval.py:320 | 取消已核准叫料單 | role not in (admin,superadmin) | 成本與總帳不再計入 | ? | 同上，影響成本／總帳，偏 F |
| modules/case/material_change.py:436 | 材料變更撤回 | owner 或 role in (admin,superadmin) | 變更申請撤回 | ? | 同 material_approval:304 |
| modules/case/api/material_approvals.py:133 | 送審 | money_visible(user) | 送審需財務檢視權 | F（間接） | 隨 money_visible |
| modules/case/api/material_changes.py:99,118,152 | 變更申請 | money_visible | 同上 | F（間接） | 隨 money_visible |
| modules/case/api/material_links.py:31 | 可連結 PO 行 | show_cost=can_see_financial | 成本顯示 | F | 隨 can_see_financial |
| modules/case/api/settlement_actuals.py:27,55 | 成本精算讀／寫 | can_see_financial(user) | 成本毛利 | F | 隨 can_see_financial |
| modules/analytics/api/dashboard.py:30 | dashboard_stats | can_finance = role in (superadmin,admin) or finance | 儀表板財務數字 | F | superadmin 或 finance |
| modules/analytics/api/dashboard.py:276 | dashboard_monthly | role not in (superadmin,admin) and finance not in mods | 月度營收 | F | 同上 |
| modules/analytics/api/dashboard.py:362 | 財務圖表端點 | 同上 | 財務圖表 | F | 同上 |
| modules/analytics/api/dashboard.py:31,494,769 | can_quotation | role in (superadmin,admin,sales) or quotation | 報價可見 | M | 不動 |
| modules/analytics/api/dashboard.py:588-589,664,768-770,818,932 | is_admin／can_dev_crm／shippingStuck／can_inventory | role in (superadmin,admin) | 待辦／動態／庫存 | M | 不動 |
| modules/analytics/api/reports.py:100-102 | _require_reports_access（11 支報表） | not in (superadmin,admin) and not reports and not finance | 營運報表（稅務匯出、現金部位、客戶歷史） | F | superadmin 或 reports 或 finance；reports 模組目前可給業務，需裁示 |
| modules/analytics/api/reports.py:3797 | bank-reconcile（docstring「僅 admin+」） | 文字；實際判斷未在 grep 中出現 | 對帳動作 | ? | 需在檔內確認實際檢查，預期改 superadmin 或 cashier |
| modules/crm/api.py:97,129 | _require_dev | not in (superadmin,admin) and dev_crm not in mods | 開發案件存取 | M | 不動 |
| modules/crm/api.py:103（_is_admin：331,440,474,626,669,759,974,1005,1037,1058,1099） | CRM 管理 | role in (superadmin,admin) | 開發案件管理／刪除／審核 | M | 不動 |
| modules/crm/api.py:486,508,681,705 | 刪除／改連結審核 | != superadmin | 僅 superadmin | M（已合規） | 不動 |

## 二、承攬／應收應付／會計／薪資

# inv_money 盤點（subcontract / arap / accounting / payroll；排除 tests；路徑相對 backend）

註：`require_any_module()`（helpers/auth.py:162）本身只讓 superadmin 直通、admin 已不直通，不需改；下表不列。`user_has_module(…, "cashier"/"finance")` 單獨出現（無 admin 並列）者亦不需改，只在「已正確」節列出。
`can_see_financial`（helpers/auth.py:197）本體含 `role in (superadmin, admin, sales)`，不在本區範圍，但本區 4 處呼叫它；改法在 helpers 一處改，見 F-1。

## 表

| 檔案:行 | 函式/端點 | 判斷原文 | 用途 | 分類 | F 改法建議 |
|---|---|---|---|---|---|
| helpers/auth.py:197（本區呼叫處見下 4 列） | can_see_financial | `role in ("superadmin","admin","sales") or financial_view` | 案件財務金額可視 | F（範圍外，但本區依賴） | 改為 superadmin 或持 finance/cashier/financial_view；注意 sales 仍直通要不要留（?-1） |
| modules/subcontract/api/contractor_vouchers.py:73 | _voucher_visible 類（承攬商付款可視） | `not can_see_financial(user) and not is_document_approver(...)` | 金額層：非財務者且非簽核人看不到匯款單 | F（間接） | 隨 can_see_financial 改；簽核人例外（is_document_approver）必須保留 |
| contractor_vouchers.py:87 | _voucher_public | `if can_see_financial(user)` | 決定回不回金額欄位 | F（間接） | 同上；簽核人看金額的現行行為不動 |
| contractor_vouchers.py:234 | GET /api/contractor-vouchers/remit-fee-total | `if not can_see_financial(user): 403` | 案件已匯款手續費合計（成本） | F（間接） | 同上 |
| contractor_vouchers.py:142 | _require_admin（定義） | `role not in ("superadmin","admin")` | 匯款申請建立/送審等閘門 | F | 新 helper：改 `has_finance_access(user)`（superadmin 或 finance；是否含 cashier 見 ?-2）|
| contractor_vouchers.py:306 | POST /api/contractor-vouchers 建立匯款申請 | `_require_admin(user)` | 建匯款憑證（含金額） | F | 同 142（誰來「申請」見 ?-2：現為 admin，可能實為業務／採購負責人） |
| contractor_vouchers.py:458 | POST …/preview 分期試算 | `_require_admin(user)` | 試算匯款金額／稅額 | F | 同 142 |
| contractor_vouchers.py:480 | DELETE …/{voucher_no} | `_require_admin(user)` | 刪匯款申請 | F | 同 142 |
| contractor_vouchers.py:512 | PATCH …/{voucher_no}/invoice | `_require_admin(user)` | 登分期發票號/日（影響 E04 認列分錄） | F | 同 142（finance） |
| contractor_vouchers.py:546 | POST …/{voucher_no}/void | `_require_admin(user)` | 作廢匯款申請；已付款先撤銷 | F | 同 142（finance；撤銷付款是否需 cashier 見 ?-2） |
| contractor_vouchers.py:579 | POST …/{voucher_no}/submit | `_require_admin(user)` | 送審 | F | 同 142 |
| contractor_vouchers.py:753 | POST …/{voucher_no}/revoke-approval | `_require_admin(user)` | 撤銷核准退草稿 | F | 同 142 |
| contractor_vouchers.py:874 | POST …/{voucher_no}/export | `_require_admin(user)` | 匯出匯款憑證（含金額）記錄 | F | 同 142（finance 或 cashier 任一較合理） |
| contractor_vouchers.py:964 | GET …/{voucher_no}/personnel-links | `role not in (superadmin,admin) and not user_has_module(cashier)` | 出納頁挑勞報單（匯款金額） | F | 改 `has_cashier_access(user)`（superadmin 或 cashier）；視需要加 finance |
| contractor_vouchers.py:998 | POST …/{voucher_no}/personnel-link | 同上 | 匯款單關聯勞報單 | F | 同上 |
| contractor_vouchers.py:1061 | paid-toggle（標記已匯款/核可差額） | `role not in (superadmin,admin) and not user_has_module(cashier)`；註解稱「額外放行 cashier」 | 標記已匯款（出納執行動作） | F | `has_cashier_access`；注意 action 含差額審核 approve/reject（與 cashier.py:231 同性質，見 ?-3）；錯誤訊息「管理員或出納」改「出納」 |
| contractor_vouchers.py:942 | GET …/settings/remit-require-payslip | `role not in ("superadmin","admin")` | 讀「個人外包匯款是否強制勞報單」開關 | M | 不動（PUT 已 superadmin）；若畫面僅出納頁用可改 cashier/finance（?-5） |
| contractor_vouchers.py:695 / 951 | approve 無鏈分支 / PUT 開關 | `role != "superadmin"` | 最高管理者專屬 | M（已正確） | 無 |
| subcontract/api/remit_kinds.py:16 | GET /api/remit-kinds | `role not in ("superadmin","admin")` | 取目前啟用的匯款款別（匯款申請畫面用） | ? | 解讀A：款別是匯款設定資料，屬一般管理 M；解讀B：只有建匯款申請的人用，隨 contractor_vouchers 的 _require_admin 改成 finance 才不會「建得了卻拿不到款別」 → 建議跟 142 同步（?-2） |
| remit_kinds.py:31 | GET …/definition | `role != "superadmin"` | 款別定義 | M（已正確） | 無 |
| subcontract/api/dispatch_approval.py:81 | _require_dispatch_user | `require_any_module(procurement/case_manage/contractor_list)` + `role not in (superadmin,admin)` | 派工審核（簽核流程）操作者閘門 | M | 不動（派工管理）。注意：派工審核流程金額由簽核人看，非 admin 簽核人走 :293 `_require_user`（不看角色），改 admin 不影響 |
| dispatch_approval.py:265 | 撤回/取消 | `role != "superadmin" and requestedBy != username` | 申請人或 superadmin | M | 無 |
| subcontract/api/vendor_contractors.py:26/31 | _require_admin（定義；各檔各自定義） | `role not in ("superadmin","admin")` | 派發建立/修改/文件/發票上傳閘門 | M（整體），其中發票類 ? | 見下列各端點 |
| vendor_contractors.py:555 | POST /api/contractor-dispatches | `_require_admin` | 建派工（含金額，後凍結進匯款憑證） | M（?-4：金額欄位） | 派工管理，照舊 |
| vendor_contractors.py:610 | PUT /api/contractor-dispatches/{did} | `_require_admin` | 改派工 | M | 照舊 |
| vendor_contractors.py:690 | DELETE dispatch | inline role 判斷 | 刪派工 | M | 照舊 |
| vendor_contractors.py:726 / 822 | dispatch files 上傳/刪除（報價/估價文件） | `_require_admin` | 報價文件管理 | M | 照舊 |
| vendor_contractors.py:1019 / 1051 / 1085 | dispatch invoice-files 上傳/刪除、invoice-date | `_require_admin` | 廠商發票附件與發票日（發票日影響應付認列） | ? | A：派工管理的附件，M；B：發票日決定 E04 應付認列分錄，屬會計 → F 改 finance（?-4） |
| vendor_contractors.py:1123 | PATCH …/accept 驗收 | inline role 判斷 | 待驗收/驗收 | M | 照舊 |
| vendor_contractors.py:1169 | POST …/status | inline role 判斷 | 派發狀態 | M | 照舊 |
| vendor_contractors.py:223/273/301/350/361/379/420/453 | 廠商名冊 list/create/update/隱私聲明/停用/存摺/刪除 | inline `role not in (superadmin,admin)` | 廠商主檔管理（含存摺＝銀行帳號） | M | 照舊（存摺圖/帳號遮罩見 bank_mask.py 已 superadmin） |
| vendor_contractors.py:1236/1269 | GET dispatch cost（COST_VIEW_MODULES） | `require_any_module(finance,cashier,procurement,case_manage,contractor_list)` | 派工成本檢視 | ?（已無 admin 直通） | 成本屬金額；現行 procurement/case_manage/contractor_list 持有者即可看。是否收窄到 finance/cashier（?-4）；與 admin 無關 |
| modules/arap/api/cashier.py:43 | _require_view_access | `role not in (superadmin,admin) and not cashier and not finance` | 出納頁所有「查看」端點閘門 | F | 改 `has_cashier_access(user) or has_finance_access(user)`（刪 admin） |
| cashier.py:79 | _can_pay | `role in (superadmin,admin) or user_has_module(cashier)`（註「finance 只能看」） | 登錄付款／paid-toggle／canPay | F | 改 `has_cashier_access(user)`；finance 維持只能看 |
| cashier.py:131 | 收款人銀行帳號是否遮罩 | `superadmin or (role != "admin" and cashier)` | 完整帳號僅最高管理者與出納 | F（已把 admin 排除） | 可簡化為 `has_cashier_access(user)`（admin 角色不再有 cashier 樣板後 `!= "admin"` 可刪）；行為不變。注意：若 admin 角色仍預設帶 cashier 模組，須先確認樣板 |
| cashier.py:205 `_is_admin` / :224 canDecide / :231 | 差額待審核清單 canDecide、核可/退回 | `role in ("superadmin","admin")` | 實付≠應付差額的核可/退回 | F | 決策者要誰？見 ?-3：A superadmin only；B superadmin 或 finance；C 加 cashier（不建議：自己匯自己核可）。注意 remit.py:8-9 docstring/通知對象「admin」文字也要改 |
| cashier.py:58 `_bonus_visible` / :369 `_payslip_visible` / :407 canMarkPaid | 獎金/勞報單可視、標記已發放 | `superadmin or user_has_module(cashier)` | 已正確 | M（已正確） | 無 |
| cashier.py:683 | POST bank-reconcile 銀行對帳 | `role not in (superadmin,admin) and not cashier` | 銀行對帳單比對（金額） | F | `has_cashier_access`（finance 是否可對帳見 ?-3 同類） |
| modules/arap/api/invoice_vouchers.py:71,97,116 | 開票憑證可視 | `can_see_financial(user) or is_document_approver` | 金額層 | F（間接） | 隨 can_see_financial；簽核人例外保留 |
| invoice_vouchers.py:141 | _require_admin（定義） | `role not in ("superadmin","admin")` | 開票憑證操作閘門 | F | 改 `has_finance_access(user)`（或 finance+cashier 任一，?-2） |
| invoice_vouchers.py:306/463/488/659/775 | 開票憑證 建立/修改/…/送審/撤銷等 | `_require_admin(user)` | 開票憑證操作（應收、發票金額） | F | 同 141 |
| invoice_vouchers.py:602 | 核准無鏈分支 | `role != "superadmin"` | 最高管理者專屬 | M（已正確） | 無 |
| modules/arap/api/payment_requests.py:73,87 | 請款單可視 | `can_see_financial` | 金額層 | F（間接） | 隨 can_see_financial |
| payment_requests.py:139 | _require_admin（定義） | `role not in ("superadmin","admin")` | 請款單操作閘門 | F | 同 invoice_vouchers 141 |
| payment_requests.py:366/462/556/581/751/867 | 請款單 建立/修改/送審/撤銷/匯出等 | `_require_admin(user)` | 請款單操作（應收金額） | F | 同 141 |
| payment_requests.py:694 | 核准無鏈分支 | `role != "superadmin"` | 已正確 | M | 無 |
| modules/accounting/api/accounting_export.py:223 | GET /api/settings/t100-export-config | `role not in ("superadmin","admin")` | 讀 T100 匯出科目代號設定 | F | 會計設定：改 superadmin 或 finance（PUT :239 已 superadmin） |
| accounting_export.py:491-493 `_require_t100_admin` | 被 :512/:536/:562/:591/:622 呼叫 | `role not in ("superadmin","admin")`，訊息「財務報告僅管理員以上」 | T100 傳票匯出 vouchers/preview/confirm/confirmed/unconfirm | F | 改 `has_finance_access(user)`（confirm/unconfirm 寫入是否限 superadmin 見 ?-5） |
| modules/payroll/api/bonus.py:62-73 `_is_manager` | 被 :503/567/669/1052/1115/1444/1502 及 :780 can_create_award 呼叫 | `role in ("superadmin","admin")` | 獎金基數、規劃、產生分潤單、預覽/PDF（金額） | ? | A：admin 仍可「產生」獎金單（BN9 現狀，讀已收緊到 superadmin 但寫仍 admin）→ 屬一般管理不動；B：基數/毛利/PDF 本質是金額，依使用者裁示應改 superadmin 或 finance（?-1）。:503 get_bonus_base、:1444/1502 preview/pdf 讀金額，最傾向 F |
| bonus.py:93 `_sees_all_lines` 等、其餘 require_superadmin=True | 已 superadmin | M（已正確） | 無 |
| bonus.py:2430、bonus_correction.py:51/108/376、payslips.py:579/685、payroll/attachments.py:27/52 | `superadmin or cashier` | 已正確 | — | M（已正確） | 無 |
| modules/payroll/bank_account.py:89-98 | may_see/may_edit | `superadmin or finance or cashier` | 已無 admin | M（已正確） | 無 |
| modules/subcontract/bank_mask.py:17、payslip_bank.py:17、attachments.py:133、dispatch_flow.py:129/142 | superadmin 專屬或模組 | 已正確 | — | M（已正確） | 無 |
| modules/accounting/api/ledger_*.py、vouchers.py、voucher_common.py、attachments_catalog.py | `require_any_module(cashier/finance)`＋superadmin 專屬動作 | 已無 admin 直通 | — | M（已正確） | 無 |
| modules/subcontract/remit.py:8-9（註解） | docstring | 「通知 admin、admin／superadmin 核可」 | 差額審核通知對象 | F（文字/通知對象） | 配合 cashier.py:231 決策後，同步改通知對象與註解；需看 remit.py 通知邏輯是否以 role 查 admin（本檔未見 role 字面，通知可能在 contractor_vouchers 或 helpers） |

## 統計（以「判斷點」計，同一 `_require_admin` 的多個呼叫端點各算一筆）
- F：contractor_vouchers 13（73,87,234 間接 3＋_require_admin 定義 1＋呼叫 8＋cashier 類 3 實為 964/998/1061 → 另計）— 見下方精確數
- 精確數：F＝約 45 筆（contractor_vouchers 16、invoice_vouchers 9、payment_requests 9、cashier 6、accounting_export 7＋1、remit.py 文字 1，含 can_see_financial 本體間接依賴）；M＝約 35 筆（含已正確的 superadmin/模組判斷與 vendor_contractors 派工/名冊管理）；?＝6 筆（bonus _is_manager 群、remit_kinds:16、dispatch invoice 三支、COST_VIEW_MODULES、can_see_financial 的 sales）

## 最需裁示的模糊點
1. bonus `_is_manager`（bonus.py:62）：admin 產生獎金單／看基數、預覽、PDF（讀金額）。BN9 已讓 admin 讀不到別人那列，但基數/預覽/PDF 仍可見；全改 superadmin（建議讀類端點），產生單是否也收回？
2. 誰是「匯款申請／開票／請款」的操作者（contractor_vouchers／invoice_vouchers／payment_requests 的 `_require_admin`，共 3 檔約 27 個端點）：改 finance 單一，還是 finance 與 cashier 任一？cashier 是否可建立/作廢（現只能標已匯款）？remit_kinds GET 要同步。
3. 差額審核（cashier.py:231、contractor_vouchers paid-toggle 的 approve/reject）：核可/退回者＝僅 superadmin？或 superadmin＋finance？cashier 不可（自匯自核）。與 remit.py 通知「admin」對象連動。
4. 派工金額/成本/發票日：vendor_contractors 派工建立修改、發票日（1085）、COST_VIEW_MODULES 成本檢視，視為 M（派工管理）還是 F（金額、應付認列）？
5. T100 傳票匯出與設定（accounting_export.py:223、493）及 confirm/unconfirm：改 finance 即可，還是 confirm/unconfirm（寫入）僅 superadmin？另 can_see_financial 的 `sales` 角色直通是否保留（helpers，範圍外但影響本區 4 處）。

## 三、核心（helpers／routers／supply／前端）

# inv_core：admin 角色判斷盤點（backend helpers/routers/main/db/supply/lodging/tools ＋ 前端）
行號為 D:\開發測試檔\w1-fd 當下工作樹。分類 F＝金額/出納/財務（要改）、M＝一般管理（不動）、?＝模糊。

## 先講結論：user_has_module / require_any_module 對 admin 的行為
- `user_has_module(user,key)`（helpers/auth.py:151）：只解析 `user["modules"]` JSON 比對 key，完全不看 role；admin 不被當成自動擁有任何模組。
- `require_any_module`（auth.py:162-194）：只有 `role=="superadmin"` 直通；admin 必須持有 keys 之一，否則 403（2026-09-14 使用者裁示已取消 admin 直通）。
- `_require_user(..., require_superadmin=True, module=)`（auth.py:218-247）：只放行 superadmin 或持有該 module 者；admin 不直通。
- 但 admin 角色樣板（module_registry.py:85）預設含 finance、financial_view、cashier、reports，db.py:3883 的啟動回填 `if role=="admin": add += admin_template` 會把這些補給既有 admin 帳號。所以模組制檢查之下 admin 仍「實際持有」cashier/financial_view。要真正脫鉤，除了改程式，還要改樣板並決定是否回收既有 admin 帳號的這些模組（需使用者確認）。
- 殘留的 admin 直通全在寫死 role 比較：can_see_financial、前端 canSeeFinancial／canMarkPayment／cashier.js／reports.js 等。

## A. 後端
| 檔案:行 | 函式/端點 | 判斷原文 | 用途 | 分類 | F 的改法建議 |
|---|---|---|---|---|---|
| helpers/auth.py:214 | can_see_financial | `role in ("superadmin","admin","sales") or user_has_module(user,"financial_view")` | 案件財務金額（成本/毛利/應收應付/銷售訂單）可見 | F | 改為 `role=="superadmin" or user_has_module(financial_view)`。同列 sales 也直通，使用者只講 admin，sales 去留需裁示。連動呼叫者：approval_queue、custom_records、financial_mask.money_visible、case 模組 |
| helpers/auth.py:155 | user_has_module docstring | 範例含 `("superadmin","admin")` | 註解範例 | M | 順手改註解 |
| helpers/financial_mask.py:40 | money_visible | `can_see_financial(user) or user_has_module(user,"cashier")` | 案件頁金額遮蔽（CM13） | F（間接） | 免改，隨 can_see_financial 連動；cashier 持有者維持可見 |
| helpers/expense_types.py:342 | _is_cashier | `role=="superadmin"` 或 modules 含 cashier | 出納專屬欄位可填 | F（已合規） | 無 admin 直通，免改 |
| helpers/row_access.py:31,76 | ADMIN_ROLES / _bypass | `ADMIN_ROLES=("superadmin","admin")`；`role in ADMIN_ROLES: return True` | row_access 所有登錄表（case、dev_case…）的 owner/read 旁路 | ? | A：只管「看不看得到案件列」屬一般管理 ⇒ M；B：案件列含金額，但金額另由 money_visible 遮蔽，不在此處 ⇒ 仍 M。建議 M，請確認 |
| helpers/case_access.py:101,166,230,243,258,270 | CASE_ACCESS / SUMMARY_PURPOSE_MODULES | 走 row_access；`("cashier","finance")` | 案件讀取規則 | M | 無 admin 字面，已是模組制 |
| helpers/custom_builder_support.py:23,40,43,181 | VISIBLE_ROLES / can_see_field | `VISIBLE_ROLES=("superadmin","admin",...)`；只 superadmin 直通 | 自訂欄位/選單 visibleTo 可選角色清單 | M | admin 未直通，不動 |
| helpers/mail_types.py:25 | ROLES | 角色清單含 admin | 信件類型合法角色 | M | 不動 |
| routers/mail_settings.py:170 | receivable | `"admins": role in ("admin","superadmin")` | 郵件群組「管理員」收信 | M | 不動 |
| helpers/email_notify.py:242 | _users_emails 群組 | `role IN ('admin','superadmin')` | admins 群組寄信 | ? | A：一般通知 ⇒ M；B：若 group=admins 的事件含付款/匯款通知，應改依 cashier/finance 模組挑收件人。需查哪些 mail_type 用 admins 群組 |
| helpers/module_registry.py:85 | admin 角色樣板 | 含 finance, financial_view, cashier, reports | admin 預設模組 | F（資料面） | 從樣板移除財務類模組；既有帳號是否回收需使用者確認 |
| db.py:3883 | 模組回填 | `if role == "admin": add += admin_template` | 啟動補模組 | F（資料面） | 樣板改了就不再補；已補的不會自動移除，需另做 migration |
| db.py:1051 | _m007 role_labels | `"admin": "管理員"` | 顯示名稱 | M | 不動 |
| db.py:4583,4597 | bonus 表 | `category IN ('sales','project','admin')` | 獎金分類，非角色 | M（非角色） | 不動 |
| routers/approval_queue.py:52 | 簽核佇列項目可見 | `role in ("superadmin","admin")` ⇒ True | admin 看到所有簽核單 | ? | A：簽核可見性屬一般管理 ⇒ M；B：單含匯款金額，但金額已由下行 _can_see_queue_money 遮蔽 ⇒ 仍 M。建議 M |
| routers/approval_queue.py:303 | _can_see_queue_money | `can_see_financial(user)` 或本單簽核人 | 簽核單金額遮蔽 | F（間接） | 隨 can_see_financial 連動 |
| routers/custom_records.py:376-379 | custom_finance_of_case | `if not can_see_financial(u): 403` | 自訂模組案件入帳金流 | F（間接） | 連動，免改 |
| routers/item_reads.py:177 | _visible_keys | `role in ("superadmin","admin")` | 未讀標記可見 key | M | 不動 |
| routers/map_points.py:573 | 地圖快取鍵 | `role not in ("superadmin","admin")` | 快取鍵含使用者 | M | 不動 |
| routers/module_versions.py:13-19 | _require_admin | `_ROLE_RANK admin=2` | 模組版本管理 | M | 不動 |
| routers/search.py:22,31,39,60,68 | global_search | `is_admin = role in ("superadmin","admin")` | 全域搜尋客戶/供應商/開發案/料號 | M | 不動（無金額欄位） |
| routers/system.py:239 | get_operating_targets | `role not in ("superadmin","admin")` ⇒ 403 | 年度營運目標（營收/毛利目標）查閱 | ? | A：管理設定 ⇒ M；B：內含營收/獲利目標數字屬財務金額 ⇒ F，改 superadmin 或 finance/financial_view |
| routers/system.py:653,680,710,760 | work_logs 修改/刪除 | `role not in ("superadmin","admin") and id != owner` | 工作日誌 | M | 不動 |
| routers/system.py:2621,2698 | custom roles / role labels | `_VALID_BASE_ROLES`、`"admin": "管理員"` | 角色名單 | M | 不動 |
| main.py:556 | idle timeout | `is_high_priv = role in ("superadmin","admin")` | 閒置逾時 2h vs 8h | M | 不動 |
| modules/supply/api/inventory.py:45,569 | _require_admin → toggle_batch_paid | `role not in ("superadmin","admin")` | 進貨批次「標記已付款」 | F | 改為 `superadmin or user_has_module(cashier/finance)`（拆專用檢查，勿動共用 _require_admin） |
| modules/supply/api/inventory.py:414,530 | create_batch / update_batch_header | 同 _require_admin | 進貨批次建立/修改（含進價、單價） | ? | A：進貨作業 ⇒ M；B：批次含成本金額 ⇒ F。請裁示 |
| modules/supply/api/inventory.py:614,671 | adjust / delete stock item | 同 _require_admin | 庫存調整/刪除 | M | 不動 |
| modules/supply/api/shipping_notes.py:56（用於 :241,258,291,317,342,568,671,693,727） | _require_admin | `role not in ("superadmin","admin")` | 出貨單建立/編輯/刪除/送審/匯出/回簽 | M | 不動 |
| modules/supply/api/shipping_notes.py:666 | download_shipping_pdf | `role in ("admin","superadmin") or is_document_approver` | 出貨單 PDF | M | 不動 |
| modules/supply/api/shipping_notes.py:816 | 刪除回簽附件 | `role not in ("superadmin","admin")` | 刪附件 | M | 不動 |
| modules/supply/api/suppliers.py:37 | list_suppliers | `role not in ("superadmin","admin")` ⇒ [] | 供應商清單 | M | 不動 |
| modules/lodging/api_records.py:33,123,161 | _ADMIN_ROLES | `("superadmin","admin")` | 旅宿搜尋紀錄可見 | M | 不動 |
| helpers/startup.py:222 | FRESH_ADMIN_USERNAME | `"admin"` | 預設帳號名字串 | M（非角色） | 不動 |
| tools/audit_account_permissions.py:7,48 | 稽核工具 | `WHERE role IN ('superadmin','admin')` | 列高權限帳號 | M | 不動；可選：新增「admin 且持 cashier/financial_view」清單方便回收核對 |
| helpers/tiered_approval.py、custom_def_review.py、custom_modules.py、approval_delegates.py、routers/auth.py、definitions.py 等 | — | 皆 `== "superadmin"` | 無 admin 直通 | M | 免改 |

## B. 前端對應處（相對 frontend/）
| 檔案:行 | 函式 | 判斷原文 | 用途 | 分類 | F 的改法建議 |
|---|---|---|---|---|---|
| js/case-management-core.js:69-72 | canSeeFinancial() | `modules.includes('financial_view') \|\| ['superadmin','admin','sales'].includes(role)` | 案件頁 KPI 金額、財務分頁、額外支出分頁（與後端 can_see_financial 逐字對應） | F | 與後端同步：`role==='superadmin' \|\| modules.includes('financial_view')`（sales 同後端裁示）。連動 case-management.html:86,121,512,516,612,1466,2155 與 close.js:16-19 |
| js/case-management-core.js:782 | canMarkPayment() | `['superadmin','admin'].includes(role) \|\| hasModule('cashier')` | 案件頁標記收款 | F | 改 `role==='superadmin' \|\| hasModule('cashier')` |
| js/case-management-close.js:138,140 | — | `_hasModule('cashier') \|\| _hasModule('finance')` | 結案憑證流 | F（已合規） | 免改 |
| js/case-management-xexp.js:265 | xeCanModify | `['superadmin','admin'].includes(role) → true` | 額外支出可否修改（後端 _can_modify 為準） | ? | A：額外支出=案件成本單據屬財務 ⇒ F，需與 case 區後端同步；B：僅單據編修權 ⇒ M |
| js/cashier.js:148-156 | isAdminPlus / hasCashierAccess / canExecuteCashier | `r==='admin'\|\|'superadmin'`；`isAdminPlus \|\| cashier \|\| finance` | 出納頁進入/執行 | F | isAdminPlus 改僅 superadmin；hasCashierAccess=`superadmin\|\|cashier\|\|finance`；canExecuteCashier=`superadmin\|\|cashier` |
| js/reports.js:421-429,481,1231 | isAdminPlus / hasCashierAccess / loadData | 同上 | 營運報表 11 個財務頁籤＋出納頁籤進入 | F | 財務報表頁籤改 `superadmin \|\| 某財務模組`（用 finance/financial_view/reports 哪個需裁示）；出納頁籤同 cashier.js |
| pages/reports.html:340,2060 | isAdminPlus() | 財務 KPI 摘要 | 財務 KPI 顯示 | F | 隨 reports.js |
| pages/case-management.html:1800,1805 | 申請請款單／申請開立發票按鈕 | `['superadmin','admin'].includes(role) && !arapMissing` | 案件頁請款/開票入口 | F | 改 superadmin 或 finance/cashier 模組，對齊 arap 後端門檻 |
| pages/case-management.html:1997 | 沖銷（稅額歸零）申請 | `['superadmin','admin'].includes(role)` | 發票沖銷 | F | 同上 |
| pages/case-management.html:2075,2141 | 請款單/發票憑證操作列 | 同上 | 憑證狀態操作 | F | 同上 |
| pages/case-management.html:3005 | 匯款申請區塊 | `_cvRowVisible(d) && ['superadmin','admin'].includes(role)` | 承攬派發匯款申請 | F | 改 superadmin 或 cashier/finance；對齊 subcontract contractor_vouchers |
| js/case-management-dispatch.js:381 | loadRemitKinds | `!['superadmin','admin'].includes(role) return` | 載入匯款類型 | F | 改 superadmin 或 cashier/finance；對齊 subcontract remit_kinds |
| pages/case-management.html:2974,2989 | 派發「上傳報價」等 | `['superadmin','admin'].includes(role)` | 派發單上傳報價 | ? | A：一般派發作業 ⇒ M；B：報價是承攬金額 ⇒ F |
| pages/vendor-contractors.html:651 | 頁面進入閘 | `!['superadmin','admin'].includes(role)` ⇒ 退出 | 承攬商管理頁（含銀行帳號/付款資訊） | ? | A：主檔管理 ⇒ M；B：含銀行帳號/付款 ⇒ F；後端在 subcontract 區，需對齊 |
| js/case-management-exec.js:211 | moShowCancel | `已核准 && admin+` | 材料單作廢 | ? | 牽涉材料付款（case 區），預設 M，與 case 區對齊 |
| js/case-management-exec.js:291,1405 | moCanEdit / netplan | `admin+ \|\| project_manage／netplan_edit` | 工程執行/網路規劃編輯 | M | 不動 |
| js/case-management-core.js:255 | canDeleteSignedBack | admin+ 或上傳者 | 刪回簽附件 | M | 不動 |
| js/case-management-feed.js:207 | canDeleteAttachment | admin+ | 刪動態附件 | M | 不動 |
| js/case-management-list.js:273 | canBatchAssign | admin+ | 批次分派案件 | M | 不動 |
| pages/case-management.html:1415,1445,1451 | 行動項刪除／指派成員 | admin+ | 案件成員指派 | M | 不動 |
| pages/case-management.html:3077,3122-3303 | 出貨單操作 | admin+ | 出貨單 | M | 不動 |
| pages/quotation-form.html:922,1088,3015,3280,3587 | 匯出記錄／回簽／成案降級／附件 | admin+ | 報價單管理操作 | M | 不動 |
| pages/quotations.html:151,310,311,538,670-678 | 篩選/成案標記/刪除 | admin+ | 報價單列表管理 | M | 不動 |
| pages/approval-queue.html:1046；approval-history.html:150 | isAdmin | admin+ | 簽核佇列/歷史「全部」範圍（對應後端 approval_queue:52） | ? | 與 approval_queue:52 同裁示，預設 M |
| pages/dev-crm.html:1580 等、tender-radar.html:717、daily-tasks.html:2762、module-versions.html:695、network-plan-form.html:631、work-log.html:293、users.html（多處） | 各 isAdmin | admin+ | CRM/標案/日誌/模組版本/網路規劃/帳號管理 | M | 不動 |

## C. 統計（以判斷點計；連動呼叫端不重複算）
- F：後端 4（can_see_financial、module_registry 樣板、db.py 回填、inventory toggle_batch_paid）＋間接連動 4（money_visible、approval_queue:303、custom_records:379、_is_cashier 已合規）；前端 11 組（canSeeFinancial、canMarkPayment、cashier.js、reports.js、reports.html、case-management.html 請款/開票/沖銷/憑證/匯款、dispatch.js:381）。
- M：後端約 22、前端約 16。
- ?：後端 6（row_access、email_notify admins、approval_queue:52、operating-targets、inventory create/update batch）；前端 5（xexp:265、派發上傳報價、vendor-contractors 頁閘、moShowCancel、approval isAdmin）。
