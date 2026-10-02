# 測試衛生盤點（da；唯讀；初版 2026-10-03）

對象：整合樹 `wip/train-33-int1`@744ddf05（1,059 個 `test_*.py`、tests/platform 148 檔有計時）。
方法：**純靜態分析**（AST／路由表／檔案存在性）＋既有計時檔 `tools/platform/author_gate_times.json`（a5dea50c 實測）＋我本班稽核時做的突變紀錄。**沒有跑全量**，所以「執行期實際略過 60 題、xfail 3 題」無法逐題列出（手邊沒有近期 junit／fail_stream 紀錄）；下面用「靜態條件」推斷哪些會長期略過，並標明不確定處。
腳本：`hyg.py`（在 da 的 scratchpad，可重跑；輸出 JSON 約 1,000 行）。**沒有刪任何檔。**

## 結論先行
1. **沒有發現「測試對象已不存在、卻仍在驗證」的失效守門。** 靜態掃到的 91 個端點、75 個頁面、26 個 js、2 個 import 引用「不存在的東西」，抽查後**除 1 組孤兒死程式碼（見 §2）外全是刻意的**：合成路由／頁面（`/api/zz*`、`foo.html`）、「這個檔案不可以回來」的反向守門（`case-management.js`、`custom-modules-nav.js`）、候選名單（`accounts.html` 等）、測試資料夾內的 fixture。無一是「功能被移除而測試漏改」。
2. **長期略過只有兩類是真的**：Passkey 功能暫緩（`PASSKEY_ENABLED=False`，6 檔）與一題 `pypdfium2` 未安裝；另有 1 題 xfail（WD1 `helpers/wording.py` 尚未建立，使用者裁示先 xfail）。其餘 800 多個「略過標記」都是**模組不在安裝包／平台別／環境旗標**的條件式，在完整產品環境下會執行。
3. **「沒有 assert」的 59 題大多是誤報**（改用 `expect=422`、`_refused()`、`_clean()`、`scenario_*()` 等輔助函式斷言）；真正偏弱的只有「不丟例外」型，見 §3。
4. **重複覆蓋很少**：函式本體完全相同、跨檔的只有 2 組。46 組「同檔名主幹、散在 modules/*/tests 與 backend/tests」的檔案**內容全不相同**（各模組只放自己那部分），不是複製。
5. **高成本低價值**主要在 tests/platform 的「工具演練類」（建包／模組更新／scope gate／modtest／stepfile），前 30 檔合計約 22 分鐘（全 148 檔約 28 分鐘）；多數只在**工具或其輸入檔改動**時才有意義，建議依 diff 觸發（見 §5）。

## (1) 長期略過／預期失敗
靜態標記數：`requires_module` 292、`pytest.importorskip` 269（其中 252 是 playwright）、`pytest.skip(...)` 185、`skipif` 77、`xfail` 1。

| 類別 | 條件／原因 | 數量（靜態） | 永遠略過？ | 建議 |
|---|---|---|---|---|
| Passkey 暫緩 | `not PASSKEY_ENABLED`；`backend/helpers/auth.py:83 PASSKEY_ENABLED = False`（常數） | `test_e2e_passkey_2026_09_11`、`test_webauthn_b64url`、`test_webauthn_basic`、`test_webauthn_config`、`test_webauthn_rp_id_column` 各 1 組 skipif；`test_passkey_disabled_2026_09_16` 是反向（只在啟用時略過） | **是**（只要常數為 False） | **必須保留**：功能只是暫緩、程式還在；改成「功能開關」而非常數時它們會自動復活。若決定永久移除 passkey，才一併刪（需「功能已移除證據＋反向控制」） |
| pypdfium2 未安裝 | `pytest.importorskip("pypdfium2")`：`tests/test_unapproved_every_page_2026_10_01.py:94` | 1 題 | **是**（開發環境 `.venv312` 實測 find_spec＝False） | **該修**：要嘛把 pypdfium2 列入開發需求（讓它真的跑），要嘛註明此題只在有該套件的環境跑；現在是「看起來有守門、實際沒跑」 |
| WD1 xfail | `test_wording_guards_2026_09_23.py:130` xfail：`helpers/wording.py` 尚未建立（使用者 2026-09-24 裁示併入平台化「內容層」設計） | 1 檔（另有 `import_module('helpers.wording')`） | 條件永遠成立直到建立該檔 | **必須保留**（已有裁示）；建議在檔頭寫明裁示日期與解除條件，並設一個到期提醒 |
| 模組不在安裝包 | `module_installed("modules/<m>/")`、`_subcontract_installed()` 等 | 約 45 處 skipif＋185 個 `pytest.skip("…不在這個安裝包")` | 否（完整產品會跑；模組缺席的演練會跑反向題） | 必須保留（PLAYBOOK §B-11：模組可獨立販售的核心守門） |
| 平台別 | `sys.platform != "win32"`、`os.name != "nt"`（14 處） | — | 否（開發／正式機皆 Windows） | 保留 |
| 列車旗標 | `MOTRIX_TRAIN != "1"`（`test_generated_maps`、`test_unit_cards`） | 3 處 | 平時略過、列車時執行 | 保留（要確認每班列車確實設了 `MOTRIX_TRAIN=1`——我稽核時的單檔執行未設，這些題在我的結果是「略過」而不是「綠」） |
| 外部程式 | `NODE is None`、`shutil.which("node"|"powershell")`、`not HAS_XDIST`、`not _has_v9_base()` | ~9 處 | 否（本機皆有） | 保留；`_has_v9_base()` 需 V9 基準 commit c83dae6e 在 clone 內 |
| 其他 | `test_case_attachments_used_marker:448` 等「只驗 M05 不在時的行為」 | 少數 | 否 | 保留 |

不確定處：實際「60 skipped」是哪 60 題，需要跑一次 `pytest -rs` 才知道；建議下一輪全量階段把 `-rs`／junit 存檔，我可據以更新此節。

## (2) 測的對象已不存在
- import 掃描（`from modules.x import y`、`import_module("…")`、`tests.` 與頂層模組）：缺檔 2 個（`routers.reports`，見下）＋字串模組名 2 個（`helpers.a`＝合成、`helpers.wording`＝WD1）；具名匯入缺名 **0**。
  - `modules/payroll/tests/test_payroll_money_round_half_up_2026_09_26.py:126`、`modules/subcontract/tests/test_money_round_half_up_2026_09_26.py:146` 的 `import routers.reports as rp`：`backend/routers/reports.py` **已不存在**（報表搬到 analytics 模組）。這兩處在 `_patch_entries()` 內，而該輔助函式在檔內**沒有任何呼叫者**（grep 只有定義）⇒ 不會執行、不會紅，是**孤兒死程式碼**（引用已移除模組）。**建議刪除這兩個未使用的輔助函式**（無功能風險；刪除前請 owner 確認無外部 import）。
- 端點字串：91 個「找不到路由」皆為合成路由、守門檢查用的假路徑、或 `%s` 樣板；`/api/expense-categories` 經查存在於 `ledger_category_map.py` 的 `list_router`（我的掃描器沒認出該寫法）。`/api/tenders` 與 `/api/cashier/bonus-payouts` 的命中在註解／`if False` 的死程式碼（見 §3）。
- 頁面／js：`accounts.html`／`account-tree.html`／`chart-of-accounts.html` 是「候選名稱」（測試找出實際存在的那個）；`tender_detail_20260921.html` 是 fixture；`case-management.js`、`custom-modules-nav.js`、`session_policy.js` 是「不可回來」或候選。
- `docs/platform/test_map.json` 的 `unmapped` 13 檔（比通知的 12 多 1，因 `test_no_swallowed_dict_keys_2026_10_03.py` 是新增）：`test_deploy_dashboard_{gates,health,jobs,scope_gate}`、`test_no_leaky_tempdirs`、`test_no_swallowed_dict_keys`、`test_stepfile_drill`（tests/platform，屬全域守門，無單一模組歸屬，合理）；`test_approval_queue_extra_types`、`test_e2e_bn12/bn3/bn4…`（獎金頁 e2e，歸屬 payroll／analytics 不明）、`test_netguard`、`test_stock_batch_payment`（歸屬 supply／accounting 不明）。**建議**：後 6 檔補歸屬，否則「依 diff 選題」永遠選不到它們（只在全量時跑）。

## (3) 無效測試
靜態：
- `assert 常數`／`assert x == x`：1 處，`accounting/tests/test_voucher_summary_length_2026_09_23.py::test_jv12_the_visual_layout_is_a_human_verification_item:175`——**刻意的**（註記「視覺版面是人工驗證項目」，等於佔位）。建議改成 `pytest.skip("人工驗證項目：…")`，避免永遠綠燈被誤當成已驗證。
- 被 `try/except` 吞掉的斷言：0。
- 無 assert 的 59 題：抽查 9 題（company_locations、map_user_location、module_update、ledger_base_schema、xss_sinks、runtime_switches、stage_select…）**8 題以輔助函式斷言（有效）**；偏弱：`test_calendar_event_toggles::test_push_never_raises`（只驗不丟例外，沒驗「失敗時有通知」）、`test_ledger_base_schema::test_smoke_insert_into_every_new_table`（純冒煙，可接受）。
- 死程式碼：`tests/test_bonus_correction_2026_09_30.py:279` `cash = client.get(...) if False else None`——該行永遠不執行（之後若有針對 `cash` 的斷言即為恆略過）。建議確認並刪除這行或補回真實呼叫。

突變抽樣：不是隨機抽樣，是我本班稽核時對產品碼植入破壞的紀錄——**共 31 次突變，26 次使測試轉紅**。沒轉紅的 5 次：S2b 兩次（案件財務摘要略過作廢、取消派發過濾；a3 已補測試）、S5 一次（允許欄位；a3 已補）、A4 一次（unkeyed 視為 live；nit）、S4 一次（等價突變）。結論：本班新增的守門整體有效，缺口集中在「新規則的邊界」，且都在稽核時被補上。**舊守門的有效性我沒有做大樣本突變**——要做需要為每個測試設計突變，建議每班由稽核線對新增守門各做至少 1 個突變（本班已是這樣做），舊守門可分批抽樣。

## (4) 重複覆蓋
- 完全相同的函式本體（跨檔）2 組：`test_accounting_voucher_line_rounds_half_up`（`accounting/tests/test_money_round_half_up_2026_09_26.py` ＝ `tests/test_money_round_half_up_2026_09_26.py`）、`test_changing_a_view_filter_does_not_arm_the_leave_warning`（`analytics/tests/…` ＝ `tests/…test_e2e_view_filters_not_dirty…`）。
- 同主幹檔名 46 組（例：`money_round_half_up` 7 份、`module_permission_fixes` 4 份）：內容皆不同＝各模組自有的版本。成本是**維護與執行時間**，不是失效。建議（可降頻）：`money_round` 類由全域守門 `test_legal_amount_rounding_guard` 涵蓋後，各模組副本只在該模組改動時跑（test_map 已能依 diff 選到）。

## (5) 高成本低價值（tests/platform，作者閘門量測秒數，序列）
前 30 檔共約 1,343 秒（22.4 分），tests/platform 全部 148 檔約 28.2 分。

| 檔（秒） | 保護對象 | 建議 |
|---|---|---|
| module_update_delivery（178）、scope_gate（102）、stepfile_drill（71）、ship_tier（52）、module_selection（55）、core_upgrade（24） | 模組更新／交付／選配／範圍閘的**工具鏈** | **可降頻**：只在 `tools/platform/`、`backend/core/`、`delivery.py`、`module_update` 相關檔案改動時跑（author_gate 的 TOOL_DRILL 已有同類機制，可擴到這幾檔）；列車全量階段仍跑 |
| modtest_rebase_check（72）、modtest_json_stdout（71）、modtest_scope（60）、modtest_rebase_bookkeeping（27）、build_stage_reuse（15）、build_opt（14）、failfast（40）、fail_stream（21） | 建包／測試選題**工具本身** | **可降頻**（同上：只在 `tools/platform/modtest*`、`build_test_reuse.py`、`stage_select.py` 等改動時跑） |
| pii_forms_notice（84） | 個資告知（含 e2e／頁面） | 必須保留（個資），但可改成只在含 pii／privacy 路徑改動時全跑，平時跑精簡版 |
| module_boundaries（69）、module_changelog_follows_code（51，依 git 歷史）、generated_maps（42）、unit_cards（22）、integration_points_registered（36）、startup_writes_only_via_startup（32）、requirements_cover_imports（28）、mail_registry（23） | **架構守門**（模組邊界、版號與變更紀錄、生成檔、整合點、啟動寫入、相依） | **必須保留**每次全量；它們正是第 31–33 班連紅的來源，價值高、成本在可接受範圍。`changelog_follows_code` 因逐檔呼叫 git 偏慢，可考慮一次 `git log` 批次化（效能優化，不是刪） |
| e2e_classification（47）、e2e_menu_layout（15）、case_stage_connectors（20）、case_summary_purpose（15）、approval_queue_l1（14）、prod_status_snapshot（28）、deploy_dashboard_*（約 14+） | 分類／選單／案件階段／佇列／部署儀表板 | 保留；`prod_status_snapshot`、`deploy_dashboard_*` 屬部署儀表板，若儀表板不隨 33A 改動可降頻 |

註：modules/*/tests 與 backend/tests 非 platform 的檔沒有計時紀錄，e2e（playwright 252 檔）是全量大宗，建議下一輪階段輸出 `--durations=30` 與 junit 存檔後，我再補第二版（尤其 e2e 的 30 個最慢檔）。

## (6) 分類建議
**A. 安全可刪（需使用者與主持裁示；每項要有「功能已移除證據＋反向控制」）**：目前**沒有**符合條件者。唯一接近的是 Passkey 6 檔——但功能只是暫緩，不是移除，所以**不建議刪**。
**B. 可降頻（改成依 diff 觸發，全量階段照跑）**：§5 前兩列共約 15 檔、約 12–13 分鐘（module_update_delivery、scope_gate、stepfile_drill、ship_tier、module_selection、core_upgrade、modtest_×4、build_stage_reuse、build_opt、failfast、fail_stream）。落地方式：作者端守門與列車前置預演只在對應工具／核心檔改動時選入（`tools/platform/author_gate.py` TOOL_DRILL＋`guard_patterns.json`），不改測試本身。
**C. 必須保留**：架構守門（§5 第三列）、個資、金額進位、權限／可見度、所有「不可回來」的反向守門（如 `case-management.js`）、模組缺席演練、Passkey 暫緩檔、WD1 xfail。

## 待辦（建議）
1. 下一輪階段存 junit＋`-rs`，我據以補「實際 60 skipped／3 xfailed」逐題清單與 e2e 慢檔。
2. `pypdfium2` 要嘛列入開發需求要嘛註明；`test_bonus_correction:279` 死程式碼；`test_jv12…` 改 `pytest.skip`。
3. test_map 的 unmapped 後 6 檔補歸屬。
4. 刪除 payroll／subcontract money_round 副本中未使用且引用已移除 `routers.reports` 的 `_patch_entries()`。
