# t60/t61 分支 → 可能變紅的既有守門／e2e（閘門前預測；靜態比對，未執行）

> 作法：每個分支相對其合併基底的非測試檔案，對照既有測試／生成物引用它們的清單（grep 靜態比對）。**「預期」欄是預測，不是結果**；跑過之後以實際為準。
> 新 e2e 腳本：`tools/platform/e2e_t60_t61_on_state.py`（只寫未跑；整合樹需同時含 S5＋S6＋t60）。

## 一、跨分支通用守門（任何新路由／新檔／新設定群組都會碰）

| 守門（檔） | 觸發條件 | 哪些分支會觸發 |
|---|---|---|
| `test_write_endpoints_are_audited_2026_09_24` | 新的 POST/PUT/DELETE 路由沒有 `_audit` 且不在 EXEMPT | t60-s0s1（menu preview，已修）、t60-s2（def_pipeline approve/activate/cancel：確認有 `_audit`）、t61-s6（`POST /api/user-buttons/{m}/{p}/preview`：唯讀，需 EXEMPT 或確認） |
| `tests/platform/test_route_inventory`／`route_inventory.json`、`test_route_table_golden_2026_10_05`（`route_table_golden`） | 新增路由 | s0s1（menu preview、def-governance ×3）、s2（def-pipeline ×4）、s5（custom-fields ×2）、s6（user-buttons ×3） |
| `test_route_ownership`、`test_module_routes_declared`、`docs/platform/modules.json` | 新 router／helper 沒登記單位 | 所有改 `main.py` 的分支（s0s1、s2、s5、s6、gov） |
| `test_write_golden`＋`write_golden_cases/cases_zz_rest.py` | 新的寫入端點需要金標案例／豁免 | s2、s6-gov（train/t60-int 已改它）；s6 的 preview 若為 POST 需豁免或案例 |
| `test_l1_interface_snapshot`／`_l1_interface.py`／`test_version_slots`／`test_train_number` | `helpers/*` 公開名稱變動（新增 `builtin_fields`、`user_buttons`、`menu_builder` 等） | s0s1、s5、s6（快照要 `--update --pending`） |
| `test_changelog_sections`、`test_module_changelog_follows_code`、`test_core_bump` | 改 `core/`、`modules/*` 程式 → 對應 CHANGELOG `(next)` 段 | s0s1（core, case, supply）、s4（analytics, subcontract）、s5（core, case, supply）、s6（+subcontract） |
| `test_settings_baseline_owners`、`settings_deploy_baseline.json`、`test_settings_registry_t54`、`test_settings_ui_plain_language`、`test_settings_security_t54` | 新設定群組（`builder_menu/layout/governance/custom_fields/actions`） | s0s1、s2、s4、s5、s6（群組檔尾各一塊 ⇒ 合併時 settings_groups.py 衝突點） |
| `unscoped_reads_ratchet`（`unscoped_reads_baseline.json`） | 新的 SELECT 單位表且函式內沒有核准 helper | **s5/s6：`helpers/builtin_fields.py::usage_counts` 的 `SELECT … FROM %s`（表名是變數）⇒ 預期新增一筆 `dynamic`**（`quotations`/`suppliers` 都在 U0A 單位表內）；若走 `--write` 重產要先確認不是放寬 |
| `test_map.json`／`dep_graph.json`／`UNIT-INDEX.md`（`regen_all`） | 任何新測試檔／新模組檔 | 所有分支（合併後重產） |
| `test_wording_guards_2026_09_23`、`test_alpine_double_init_2026_09_23`、`*_no_native_dialogs*` | 前端新字串／Alpine 初始化／`confirm()`/`alert()` | s4（layout-editor）、s5（custom-fields.js、case-management.html）、s6（user-buttons.js）、menu-pending（menu-editor.js） |

## 二、逐分支

| 分支 | 非測試檔變動（要點） | 既有測試／e2e 可能受影響 | 預期 |
|---|---|---|---|
| `wip/t60-menu-pending-r1`（dcf6e85e4） | 只有 `frontend/static/menu-editor.js` | `test_alpine_double_init`／靜態前端守門（menu-editor.js 沒有被其他測試直接引用）；`test_menu_builder_bp1` 不受影響（後端沒動） | 低；新增的 node 測試要在有 node 的環境跑 |
| `wip/t60-s0s1-r1` | `core/customization.py`、`core/menu.py`（已在 t59-int）＋ def_governance、definitions.py（preview gate）、case `quotations.py`／`material_orders.py`（遮蔽）、`case-management-*.js`、`suppliers.html`、`layout-editor.js`、`layout-runtime.js`、`sidebar.js`、`def-governance.js` | `test_platform_catalog`（customization）、`test_menu_layout`／`test_menu_inject`／`test_sidebar_regroup`（core/menu）、`test_def_review_bypass_2026_09_30`／`test_definitions_draft_etag_2026_10_02`（definitions 發布路徑）、案件頁大量 `test_case_page_*`／`test_segment_base_adopts_saved`（case-management-core.js）、`test_case_money_mask`／`test_material_*`／`test_finance_role_matrix_ext`（material_orders、quotations 遮蔽）、`test_bp1_layout_suppliers`（layout-editor／layout-runtime／suppliers.html） | **中**：案件頁／發布路徑的既有測試是最可能的紅燈；旗標關閉＝逐位元不變是承諾，需靠這些測試證明 |
| `wip/t60-s2-r1`（含 s0s1） | 加 `routers/def_pipeline.py`、`definitions.py`（publish/restore 先走管線） | 同上＋`test_def_review_bypass_2026_09_30`（自訂模組送審路徑 `handle_publish` 在其前面）、`test_settings_pending_t54`（`config_changes` 共用 `def:*` domain）、配置帳本測試 | **中**：S2 旗標關時 `handle_publish` 必須回 None；e2e 腳本 S2 OFF 段驗證 |
| `wip/t60-s4-r1` | `settings_groups.py`（`builder_layout` 5 個頁面旗標）、`devices.html`/`procurement.html`/`vendor-contractors.html`、`layout-editor.js`、analytics／subcontract module.json＋CHANGELOG | `test_bp1_layout_*`、`test_tender_p9_layout_e2e_2026_09_26`、`test_layout_editor_no_native_dialogs`、各頁既有 e2e（devices／procurement／vendor-contractors 頁的 `test_e2e_*`）、`test_module_changelog_follows_code`（analytics／subcontract）、`test_module_package_files` | 中低：新增頁面掛載點＝`html` 變動，各頁既有 HTML 內容守門要看 |
| `wip/t60-s8s3-r1` | 只有 `layout-editor.js`＋2 個測試調整 | `test_bp1_layout_suppliers`、`test_layout_editor_no_native_dialogs`、`test_tender_p9_layout_e2e` | 低 |
| `wip/t61-s5-impl-r1` | 新 `helpers/builtin_fields.py`、`routers/custom_fields_builtin.py`；改 `helpers/custom_fields.py`、case `quotations.py`（分段存檔閘門＋PUT 現值覆蓋）、supply `suppliers.py`、`case-management-core.js`/`.html`、`suppliers.html`、`custom-fields.js` | **案件存檔鏈**：`test_case_stages_endpoints`、`test_case_semi_unlock`、`test_case_stage_connectors`、`test_case_change_approve_deadlock`（核准重放）、`test_begin_only_via_begin_write`、`test_segment_base_adopts_saved`（409 基準）、`test_case_page_parts`；供應商：`test_u0a_sinks`、`test_geo`、`test_map_customers_suppliers`、`test_exception_detail_leak`（POST 錯誤處理改過）；`test_custom_fields_*` | **中高**：quotations.py 的 PATCH／PUT 兩條路徑是高流量；財務角色舊整包存檔的預檢順序改動要特別看 `test_finance_role_*`；**ratchet 新增 dynamic 一筆** |
| `wip/t61-s6-impl-r1`（含 s5） | 再加 `helpers/user_buttons.py`、`routers/user_buttons.py`、`user-buttons.js`、subcontract `module.json`（匯出登記）、`suppliers.html` 插槽 | 上列＋`test_module_package_files`／`module.json` 驗證（`core/customization.py` 對 exports 未知鍵＝載入失敗，本分支沒加鍵）、`test_capabilities_registry`、`test_core_loader`、`test_e2e_*` 供應商頁（suppliers.html 加 `data-button-slot`） | 中：subcontract module.json 變動連動 CHANGELOG／套件檔守門 |
| `wip/t61-s6-gov-r1`（含 t60 全部 ＋ `ACTIVE_KINDS` 加 `user_buttons`） | `def_pipeline.py` 的名單、`test_t61_s6_gov` | 同 s2；`ACTIVE_KINDS` 含 `user_buttons`，kind 沒登記（s6-impl 不在樹裡）時**不起作用**（註解已說明）⇒ 單獨合併安全，但 e2e 的 S2/S6 段要在同時含 s6-impl 的樹上才有意義 | 中低 |
| `train/t60-int`（累計 16 提交） | 以上 t60 全部＋`tests/platform/test_write_golden.py`、`unscoped_reads_baseline.json`、`version_manifest.json` | `test_write_golden`（已更新）、`test_unscoped_reads_ratchet`（baseline 已更新；s5 合入後要再重產）、`version_manifest` 相關（`test_train_number`／`test_version_slots`） | 已由列車自己跑過；合入 t61 後重點是 ratchet＋route golden |

## 三、合併順序建議（降低衝突與紅燈）
1. t60-int（已含 s0s1／s2／s4／s8s3／menu-pending）→ 2. s5-impl → 3. s6-impl → 4. s6-gov（只改名單）。
2. 衝突熱點：`helpers/settings_groups.py`（檔尾區塊）、`main.py`（include_router 行）、`docs/platform/modules.json`、各 `CHANGELOG.md (next)`、`l1_interface_snapshot.json`、`settings_deploy_baseline.json`、`case-management-core.js`（s0s1 與 s5 都動）、`suppliers.html`（s0s1、s5、s6 都動）。
3. 合入後生成物一次重產：L1 快照（`--update --pending`）、`route_inventory`／`route_table_golden`／write-golden、`unscoped_reads_baseline`（先看 diff 再 `--write`）、`regen_all`。

## 四、e2e 腳本覆蓋對照（`e2e_t60_t61_on_state.py`）
| 區段 | 旗標關＝不變 | 旗標開＝可用 | 遮蔽優先 | 非最高管理者看不到管理定義 |
|---|---|---|---|---|
| S5 欄位目錄 | GET 空、寫入不存 | 驗證負例 7 種、發布、型別不可改、供應商值存取、usage | 受限檢視者讀不到供應商本體；公開形狀不含內部鍵 | 定義讀／草稿／usage 對 admin、受限者皆拒 |
| S6 按鈕目錄 | GET 空、catalog／preview 404、未登記頁 404 | catalog、驗證負例 9 種、預覽、發布、關回 OFF 與基準相同 | 受限者與無權限 admin 看不到匯出鈕；預覽以他人身分隱藏 | catalog／定義／草稿／預覽對 admin、受限者皆拒 |
| S2 治理 | ledger／pending 404 | 放寬→pending（changeId、effectiveAt、reasons）、未生效、不得自己核准、第二位核准、啟用或誠實拒絕、收緊立即 | pending 不改公開欄位 | ledger／pending 對受限者拒 |
| S4 版面旗標 | 5 個頁面旗標預設可切、`/api/layout` 不變 | （僅旗標；頁面級瀏覽器驗證待機器空閒） | — | — |
| BP1 選單＋pending | 無 builderMenu、preview 404 | relabel 發布誠實（pending⇒選單不變；直接⇒已變） | 受限者選單不出現原本看不到的項目；builderMenu 只給最高管理者 | 同左 |

## 五、限制（誠實）
- 腳本沒跑過；建立供應商的 body、`/api/layout/<module>` 的模組鍵、`approve` 的回應碼等，依本樹實況可能需微調（找不到的區段印 SKIP，不會靜默 PASS）。
- 沒有案件資訊（`case_info`）的值寫入段：案件存檔鏈需要完整報價單夾具，HTTP 腳本只驗定義與公開欄位；案件存檔的 409／財務角色路徑由 `test_builtin_custom_fields_2026_10_14` 負責。
- 瀏覽器（點擊）驗證沒有寫：機器安靜期不開瀏覽器；待 02 放行後另補。
