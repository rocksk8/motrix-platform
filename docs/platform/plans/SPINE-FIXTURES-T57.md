# 脊柱 E-b 測試夾具設計（僅文件）——`features[]` 宣告檔驗證器的正反樣本與掃描器正對照

> 作者：hichan-c7（輕量作者）；對象：2b 的 E-b 引擎（`core/spine.py`）與其驗證；依據 `FIELD-LAYOUT-FRAMEWORK-T56` r8/r9 §17.1（13 項登錄檢查清單）、§17.2（E-a…E-f）、§17.2b（執行期降級）、§17.5（登錄表驅動的守門）。
> 範圍：**只寫夾具的設計**（要有哪些樣本、預期的驗證結果、哪些測試取用）。實作等 2b 的 E-b 引擎在分支上、宣告檔格式定案後再做（0.5 pd，路線圖 r9）。本文不跑任何測試。
> 標記：**〔格式待 2b〕**＝宣告檔欄位名稱依 2b 的 schema，本文用 §17.1 的名稱暫代；**〔碼〕**＝驗證器回傳的問題代碼，本文提議一組穩定代碼，2b 可改名，但夾具的「預期結果」只引用這張表。

## 0. 實作對照（2026-10-13；E-b 引擎 r8 已在 platform）

本文是引擎出貨前寫的設計；實作依**已出貨的 `core/spine.py`** 調整如下，差異一律以實作為準：
- 宣告檔格式＝引擎的 `features[]`：`code／label／settings:{group}／mail／catalog:{fields,surfaces}／capabilities／labels／status／planned_train／notes`；問題以**白話字串**回報（沒有穩定代碼），所以預期結果寫成「含某片語」，不是問題代碼。
- 夾具是**資料驅動的案例表**（`backend/tests/platform/_spine_fixtures.py`：`CASES`／`FUTURE`／`run_case`／`sandbox`），驅動測試 `test_spine_fixture_cases.py`；不採 `good/`、`bad/` 的 JSON 目錄（引擎的驗證要同時準備設定群組、信件登記與能力，用程式組比 JSON 清楚）。
- 掃描器正對照已由 `_spine_scan.py`／`test_spine_literal_scan.py` 提供，本批不重做；本批新增的是：案例表的**空轉防護**（驅動器對故意設錯的預期必須回否）、**一案一規則**（補正唯一違規點後必須變好）、沙盒不留痕跡、真實樹宣告全部通過＋同一檢查對故意違規宣告確實回問題。
- 設計 §3 中引擎尚未落地的檢查（目錄 `isMoney` 通道／`financial_mask` 雙向、labels 鍵存在）放在 `FUTURE`（非嚴格 xfail，落地後 XPASS 即提醒搬進 `CASES`）；範本占位符（E-c）尚無宣告區段，不在案例表內。

## 1. 夾具長什麼樣子

```
backend/tests/platform/spine_fixtures/
  good/<案例>.json          # 一個模組宣告檔的 features[]（可含多個 feature），驗證器應回「無問題」
  bad/<案例>.json           # 故意違規；每個檔頭帶 "_expect": [{"code": "...", "path": "features[0]..."}]
  sources/<案例>.py.txt     # 掃描器用的合成「程式碼」樣本（副檔名 .txt，避免被當成產品檔掃描或 import）
  README.md                 # 每個案例一句話：為什麼好／壞
backend/tests/_spine_fixtures.py   # 載入器：load_case(name)、all_good()、all_bad()、make_module_tree(tmp_path, features, owner)
```

- **夾具是資料，不是邏輯**：每個壞樣本只違反**一條**規則（單一失敗點），才能斷言「恰好這個代碼」，避免一個樣本掩蓋另一個。需要組合時另開 `bad/combo_*.json`，只用於「全部問題都回報、不在第一個就停」的題。
- `_expect` 是比對來源：測試斷言 `sorted((p.code, p.path) for p in validate(case)) == sorted(_expect)`（同時抓**多報**與**漏報**）。好樣本的預期固定為 `[]`。
- `make_module_tree`：在 `tmp_path` 內組出 `modules/<擁有者>/module.json`（含該案例的 `features[]`）＋最小 `__init__.py`，給 `core/spine.py` 的「從模組樹載入」路徑與 E-a 的「只比對已載入擁有者」使用；**不碰真實 `modules/`**。
- 與真實宣告檔隔離：夾具目錄不被 `spine` 的正式載入掃到（載入器只讀 `modules/*/module.json`）；夾具中的功能代號一律以 `zz_` 開頭（與既有 `zz_` 測試慣例一致，`test_deploy_baseline_frozen` 已排除 `zz_`）。

## 2. 好樣本（驗證器必須通過；同時是正對照的「不要誤報」側）

| 檔名 | 內容 | 為什麼放 |
|---|---|---|
| `good/minimal_ops.json` | 一個功能 `zz_min`：一個 `ops` 設定群組、一個整數開關（`0/1`，`min/max` 框住）、題目／標籤／說明／`impact` 齊全、預設＝今天 | 最小可通過案例；基準線 |
| `good/choices_int.json` | 多選一欄位（`1..3`），每個選項有〔值／中文標籤／影響說明〕，預設在選項內 | E-f 值域規則的「通過」側 |
| `good/money_field_internal.json` | 欄位目錄項 `zz_margin_pct`：`isMoney=真`、類別 `internal`、有可見性判定函式名、通道只有〔畫面／內部 Excel〕 | 金額欄位的正確寫法 |
| `good/money_risk_group.json` | `money` 風險的設定群組：有 `risk_text`、`loosen`、`impact_scope`（E-e 結構化欄位） | E-e 就緒後「新登錄」的完整寫法 |
| `good/mail_type_literal.json` | 信件類型 `event_key` 為字面字串且列在登記表 | §17.5-4 的通過側 |
| `good/legacy_group_no_scope.json` | 既有群組（標 `legacy: true`、`impact_scope` 待補）風險 `money` 但無 `impact_scope` | §17.1 第 4 列：**既有群組不追溯變紅** |
| `good/template_chips.json` | 範本占位符只用白名單 chips（客戶名稱、單號），不含金額／個資欄 | E-c 通過側 |
| `good/surface_keys.json` | 表面鍵 `module:zz_min.form`、剛好 30 字的邊界值 | 長度邊界的通過側（≤30） |

## 3. 壞樣本與預期結果（一檔一條規則）

| 檔名 | 違反什麼 | 預期〔碼〕 | 依據 |
|---|---|---|---|
| `bad/dup_group_code.json` | 兩個 feature 用同一群組代號（同模組） | `duplicate_group` | §17.1-1「重複代號 ⇒ 載入失敗」 |
| `bad/dup_group_code_cross_module.json` | 兩個模組擁有者宣告同一群組代號 | `duplicate_group`（路徑含兩個擁有者） | E-a 的跨擁有者唯一 |
| `bad/missing_impact.json` | 設定欄位缺 `impact` | `missing_impact` | §17.1-4（影響說明必填） |
| `bad/missing_impact_scope_new_money.json` | **新**登錄、風險 `money`，缺 `impact_scope`（E-e 就緒後） | `missing_impact_scope` | §17.5-3 |
| `bad/missing_risk_text.json` | 風險 `security`，缺 `risk_text` | `missing_risk_text` | 既有規則 |
| `bad/wrong_risk_class_invented.json` | 風險寫成 `irreversible`（不存在的類別） | `unknown_risk_class` | §17.1-4「沒有 irreversible」 |
| `bad/wrong_risk_class_permission.json` | 設定的效果是「誰能建立／編輯」但風險標 `ops` | `permission_effect_not_security` | §17.1-6「帶權限效果的設定必為 security」 |
| `bad/money_without_ismoney.json` | 鍵在 `financial_mask` 金額鍵清單內，但目錄項 `isMoney` 為假／缺 | `catalog_mask_mismatch` | §17.5-1（雙向） |
| `bad/ismoney_not_in_mask.json` | 目錄項 `isMoney=真`，但不在 `financial_mask` 清單 | `catalog_mask_mismatch`（反向） | §17.5-1 |
| `bad/ismoney_without_visibility_fn.json` | `isMoney=真` 但沒有可見性判定函式 | `money_without_visibility_fn` | §17.1-2 |
| `bad/ismoney_in_customer_channel.json` | `isMoney=真` 的項目通道含「客戶 PDF」 | `money_in_customer_channel` | §17.1-2／§17.5-2 |
| `bad/ismoney_as_filename_var.json` / `ismoney_in_carry_in_whitelist.json` / `ismoney_as_template_placeholder.json` | 金額項分別成為檔名變數／帶入白名單／範本占位符 | `money_in_customer_channel`（各自路徑） | §17.5-2（一條查詢涵蓋四種輸出） |
| `bad/default_not_in_choices.json` | 選項欄位預設值不在 `choices` 內 | `choice_default_not_in_choices` | E-f |
| `bad/choices_str_type.json` | 選項欄位用 `str`＋`choices` | `choice_field_must_be_int` | §17.1-4（一律整數代碼；`str` 會接受任何字串） |
| `bad/choice_missing_impact.json` | 某選項缺〔影響說明〕 | `choice_missing_impact` | §17.1-4 |
| `bad/unavailable_choice_used.json` | 功能的預設組（presets）／建議值引用一個不在 `choices` 的值（例如選項被拿掉但建議值還指向它） | `choice_value_unavailable` | 「不可用的選項被使用」 |
| `bad/loosen_on_non_int.json` | `loosen` 設在 `bool`／`str` 欄位 | `loosen_requires_numeric` | §17.1-4（`_loosens` 只認數字） |
| `bad/orphan_group.json` | 設定群組已登錄（程式裡有 `register_group`）但沒有任何 feature 宣告它 | `orphan_group` | §17.5-7 反向 |
| `bad/feature_references_missing_group.json` | feature 引用一個不存在的群組代號 | `orphan_group`（引用側） | 雙向 |
| `bad/unregistered_setting_key.json` | 程式讀 `settings.get("zz_min", "x")`，宣告檔沒有 `x` | `unregistered_setting_key` | §17.5-7 |
| `bad/bad_surface_key.json` | 表面鍵格式錯（缺 `module:`、含空白） | `bad_surface_key` | §17.1-3 |
| `bad/surface_key_too_long.json` | 表面鍵 31 字（邊界） | `bad_surface_key` | 長度 ≤30 |
| `bad/feature_without_surface.json` | 目錄項沒有任何表面 | `field_without_surface` | §17.1-3「每項至少一個表面」 |
| `bad/mail_unregistered_event_key.json` | 信件類型 `event_key` 未列入登記表 | `unregistered_event_key` | §17.5-4 |
| `bad/template_placeholder_money.json` | 範本占位符是金額／個資欄 | `placeholder_is_money_or_pii` | E-c |
| `bad/template_unknown_placeholder.json` | 範本使用白名單外的占位符 | `placeholder_not_whitelisted` | E-c |
| `bad/legacy_flag_on_new.json` | 新登錄偷標 `legacy: true` 規避 `impact_scope` | `legacy_flag_not_allowed`（legacy 只能出現在凍結清單內的既有群組） | 防止白名單被濫用 |
| `bad/malformed_json_features.json` | `features` 不是陣列／元素不是物件 | `features_malformed` | 載入器健壯性 |
| `combo_all_problems.json` | 以上多條同時出現 | 全部都回報（不在第一個停） | 驗證器一次回報所有問題 |

> 〔碼〕總表（提議）：`duplicate_group`、`missing_impact`、`missing_impact_scope`、`missing_risk_text`、`unknown_risk_class`、`permission_effect_not_security`、`catalog_mask_mismatch`、`money_without_visibility_fn`、`money_in_customer_channel`、`choice_default_not_in_choices`、`choice_field_must_be_int`、`choice_missing_impact`、`choice_value_unavailable`、`loosen_requires_numeric`、`orphan_group`、`unregistered_setting_key`、`bad_surface_key`、`field_without_surface`、`unregistered_event_key`、`placeholder_is_money_or_pii`、`placeholder_not_whitelisted`、`legacy_flag_not_allowed`、`features_malformed`。

## 4. 掃描器的正對照（§17.5-7：宣告檔存在守門，限精確字面案例）

掃描器只檢查三類字面：`send_registered("…")`／`mail_types.register("…")` 的 `event_key`、`register_group("…")`／`SettingDef("…")` 的字面鍵、`QUOTE_MONEY_KEYS`／`QUOTATION_MONEY_COLS` 的金額鍵名。**每一類至少一個「必須被抓到」的合成樣本，加一個「不得被抓到」的對照**：

| 樣本（`sources/*.py.txt`，以字串餵給掃描函式，不寫進產品樹） | 預期 |
|---|---|
| `event_key_unregistered.py.txt`：`mail_types.register("zz_unlisted_event", …)`，宣告檔沒有 | 抓到：`unregistered_event_key` |
| `event_key_concat.py.txt`：`send_registered("zz_" + name)`／f-string／變數 | 抓到：`non_literal_event_key`（**散文與動態組裝對靜態守門隱形**，所以非字面 ⇒ 直接紅，而不是略過） |
| `group_unregistered.py.txt`：`register_group("zz_ghost", …)` | 抓到：`orphan_group` |
| `setting_key_unregistered.py.txt`：`SettingDef("zz_ghost_key", …)` 所屬群組已宣告但缺此鍵 | 抓到：`unregistered_setting_key` |
| `money_key_new.py.txt`：`QUOTE_MONEY_KEYS = (…, "zz_new_money")`，目錄沒有 | 抓到：`catalog_mask_mismatch` |
| `clean_registered.py.txt`：以上字面都在宣告檔內 | **不報**（誤報側） |
| `prose_mention.py.txt`：註解／docstring／散文提到 `register_group("zz_ghost")` | **不報**（只掃程式語法節點，不掃散文——避免啟發式誤報） |
| `definition_site.py.txt`：定義 `def register_group(...)` 本身 | **不報**（定義處豁免，同 `test_permmatrix_writes_unwired` 的 OWNER 慣例） |

- **掃描器自我檢查**：測試先對「抓到」側樣本斷言**確實抓到**（抓不到 ⇒ 掃描器自己紅，避免空轉）；再對真實樹斷言無問題。與既有 `test_positive_control_detects_every_way_of_reaching_the_write_functions` 同型。
- **誤報白名單 `spine_scan_allowlist.json`**：夾具要有三種白名單題——①有效項（原因、擁有者、到期日齊全，且在程式中仍對得上）⇒ 放行；②**到期**項 ⇒ 紅；③**失效**項（程式裡已無此出現）⇒ 紅；④缺欄位（無原因／擁有者／到期日）⇒ 紅。夾具提供合成白名單檔與合成程式字串，不使用真實白名單。

## 5. 執行期降級（§17.2b）的夾具

- `bad/runtime_broken_money_field.json`：一筆驗證失敗的金額目錄項。**預期（行為題，不是驗證碼）**：①該項被當成〔`isMoney=真`、`internal`〕；②對所有客戶通道（PDF／預覽／回簽頁／客戶 Excel）不可見；③不在帶入白名單、檔名變數表、範本占位符；④同模組其他功能（`good/minimal_ops` 共載）不受影響；⑤健康卡出現「有 1 項功能登錄未通過驗證」並列出功能代號與原因；⑥`audit_log` 有 `spine.validation_failed`；⑦夾具修復後恢復（正反對照）。
- 夾具以 `make_module_tree` 組出「一好一壞兩個模組」，啟動載入器（降級模式）而非 CI 模式；CI 模式同一份壞樣本 ⇒ 硬紅（驗證器直接回問題）。兩種模式對同一份樣本的差異是這組夾具的存在理由。

## 6. E-a（基準分割）與 E-f（值域）要共用的夾具

- `make_module_tree` 可組「核心＋兩個模組、其中一個缺席」：驅動 E-a 的五個測試（§17.2a-5）——core-only RC、單模組安裝包自洽、已載入擁有者基準缺群組／多群組／預設改變 ⇒ 紅、孤兒基準檔被忽略、群組總數＝宣告和。
- E-f：同一批 `choices` 樣本餵 `validate_values`（寫入拒絕）與 `_effective`（庫內被竄改成未知代碼 ⇒ 讀取回預設並記 warning）；`security` 欄位讀到未知值 ⇒ 功能存取函式回「最嚴」。

## 7. 哪些測試取用（消費者對照）

| 測試（預定檔名，2b 可調整） | 取用 | 斷言 |
|---|---|---|
| `tests/platform/test_spine_validate.py` | `all_good()`、`all_bad()` | 好樣本回 `[]`；壞樣本回恰好 `_expect`；combo 全回報 |
| `tests/platform/test_spine_scan.py` | `sources/*` ＋ 合成白名單 | 抓到側全抓、誤報側全不報、白名單四題；真實樹無問題 |
| `tests/platform/test_spine_runtime_degrade.py` | `bad/runtime_broken_money_field` ＋ `good/minimal_ops` | §5 的七點 |
| `tests/platform/test_core_loader.py`（既有，併入驗證器） | `make_module_tree` | 載入器忽略未知區塊、`features[]` 驗證併入 |
| `tests/platform/test_settings_baseline_split.py`（E-a） | `make_module_tree` | §6 五題 |
| `tests/platform/test_settings_choices_domain.py`（E-f） | `good/choices_int`、`bad/default_not_in_choices` 等 | 寫入拒絕、讀取回預設 |
| `tests/platform/test_settings_ui_plain_language.py`（既有） | `good/*` 的標籤 | 白話守門對新宣告同樣生效（夾具含一個帶英文代碼的標籤壞樣本 `bad/label_has_code.json` ⇒ 抓到） |

## 8. 開放問題（給 2b；不阻擋夾具設計）

1. `features[]` 單一 feature 的頂層欄位名（`code`／`owner`／`settings`／`catalog`／`mail`／`templates`／`surfaces`）以 2b 的 schema 為準；夾具檔頭帶 `"_schema": 1` 以便日後升版。
2. 〔碼〕要不要分「錯誤」與「警告」兩級（例如 `legacy` 群組缺 `impact_scope` 為警告）；目前提議全部為錯誤，`legacy` 以凍結清單豁免。
3. 掃描器掃描範圍＝`source_tree.product_files()`（不含各層 tests），與 `test_permmatrix_writes_unwired` 相同，夾具因此不會被當產品碼。
4. 夾具要不要隨模組走（每個模組放自己的 `tests/spine_fixtures/`）；目前提議核心共用一份，E-a 之後各模組可加自己的**好**樣本當作自測，壞樣本留在核心。
5. 實作量：0.5 pd 假設驗證器 API 為 `validate(manifest_dict) -> [Problem(code, path, message)]` 與 `scan(sources: dict) -> [Problem]` 兩個純函式；若 2b 只給「從模組樹載入」入口，夾具以 `make_module_tree` 補齊，工量不變。
