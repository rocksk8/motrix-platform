# 稽核：C 的 M01 ④——SO 提示、D 兩項補題、拿掉 M01 之後的處置（wip/c-m01-4 221adaa0；疊在 ③ 8999d769 上）（D，2026-09-27 03:07）

> 完整稽核，也是 M01 的最後一包：D1 的 M01「拿掉照常」看它。稽核者 D 沒有寫過任何受稽核的程式碼。
> 反向控制用 sparse 工作樹（`!/backend/modules/case/`，不刪檔），基準是 221adaa0。

## 0. 結論

- **必修 3、建議 2、觀察 4**。
- 主持已在 D 的中間通報後裁示 M4-M3 在 ④ 內處置；C 會連同 M4-M1、M4-M2 推 `wip/c-m01-5`。
- **複核重點**：M01 在時，每檔實際執行的題數要與改前相同。D 已存下改前的逐檔基準，見 §4。

## 1. 主持重點

| # | D 的驗證 | 結果 |
|---|---|---|
| CA3-M1 複核 | netplan 題改用 `_without`，拿掉後斷言 `single_provider is None`。其餘直接動 `_LEGACY_PROVIDERS` 的題抽查：arap／payroll 的過濾式另外改了 `providers` 或有事後斷言；`dispatch_row_provider:47` 的 `{}` 驗的是登錄表規則本身；`custom_modules:477` 是 L1 的 import 時登記 | **CA3-M1 關閉** |
| §5-5 三類處置（tests/platform） | 真刪 M01：**1171 過、64 skip、5 紅＝§B-11 允許的 5 題**，與 C 相同。skip 理由逐項列出（§2 附表），抽查見 M4-S1 | 成立 |
| 「略過」有沒有其實該改驗不在時行為的 | M01 提供給別人的每個能力，在 M01 不在時消費端都至少有一題實際在跑：`case.access`（404）、`case.locations`（地圖說明原因）、`attachments.for_document`（缺席點名）、`daily.check`、`calendar.writeback`（沒有擁有者時不寫）、`case.recognition`（報表說明原因）、`default_terms`、`doc_version`。兩題附件題的略過理由不精確 ⇒ M4-S1 | 大致成立 |
| SO 提示＋e2e | 真刪樹 `/api/sales-orders` 確實回 404（JSON，不是被靜態檔接走）。突變 SO3「拿掉 404 判斷」⇒ 紅（④ 驗收字面成立）。**SO1「提示不顯示」、SO2「選單不停用」⇒ 存活**；正對照題在真刪樹會紅 ⇒ M4-M1 | **不成立** |
| D 兩項補題 (a)(b) | 突變 ED1「遮蔽只看 id、不看 dataUrl」⇒ 紅；ED2「簽核鏈讀不出來當成空鏈」⇒ 紅 | 成立 |
| 真刪 M01 後 tests/platform 只剩允許 5 題 | 實跑確認 | 成立 |
| 真刪 M01 後 e2e | 全部 e2e（-n 2，35 分）：312 過、172 failed＋12 errors。扣掉 D 探針、其他題留下的探針檔（見 M4-O3），以及已在非 e2e 清單的 13 檔之後，**e2e 專屬 78 檔 166 項**。M01 在時的對照見 §3 | 見 M4-M3 |
| **tests/platform 以外**（PLAYBOOK §G 第 5 步：真刪範圍＝tests/platform＋提到該模組的檔） | 其他模組的 `modules/*/tests`：**36 檔 87 項紅**。tests/（排除 platform，整個目錄）：**98 檔 614 項紅**（已排除 M01 在時也紅的 cm12×2、subproc_helper、vr1）。多出的檔在 M01 在時對照：687 過 | **M4-M3** |

## 2. 發現

**M4-M1（必修）　SO 提示的 e2e 只驗模型，而且正對照在真刪樹必紅**
- 兩題都斷言 `Alpine.$data(...).casesNotice`，沒有看畫面：
  - SO1 把提示改成 `x-show="false"`，使用者看不到原因 ⇒ 存活；
  - SO2 拿掉選單的 `:disabled` ⇒ 存活。
- ④ 的驗收是「e2e 驗提示」，驗的應該是使用者看到的東西（〈e2e 假綠燈〉）。
- 修法：
  - 開啟新增表單後，斷言 `[data-testid=cases-unavailable]` 可見、文字正確，而且選單 disabled；
  - 正對照斷言提示不可見、選單可用；
  - `wait_for_timeout(300)` 改成等終點狀態。
- `test_no_notice_when_the_case_module_answers` 在真刪樹**紅**：M01 真的不在時，`/api/sales-orders` 就是 404。正對照要標記需要 M01，或者也用 route 回 200 模擬。

**M4-M2（必修）　§2-C「別人的頁面呼叫 M01 API」只做了 SO 這一列**
- M01-PLAN §2-C 列了 6 個呼叫方，每一列都寫了「M01 不在時」該有的行為；④ 只做了 M12 每日工作頁。
- `network-plans.html` 與 SO 同型：
  - 新增規劃書預設 `createMode='case'`；
  - `loadCaseOptions` 在 `!r.ok` 時什麼都不做，案件選單就是一個看起來「沒有已成案案件」的空清單。
- 其餘各列：
  - `payment-request-form.html` 的 `loadQuoteInfo` 非 ok 時靜默留白；
  - `reports.js` 精算彈窗 404 時跳泛用錯誤；
  - `cashier.js` 對 `/api/quotations/.../payment` 的呼叫沒有 404 分支；
  - `notif.js` 只是搜尋類型，不呼叫 M01 端點，不需要處理。
- 至少網路規劃頁要比照 SO（明說原因、選單停用，並補 e2e）。其餘各列逐一處置，或在 §2-C 註明為什麼不需要。

**M4-M3（必修，主持已裁示在 ④ 內處置）　tests/platform 以外，拿掉 M01 之後沒有處置**
- 非 e2e：modules/*/tests 36 檔 87 項＋tests/ 98 檔 614 項；e2e 專屬 78 檔 166 項。逐檔清單已交給 C，也附在 §5。
- 產品行為都符合裁示（明說原因，或依 CA-M1 條件 3 回 404），紅燈都是題目本身：
  - 前置用 M01 端點，例如 POST `/api/quotations` 落到靜態檔 mount 回 405；
  - 期望案件層成功；
  - 期望綁案成功（網路規劃書、派工匯入報價單已明說「案件模組未安裝」）；
  - `modules/daily_tasks/tests/test_case_stage_done_daily_task.py` 在模組層級 import `modules.case` ⇒ 收集錯誤；另有 4 檔在函式內 import。
- 主持裁示：加 `requires_module("case")` 檔頭標記並附理由；模組層級 import 改成延後 import；驗「L1 照常」的檔不可以標記。
- ⚠ 主持裁示用的「71 檔」是 D 第一份子集的數字（tests/ 只挑了提到 `modules.case` 的檔）。**全集是非 e2e 134 檔**，另加 e2e。

**M4-S1（建議）　兩題附件題的略過理由不精確**
- `test_invoice_voucher_attachments_keep_the_amount_layer` 的理由寫「前提用 M01 端點」，實際前提是 M05 的 `/api/invoice-vouchers` 與 L1 的 `guard_case_access`。`test_l1_side_providers_refuse_to_swallow_broken_json[arap]` 是用 SQL 直接種報價單。
- D 拿掉 `needs_case` 在真刪樹實跑：M05 端點回 404，提供者丟 `AttachmentNotVisible`。這是 CA-M1 條件 3 的 fail-closed，符合裁示；L1 那道 404 在 `test_case_access_l1` 有正反對照。
- 建議把理由改準確，並把 arap 那一格改成驗「M01 不在 ⇒ 開票申請附件 fail-closed」，讓 M05 這條路在無 M01 的安裝也有題。

**M4-S2（建議）　模組題 import 平台測試檔**
- netplan 的 `_drop` 用 `from tests.platform.test_case_stage_connectors import _without`，模組自己的題依賴一個平台測試檔的私有函式。
- 呼應 CA3-S1：下沉成共用夾具，例如 conftest 的 `drop_provider`。

**觀察**
- **M4-O1（架構，交主持）**：`/api/approval-queue`（彙整、數量、詳情、轉簽）與 approval-queue 頁屬於 M01。M01 不在時，M05／M04／M03／payroll／自訂模組雖然都提供 `approval.queue_items`，卻沒有彙整入口。沒有 M01 的安裝包（例如單賣應收應付）等於沒有待簽清單。
- **M4-O2**：反向控制只排除 `backend/modules/case/`；modules.json 裡 M01 的前端單位（case-management 頁與 js、approval-queue 頁）仍在。前端的「拿掉」沒有被量到。
- **M4-O3**：`tests/test_e2e_inflight_report_2026_09_26.py::_run_probe` 把 `test_zz_td_probe_<hex>.py` 寫進 `backend/tests/`，靠 `finally` 刪掉。D 這輪 e2e 跑完它還留在樹上（02:41 建立），而且被同一輪其他 worker 收集成一個紅。探針應該寫到 tmp_path，不要寫進受測樹。與 M01 無關。
- **M4-O4**：`tests/test_subproc_helper_2026_09_21.py::test_every_test_that_spawns_pytest_builds_its_env_with_utf8_env` 在 221adaa0、M01 在時也紅，C 的閘門沒有列出。

## 3. e2e 的對照

- 真刪樹 e2e 專屬 78 檔 166 項紅。**在 M01 在的樹（221adaa0）跑同一批 78 檔：206 過、0 紅** ⇒ 全部是 M01 不在才紅。
- 非 e2e 的 134 檔同理：M01 在時 1256 過、0 skip、0 紅。

## 4. 給 -5 的複核基準（M01 在時，逐檔實際執行題數）

- 非 e2e 134 檔共 **1256 題**，e2e 78 檔共 **206 題**，逐檔數字見 §5 的「M01 在：過」欄。
- -5 的複核會比對：
  - M01 在時每檔 passed 數要與此相同（skip 不能增加）；
  - M01 不在時紅燈只剩 §B-11 允許的題；
  - 驗「L1 照常」的檔不得出現 `requires_module("case")`。

## 5. 逐檔清單（M01 不在時紅題數／M01 在時通過題數）

### 5-1 非 e2e（134 檔）

| 檔 | M01 不在：紅 | M01 在：過 |
|---|---|---|
| `modules/analytics/tests/test_core.py` | 1 | 16 |
| `modules/analytics/tests/test_money_round_half_up_2026_09_26.py` | 1 | 4 |
| `modules/analytics/tests/test_report_recognition_basis_2026_09_24.py` | 14 | 15 |
| `modules/analytics/tests/test_reports_dispatch_row_consumer.py` | 2 | 2 |
| `modules/analytics/tests/test_reports_expenses.py` | 2 | 5 |
| `modules/analytics/tests/test_reports_export_expenses.py` | 2 | 2 |
| `modules/analytics/tests/test_reports_logic_fixes_2026_08_28.py` | 2 | 5 |
| `modules/analytics/tests/test_reports_review_fixes_2026_09_02.py` | 1 | 11 |
| `modules/analytics/tests/test_settlement_extra_expenses_pending_2026_09_09.py` | 5 | 6 |
| `modules/analytics/tests/test_settlement_extra_files_in_exports_2026_09_01.py` | 2 | 2 |
| `modules/analytics/tests/test_visual_management_2026_08_28.py` | 1 | 1 |
| `modules/arap/tests/test_cashier_module_2026_08_31.py` | 2 | 2 |
| `modules/arap/tests/test_module_permission_fixes_2026_09_13_from_tests.py` | 1 | 3 |
| `modules/arap/tests/test_money_round_half_up_2026_09_26_from_tests.py` | 4 | 8 |
| `modules/arap/tests/test_payment_requests.py` | 6 | 8 |
| `modules/arap/tests/test_signed_upload_files.py` | 1 | 1 |
| `modules/arap/tests/test_tax_basis_r2_2026_09_25.py` | 4 | 4 |
| `modules/arap/tests/test_tax_by_law_2026_09_24.py` | 3 | 8 |
| `modules/crm/tests/test_crm_api_integration.py` | 1 | 11 |
| `modules/crm/tests/test_crm_quote_deleted_provider.py` | 1 | 2 |
| `modules/daily_tasks/tests/test_case_stage_done_daily_task.py` | 1 | 5 |
| `modules/daily_tasks/tests/test_ip5_daily_task_external.py` | 3 | 3 |
| `modules/netplan/tests/test_netplan_case_access.py` | 2 | 3 |
| `modules/netplan/tests/test_network_plans.py` | 2 | 13 |
| `modules/payroll/tests/test_bonus_case_api_2026_09_24.py` | 2 | 25 |
| `modules/subcontract/tests/test_case_finance_summary_2026_09_09.py` | 2 | 2 |
| `modules/subcontract/tests/test_cashier_execution_history_2026_08_31.py` | 2 | 2 |
| `modules/subcontract/tests/test_cashier_module_2026_08_31.py` | 2 | 4 |
| `modules/subcontract/tests/test_contractor_bank_branch_2026_09_24.py` | 1 | 9 |
| `modules/subcontract/tests/test_dispatch_import_to_quote_persists_2026_09_23.py` | 2 | 2 |
| `modules/subcontract/tests/test_dispatch_invoice_payable_date_2026_08_30.py` | 1 | 6 |
| `modules/subcontract/tests/test_dispatch_row_provider.py` | 1 | 4 |
| `modules/subcontract/tests/test_subcontract_attachments_provider.py` | 1 | 2 |
| `modules/subcontract/tests/test_subcontract_providers.py` | 4 | 8 |
| `modules/supply/tests/test_privacy_notice_forms_2026_09_26.py` | 2 | 3 |
| `modules/supply/tests/test_supply_stock_and_shipping.py` | 3 | 7 |
| `tests/test_api_integration.py` | 7 | 24 |
| `tests/test_approval_delegates_2026_08_28.py` | 4 | 12 |
| `tests/test_approval_queue_badge_consistency_2026_09_15.py` | 5 | 5 |
| `tests/test_approval_queue_covers_every_doc_type_2026_09_24.py` | 8 | 11 |
| `tests/test_approval_queue_delegate_visibility_2026_08_28.py` | 4 | 4 |
| `tests/test_approval_queue_detail_2026_09_14.py` | 6 | 6 |
| `tests/test_approval_queue_detail_authz_2026_09_14.py` | 5 | 6 |
| `tests/test_approval_queue_quotation_attachments_2026_09_23.py` | 6 | 6 |
| `tests/test_approval_reassign_history_2026_09_14.py` | 13 | 13 |
| `tests/test_as3_voucher_approval_queue_2026_09_23.py` | 2 | 6 |
| `tests/test_case_action_item_edit_reset_2026_08_28.py` | 3 | 3 |
| `tests/test_case_approver_single_rule_2026_09_25.py` | 2 | 2 |
| `tests/test_case_attachments_scope_2026_09_23.py` | 6 | 7 |
| `tests/test_case_attachments_used_marker_2026_09_23.py` | 7 | 7 |
| `tests/test_case_batch_ops_2026_09_24.py` | 5 | 5 |
| `tests/test_case_bundle_2026_09_24.py` | 5 | 6 |
| `tests/test_case_change_approve_deadlock_2026_09_15.py` | 4 | 4 |
| `tests/test_case_change_summary_2026_09_14.py` | 1 | 15 |
| `tests/test_case_close_checklist_2026_09_24.py` | 3 | 3 |
| `tests/test_case_extra_expenses_api_2026_09_11.py` | 15 | 17 |
| `tests/test_case_finance_summary_2026_09_09.py` | 3 | 4 |
| `tests/test_case_gate_batch_2026_09_24.py` | 3 | 3 |
| `tests/test_case_gate_matrix_2026_09_14.py` | 7 | 7 |
| `tests/test_case_item_by_id_2026_09_24.py` | 7 | 7 |
| `tests/test_case_list_quick_filters_2026_09_24.py` | 6 | 6 |
| `tests/test_case_list_server_side_2026_09_24.py` | 7 | 7 |
| `tests/test_case_management_logic_fixes_2026_08_28.py` | 5 | 5 |
| `tests/test_case_money_mask_2026_09_24.py` | 22 | 22 |
| `tests/test_case_pdf_money_guard_2026_09_24.py` | 2 | 11 |
| `tests/test_case_project_merge.py` | 5 | 7 |
| `tests/test_case_project_overdue_2026_09_10.py` | 5 | 5 |
| `tests/test_case_record_member_guard_2026_09_24.py` | 20 | 20 |
| `tests/test_case_record_payment_gate_2026_08_31.py` | 6 | 6 |
| `tests/test_case_record_segmented_save_2026_09_24.py` | 7 | 7 |
| `tests/test_case_record_validation_releases_lock_2026_09_25.py` | 1 | 1 |
| `tests/test_case_roles_username_2026_09_24.py` | 3 | 8 |
| `tests/test_case_semi_unlock.py` | 14 | 14 |
| `tests/test_case_stage_done_calendar_2026_09_11.py` | 5 | 5 |
| `tests/test_case_stages_endpoints_2026_09_07.py` | 10 | 11 |
| `tests/test_cashier_reads_all_cases_2026_09_24.py` | 5 | 5 |
| `tests/test_completion_notes_2026_09_12.py` | 22 | 22 |
| `tests/test_core.py` | 1 | 38 |
| `tests/test_custom_modules_engine_2026_09_25.py` | 2 | 58 |
| `tests/test_doc_versions_2026_09_14.py` | 12 | 13 |
| `tests/test_exception_detail_leak_2026_09_23.py` | 4 | 8 |
| `tests/test_extra_expense_reject_permission_2026_09_24.py` | 4 | 4 |
| `tests/test_extra_expense_tier_record_2026_09_25.py` | 7 | 7 |
| `tests/test_extra_expense_uploads_2026_09_11.py` | 5 | 5 |
| `tests/test_feed_attachments_2026_09_14.py` | 6 | 6 |
| `tests/test_high_risk_routes_2026_09_22.py` | 1 | 21 |
| `tests/test_invoice_date_and_case_record_validation_2026_09_02.py` | 5 | 5 |
| `tests/test_jv24_void_reopen_lineage_2026_09_23.py` | 3 | 8 |
| `tests/test_jv35_voucher_reassign_2026_09_24.py` | 5 | 5 |
| `tests/test_jv36_voucher_line_source_files_2026_09_24.py` | 2 | 4 |
| `tests/test_last_received_bank_account_access_2026_09_25.py` | 1 | 1 |
| `tests/test_mark_payment_permission_2026_08_31.py` | 4 | 4 |
| `tests/test_material_orders_2026_09_10.py` | 7 | 7 |
| `tests/test_module_keys_consistency_2026_09_13.py` | 1 | 7 |
| `tests/test_module_permission_fixes_2026_09_13.py` | 23 | 29 |
| `tests/test_money_round_half_up_2026_09_26.py` | 5 | 14 |
| `tests/test_mp6_map_case_locations_2026_09_24.py` | 4 | 6 |
| `tests/test_online_activity_2026_09_14.py` | 2 | 26 |
| `tests/test_org_chain_approval_2026_09_15.py` | 8 | 10 |
| `tests/test_payment_item_and_material_uploads.py` | 5 | 5 |
| `tests/test_payment_receipt_validation_2026_09_24.py` | 28 | 28 |
| `tests/test_privacy_notice_forms_2026_09_26.py` | 5 | 34 |
| `tests/test_queue_and_feed_scoping_2026_09_15.py` | 6 | 6 |
| `tests/test_quotation_create_identity_2026_09_10.py` | 2 | 3 |
| `tests/test_quotation_create_no_orphan_2026_09_10.py` | 4 | 4 |
| `tests/test_quote_json_direct_writes_lost_update_2026_09_25.py` | 1 | 5 |
| `tests/test_quote_json_lost_update_2026_09_25.py` | 1 | 43 |
| `tests/test_quote_location_2026_09_22.py` | 4 | 30 |
| `tests/test_quote_location_realpath_2026_09_23.py` | 1 | 13 |
| `tests/test_quote_location_rest_2026_09_22.py` | 3 | 13 |
| `tests/test_quote_location_snapshot_2026_09_23.py` | 3 | 3 |
| `tests/test_quote_no_validation_2026_09_10.py` | 11 | 11 |
| `tests/test_quote_preview_server_layout_2026_09_24.py` | 7 | 8 |
| `tests/test_quote_submit_reasons_server_2026_09_24.py` | 12 | 12 |
| `tests/test_received_installment_lock_2026_09_24.py` | 24 | 24 |
| `tests/test_report_recognition_basis_2026_09_24.py` | 17 | 17 |
| `tests/test_reports_tax_compliance_2026_09_02.py` | 5 | 5 |
| `tests/test_row_access_callers_2026_09_25.py` | 2 | 3 |
| `tests/test_save_quotation_json_guard_2026_09_25.py` | 1 | 6 |
| `tests/test_sidebar_regroup_2026_09_22.py` | 5 | 12 |
| `tests/test_signed_upload_files.py` | 3 | 3 |
| `tests/test_site_wording_2026_09_24.py` | 1 | 4 |
| `tests/test_slow_request_log_2026_09_10.py` | 3 | 4 |
| `tests/test_stage_sync_lost_update_2026_09_25.py` | 1 | 1 |
| `tests/test_t100_export_2026_09_01.py` | 1 | 5 |
| `tests/test_tax_basis_r2_2026_09_25.py` | 6 | 20 |
| `tests/test_tax_by_law_2026_09_24.py` | 35 | 39 |
| `tests/test_upload_demo_isolation.py` | 1 | 1 |
| `tests/test_visual_management_2026_08_28.py` | 2 | 3 |
| `tests/test_voucher_attachments_2026_09_23.py` | 5 | 16 |
| `tests/test_voucher_revision_no_2026_09_23.py` | 1 | 3 |
| `tests/test_walk_batch_small_2026_09_24.py` | 9 | 10 |
| `tests/test_write_lock_released_on_error_2026_09_25.py` | 1 | 7 |
| `tests/test_xe_change_request_2026_09_11.py` | 10 | 10 |

### 5-2 e2e 專屬（78 檔；已在 5-1 的 13 檔不重列）

| 檔 | M01 不在：紅 | M01 在：過 |
|---|---|---|
| `modules/analytics/tests/test_e2e_report_recognition_2026_09_24.py` | 1 | 1 |
| `modules/arap/tests/test_e2e_cashier_receive_amount_2026_09_24.py` | 1 | 1 |
| `modules/arap/tests/test_e2e_tax_basis_r2_2026_09_25.py` | 1 | 1 |
| `modules/crm/tests/test_e2e_crm_quote_delete_no_notice_2026_09_26.py` | 1 | 1 |
| `modules/daily_tasks/tests/test_e2e_daily_tasks_without_case_module.py` | 1 | 2 |
| `modules/payroll/tests/test_e2e_bonus_queue_no_cascade_promise_2026_09_25.py` | 1 | 1 |
| `modules/subcontract/tests/test_e2e_case_open_requests_2026_09_24.py` | 1 | 1 |
| `modules/subcontract/tests/test_e2e_contractor_bank_branch_2026_09_24.py` | 1 | 2 |
| `modules/subcontract/tests/test_e2e_report_recognition_2026_09_24.py` | 1 | 1 |
| `modules/supply/tests/test_e2e_shipping_recipient_privacy_2026_09_26.py` | 1 | 1 |
| `tests/test_case_cross_module_links_2026_09_24.py` | 3 | 3 |
| `tests/test_case_page_no_native_dialogs_2026_09_24.py` | 1 | 1 |
| `tests/test_case_page_p4b_dialogs_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_account_tree_2026_09_23.py` | 1 | 2 |
| `tests/test_e2e_approval_history_2026_09_14.py` | 2 | 2 |
| `tests/test_e2e_approval_reassign_ui_2026_09_14.py` | 2 | 2 |
| `tests/test_e2e_arap_absent_notices_2026_09_26.py` | 2 | 5 |
| `tests/test_e2e_case_all_done_inline_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_case_batch_ops_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_case_color_semantics_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_case_concurrent_edit_2026_09_24.py` | 3 | 3 |
| `tests/test_e2e_case_counts_error_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_case_data_loss_2026_09_24.py` | 5 | 6 |
| `tests/test_e2e_case_header_and_payment_tab_2026_09_24.py` | 5 | 5 |
| `tests/test_e2e_case_health_overview_2026_09_24.py` | 3 | 3 |
| `tests/test_e2e_case_invoice_amounts_2026_09_24.py` | 4 | 4 |
| `tests/test_e2e_case_item_by_id_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_case_list_paging_2026_09_24.py` | 4 | 4 |
| `tests/test_e2e_case_list_quick_filters_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_case_management_font_zoom_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_case_mark_all_read_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_case_mark_one_read_count_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_case_money_mask_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_case_open_requests_2026_09_24.py` | 3 | 3 |
| `tests/test_e2e_case_page_golden_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_case_page_theme_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_case_payment_number_input_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_case_payment_request_unsaved_hint_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_case_roles_select_2026_09_24.py` | 2 | 3 |
| `tests/test_e2e_case_save_banner_persists_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_case_save_feedback_2026_09_24.py` | 3 | 3 |
| `tests/test_e2e_case_save_mode_and_labels_2026_09_24.py` | 3 | 3 |
| `tests/test_e2e_case_save_queue_after_failure_2026_09_25.py` | 1 | 1 |
| `tests/test_e2e_case_save_serialized_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_case_select_late_response_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_case_select_stale_subloads_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_case_stage_daily_task_notice_2026_09_26.py` | 1 | 1 |
| `tests/test_e2e_case_switch_state_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_case_toggle_buttons_style_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_case_without_supply_2026_09_26.py` | 2 | 2 |
| `tests/test_e2e_cashier_read_only_case_2026_09_24.py` | 2 | 2 |
| `tests/test_e2e_completion_form_2026_09_12.py` | 3 | 4 |
| `tests/test_e2e_copy_to_new_2026_09_10.py` | 1 | 1 |
| `tests/test_e2e_edit_presence_2026_09_14.py` | 1 | 2 |
| `tests/test_e2e_edit_presence_modal_2026_09_14.py` | 2 | 3 |
| `tests/test_e2e_extra_expenses_ui_2026_09_11.py` | 7 | 7 |
| `tests/test_e2e_feed_attachment_render_2026_09_15.py` | 1 | 1 |
| `tests/test_e2e_font_zoom_fits_viewport_2026_09_24.py` | 6 | 6 |
| `tests/test_e2e_inflight_report_2026_09_26.py` | 2 | 5 |
| `tests/test_e2e_material_orders_2026_09_11.py` | 2 | 2 |
| `tests/test_e2e_notice_banners_2026_09_25.py` | 2 | 4 |
| `tests/test_e2e_p8_gaps_2026_09_26.py` | 2 | 11 |
| `tests/test_e2e_page_module_guard_2026_09_13.py` | 2 | 5 |
| `tests/test_e2e_playwright_2026_09_07.py` | 2 | 3 |
| `tests/test_e2e_presence_bar_no_overlap_2026_09_24.py` | 4 | 4 |
| `tests/test_e2e_privacy_notice_docs_2026_09_26.py` | 3 | 5 |
| `tests/test_e2e_quote_delete_crm_absent_notice_2026_09_26.py` | 1 | 1 |
| `tests/test_e2e_quote_list_search_link_2026_09_24.py` | 4 | 5 |
| `tests/test_e2e_quote_number_input_2026_09_24.py` | 3 | 3 |
| `tests/test_e2e_quote_preview_server_layout_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_quote_reasons_parity_2026_09_24.py` | 3 | 4 |
| `tests/test_e2e_received_installment_lock_2026_09_24.py` | 1 | 1 |
| `tests/test_e2e_report_recognition_2026_09_24.py` | 3 | 3 |
| `tests/test_e2e_tax_basis_r2_2026_09_25.py` | 1 | 1 |
| `tests/test_e2e_tax_type_select_2026_09_24.py` | 1 | 2 |
| `tests/test_e2e_unread_marks_clear_on_click_2026_09_24.py` | 2 | 8 |
| `tests/test_e2e_voucher_attachments_absent_source_2026_09_26.py` | 2 | 2 |
| `tests/test_e2e_voucher_source_block_below_2026_09_25.py` | 10 | 10 |
