# 階段測試瘦身稽核（只讀、只出報告）

> 2026-11-13 · 起因：使用者要求「看階段測試裡哪些題已經舊了、沒用了還在浪費時間」（PM 派工）。主導 hichan-2，A／B／C 由 hichan-10 協助。
> **只讀**：沒有刪任何檔、沒有跑重型測試（禁令期間）；每個建議都要有人（對應模組的作者＋PM）確認後才動。
> 守門類（ratchet／baseline／guard）預設**保留**，除非有明確證據證明它已失效；本稿沒有建議刪任何守門。

## 0. 摘要

- **資料**：h7 預跑 `--keep-going`（run `20261113_131820_6768`）：slice0 4 684 題 / 477 s、slice1 12 201 題 / 1 105 s（4 worker）、e2e 1 306 題 / 1 346 s（2 worker）。
  牆鐘合計 **≈ 49 分**，worker-秒合計 **9 021（150 分）**。全部約 **18 200 題**，平均每題 0.50 worker-秒（非 e2e 約 0.38、e2e 約 2.06）。
- **時間集中在哪**：最慢的 30 個檔只占 **約 20%**（預跑資料）～ **38%**（11-11 累積資料、只算非 e2e）；時間是**長尾**——前 100 個檔占 61%，前 400 個才到 89%，571／1203 個檔不到 1 秒。
  所以「刪掉幾支慢檔」省不了多少；真正的槓桿是 **tests/platform 這類「掃整個 repo／起子行程」的守門與工具測試共用索引**（tests/platform 占非 e2e 檔時間的 **43%**）與 **e2e 每題各起一份伺服器**。
- **D（便宜寫法）估計可省**：約 **645～850 worker-秒（11～14 分 worker 時間，牆鐘約 3～4 分）**，題數**不減**（見 §3）；再加升級演練改排程約 96 s／輪。**整份稽核的結論：要省時間靠 D，不靠刪題。**
- **A／B／C（刪／併）**：誠實結論——**只有約 15～20 題、≈ 6～8 秒（< 0.1%）**，另有 9 題因第 42 班使用者裁示 skip（刪＝清雜訊，不省時間）；這批「舊題」是維護成本與雜訊問題，不是時間問題。唯一有感的是升級演練兩檔（≈ 96 s／輪）**改排程**到 nightly／發版前（§4）。
- 資料限制（誠實說明）：預跑 log 每階段只印**最慢 30 題**、fail_stream 每階段只存**最慢 20 檔**，所以「前 50 題」實際只湊得到 45 題（e2e 階段的最慢題只有 log 裡那幾題）；
  長尾分佈用 `full_results/file_seconds.json`（11-11、1 203 個檔、累積 4 806 s）補。**沒有逐題完整耗時**——要精確的「每題秒數」需要下一次預跑加 `--durations=0`（`--no-durations` 預設關、`--durations=N` 可調）。

## 1. ① 耗時

### 1.1 階段總覽
| 階段 | 題數 | 牆鐘 | worker | worker-秒 | 占總時間 | 平均每題 |
|---|---|---|---|---|---|---|
| slice0（靜態／守門） | 4 684 | 477 s | 4 | 1 909 | 21% | 0.41 s |
| slice1（其餘非 e2e） | 12 201 | 1 105 s | 4 | 4 420 | 49% | 0.36 s |
| e2e | 1 306 | 1 346 s | 2 | 2 691 | 30% | 2.06 s |

### 1.2 最慢的題（log 每階段最慢 30，合併；%＝占總 worker-秒 9 021）
前 45 題合計 **1 022 s＝11.3%**。
| # | 秒 | 階段 | 題 | 所在階段 | % |
|---|---|---|---|---|---|
| 1 | 66.80 | call | `tests/platform/test_e2e_classification.py::test_every_browser_test_carries_the_e2e_marker` | slice0 | 0.74% |
| 2 | 64.10 | call | `tests/platform/test_module_update_delivery_2026_09_28.py::test_ship_tests_adds_consumers_of_a_changed_provider` | slice1 | 0.71% |
| 3 | 48.36 | call | `tests/platform/test_ship_tier_2026_09_28.py::test_real_repo_every_provider_module_resolves` | slice1 | 0.54% |
| 4 | 43.79 | call | `tests/platform/test_modtest_rebase_check.py::test_own_fixture_layer_change_runs_the_diff_and_does_not_ask_for_full` | slice1 | 0.49% |
| 5 | 42.85 | call | `tests/platform/test_modtest_scope.py::test_real_helper_private_change_selects_its_tests` | slice1 | 0.48% |
| 6 | 39.07 | call | `tests/platform/test_author_gate_2026_10_02.py::test_ag_long_argv_spills_to_argsfile_and_pytest_really_runs_it` | slice1 | 0.43% |
| 7 | 38.49 | call | `tests/platform/test_modtest_json_stdout_2026_09_29.py::test_json_stdout_parses_even_when_worker_caps_are_set` | slice1 | 0.43% |
| 8 | 37.69 | call | `tests/platform/test_integration_points_registered.py::test_every_installed_module_can_be_removed_without_breaking_the_registry` | slice0 | 0.42% |
| 9 | 32.40 | call | `tests/platform/test_scope_gate_2026_09_30.py::test_m1_global_nails_are_selected_for_a_real_module_file` | slice0 | 0.36% |
| 10 | 31.06 | call | `tests/platform/test_module_boundaries.py::test_rc_end_to_end_through_real_source` | slice0 | 0.34% |
| 11 | 28.85 | call | `tests/platform/test_response_keys_baseline.py::test_record_or_compare_against_baseline` | slice0 | 0.32% |
| 12 | 27.64 | call | `tests/platform/test_module_boundaries.py::test_prune_keeps_other_keys_and_edges_of_modules_not_installed` | slice0 | 0.31% |
| 13 | 24.09 | call | `tests/test_upgrade_drill_2026_09_25.py::test_convert_then_rollback_restores_v9[code]` | slice1 | 0.27% |
| 14 | 23.97 | call | `tests/test_upgrade_drill_2026_09_25.py::test_convert_then_rollback_restores_v9[full]` | slice1 | 0.27% |
| 15 | 22.53 | call | `tests/test_e2e_nav_hierarchy_2026_11_11.py::test_report_hub_only_lists_reports_this_user_can_open` | e2e | 0.25% |
| 16 | 22.05 | call | `modules/payroll/tests/test_payslip_perm_wiring_http_t68.py::test_http_gate_is_403_exactly_when_todays_gate_would_block` | slice1 | 0.24% |
| 17 | 21.86 | call | `tests/platform/test_generated_maps.py::test_rc_the_three_guards_do_go_red_on_a_full_tree` | slice0 | 0.24% |
| 18 | 20.94 | call | `tests/platform/test_generated_maps.py::test_rc_stale_test_map_is_detected` | slice0 | 0.23% |
| 19 | 20.12 | call | `tests/platform/test_generated_maps.py::test_test_map_json_is_current` | slice0 | 0.22% |
| 20 | 19.51 | call | `tests/test_e2e_p8_module_builder_2026_09_26.py::test_acceptance_equipment_loan_built_in_browser_then_used_end_to_end` | e2e | 0.22% |
| 21 | 18.82 | call | `tests/platform/test_unit_cards.py::test_rc_stale_index_is_red` | slice0 | 0.21% |
| 22 | 18.25 | call | `tests/platform/test_module_changelog_follows_code.py::test_every_module_changelog_follows_its_code` | slice0 | 0.20% |
| 23 | 17.94 | call | `tests/test_e2e_case_page_theme_2026_09_24.py::test_dark_mode_has_no_light_blocks_or_black_text` | e2e | 0.20% |
| 24 | 17.28 | call | `modules/supply/tests/test_supplier_perm_wiring_http_t70.py::test_http_gate_is_403_exactly_when_todays_gate_would_block` | slice1 | 0.19% |
| 25 | 16.89 | call | `tests/test_e2e_edit_presence_modal_2026_09_14.py::test_modal_pops_when_someone_joins_midway` | e2e | 0.19% |
| 26 | 15.59 | call | `tests/test_company_setup_gate_2026_09_28.py::test_every_other_api_route_is_blocked_when_unconfigured` | slice1 | 0.17% |
| 27 | 15.17 | call | `tests/test_e2e_material_approval_2026_10_02.py::test_material_order_approval_round_trip_in_the_browser` | e2e | 0.17% |
| 28 | 15.17 | call | `tests/platform/test_field_policy_exits_quotation_t65.py::test_put_quotation_restores_masked_parts_exactly_when_the_old_table_says_so` | slice0 | 0.17% |
| 29 | 13.88 | call | `tests/platform/test_route_ownership.py::test_real_tree_has_no_route_ownership_errors` | slice0 | 0.15% |
| 30 | 13.75 | setup | `tests/platform/test_module_boundaries.py::test_scanner_sees_the_codebase` | slice0 | 0.15% |
| 31 | 13.66 | setup | `tests/platform/test_generated_maps.py::test_dep_graph_json_is_current` | slice0 | 0.15% |
| 32 | 13.65 | call | `tests/test_e2e_case_page_golden_2026_09_24.py::test_case_page_behaviour_matches_golden` | e2e | 0.15% |
| 33 | 13.61 | call | `modules/accounting/tests/test_ledger_mutation_guards_2026_10_01.py::test_mutation_is_caught_by_detectors[M1-no-category-map-call]` | slice1 | 0.15% |
| 34 | 13.49 | call | `tests/test_e2e_inflight_report_2026_09_26.py::test_rc_teardown_hang_fails_only_that_test[n1]` | e2e | 0.15% |
| 35 | 13.17 | call | `modules/accounting/tests/test_ledger_mutation_guards_2026_10_01.py::test_mutation_is_caught_by_detectors[M3-engine-ignores-line-account-code]` | slice1 | 0.15% |
| 36 | 12.97 | call | `tests/platform/test_stepfile_drill_2026_09_30.py::test_drill_nongit_install_passes_verify_package_with_the_package_list` | slice1 | 0.14% |
| 37 | 12.71 | setup | `modules/accounting/tests/test_ledger_mutation_guards_2026_10_01.py::test_mutation_is_caught_by_detectors[M1-no-category-map-call]` | slice1 | 0.14% |
| 38 | 12.52 | call | `tests/test_e2e_form_designer_beginner_tasks_2026_10_02.py::test_delete_can_be_undone_and_a_referenced_field_cannot_be_deleted` | e2e | 0.14% |
| 39 | 12.46 | call | `modules/payroll/tests/test_e2e_bonus_correction_page_2026_09_30.py::test_full_lifecycle_supplement` | e2e | 0.14% |
| 40 | 12.02 | call | `tests/test_e2e_inflight_report_2026_09_26.py::test_rc_teardown_hang_fails_only_that_test[n0]` | e2e | 0.13% |
| 41 | 11.88 | call | `tests/test_e2e_p8_module_builder_2026_09_26.py::test_publish_waits_for_the_draft_save_with_a_limit` | e2e | 0.13% |
| 42 | 11.52 | call | `modules/case/tests/test_e2e_material_recognize_denied_2026_10_13.py::test_denied_recognition_is_visible_at_once_without_reload` | e2e | 0.13% |
| 43 | 10.97 | call | `tests/test_e2e_material_change_2026_10_03.py::test_material_change_request_round_trip_in_the_browser` | e2e | 0.12% |
| 44 | 9.99 | call | `tests/test_e2e_material_unsent_2026_10_02.py::test_new_material_request_stays_unsent_until_submit` | e2e | 0.11% |
| 45 | 8.77 | call | `tests/test_e2e_form_designer_beginner_tasks_2026_10_02.py::test_task5_hide_memo_from_the_list` | e2e | 0.10% |

### 1.3 最慢的檔（fail_stream 每階段最慢 20 檔，合併取前 30）
前 30 檔合計 **1 785 s＝19.8%**。
| # | 秒 | 題數 | 檔 | 所在階段 | % |
|---|---|---|---|---|---|
| 1 | 128.10 | 45 | `tests/platform/test_module_update_delivery_2026_09_28.py` | slice1 | 1.42% |
| 2 | 100.91 | 8 | `modules/accounting/tests/test_ledger_mutation_guards_2026_10_01.py` | slice1 | 1.12% |
| 3 | 90.28 | 13 | `tests/test_e2e_form_designer_beginner_tasks_2026_10_02.py` | e2e | 1.00% |
| 4 | 88.04 | 38 | `tests/test_e2e_mobile_nav_cases_2026_11_13.py` | e2e | 0.98% |
| 5 | 84.24 | 63 | `tests/platform/test_ship_tier_2026_09_28.py` | slice1 | 0.93% |
| 6 | 79.14 | 131 | `tests/platform/test_gov_contract_2026_11_08.py` | slice0 | 0.88% |
| 7 | 77.43 | 11 | `tests/platform/test_generated_maps.py` | slice0 | 0.86% |
| 8 | 73.02 | 27 | `tests/platform/test_module_boundaries.py` | slice0 | 0.81% |
| 9 | 68.30 | 8 | `tests/platform/test_e2e_classification.py` | slice0 | 0.76% |
| 10 | 67.47 | 16 | `tests/platform/test_modtest_scope.py` | slice1 | 0.75% |
| 11 | 64.36 | 103 | `tests/platform/test_scope_gate_2026_09_30.py` | slice0 | 0.71% |
| 12 | 63.71 | 16 | `tests/platform/test_modtest_rebase_check.py` | slice1 | 0.71% |
| 13 | 54.80 | 43 | `tests/test_quote_json_lost_update_2026_09_25.py` | slice1 | 0.61% |
| 14 | 51.46 | 17 | `tests/test_e2e_users_list_privacy_pages_t47_2026_10_08.py` | e2e | 0.57% |
| 15 | 51.36 | 77 | `tests/test_finance_role_matrix_ext_2026_10_05.py` | slice1 | 0.57% |
| 16 | 49.10 | 58 | `tests/platform/test_module_selection.py` | slice0 | 0.54% |
| 17 | 48.07 | 2 | `tests/test_upgrade_drill_2026_09_25.py` | slice1 | 0.53% |
| 18 | 47.94 | 7 | `tests/platform/test_stepfile_drill_2026_09_30.py` | slice1 | 0.53% |
| 19 | 47.90 | 104 | `tests/test_line_events_all_2026_11_13.py` | slice1 | 0.53% |
| 20 | 46.40 | 47 | `tests/platform/test_pii_forms_notice.py` | slice0 | 0.51% |
| 21 | 45.99 | 15 | `tests/platform/test_recyclebin_guards_t53.py` | slice0 | 0.51% |
| 22 | 45.43 | 23 | `tests/platform/test_author_gate_2026_10_02.py` | slice1 | 0.50% |
| 23 | 43.86 | 9 | `tests/platform/test_integration_points_registered.py` | slice0 | 0.49% |
| 24 | 43.08 | 11 | `modules/crm/tests/test_crm_api_integration.py` | slice1 | 0.48% |
| 25 | 38.82 | 6 | `tests/test_e2e_draft_conflict_builder_2026_10_02.py` | e2e | 0.43% |
| 26 | 38.50 | 1 | `tests/platform/test_modtest_json_stdout_2026_09_29.py` | slice1 | 0.43% |
| 27 | 37.82 | 25 | `tests/platform/test_stage_select_2026_10_02.py` | slice0 | 0.42% |
| 28 | 37.26 | 6 | `tests/test_e2e_p8_module_builder_2026_09_26.py` | e2e | 0.41% |
| 29 | 36.67 | 8 | `tests/test_e2e_hard_cap_2026_09_25.py` | slice1 | 0.41% |
| 30 | 35.05 | 14 | `tests/test_e2e_pdf_unapproved_2026_09_30.py` | e2e | 0.39% |

### 1.4 長尾（11-11 累積 `file_seconds.json`，只含非 e2e 檔；1 203 檔／4 806 s）
前 10 檔 18.4%、前 30 檔 38.2%、前 100 檔 61.3%、前 200 檔 74.8%、前 400 檔 88.8%、前 800 檔 98.6%；不到 1 秒的檔 571 個、不到 3 秒的 880 個。
依資料夾：tests/platform 2 079 s（43%）、tests/ 其餘 1 450 s（30%）、modules/*/tests 1 162 s（24%）、檔名含 e2e 的非 e2e 階段檔 115 s。
原始表：`D:\Claude-pm\prune-audit\timing.tsv`。

## 2. 看出來的三個結構性事實
1. **tests/platform 太貴**：slice0 的 4 684 題用了 1 909 worker-秒，其中**每題 >5 秒的幾乎都是「掃整個 repo」或「起 git／pytest／modtest 子行程」**（見 §3 D1～D8）；它們在每一輪預跑、每一次建包都重做同一份索引。
2. **每個測試各自重建同一份昂貴的索引**：`ship_tier`／`module_update_delivery`／`modtest_*`／`scope_gate`／`gov_contract` 各自 `rglob("*.py")` 讀全部原始碼＋建 AST；`integration_points_registered` 對每個模組各掃一次「拿掉它之後」的全部檔（O(模組×檔)）。
3. **e2e 每題一份 live_server＋瀏覽器脈絡**（`live_server` 是 function scope）：最慢的檔每題 ≈ 7 秒；e2e 全體每題 2.06 秒，是非 e2e 的 5 倍多。`client` 夾具已經做過優化（範本庫複製＋demo 庫到用才複製），不是瓶頸。

## 3. D：很慢但可以改便宜寫法（只改寫、**題數不減**，守門意圖不變）
> 「估計省」是 worker-秒、依上面機制推估、**尚未實測**；實作時每一項要先量改前改後。建議動工順序＝省得多又不碰守門語意的先做。
| # | 檔／題 | 現況耗時（預跑） | 為什麼慢（證據） | 改法 | 估計省 | 風險／建議 |
|---|---|---|---|---|---|---|
| D1 | `tests/platform/test_e2e_classification.py::test_every_browser_test_carries_the_e2e_marker`（檔 68 s／8 題） | 66.8 s（全預跑最慢的一題） | `_collect()` 在子行程把**整個 tests＋modules**（~18 000 題）跑一次 `--collect-only`（`-p e2e_cls_probe`，第 61 行）；全閘門與 `gate_slices --check` 本來就各 collect 一次 | 改成**靜態**判定：AST 掃每個測試檔「用 e2e_browser／new_page／playwright 的函式 vs 有沒有 e2e marker」（檔級＋函式級），反向控制題（合成檔）保留；或重用全閘門預先 collect-only 的結果（`gate_slices.expected`） | **≈ 55 s** | 守門類，**保留語意、改寫**；改後要證明對現有 5 種寫法（`_PW_WAYS`）仍都紅 |
| D2 | `tests/platform/test_integration_points_registered.py::test_every_installed_module_can_be_removed_without_breaking_the_registry`（檔 44 s／9 題） | 37.7 s | 對每個已安裝模組 `code_capabilities(rest)` **重掃全部原始碼**（第 221～227 行，O(模組×檔)） | 每個檔的能力掃描結果只算一次（以檔為鍵快取），「拿掉模組」＝從合集裡扣掉該模組檔的貢獻 | **≈ 30 s** | 守門，保留；比對結果必須與舊算法逐模組相同（加一題等價對照） |
| D3 | `tests/platform/test_ship_tier_2026_09_28.py::test_real_repo_every_provider_module_resolves`（檔 84 s／63 題）、`test_module_update_delivery_2026_09_28.py::test_ship_tests_adds_consumers_of_a_changed_provider`（檔 128 s／45 題）、`test_scope_gate_2026_09_30.py`（檔 64～82 s／103 題）、`test_gov_contract_2026_11_08.py`（檔 79 s／131 題） | 48.4 s、64.1 s、32.4 s（最慢題） | 各檔**自己** `rglob("*.py")` 讀 `backend` 全部原始碼＋`ST.Repo(src)` 建 AST（module_update_delivery 第 316～318 行、ship_tier 的 `real_repo` fixture 第 331～338 行）；同一輪 4 個檔各做一次 | 抽一個 **session scope** 的 `repo_sources`／`ship_tier_repo` fixture（放 `tests/platform/conftest.py`），所有「讀真實 repo」的守門共用；`provider_check` 結果以 (模組, 政策) 快取 | **≈ 150～200 s** | 低；注意 xdist 每個 worker 各建一份（4 份），仍比現在每檔一份少 |
| D4 | `test_modtest_rebase_check.py::test_own_fixture_layer_change_…`（檔 64 s）、`test_modtest_scope.py::test_real_helper_private_change_selects_its_tests`（檔 67～87 s）、`test_author_gate_2026_10_02.py::test_ag_long_argv_spills…`（檔 45 s）、`test_modtest_json_stdout_2026_09_29.py`（1 題 38.5 s）、`test_stepfile_drill_2026_09_30.py`（檔 48 s） | 43.8、42.9、39.1、38.5、13.0 s | 這些是「測工具本身」：在**真實 repo** 上起 modtest／pytest／git 子行程（每題 40 秒上下），本質是工具的冒煙／整合測試，不偵測整合紅（`gate_slices.json` 的 slice0 `exclude` 也這樣歸類） | 保留**每個工具一題真實 repo 冒煙**，其餘改用 `tmp_path` 的**合成小 repo**（5～20 個檔）；或標成 `tool_slow` 只在改到 `tools/platform/**` 時才選（modtest 的差異選題已支援） | **≈ 120～160 s**（每輪） | 中：要確認「真實 repo 才會出的 bug」仍有一題抓得到；不刪題只換夾具 |
| D5 | `modules/accounting/tests/test_ledger_mutation_guards_2026_10_01.py`（檔 101 s／8 題，每題約 13 s；setup 也 12.7 s） | 13.6＋13.2＋… | 每個突變題都 `shutil.copytree(BACKEND)`＋`frontend` 整份複製，再起子 pytest（第 52～58 行）；6 個突變＝複製 6 次 | 複本**只複製一次**（module scope），每題對複本裡的檔做字面取代、跑完還原；或只複製 `modules/accounting`＋所需 core | **≈ 50～60 s** | 突變守門＝**保留**；還原必須驗（已有「還原全綠」正向控制題） |
| D6 | `tests/platform/test_generated_maps.py`（檔 77 s／11 題：`test_rc_the_three_guards_do_go_red_on_a_full_tree` 21.9 s、`test_rc_stale_test_map_is_detected` 20.9 s、`test_test_map_json_is_current` 20.1 s、setup 13.7 s） | 同左 | 三題各自重算一次 test_map／dep_graph（git 與全樹掃描），第一題 13.7 s 的 setup 也在重建圖 | module scope 共用一份「現算結果」，反向控制題只在複本上改一個欄位再比對 | **≈ 35～45 s** | 守門，保留；注意與 `generated` 組的「是否最新」題語意一致 |
| D7 | `tests/platform/test_module_boundaries.py`（檔 73 s／27 題：兩題 31.1／27.6 s、setup 13.8 s）、`test_response_keys_baseline.py::test_record_or_compare_against_baseline`（28.9 s）、`test_unit_cards.py::test_rc_stale_index_is_red`（18.8 s）、`test_module_changelog_follows_code.py`（18.3 s，git 逐模組） | 見左 | 各自重掃全樹（有 6 個 module scope fixture 但「prune／end-to-end」題另外重掃） | 共用 D3 的 `repo_sources`；changelog 題對每個模組一次 `git log` ⇒ 改成一次 `git log --name-only` 後記憶體分組 | **≈ 60～90 s** | 守門，保留；`changelog` 題要保證與現有判定同結果 |
| D8 | `tests/test_upgrade_drill_2026_09_25.py`（2 題各 24 s） | 24.1＋24.0 s | `test_convert_then_rollback_restores_v9[code|full]`：兩個參數各跑一次完整轉換＋回滾（git＋複製） | 兩個參數共用同一份基底複本（module scope），只重做轉換與回滾；或把 `[code]` 縮成較小的樹 | **≈ 20～25 s** | 升級流程的驗收題，**保留**；只換夾具 |
| D9 | e2e：`test_e2e_form_designer_beginner_tasks`（90 s／13 題）、`test_e2e_mobile_nav_cases`（88 s／38 題）、`test_e2e_users_list_privacy_pages_t47`（51 s／17 題）、`test_e2e_draft_conflict_builder`（39 s／6 題）、`test_e2e_p8_module_builder`（37 s／6 題）、`test_e2e_pdf_unapproved`（35 s／14 題）、`test_e2e_ux_onboarding`（35 s／11 題）、`test_e2e_nav_hierarchy`（29 s／8 題） | 這 8 檔合計 ≈ 404 s（e2e 階段 15%） | `live_server` 是 **function scope**（`conftest.py:2146`）：每題起一份 uvicorn＋新庫；`designer` fixture 每題重新開設計器頁。多數題是**只讀頁面**或「每題各自改草稿、不互相依賴」 | ① 加 `live_server_ro`（module scope、範本庫、**只給宣告只讀的檔用**：users_list、nav_hierarchy、mobile_nav 的畫面斷言題）；② 設計器題用 module scope 的頁面＋每題 `reload` 還原；③ 設計器 beginner 檔 `wait_for_timeout`／固定等待改成 `wait_for(state=…)` | **≈ 100～160 s（e2e 2 worker ⇒ 牆鐘 ≈ 1～1.5 分）** | 中高：e2e 共用伺服器會帶來題間污染（見記憶：偶發失敗先當競態）；**只對宣告只讀的檔做**、每檔改完壓力跑 3 次 |
| D10 | 非 e2e 的大型 client 檔：`test_quote_json_lost_update_2026_09_25.py`（55 s／43 題）、`test_finance_role_matrix_ext_2026_10_05.py`（51 s／77 題）、`test_line_events_all_2026_11_13.py`（48 s／104 題）、`modules/crm/tests/test_crm_api_integration.py`（43 s／**11 題＝每題 4 s**）、`test_strict_bool_sites_t49.py`（累積 68 s） | 同左 | 每題一份 `client`（範本庫複製＋lifespan）；crm 每題 4 s 異常高（可能每題 `make_user` 多個＋建大量資料） | 先量（`--durations=0` 單檔）再決定：crm 檔看是否每題都重建同一批資料 ⇒ module scope 的資料夾具；其餘 3 檔多為 N 題×0.5～1 s，**不建議動**（風險＞收益） | crm ≈ 25 s；其餘不動 | 只動 crm；其餘「保留」 |

**D 合計（保守～樂觀）**：≈ 645～850 worker-秒（非 e2e 545～690、e2e 100～160），約占預跑總 worker-秒的 **7～9%**；牆鐘約 **3～4 分**（非 e2e 除以 4 worker ≈ 2.3～2.9 分、e2e 除以 2 worker ≈ 0.8～1.3 分；階段之間是序列）。題數**不減**（0 題）。

> 如果再加上 §4 的 A／B／C 刪併，才有「題數」的減少；下表是彙整位置。

## 4. A／B／C：舊而無用的候選（hichan-10）

- 方法：靜態 AST 掃描全部 `backend/tests`、`backend/modules/*/tests`（只讀、未跑任何測試）；證據是原始碼行號與路由清冊（`tests/platform/route_inventory.json`）比對。
- 估秒：不在 `timing.tsv` 前 30 檔／前 50 題者，一律用 ≈0.37 s/題 估；跳過的題實際成本≈0（只剩收集時間）。
- 守門類（ratchet／baseline／guard）預設保留，這裡不列。
- **誠實結論：A／B／C 三類加起來可省的時間只有個位數秒到十幾秒（< 0.1% 的 9021 worker-秒）。** 這批「舊題」是維護成本與雜訊問題，不是時間問題；時間大頭在重型守門與 e2e（hichan-2 的 D 段）。下面 C 段列出的升級演練（約 96 s）是唯一值得考慮「改排程」的項目，但它們是管線演練，不是廢題。

### A　功能已不存在／改名／空殼／整檔 skip／xfail

| test (file::name or file) | evidence | est. seconds | est. tests | recommendation |
|---|---|---|---|---|
| `tests/platform/test_attachments_providers.py` 第 209／287／325／395／477／527／560 行共 7 題（`@pytest.mark.skip`） | 全部 skip 理由＝「第42班（使用者裁示）：傳票／出納／財務金額能力只屬財務角色與 superadmin…」；裁示後能力模型已改，題目測的是已被推翻的分工，不會再被啟用 | ≈0（收集成本） | 7 | **delete**（理由已寫在 skip；若要留歷史，改一行註解進檔頭即可）。需使用者／PM 點頭，因為是「使用者裁示」造成的 skip |
| `modules/payroll/tests/test_bank_account_2026_10_01.py:154` | skip 理由＝第42班「財務與出納合併」，出納唯讀／財務可編輯分工不再存在，行為由其他題涵蓋 | ≈0 | 1 | **delete**（同上，需點頭） |
| `modules/subcontract/tests/test_cashier_module_2026_08_31.py:136` | skip 理由＝第42班合併，「財務只能看、不能執行」不再存在 | ≈0 | 1 | **delete**（同上） |
| `tests/test_e2e_paydate_gap_t48.py:206` | skip 理由＝「等第 47 班 L1（payable_due_core）進 platform 才寫」，函式本體是佔位（`pass`／無斷言） | ≈0 | 1 | **rewrite or delete**：L1 已進 platform 就把它寫實；否則刪掉佔位，改在 backlog 記一條。不要讓佔位永遠算「已收集」 |
| `tests/platform/test_fail_stream_2026_09_30.py:55` `@pytest.mark.skip(reason="x")` | 位於**字串常值**內（待測的假測試檔原始碼），不是真的被 skip 的題 | 0 | 0 | **keep**（誤報；正對照用的夾具） |
| `tests/test_wording_guards_2026_09_23.py`：`_WD1_DEFERRED` 標的 3 題（GW1／GW2…） | `xfail(strict=True)`，理由＝使用者 2026-09-24 裁示先 xfail，等 `helpers/wording.py`；該檔至今不存在（已查 `helpers/wording.py`＝無此檔） | ≈1 | 3 | **keep**（strict xfail 是有意設計：檔案一出現就會 XPASS 變紅提醒拿掉標記）。只是 7 週沒動，建議 PM 決定要做還是撤案 |
| `tests/platform/test_gov_contract_2026_11_08.py` p3 `pytest.skip(...)` 分支（約 L254） | `KNOWN_P3_NOT_APPLICABLE = {}` 是空表 ⇒ 該 `skip` 分支永遠不會走（死分支）；第二個 skip（L302「不在強制名單」）是活的 | 0 | 0（死程式碼，不是死題） | **rewrite**：刪死分支與空表，或留註解說明「表空＝全部適用」。低優先 |
| `modules/payroll/tests/test_bonus_correction_2026_09_30.py:282` | `client.get(...) if False else None` 的死行（`cash` 變數沒被後面使用） | 0 | 0 | **rewrite**（刪該行）；小清理 |
| `tests/platform/test_option_lists_t62.py:304-307` | 條件恆假的殘留區塊（掃描判為死行） | 0 | 0 | **rewrite**（刪死行）；需人工再確認一次後再動 |
| `tests/test_image_guard_2026_11_13.py:602-604` | 掃描判為死行（今日新檔，仍在 T84 列車上變動中） | 0 | 0 | **keep**（等該檔穩定再說） |
| 0 題的檔 6 個：`modules/payroll/tests/test_bn16_award_status_filter_2026_09_24.py`、`modules/payroll/tests/test_bonus_award_export_watermark_2026_09_23.py`、`tests/test_e2e_bn12_award_preview_recall_page_2026_09_24.py`、`tests/test_e2e_bn3_manual_people_page_2026_09_24.py`、`tests/test_e2e_bn4_bonus_page_name_2026_09_24.py`、`tests/test_stock_batch_payment_2026_09_01.py` | AST 掃描：檔內 0 個 `test_*`（墓碑／搬走後留下的空殼）。**注意**：`..._watermark_...` 這支可能被會計側題目 import（待查），其餘 5 支僅有檔頭說明 | 收集 <0.1 s／檔 | 0 | **delete**（5 支）；`watermark` 先查有無 import 再刪。屬 PLAYBOOK「搬走後留墓碑」習慣的殘留 |
| `tests/test_e2e_*` 對應 bn12/bn3/bn4 頁面（上列 3 支） | 頁面 e2e 已被他處覆蓋或搬走，檔內無題 | 0 | 0 | 併入上一列 |
| 對「端點已不存在」的呼叫（`scan3`：測試呼叫、路由清冊查無） | 初篩 100+ 筆，**絕大多數是誤報**：測試自己掛臨時 app／`mount_modules` 假路由（`test_core_loader.py`、`test_deploy_dashboard_delivery_*` 等）。僅 `modules/payroll/tests/test_bonus_correction_2026_09_30.py::test_approve_opens_reversal_and_rebook_drafts_and_waits_for_payout` 是真要複核 | ≈1 | 1 | **keep**（全部）；上述 bonus 題人工複核：它呼叫的 `bonus.payouts` provider 路徑仍在，判不是死題 |

### B　重複題

| test (file::name or file) | evidence | est. seconds | est. tests | recommendation |
|---|---|---|---|---|
| `modules/payroll/tests/test_payslip_races_t46.py` 整檔 ⊂ `test_payslip_races_t47.py` | 8 題與 t47 同名且本體相似度 1.0（逐題比對：`..._plant_paid_via_remit...`、`..._delete_takes_the_write_lock...`、`..._unpay_does_not_wipe...`、`..._unsign_after_concurrent_payment...`、`..._delete_signed_file...`、`..._upload_after_concurrent_upload...`、`..._upload_after_concurrent_payment...` 等）；t47 是 t46 的超集 | ≈3（8 題×0.37） | 8 | **delete** t46（保留 t47）；請 payroll 作者（t46/t47 班）確認 t47 沒有少 t46 獨有的題後再刪 |
| `tests/test_money_round_half_up_2026_09_26.py::test_accounting_voucher_line_rounds_half_up`（L173） | 與 `modules/accounting/tests/test_money_round_half_up_2026_09_26.py::test_accounting_voucher_line_rounds_half_up`（L8）**逐字相同**；後者檔頭寫明「M06 搬遷自 tests/ 同名檔」，前者是搬遷後留下的副本（還包了 `@requires_module`） | ≈0.4 | 1 | **delete** tests/ 那份（模組內那份是正本） |
| `tests/test_totp_qr_push_2026_09_08.py::test_qr_approve_via_session_token_same_account_succeeds`（L115）vs `test_qr_approve_with_phone_session_then_status_issues_session_once`（L218） | 相似度 1.0；前者的步驟是後者的前半段 | ≈0.7 | 2 | **merge**（保留較完整的後者，補一個斷言即可）；也可 keep——題小、風險低 |
| `tests/platform/test_bp1_layout_c1_2026_10_14.py`、`..._c2_...`、`..._quote_form_...` 三檔各有一題 `test_flag_gated_x_show_has_no_static_inline_display` | 相似度 0.86：同一個「x-show 不可有靜態 inline display」檢查在三個頁面各複製一份（只差頁面檔名） | ≈1 | 3 | **merge** 成一題參數化（三頁面參數）；題數 3→1（或 1×3 param），省不了多少秒，只減維護 |
| `modules/payroll/tests/test_payslip_perm_wiring_t68.py` vs `modules/supply/tests/test_supplier_perm_wiring_t70.py` 的 `test_editing_the_matrix_changes_the_outcome_and_superadmin_is_unaffected` | 相似度 0.86，但各測自己模組的權限矩陣接線 | — | 2 | **keep**（不同模組的接線，不是重複） |
| `tests/test_h3_attack_merge_tools.py::test_post_route_summary_does_not_absorb_new_select_star` ↔ `tests/platform/test_resolve_baselines_2026_11_13.py::test_select_star_mismatch_is_reported_and_summary_is_still_recomputed` | 相似度 0.82–0.83，同在驗合併工具的 select-star 行為 | ≈1 | 2 | **keep**（兩邊是不同工具層；且在 T84 列車上正在變動，先別動） |
| 同檔近似題（相似度 0.80–0.92）：`modules/crm/tests/test_crm_item_reads_2026_09_24.py`、`modules/tender_radar/tests/test_tender_source_state_2026_10_03.py`、`tests/test_dashboard_mine_2026_11_13.py`、`tests/test_webauthn_rp_id_column_2026_09_11.py`、`tests/test_backup_retention_settings_2026_09_01.py`、`modules/analytics/tests/test_reports_sales_owner_2026_09_14.py` | 同一檔內兩題「準備＋斷言」結構相似但斷言不同（不同分支／不同前置） | — | 約 12 | **keep**（相似≠重複；合併會讓失敗訊息變差） |

### C　一次性遷移／修補驗證，數班不變

| test (file::name or file) | evidence | est. seconds | est. tests | recommendation |
|---|---|---|---|---|
| `tests/test_overhead_recalc_t48.py` 與 `tests/test_charity_recalc_t52.py`（凍結重算類） | 驗「一次性重算遷移」；但 `api/overhead.py` 仍呼叫 `migrations_frozen`，所以遷移函式仍是活程式 | 小（≈各數秒；未在 top-50） | 未逐題計 | **keep**（程式還活著）；可 **slim**：只留「冪等＋金額正確」兩題，其餘情境題下放 slow 標記 |
| `tests/test_upgrade_drill_2026_09_25.py`（2 題參數化，`skipif` 無 V9 commit `c83dae6e`） | 升級演練：用舊版 V9 commit 建庫再升到現行；`timing.tsv` 約 48 s | ≈48 | 2 | **keep，改排程**：每日重型驗證不必每班都跑，建議移到 nightly／發版前（屬 hichan-2 D 段「排程」） |
| `tests/platform/test_stepfile_drill_2026_09_30.py`（7 題） | step-file 演練：整條升級管線的實跑；約 47.9 s | ≈48 | 7 | **keep，改排程**（同上） |
| 其餘檔名含 `migration`／`backfill` 的測試（`tests/` 與 `modules/*/tests/` 共 7 檔，檔名比對；未逐檔驗內容） | 驗一次性回填函式；若函式仍在啟動鏈上就每次啟動都會跑（未逐一核對鏈，標「待查」） | 估 ≈10 | 約 25（估） | **keep**（無證據顯示已失效；逐檔核對啟動鏈後才能談刪） |
| `modules/*/tests/*_t4x.py` 老班次（t42–t52）回歸題 | 檔名班次老，但被測函式與端點皆還在（已用路由清冊與 import 檢查） | — | — | **keep**；老≠舊，沒有證據顯示已失效 |

### hichan-10 小結

- **可直接刪、風險低**：6 個 0 題空殼檔（5 支確定；watermark 一支先查 import）、`tests/` 內與 `modules/accounting/tests` 重複的 `test_accounting_voucher_line_rounds_half_up`、`test_payslip_races_t46.py`（作者確認後）。
- **需要使用者／PM 點頭**：9 個因第42班使用者裁示而 skip 的題（7＋1＋1）。
- **需人決定做或撤**：`_WD1_DEFERRED`（3 題 strict xfail，`helpers/wording.py` 不存在）、`test_e2e_paydate_gap_t48` 佔位題。
- **整體節省**：約 15–20 題、≈6–8 s。**升級演練 ≈96 s 改排程**才是這三類裡唯一有感的項目。
- 沒跑任何測試；未逐題驗證的項目（`watermark` 檔有無被 import、`test_option_lists_t62.py:304-307` 死行）已在表內標「待查」。

### hichan-2 抽查（讀碼，沒跑測試）
- 6 個 0 題檔：逐檔 `def test_` 計數都是 0（各 9 行、`test_stock_batch_payment` 18 行）。`test_bonus_award_export_watermark_2026_09_23.py` 全 repo 只在 `modules/accounting/tests/test_voucher_export_watermark_2026_09_23.py:11` 的**文件字串**被提到、沒有 import ⇒ 6 支都可以刪。
- `test_payslip_races_t46.py`（9 題）的題名**全部**出現在 `test_payslip_races_t47.py`（14 題）裡；t47 多 5 題。⇒ t46 確實是 t47 的子集（本體是否逐題相同由 payroll 作者確認）。
- h10 標「待查」的兩項（`test_option_lists_t62.py:304-307` 死行、`bonus_correction` 的 `if False else None` 行）沒有再核，維持「小清理、低優先」。

### A／B／C 合計
| 類 | 題數 | 省時 | 備註 |
|---|---|---|---|
| 可直接刪（低風險） | 6 個空殼檔（0 題）＋1 個重複題＋t46 整檔 8～9 題 ≈ **10 題** | ≈ 4 s | 6 空殼檔、`tests/` 內與 `modules/accounting/tests` 同名重複題、t46 |
| 需 PM／使用者點頭 | 9 題（第 42 班使用者裁示造成的 skip：7＋1＋1） | ≈ 0（skip 本來就不跑） | 刪＝清雜訊，不省時間 |
| 需人決定做或撤 | 3 題 strict xfail（`_WD1_DEFERRED`，`helpers/wording.py` 不存在）＋1 個 paydate_gap_t48 佔位 | ≈ 1 s | 保留到有決定 |
| 合併（B） | 三頁面 x-show 檢查 3→1、totp 兩題 2→1 | ≈ 2 s | 只減維護 |
| **合計** | **約 15～20 題（不含 9 題 skip）** | **≈ 6～8 s** | **< 0.1% 的 9 021 worker-秒** |
| **改排程（不是廢題）** | `test_upgrade_drill`（2 題 ≈ 48 s）＋`test_stepfile_drill`（7 題 ≈ 48 s） | **≈ 96 s／輪** | 移到 nightly／發版前；與 §3 D8（共用基底複本）擇一或併用 |


## 5. 建議的做法（順序）
1. **先量**：下一次預跑（`modtest --full --keep-going`）加 `--durations=0`，存逐題耗時，這份稿的 §1 就能換成精確的前 50 題／前 30 檔。
2. **D3＋D7（共用 repo_sources fixture）**最先做：一個 `tests/platform/conftest.py` 的 session fixture 影響約 10 個檔，省得最多、風險最低、不碰任何守門語意。
3. **D1、D2、D5、D6**：各自獨立、單檔改寫，改前改後各量一次，附「反向控制仍紅」的證據。
4. **D4（工具測試換合成 repo）**：每個工具保留一題真實 repo 冒煙；請工具作者（modtest／author_gate／ship_tier）確認。
5. **D9（e2e 共用伺服器）**最後做、只對宣告只讀的檔，並在改完壓力跑；e2e 的牆鐘大頭（22 分）值得，但風險最高。
6. **A／B／C 的刪除**：每一項都需要對應模組作者確認；刪的同時調低 `preflight_guards.json` 的 `min_tests` 與 `gate_slices.json` 的清單（守門測試會在題數縮水時報「未能檢查」，這是設計）。

## 6. 本稿**沒有**建議動的
- 所有 ratchet／baseline／guard（`tests/platform` 的 `*_ratchet*`、`*_baseline*`、`test_no_*`、`test_*_guard*`、`unit_cards`、`route_table golden`、`changelog follows code` 等）：只建議**改寫得更便宜**，沒有一項建議刪。
- 單檔 0.5 秒以下的長尾（占題數大宗、占時間小宗）：逐題檢討的收益太低。
- 資料不足以判斷的題：寫成「先量」（§5-1），不憑感覺刪。
