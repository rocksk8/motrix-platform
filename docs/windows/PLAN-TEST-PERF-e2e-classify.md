# §4.2 素材：e2e 題能不能降為 API 層題（逐檔分類）

範圍：`backend/tests/` 下含 `pytest.mark.e2e` 的 109 檔。只讀原始碼、沒有執行。
判準偏保守：拿不準的一律歸 UI。凡是因為「前端送錯或沒送」（接線缺陷）才存在的題，即使斷言打在 DB 上也算 UI。

## 1. 總表（以 `@pytest.mark.e2e` 的函式為單位，參數化算 1 條）

| 類別 | 條數 | 佔比 |
|---|---|---|
| UI（必須留在瀏覽器） | 263 | 94.6% |
| MIXED（可拆成 1 條 UI 冒煙＋其餘 API 題） | 14 | 5.0% |
| DATA（可整條降為 API 題） | 1 | 0.4% |
| **合計** | **278** | 100% |

附帶發現（不在上表內）：
- 這 109 檔裡還有 **65 條以上的函式不開瀏覽器**，也**沒有** e2e 標記：API 題、靜態掃描、純函式各都有，分布在 jv29／jv32／jv36／mp1～mp8／module_registry／voucher_expense_brought_in_once 等檔。
  - 它們本來就跑在非 e2e 的快速層，不在 e2e 階段，**不需要處理**。
  - 但檔名帶 `test_e2e_`／`jv*`，靠檔名估算 e2e 份量時會高估。
- 沒有任何檔在檔案層級寫 `pytestmark = e2e`，所以不會發生「整檔被誤歸成 e2e」。
- 建包腳本的 e2e 階段是 `-m e2e`，**沒有帶 -n**（`build_deploy_package.ps1:563`），也就是單程序循序跑。這一點與 §4.4 的平行化有關。

**結論：降為 API 層題能省的很少。** 這批 e2e 幾乎都是為了某個「只有瀏覽器看得到」的缺陷而寫的回歸題，例如前端競態、接線、版面、對話框、離頁警告。所以省時間要靠 §4.1（共用伺服器與瀏覽器）與固定等待，不能靠降層。

## 2. DATA 與 MIXED 逐條

| 檔名::函式 | 類別 | 理由 | 改成 API 題時要保留的斷言 |
|---|---|---|---|
| test_e2e_extra_expenses_ui_2026_09_11::test_create_save_and_author_is_filled_in | DATA | 填寫人、小計、狀態都由後端決定；瀏覽器只是觸發 | created_by＝登入者、created_by_inferred＝0、total_cost 由後端算（3000）、status＝草稿 |
| test_e2e_approval_reassign_ui_2026_09_14::test_superadmin_can_reassign_from_queue | MIXED | 換人、原因入庫、沒填原因就擋都是後端規則；畫面只需顯示原因 | API：沒原因要擋、reassignedFrom／reassignReason 入庫；UI：佇列上顯示原因 |
| test_e2e_bonus_case_page_2026_09_24::test_superadmin_builds_draft_and_submits_in_page | MIXED | 獎金池、各類金額、草稿狀態是後端算的 | API：rate_bp／pool_amount／lines 金額；UI：「已精算」卡片、bn-remainder＝NT$ 0 |
| test_e2e_bonus_case_page_2026_09_24::test_member_sees_own_line_and_cashier_marks_paid | MIXED | 可見範圍若由 API 遮蔽，就可以在 API 驗 | API：成員只拿到自己那一列、沒有 pool；UI：自己那一列的金額文字（冒煙） |
| test_e2e_bonus_live_recalc_2026_09_25::test_editing_in_review_warns_and_voids_signatures | MIXED | 簽核作廢是後端規則；「先警告」是 UI | API：審核中修改後 currentTier 歸零、approvedAt 清空；UI：先跳警告 |
| test_e2e_bonus_vouchers_page_2026_09_24::test_superadmin_voucher_account_settings_refuse_bad_codes | MIXED | 拒收不存在或停用的科目是後端規則 | API：不存在或停用的科目 4xx 且不入庫；UI：畫面寫出原因 |
| test_e2e_case_batch_ops_2026_09_24::test_batch_executor_and_export | MIXED | 批次改執行者與匯出內容是後端做的 | API：只改勾選的兩件、匯出只有兩列；UI：「已選 2 件」、勾選不會打開案件 |
| test_e2e_case_roles_select_2026_09_24::test_users_page_lists_unmapped_case_roles | MIXED | 未對應清單由後端計算，頁面只負責顯示 | API：清單含「業務負責／單號」；UI：區塊出現（冒煙） |
| test_e2e_contractor_bank_branch_2026_09_24::test_roster_list_shows_branch_and_import_reports_result | MIXED | Excel 匯入的解析與分行入庫都在後端 | API：更新 1 位、未匯入 1 列、bank_branch 入庫；UI：清單有「分行」欄 |
| test_e2e_extra_expenses_ui_2026_09_11::test_change_request_round_trip_in_browser | MIXED | 存草稿不動本體、核准後才生效是後端規則；打的值送到後端是接線 | API：草稿不改 total／description、核准後生效；UI：畫面輸入的值有送出（保留 1 條） |
| test_e2e_playwright_2026_09_07::test_inventory_purchase_suggestions_modal_smoke | MIXED | 建議量（ceil(10×1.5)＝15）若由後端算，就可以在 API 驗 | API：建議量＝15；UI：Modal 開得起來並列出料號 |
| test_e2e_playwright_2026_09_07::test_case_finance_summary_smoke | MIXED | 應收、已收的數字由後端彙總 | API：應收 100,000、已收 40,000、發票號；UI：總覽區塊顯示（冒煙） |
| test_e2e_totp_recovery_ui_2026_09_11::test_recovery_remaining_and_regenerate_flow | MIXED | 重產 10 組、新舊不重疊、存量是後端規則 | API：重產後 10 組且與舊的不重疊、使用後剩 9；UI：卡片顯示存量 |
| test_jv34_voucher_input_and_print_2026_09_24::test_jv34_void_and_reopen_from_the_page_opens_the_new_draft | MIXED | 作廢並重開的 supersedes_no 是後端做的 | API：新單 supersedes_no＝舊號、狀態草稿；UI：畫面切到新單 |
| test_jv35_voucher_reassign_2026_09_24::test_jv35_the_queue_shows_a_reassign_button_on_a_voucher | MIXED | 轉簽入庫是後端規則 | API：簽核人換成新的、記 reassignedFrom；UI：選到傳票時轉簽鈕出現 |

MIXED 的效益要說清楚：拆開之後每一條**仍然保留 1 條 UI 冒煙**，瀏覽器啟動與登入一次都沒少。省下的只有冒煙題裡原本的 DB 前置與斷言時間，估計每條 0.5～2 秒。14 條合計不到 30 秒 CPU。

## 3. UI 類（263 條；依主題分組，列檔名＋代表理由）

- **前端競態／非同步順序**：case_select_late_response、case_select_stale_subloads、case_switch_state、case_save_serialized、case_open_requests、case_list_paging（件數晚到）、case_mark_all_read、case_mark_one_read_count、unread_marks_clear_on_click、org_select_matches_model、case_data_loss（切換前打的字）。理由：只有真實的渲染與請求交錯才量得到。
- **接線（前端送錯或沒送）**：boolean_status_select、case_money_mask、case_invoice_amounts、case_item_by_id、case_payment_number_input、quote_number_input、jv32（頁面那兩條）、case_roles_select（存帳號）、completion_form、material_orders、report_recognition（案件頁四處補登）、jv29（頁面手選）、jv36、walk_batch_small（匯出帶口徑）、case_concurrent_edit、system_settings_ui（retention 來回）。理由：斷言在 DB 上，但壞的是前端送出的內容。
- **對話框、離頁警告、鍵盤、焦點**：ui_dialogs、case_page_no_native_dialogs、case_page_p4b_dialogs、case_all_done_inline、case_payment_request_unsaved_hint、filter_fields_no_leave_warning、view_filters_not_dirty、global_search_not_dirty、login_enter_submits、case_close_checklist、received_installment_lock、cashier_receive_amount。
- **版面、樣式、深色、字級、z-index**：case_page_theme、dark_mode_sidebar、case_toggle_buttons_style、case_color_semantics、case_header_and_payment_tab、font_zoom_fits_viewport、case_management_font_zoom、presence_bar_no_overlap、map_under_topbar、voucher_summary_panel_side_by_side、voucher_preview_iframe_height、mp5、walk_batch_small（客戶彈窗）。
- **前端計算與顯示**：bonus_live_recalc（改比例即時重算、分配不是 100% 就擋）、quote_reasons_parity、tax_type_select、quote_terms_presets、reports_period_sync、reports_period_select_matches_model、case_health_overview、case_list_quick_filters、extra_expenses_ui（推定標示、送審中金額）、jv34（清單篩選、Enter 新增行、科目選單）、jv31、jv22、approval_history（前端搜尋）。
- **頁面存在、權限門、選單**：page_module_guard、online_widget、bonus_empty_state、bonus_case_page（outsider 選單）、account_tree、selection_overview、t100_unconfirm（「全程只用畫面操作」就是題目本身）、gov_name_search、case_cross_module_links、module_registry（頁面組清單）、cashier_read_only_case、ql24。
- **跨分頁、多人同步**：edit_presence、edit_presence_modal、unread_marks_clear_on_click（另一分頁）。
- **瀏覽器本身的能力**：passkey（CDP 虛擬認證器）、feed_attachment_render（圖片真的載得出來）、jv28（blob 預覽、SVG 不內嵌、revoke）、contractor_pii_upload_failure、mp0（XSS 跳脫）、mp1～mp8（Leaflet）、copy_to_new（取號失敗的畫面行為）、voucher_feedback、voucher_summary、voucher_preview_export_feedback、voucher_expense_brought_in_once（面板紅字）、playwright smoke 其餘兩條（黃金路徑、QR 登入）。

## 4. 最不確定的 5 條

1. **test_e2e_passkey_2026_09_11::test_passkey_login_updates_sign_count**（歸 UI）：斷言全落在 DB（sign_count、last_used_at）。如果有軟體認證器函式庫可以在 Python 產生 assertion，就能降為 API 題。現在歸 UI，是因為 CDP 虛擬認證器是目前唯一的產生方式，換掉等於換了一套信任的簽章來源。
2. **test_e2e_case_concurrent_edit_2026_09_24 三條**（歸 UI）：衝突判定在後端（分段基準），但分段基準是**前端記住並送出**的。沒有逐行讀 core.js，無法確定 API 層能不能等價構造出前端會送的 base。
3. **test_e2e_extra_expenses_ui::test_create_save_and_author_is_filled_in**（歸 DATA）：docstring 寫「不是前端亂填的」。如果前端曾經送 created_by 而後端照收，這題就是接線題，應該歸 UI。需要查當初的缺陷紀錄。
4. **test_e2e_bonus_case_page::test_member_sees_own_line_and_cashier_marks_paid**（歸 MIXED）：如果可見範圍是前端藏、不是 API 遮蔽，那 API 題驗不到，應該整條留 UI。沒有讀 routers/bonus 確認。
5. **test_e2e_playwright::test_case_finance_summary_smoke**（歸 MIXED）：應收、已收如果是前端從 bundle 自己加總，就是前端計算，應該歸 UI。
