# MS1 組裝計畫（M2.1 之後的下一班；2026-10-13）

> 只讀盤點：沒有建任何分支、沒有跑測試。基準＝`origin/platform` ＝ `33b84b332`（M2.1 已上線，`prod/41348ee6`）。
> 資料來源：`git merge-base`／`rev-list`／`diff --name-only`，以及 `git merge-tree --write-tree` 的**逐一模擬合併**（只產生物件、不動任何 ref／工作樹；腳本在整合者暫存區，可重跑）。
> 結論先行：**MS1 建議＝E-a（含 S1）＋ A7；E-b 若 0d 稽核通過再加；M3、完工單、專案毛利放 MS2。** 理由在 §5。切線由主持定。

## 1. 候選清單與祖先關係

| 候選 | 分支（尖端） | 與 platform 的基底 | ahead／behind | 檔數 | 備註 |
|---|---|---|---|---|---|
| S1 設定中心編輯 r2 | `wip/t57-s1-settings-edit-r2` `de3321788` | c87079be2（M2 頭） | 9／8 | 15 | **是 E-a r3 的祖先** |
| E-a r3（含 S1 r2） | `wip/t57-ea-owner-r3` `278180804` | c87079be2 | 13／8 | 23 | 合併 E-a 就帶進 S1 r2；已內含 M2.1 的 S1-1（`8b16cbcfa`） |
| E-b | `wip/t57-eb-spine-r1`（2b 寫碼中） | — | — | — | 尚未推；依賴 E-a |
| M3 擇一方案報價 | `wip/t57-m3-t11-r6` `c51fc84d1` | c87079be2 | 17／8 | 43 | 資料模型＋報價單表單 V3.23 |
| A7 下載檔名 p1 | `wip/t57-download-name-p1-r2` `f2c05a746` | c87079be2 | 9／8 | 39 | **是 p2 的祖先** |
| A7 下載檔名 p2 | `wip/t57-download-name-p2-r1` `b36573ceb`（p2-r2 將出） | c87079be2 | 12／8 | 58 | 合併 p2 就帶進 p1 |
| 專案毛利 | `wip/t56-quote-project-margin-r5` `1061e6172`（5e 寫碼中） | c14f0a1df（落後 67） | 12／67 | 2 | 目前只有設計文件 |
| 完工單堆疊 | `wip/t57-completion-{core,fixes,hardening,diffdialog}-r1`（尖端 `040271a6d`） | c87079be2 | 4／8 | 17 | 鏈：core→fixes→hardening→diffdialog；c7 正在 rebase |
| 完工單帶入設計 | `wip/t56-completion-quote-items-r8` `3534b9d22` | c14f0a1df | 9／67 | 1 | 僅文件 |
| CRM 批示設計 | `wip/t56-crm-directive-r3` `8989cd920` | c14f0a1df | 10／67 | 2 | 僅設計文件，不進閘門 |
| 脊柱引擎設計 | `wip/t57-spine-engine-design-r3` `dfc129524` | c87079be2 | 11／8 | 16 | **含 S1 r1 程式碼（舊版）**——只能挑其中 3 個純文件 commit（`84c6493ca`、`d018db588`、`dfc129524`），不可整支合 |
| 脊柱夾具設計 | `wip/t57-spine-fixtures-r1` `61f7ee990` | c87079be2 | 1／8 | 1 | 僅文件 |

兩兩祖先（程式分支間）：S1 r2 ⊂ E-a r3；A7 p1 ⊂ A7 p2；完工單 core ⊂ fixes ⊂ hardening ⊂ diffdialog。**其餘彼此獨立（沒有誰包含誰）。**
所有程式候選都以 c87079be2（M2）為基底，**不含** M2.1 的 5 個 commit 與基準 chore；其中 M2.1 的 S1-1 內容與 E-a 內的 `8b16cbcfa` 相同（見 §3 的模擬：E-a 對 platform 乾淨）。

## 2. 重疊檔案（對照 platform 逐一模擬後仍會衝突的才列衝突）

| 檔案／區塊 | 誰動 | 處理 |
|---|---|---|
| `backend/helpers/settings_groups.py`（各自在尾端加群組區塊） | E-a、M3、A7、完工單；platform 已有 M2.1 的 S1-1 改動 | **文字衝突**（A7、M3、完工單對 platform 都會衝突）。全部區塊保留、不改寫，合完後確認 `register_group` 別名仍在（E-a r3 保留）、群組鍵不重複 |
| `backend/tests/platform/settings_deploy_baseline.json` | M3、A7、完工單 | **文字衝突**；取聯集（新增鍵全保留），合完用該檔的重產工具確認 |
| `docs/quick/changelog.md`（最新段落放最上面） | M3、A7、完工單；platform 已有 M2.1 段 | **文字衝突**；每一候選的段落全留，新→舊排序 |
| `backend/modules/case/SPEC.md` | M3、完工單 | **文字衝突**；兩邊新增小節都留 |
| `backend/modules/case/module.json`（version） | M3、完工單（1.0.178／181） | **完工單衝突**：它的 1.0.178～181 與 M2.1 已出貨的 case 1.0.178 撞號，須 rebase 後改用 `(next)` 讓取號決定 |
| `backend/modules/case/tests/test_completion_fixes_t57.py` | 完工單（fixes 內含與 M2.1 熱修同內容的 commit） | **衝突**（M2.1 已有同名檔）；完工單 rebase 時丟掉重複的熱修 commit |
| `backend/version_manifest.json` | E-a（13b、13d）、M3（13e、13f）、A7（`next`）、完工單（12c、12d、13d、13e） | 標籤撞號：E-a 的 13b 與 platform 已出貨的 13b **相同內容**（模擬乾淨）；完工單的 13d／13e 與 E-a／M3 撞號 ⇒ 所有人改用 `next`，讓 `train_number assign` 依 (date,time) 取號 |
| 各 `CHANGELOG.md` `(next:minor)`／`(next)` | E-a／S1（core `(next:minor)`）、A7（core 另一段 `(next:minor)` 加多個模組 `(next)`）、完工單 | 同模組在整合分支上兩段 `(next)` 要**併成一段**（PLAYBOOK §G7.1.2）；取號放在最後一個程式修正之後 |
| `backend/tests/platform/l1_interface_snapshot.json` | S1、E-a、A7、脊柱 | 合完以 `_l1_interface.py --update --pending` 重產（不要手併 JSON） |
| `backend/modules/case/tests/route_table_golden.json` | S1、E-a、M3、完工單、脊柱 | 合完以該 golden 的重錄工具重產；差異應只含各候選新增的路由 |
| `UNIT-INDEX.md`／`dep_graph.json`／`test_map.json` | 各候選都**沒有**提交（已遵守規則） | 組裝後 `regen_all.py` 一次，單獨一個 bookkeeping commit |
| `frontend/pages/quotation-form.html`／FORM_VERSION | M3（V3.22→V3.23）；專案毛利計畫（V3.24） | 版本槽依序：M3＝V3.23、專案毛利＝V3.24；兩者不同班就各自順序，同班則必須 M3 先於毛利 |
| `menu_l1.json`／`l1_pages.json` | **沒有任何候選動** | 無風險 |
| `frontend/static/download.js`、各模組 api 的下載呼叫 | A7（只有 p1／p2） | 與其他候選無重疊；範圍廣（6 個模組），回歸面大但內容機械 |

## 3. 逐一模擬合併結果（對 platform 起算）

| 順序 | 結果 |
|---|---|
| E-a r3 單獨 | **乾淨** |
| A7 p2 單獨 | 衝突 3 檔：`settings_groups.py`、`settings_deploy_baseline.json`、`docs/quick/changelog.md` |
| M3 單獨 | 衝突 3 檔：`settings_groups.py`、`case/SPEC.md`、`docs/quick/changelog.md` |
| 完工單（diffdialog）單獨 | 衝突 6 檔：上列＋`case/module.json`、`test_completion_fixes_t57.py`、`settings_deploy_baseline.json` |
| E-a → A7 | A7 這步衝突同上（3 檔）；順序反過來（A7→E-a）E-a 仍乾淨 |
| E-a → A7 → M3 | M3 這步衝突 3 檔（`settings_groups.py`、`SPEC.md`、`changelog.md`），與單獨相同，沒有新增衝突 |
| E-a → A7 → M3 → 完工單 | 完工單 6 檔，與單獨相同 |

結論：**衝突都是「同一處尾端追加」型，沒有語意衝突**；每個候選的衝突檔集合與順序無關，所以順序不影響人力，只影響「哪個先過閘門」。

## 4. 建議合併順序與風險

1. **E-a r3（含 S1 r2）**——乾淨；先進來，後面的候選才有 `register_group` 別名與擁有者機制可用。
2. **E-b**（若 0d 稽核通過）——依賴 E-a 的擁有者範圍／宣告⇔登錄；碰 `core/spine.py` 與掃描器，進來後所有後續候選的 settings 宣告都要符合脊柱驗證。
3. **A7 p2**（p2-r2 出來後換）——3 檔文字衝突；解法＝保留全部區塊。
4. （MS2）**M3**——3 檔文字衝突＋表單版本 V3.23。
5. （MS2）**完工單堆疊**——須 c7 先 rebase 到 platform（去掉與 M2.1 重複的 fixes commit、case 版號改 `(next)`）；之後 6 檔衝突降到約 3 檔。
6. （MS2）**專案毛利**——等 5e 推碼；V3.24 在 M3 之後。
7. 文件類（毛利 r5、完工單帶入 r8、CRM r3、脊柱設計／夾具）：只含文件，可隨任一班夾帶；**CRM 批示只做設計，不進閘門**。

風險與守門：
- **`register_group` 別名**：E-a r3 保留別名是為了「合併安全」；M3／A7／完工單都在呼叫它。合完必須 `grep register_group` 並跑 settings 相關守門；E-a 若晚於它們進，別名還沒存在就會 NameError。⇒ **E-a 一定最先**。
- **manifest 標籤撞號**（13b／13d／13e）與 **case 1.0.178 撞號**：所有候選改用 `next`／`(next)`，統一在最後取號；不要在分支上寫字母。
- **同一模組兩段 `(next)`**（core：S1 `(next:minor)` 與 A7 另一段）要併成一段。
- **L1 snapshot／route golden** 是 JSON，**不要手併**，合完重產（會多一輪 full-lint）。
- **A7 範圍廣**（58 檔、6 個模組的下載路徑）：回歸面大但機械；e2e 會跑到各模組頁面，閘門時間不增，但出紅時定位成本高。
- **spine 設計分支含舊 S1 程式**：不可整支合，否則把 S1 r1 舊碼帶進來。
- **完工單 fixes** 與 M2.1 熱修同內容，必須由 c7 rebase 去重，否則 `test_completion_fixes_t57.py`、`module.json` 衝突。

## 5. MS1／MS2 切法（閘門約 70 分鐘一輪）

一輪完整閘門＝組裝＋regen（約 10 分）＋full-lint（約 13）＋not_e2e（約 25～30）＋e2e（約 18～20）＋建包／驗證／演練（約 10）＋稽核；實際一輪約 70 分鐘。**每多一個有紅的候選，就多重跑一次 lint 起算的流程（M2 的 permmatrix 探針就因三種小紅燈多跑了 3 輪）**，所以**候選越少、MS1 越穩**。

| 切法 | MS1 內容 | 預期 | 風險 |
|---|---|---|---|
| A（最小） | E-a r3（含 S1） | 乾淨合併，約 1 輪 | 最低；使用者可見成果少 |
| **B（建議）** | E-a r3 ＋ A7 p2；E-b 若稽核通過再加 | A7 需處理 3 檔文字衝突；約 1～2 輪 | 低到中；A7 範圍廣但機械 |
| C | B ＋ M3 | 再加 3 檔衝突、V3.23、金額邏輯（擇一方案）e2e | 中到高；M3 17 個 commit、43 檔，含報價金額，出紅機率高 |
| D | C ＋ 完工單 | 需 c7 先 rebase | 高；撞號與重複 commit 未解 |

MS2：M3 → 完工單（rebase 後）→ 專案毛利（V3.24）→ 文件類。

建議理由：E-a／S1 已經 0d 兩輪稽核、對 platform 乾淨；A7 的內容與設定中心無語意耦合、衝突都是尾端追加；M3 與完工單都動案件模組與報價金額路徑，且完工單還欠一次 rebase，放 MS2 才不拖慢 MS1。

## 6. 組裝步驟（給整合者，可直接照做）

1. 從 `origin/platform` 開 `train/ms1-int`；依 §4 順序 `merge --no-ff`（或 cherry-pick），每步解衝突只做「保留全部區塊」。
2. 全部候選都用 `next` 號；最後一個程式修正之後 `train_number assign`（單獨一個 commit）。
3. `PYTHONIOENCODING=utf-8 python tools/platform/_l1_interface.py --update --pending`、route golden 重錄、`regen_all.py`；各單獨 commit。
4. 守門：`register_group` grep、manifest／changelog／page_paths／version_slots 守門先單跑，再 full-lint。
5. 閘門與心跳照現行規則（死線：lint 20、not_e2e 42、e2e 30、建包＋驗證 45；RAM <4 GB 中止、<8 GB 通報；其他視窗靜止）。
6. 建包仍需 VR7 最小 DB（正式機 `module_versions` 配對）與 UTF-8 主控台啟動（見 `BUILD-GATE-NOTES-M2.md`）。

## 7. E-a／E-b（含 S1）合併順序與組裝注意事項（1d 補，2026-10-13；給 5c／整合者）

> 來源：1d 自己的分支與各單檔測試結果（不是模擬合併；§1～§6 的衝突模擬仍以整合者的為準）。鏈：S1 r2 `de3321788` ⊂ E-a r1 `5bff2f28c` ⊂ E-a r2 `4a04ad556` ⊂ E-a r3 `278180804` ⊂ E-b M1 `df5e7f0e3` ⊂ r2 `8428ecfe3` ⊂ r3 `031205075` ⊂ r4 `73decbb5c` ⊂ **r5 `25664078f`**（**鏈必須終止在 r5 或更新**：r3 單獨仍會透過 `GET /api/definitions/setting_group*` 洩漏 `hidden`／`planned` 群組，r5 才補上通用定義路由的閘門與撞名輸家的 hidden；r5 的提交訊息寫明『測試尚未執行』，**r5 必須通過正式閘門**；E-b 另需 0d 稽核通過才可出貨）。r5 沒有新增路由，route golden 仍是 6 條；組裝後請再跑 `_l1_interface.py --diff` 確認只有新增。（r5 之後若有新尖端，以 `wip/t57-eb-spine-r*` 最大號為準。）

### 7.1 檔案範圍（相對 M2 頭 `c87079be2` 共 31 檔；含 S1＋E-a＋E-b）

| 區 | 檔案 | 備註 |
|---|---|---|
| L0 | `core/spine.py`（新）、`core/loader.py`、`core/registry.py` | spine 只用標準庫；loader 在 import 前呼叫 `parse_features`／`declared_settings_groups`，import 後 `register_manifest`／`check_declared_settings`，全部載完 `validate_all()` |
| L1 | `helpers/settings_registry.py`、`helpers/settings_groups.py`、`helpers/mail_types.py`、`helpers/config_ledger.py`、`routers/settings_center.py`、`routers/definitions.py` | `config_ledger.py`／`definitions.py` 的改動＝M2.1 已上線的 S1-1，內容相同（模擬乾淨） |
| 畫面 | `frontend/pages/settings-center.html`（JS 內嵌；不新增 static 檔） | |
| 文件／登記 | `docs/platform/modules.json`（+`plat:spine`）、`docs/platform/plans/S1-EDITOR-WORKPLAN-T57.md`、`backend/core/CHANGELOG.md`、`backend/version_manifest.json` | |
| 既有測試被改 | `test_module_selection.py`（registry 表守門把 `_OWNED` 與 `_LEGACY_PROVIDERS` 同列例外）、`test_settings_pending_t54.py`（`test_deploy_baseline_frozen` 改為只比對 owner＝core）、`test_ac1_write_actions_2026_09_23.py`（拿掉 settings-center 的唯讀登記）、`test_write_endpoints_are_audited_2026_09_24.py`（EXEMPT +4：preview／impact／reset／restore，各附理由） | 這四個檔其他候選也可能碰，合併時以『保留雙方新增』為原則 |
| 新測試（組裝時要 `git add`） | `test_s1_managed_kind.py`、`test_settings_editor_s1.py`、`test_e2e_settings_center_edit_s1.py`、`test_spine_owner_e_a.py`、`test_settings_baseline_owners.py`、`_settings_baseline.py`（輔助）、`test_spine_e_b.py`、`test_settings_center_status_routes.py`、`test_spine_literal_scan.py`、`_spine_scan.py`（輔助）、`spine_scan_allowlist.json` | 前述都在 `backend/tests/platform/`，除了 `test_e2e_settings_center_edit_s1.py` 在 `backend/tests/` |

### 7.2 `settings_groups.py` 別名（合併安全，E-a 一定最先）

- E-a r3 之後 `helpers/settings_groups.py` 不再 import `register_group` 本名，而是：私有包裝 `_register_core`（以 `owner_scope("core")` 登記，核心群組永遠屬 core）＋模組層級別名 **`register_group = _register_core`**。
- **M3、A7、完工單都在這個檔尾端追加區塊並呼叫 `register_group(`**：別名必須保留，否則 import 時 `NameError`、整個設定登錄表掛掉。它們的群組因此也屬 core，仍留在**核心**凍結基準 `settings_deploy_baseline.json` 裡（基準檔仍是聯集，只是現在由 owner＝core 過濾比對）。
- 合完後必做：`grep -n "register_group" backend/helpers/settings_groups.py`（別名存在、各區塊都用它）＋單跑 `test_spine_owner_e_a.py::test_settings_groups_still_exposes_register_group_and_keeps_blocks_core_owned`。
- **模組內（`modules/**`）不得呼叫 `register_group`／`owner_scope`／碰 `_register_core`／`_OWNER`**——靜態守門 `test_modules_never_touch_the_owner_machinery` 會紅。若某候選把群組搬進模組，必須在該模組 `module.json` 加 `settings: {"groups": [...]}`，且宣告＝實際登錄（缺或多都使該模組**載入失敗**）。

### 7.3 `docs/platform/modules.json`

- E-b 在 `plat:source_tree` 之後加一行 `"plat:spine"`（`plat:` 單位清單按字母序）。其他候選不動這個檔；若有人也加單位，保持字母序、保留雙方。
- 沒有這一行，`_l1_interface.py` 看不到 `core/spine.py`，L1 快照就不含它。

### 7.4 L1 快照（不要手併）

- 全部合完後 `PYTHONIOENCODING=utf-8 python tools/platform/_l1_interface.py --update --pending`（分支模式，`core_version` 記為 `next`；只有『新增』、沒有修改或刪除）。
- 對照用（1d 在 E-b r4 上的結果）：相對 M2 頭，`helper:settings_registry` 新增 `impact_scope`（`SettingDef.__init__` 參數）、`banner_of`、`plan`、`live_impact`、`field_defs`、`field_views`、`show_value`、`group_status`、`group_info`、`profile_skipped`、`cancel_pending_of_nonopen`、`audit_spine_failures`、`owner_groups`、`unregister_owner`、`RISK_ORDER`、`IMPACT_SCOPE_GRANDFATHERED`、`register_group(owner=)`；`plat:registry` 新增 `owner_scope`／`current_owner`／`on_unload`／`register_owned`／`owned`；`plat:loader` 新增 `declared_settings_groups`／`check_declared_settings`；新單位 `plat:spine`（`STATUSES`、`parse_feature(s)`、`register_manifest`、`validate_all`、`report`、`register_validator`、`on_validated`、`drop_owner`、`feature_enabled`／`feature_status`／`group_status`／`group_info`／`planned_train`、`snapshot`／`restore`／`reset`）。**沒有任何『修改』或『刪除』**；若重產後出現修改／刪除，代表合併時有人動到簽章，請回報。
- `helpers/settings_groups.py` 的別名是模組層級賦值（非 `def`），不進快照（已用 `--diff` 確認 0 變動）。

### 7.5 `CHANGELOG.md`（core）`(next:minor)` 合併

- `backend/core/CHANGELOG.md` 最上面要有**一段** `## (next:minor) — …`（`pending_problems` 守門認這個標題；快照 `core_version=next` 時缺這段會紅）。E-a／S1／E-b 的全部要點都在**同一段**裡（依序：S1 L1 新增、E-f 值域規則、S1-4／S1-5 端點、E-a L0／L1 新增與兩輪稽核補強、E-a3 測試基礎、E-b L0 `core.spine`、E-b 引擎層、E-b r2 補強、E-b 路由層、E-b r4 健康卡／稽核去重／掃描器）。A7 另有一段 `(next:minor)` 時**併成一段**（PLAYBOOK §G7.1.2）；兩邊的 bullet 全留，不改寫。
- `## 1.129` 底下 S1-1 的 `(併入)(next)` bullet 是 M2.1 已出貨的內容，保持原樣、不要搬動。

### 7.6 `version_manifest.json` 標籤

- E-a／E-b **沒有**新增 manifest 條目（內部機制）。S1 帶兩個條目：`2026-10-13b`（模組『平台/設定中心』，＝M2.1 已出貨的 S1-1，內容相同，模擬乾淨）與 `2026-10-13d`（模組『平台/設定中心編輯畫面』，S1 畫面，**待取號**）。
- 依 §6 規則：未出貨的條目改用 `next`，最後一個程式修正之後 `train_number assign`；**同一模組在未出貨包內只能有一筆**（`test_version_manifest_2026_09_22` 守），所以 `2026-10-13d` 的模組名刻意與 `2026-10-13b` 分開；組裝時不要把兩者改成同一模組名。
- **標籤撞號明列（組裝者用 `train_number assign` 重取，同一模組在未出貨包內只留一列）**：S1 畫面條目『平台/設定中心編輯畫面 `2026-10-13d`（待取號）』↔ 完工單 r2『案件管理/完工單帶入報價項目 `2026-10-13d`』↔ M3 自己的列（`13e`／`13f`）↔ M2.1 已出貨的 `13a`～`13c`（S1-1 的 `13b` 與 platform 內容相同）。四組字母互撞，全部改 `next`，由取號依（日期,時間）排序重發；『平台/設定中心』（`13b`，已出貨）與『平台/設定中心編輯畫面』（S1 畫面）是兩個模組名，**不要合併**。
- 若要讓使用者在『更新紀錄』看到功能狀態頁（灰色『開發中，預計 MSn 版提供』），由整合者在取號時加一筆（模組沿用『平台/設定中心編輯畫面』即可，合併到 `13d` 那筆的 content，**不要新開同模組第二筆**）。

### 7.7 route golden

- 這條鏈只新增 **6 條**路由（全在設定中心，E-a／E-b 本身沒有新增）：`GET /api/settings-center/groups/{group}/versions`、`GET …/{group}/diff`、`POST …/{group}/preview`、`POST …/{group}/impact`、`POST …/{group}/reset`、`POST …/{group}/restore/{version}`。排序＝（路徑, 方法）。
- **用官方指令重錄，不手改**：`T40_WRITE_GOLDEN=1 pytest backend/modules/case/tests/test_route_table_golden_2026_10_05.py -q`（單檔）；重錄後 diff 應**只含各候選新增的路由**，其中 1d 這條鏈的就是上列 6 條。手動備援：golden 每行是 `["方法","路徑","函式名",[參數…],[body…],[]]`，函式名＝`<函式>_<路徑底線化>_<方法小寫>`（例：`group_diff_api_settings_center_groups__group__diff_get`），可從 `origin/wip/t57-eb-spine-r4` 的 golden 對 M2 頭的 diff 直接複製這 6 行。
- 另有路由表驅動測試 `test_settings_center_status_routes.py`：設定中心若被其他候選新增路由，必須在該測試的 `CASES` 分類，否則紅（這是刻意的）。

### 7.8 regen 清單（組裝完成後，單獨一個 bookkeeping commit）

1. **先 `git add` 上列所有新測試檔與輔助檔／白名單 JSON**（`regen_all.py` 從已追蹤檔產生，沒 add 的新檔不會進 `test_map.json`）。
2. `regen_all.py` 產出：`docs/platform/UNIT-INDEX.md`（新增 `plat:spine`；`plat:registry`、`plat:loader`、`helper:settings_registry`、`helper:mail_types` 的公開介面清單與測試欄位變動）、`docs/platform/dep_graph.json`（新增邊：`loader→spine`、`spine→registry`、`settings_registry→spine`、`settings_registry→registry`、`mail_types→spine`、`routers/settings_center→spine`／`registry`）、`docs/platform/test_map.json`（上列新測試檔）。
3. 順序：先 L1 快照 `--update --pending`、再 route golden、最後 `regen_all.py`（`regen_all` 讀得到新路由與新單位）。

### 7.9 合完後的守門與已知會紅的地方

- **字面掃描器**（`test_spine_literal_scan.py`）：其他候選若在 `modules/**` 新增 `mail_types.register("<key>", …, "business|approval|system", …)` 或 `register_group("…")` 的字面呼叫，掃描器會紅——處理方式二選一：①在該模組 `module.json` 加 `features[].mail`／`settings.groups` 宣告（建議，做法見 `SPINE-ENGINE-DESIGN-T57.md` §3.2）；②附 reason／owner／expires 加進 `spine_scan_allowlist.json`（目前 8 檔 53 筆既有項目）。**已核對（1d，2026-10-13，對 `origin/platform` 逐檔比較 `mail_types.register`／`_mt.register`／`register_group(` 的出現次數）**：完工單 r2（`wip/t57-completion-r2`）、M3（`wip/t57-m3-t11-r6`）、A7 p2（`wip/t57-download-name-p2-r2`）在 `backend/modules/**` **沒有新增任何被掃描的字面登記**——它們新增的設定群組都寫在 `backend/helpers/settings_groups.py`（core，不在掃描範圍）。所以預期**不會**觸發掃描器；之後若有候選把通知類型或設定群組登記放進模組，才需要宣告或加白名單。
- **載入器核對**：任何候選若把設定群組搬進 `modules/**`，需 `module.json settings.groups` 與實際登錄相等，否則該模組載入失敗（`registry.failed()` 有原因）。
- **凍結基準**：`test_deploy_baseline_frozen` 現在只比對 owner＝core；候選在 `settings_groups.py` 追加的群組仍屬 core，需同步更新核心基準 JSON（取聯集，§2 已列）；新增的 `test_settings_baseline_owners.py` 會檢查『每個有群組的擁有者都有基準』。
- **E-b 啟動順序**：`validate_all()` 在 `load_all` 結尾執行；其回呼（取消非 open 群組的待生效項、稽核去重）需要資料庫，任何錯誤只記 log。沒有宣告 `features[]` 的既有模組完全不受影響（未宣告＝open）。

### 7.10 建議的單檔驗證順序（full-lint 前，每次一檔）

`test_spine_owner_e_a` → `test_settings_baseline_owners` → `test_spine_e_b` → `test_settings_center_status_routes` → `test_spine_literal_scan` → `test_core_loader` → `test_l1_interface_snapshot` → `test_module_selection` → `test_mail_registry` → `test_system_hub` → `test_settings_editor_s1` → `test_s1_managed_kind` → `test_settings_registry_t54`／`pending_t54`／`audit_fixes_t54`／`security_t54`／`ui_plain_language` → `test_write_endpoints_are_audited` → `test_route_table_golden` → `test_alpine_double_init`／`test_ac1_write_actions`。瀏覽器 e2e（`test_e2e_settings_center_edit_s1.py`，含 planned 灰色卡片）依規定在機器空出來時才跑。

### 7.11 不在 MS1 的後續小項（backlog；98 路線圖 r18 §3.9b：E-b 出貨**之後**才做）

E-b 出貨後由 1d 在新分支（預計 `wip/t57-eb-spine-r6`）依序做，每項單檔測試與 L1 快照 `--update --pending`：①`register_kind_gate(kind, fn)`（通用定義路由的 hidden／planned 閘門改為掛點，`setting_group` 搬上去，`alert_rule` 以受管 kind 接入；約 0.25 pd）；②`spine.register_health_source`（多來源共用『設定中心』卡的單一徽章；約 0.2 pd）；③`SettingDef.loosen="both"`（任何數值變動都算放寬；約 0.1 pd）；④`settings_registry.group_stamp(group)`（規則快取鍵用）；⑤`spine.surface_status(surface)`（目錄表面繼承功能狀態；規則發布／還原時檢查）。**這些不屬於 MS1 組裝範圍，組裝者不需處理。**
