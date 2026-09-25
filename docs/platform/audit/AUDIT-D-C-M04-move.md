# 稽核：C 的 M04 外包工班搬進 modules/subcontract（PLAYBOOK §B；合回前稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。只審新版（CORE-SPEC 35014aaa）。
> 對象：`origin/wip/c-m04` **`dd6f1550`**（疊在 c-case-access-2 a82da8ec 上；基底 `58c8d652`）。搬遷 `a4be3e17`；前置 `f96b062f`（normalize_date 下沉 L1）、`e390e748`（IP-12／13／14）、`0980c06e`（dep_scan 改用 module_files）；後續 `b3a79250`、`f5e59af4`、`9b5b4a26`、`aa19fe48`、`edcb123f`、`dd6f1550`。
> 主持 2026-09-26：C 已經找到 5 道「會隨模組在不在而改變」的守門，並分派給 A、B 修；這幾道列為「已知、已分派」，不算 M04 的必修。之後 C 會改用 `wip/c-case-access-3`、`wip/c-m04-2` 重新上車；D 屆時只複核差異與 CA-M1。
> 反向控制的範圍依主持定的標準：**`tests/platform`，加上所有提到該模組的測試檔**（PLAYBOOK §B-11）。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（真的刪掉模組）、`-D2`（模組在時的基準），都是 detached；Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。

## 0. 結論

- **系統照常這一半成立**：刪掉模組之後，app 照常啟動，`tests/platform` 裡除了允許清單與已知的題目之外全綠；IP-12／13／14 的缺席說明也有題目守。D 做了 4 項突變，全部轉紅。
- **必修 1 項**：
  - M04-M1：真的刪掉 `modules/subcontract` 之後，`tests/platform` 加上 49 個提到外包工班的檔，結果是 **1273 passed、77 failed、2 個檔收集失敗**。同一批題在模組存在時是 **1411 passed、0 failed**。
  - 扣掉允許清單的 2 題、已知已分派的 4 題，以及第四班合回後會轉綠的 1 題（EM1 other），**還有 70 題加 2 個收集失敗的檔**。這些題需要 M04 存在，卻放在模組外面。
  - C 在 `9b5b4a26` 做的反向控制只跑了 `tests/platform`，範圍比 §B-11 要求的小。
- 建議 3 項、觀察 3 項。

## 1. 反向控制實測（§B-11，新範圍）

| 輪次 | 樹 | 結果 |
|---|---|---|
| 模組在（基準） | D2 `dd6f1550`：tests/platform＋`modules/subcontract/tests`＋49 檔 | **1411 passed**、exit 0 |
| 刪掉模組（加 `--continue-on-collection-errors`） | D `dd6f1550`：tests/platform＋49 檔 | **1273 passed、77 failed、2 errors**（19 分鐘） |
| 刪掉模組（`--collect-only`，不加旗標） | 同上 | **Interrupted: 2 errors during collection**、exit 2 ⇒ 預設參數下這一輪一題都不跑 |

紅的題分類如下：

| 類別 | 題 |
|---|---|
| §B-11 允許（2） | `test_modules_json_lists_only_existing_units`、`test_unit_index_is_current` |
| 已知、已分派（主持 06:02；4） | `test_case_read_scope::test_every_case_read_is_classified`、`test_integration_points_registered::test_real_scan_sees_a_known_capability`（正對照綁 `dispatch.row`；a-m10 d2a95371 已改綁 `daily.check`，已隨第四班合回）、`::test_registry_matches_code`、`test_l1_interface_snapshot::test_interface_matches_snapshot` |
| 第四班合回後會轉綠（1） | `test_em1…::test_em1_the_other_long_messages_did_not_change_a_single_character`（origin 上已經改用 `module_installed` 略過） |
| **M04-M1：需要 M04，卻在模組外（70＋2 個收集失敗的檔）** | 見下表 |

| 檔 | 紅 |
|---|---|
| `test_report_recognition_basis_2026_09_24.py` | 7 |
| `test_dispatch_invoice_payable_date_2026_08_30.py` | 6 |
| `test_contractor_bank_branch_2026_09_24.py` | 5 |
| `test_contractor_voucher_paid_date_2026_08_31.py`、`test_cashier_module_2026_08_31.py` | 各 4 |
| `test_t100_export_2026_09_01.py`、`test_legal_audit_d_r1_r3_2026_09_26.py`、`test_dispatch_file_uploads.py` | 各 3 |
| `test_reports_export_expenses`、`test_privacy_notice_r3`、`test_pii_archive_mirror`、`test_mp1_map_points_link_to_records`、`test_money_round_half_up`、`test_module_permission_fixes`、`test_e2e_report_recognition`、`test_e2e_contractor_pii_upload_failure`、`test_dispatch_import_to_quote_persists`、`test_dispatch_edit_guard`、`test_cashier_execution_history`、`test_case_finance_summary` | 各 2 |
| `test_visual_management`、`test_reports_expenses`、`test_module_history`、`test_exception_detail_leak`、`test_e2e_privacy_notice_r3`、`test_e2e_cashier_subcontract_absent_notice::test_no_notice_when_subcontract_is_present`、`test_e2e_case_page_golden`、`test_e2e_case_open_requests`、`test_cascade_self_tiers_records_signer`、`test_api_integration::test_contractor_dispatch_update_conflict_returns_409`、`test_em1…::test_em1_the_five_messages_speak_the_screen_words_not_the_code_words` | 各 1 |
| **收集失敗**：`test_quote_json_lost_update_2026_09_25.py`（:19 `import modules.subcontract.api.vendor_contractors as vc`）、`test_write_lock_released_on_error_2026_09_25.py`（:10 `import modules.subcontract.api.contractor_vouchers as cv`） | 整檔 |

## 2. D 的突變

題目：`modules/subcontract/tests`＋`tests/platform/test_subcontract_connectors.py`＋`test_cashier_module`＋`test_t100_export`＋`test_case_bundle`，共 36 題；每一輪都確認有收到題。

| # | 突變 | 結果 |
|---|---|---|
| MM1 | 出納執行歷史在 M04 不在時不說明缺什麼（`contractorNotice` 恆為空） | 紅（`test_cashier_and_t100_without_m04`） |
| MM3 | T100 預覽在 M04 不在時不說明缺什麼 | 紅（同上） |
| MM5 | ModuleSpec 不登記 IP-12 `dispatch.list_for_case` | 紅（6） |
| MM6 | ModuleSpec 不登記 IP-14 `contractor_voucher.public` | 紅（7） |

## 3. 發現

### 必修

**M04-M1　70 題＋2 個檔需要 M04，卻留在模組外，新範圍的 §B-11 反向控制不過**
- 為什麼是必修：與 M12 的 M-1、M02 的 M02-M1 屬於同一類，而這次量最大。其中 2 個檔在模組層級 import `modules.subcontract` ⇒ 預設參數下，整輪反向控制在收集階段就中斷。
- 建議修法（比照 M02-M1）：
  - 純 M04 行為的檔整檔搬進 `modules/subcontract/tests`：派工、匯款申請、承攬人員名冊、銀行分行、付款日等。
  - 混合檔只拆出需要 M04 的題；「L1／其他模組拿外包工班當資料來源」的題（報表認列、出納、T100、封存個資、地圖、稽核 D 的 R3 題），改成 M04 不在時 skip 並寫明原因，或者改用合成資料。
  - 兩個收集失敗的檔：把 import 移進題目裡面。
  - 修完用新範圍重跑，**同時跑一輪不加 `--continue-on-collection-errors` 的**，附上數字。

### 建議

- **M04-S1　INTEGRATION-POINTS 的提供方路徑寫錯**：IP-1、IP-12 寫成 `modules/subcontract/vendor_contractors.py`，IP-14 寫成 `modules/subcontract/contractor_vouchers.py`，但實際檔案在 `modules/subcontract/api/` 底下。D 把 INTEGRATION-POINTS 裡所有 `.py` 路徑逐一對照 `dd6f1550`，不存在的只有這兩個。X-2 豁免只看 `modules/<key>` 資料夾，所以守門沒有紅。建議修正路徑，並在登記表守門加一條：模組在的時候，提供方路徑的檔案要存在。
- **M04-S2　README 的「案件模組不在時」還是舊的判準**：README 寫「案件表不存在 ⇒ 404」，這是 CA-M1 修正前的說法。c-case-access-2 已經改看 `case.present`，而 c-case-access-3 將改走 IP-12。重新上車時要一起更新。
- **M04-S3　SPEC.md 的依據指向模組外的題**：與 M02-S1 同一件事。M04-M1 修完之後，要改指 `modules/subcontract/tests`。

### 觀察

- **O-1　`privacy_notice_acks` 改用模組自己的表延後了**：ROADMAP 原本寫「M04 搬遷時改用模組自己的表」。C 延後，理由是需要模組 migration 加上資料移轉，並且在 README 與 ROADMAP 都寫明。D 認為理由成立，但這是在改變 ROADMAP 已排定的事，**需要主持確認**要延後到哪一班、由誰做。
- **O-2　其他模組仍然直接讀 M04 的四張表**：README 已經寫明（凍結 migration 讓表在模組不在時仍然存在，所以讀取不會壞）。讀取連接器另外開題。
- **O-3　稽核樹的殘留資料夾**：D 的兩個稽核樹在切換分支之後，留下只剩 `__pycache__` 的 `modules/crm`、`daily_tasks`、`netplan`。這次開跑前已經清掉。這就是 AUDIT-D-A-M10-M12 的 O-4：`module_installed` 會把這種資料夾當成「模組在」。列車與各線在切換分支後跑反向控制，要先清掉這種資料夾。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| M04-M1 | | | |
| M04-S1～S3 | | | |
| O-1～O-3 | | | |
