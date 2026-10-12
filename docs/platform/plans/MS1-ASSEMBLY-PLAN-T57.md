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
