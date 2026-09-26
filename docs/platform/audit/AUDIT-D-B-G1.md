# 稽核：B 的 G1 顯式宣告（`__l1_public__`）與 core-only 反向控制工具（wip/b-g1；合回前）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。只審新版（CORE-SPEC 35014aaa）。
> 對象：`origin/wip/b-g1` **`6b0c8fdd`**（`c78d36a5` G1＋工具、`6b0c8fdd` 修三道守門；基底 `227f86e6`）。月台登記在 `0d8b9caf`（那是 RUN-PLAN 的登記 commit，不是分支本身）。
> 主持點名三件事：①公開名稱的宣告漏寫或多寫會不會紅；②工具是否真的拿掉全部 L2、結果不隨「哪些模組在」而變、殘留 `__pycache__` 資料夾；③PLAYBOOK §G3。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。

## 0. 結論

- **①宣告：成立**。漏寫會紅（合成樹反向控制＋真實樹守門）；格式錯誤會被拒絕；介面不再依賴 L2 怎麼用。D 做了 4 項突變，全部轉紅。「多寫」是另一回事：宣告一個檔案裡不存在的名稱，會被**靜默忽略**（G-S2）；目前真實的樹裡沒有這種宣告。
- **②工具：機制成立，但在 B 自己的 commit 上不綠**。
  - 機制：用拋棄式 worktree，只刪有 `module.json` 的資料夾，而且斷言刪乾淨了。新 checkout 的樹不會有 `__pycache__` 殘留，所以 O-4 的問題在構造上就排除了。
  - D 實際執行 `core_only_rc.py --commit 6b0c8fdd`：拿掉 daily_tasks、netplan、tender_radar，結果是 **8 failed、989 passed**。扣掉允許的 2 題，**非預期紅 6 題**，其中 2 題 B 說明已在 wip/b-m08 修，**另外 4 題沒有處理、也沒有分派**（G-M1）。
  - 另外，工具在「一題都沒跑」時會判定通過（G-S1）。
- **③PLAYBOOK §G3：已寫入**。內容是每一班都要跑，而且除了允許的 2 題之外必須全綠。
- 必修 1、建議 2、觀察 2。

## 1. ①公開名稱的宣告

| 項目 | 結果 | 證據 |
|---|---|---|
| 漏寫：L1 以外用到底線名稱而沒有宣告 ⇒ 紅 | ✅ | `test_l2_uses_only_declared_l1_underscore_names`（真實樹）；`test_rc_undeclared_use_is_caught_in_a_synthetic_tree`（合成樹：直接 import 與經 `helpers.__all__` 轉出，兩種都報；補上宣告就不報） |
| 格式錯誤 ⇒ ValueError | ✅ | `test_rc_malformed_declaration_is_refused`（字串、非底線名稱、非常數） |
| 拿掉宣告 ⇒ 算刪除、要升主版號 | ✅ | `test_rc_declared_underscore_names_are_part_of_the_interface` |
| 介面不依賴 L2 | ✅ | `test_interface_does_not_depend_on_who_uses_it`（`cross_boundary_public` 一被呼叫就炸，介面照樣算得出來並等於快照） |
| 多寫：宣告了不存在的名稱 | ⚠ 靜默忽略 | D 探測：`__l1_public__ = ("_ghost", "_a")` ⇒ 介面只有 `_a`，沒有任何題會紅（G-S2）。真實樹掃描：不存在的宣告 0 個；宣告了卻沒人用的名稱 0 個 |

D 的突變（`tests/platform/test_l1_interface_snapshot.py`，24 題）：

| # | 突變 | 結果 |
|---|---|---|
| G1a | `declared_public` 恆回空集合 | 紅（5） |
| G1b | `interface_of` 不看宣告 | 紅（3） |
| G1c | `undeclared_uses` 不報漏宣告 | 紅（合成樹題） |
| G1d | `current_interface` 退回看 L2 用量 | 紅（`test_interface_does_not_depend_on_who_uses_it`） |

## 2. ②core-only 工具

- 讀碼：
  - 用 `git worktree add --detach` 開一棵拋棄式樹，不碰任何人的工作樹。
  - `module_dirs` 只收有 `module.json` 的資料夾，與 loader 的判準一致；刪完後 `assert not module_dirs(backend)`。
  - 帶 `--continue-on-collection-errors`，收集錯誤以檔案路徑記為失敗。
  - 低優先權、`-n 2`；最後清掉工作樹與 basetemp。D 跑完後查過，沒有殘留。
- **殘留 `__pycache__`**：拋棄式樹是從 commit 新 checkout 的，不會有未追蹤的殘留資料夾，所以 O-4 那一類在構造上就排除了。這比「跑之前先清」可靠。
- **D 實際執行**（`--commit 6b0c8fdd --workers 2`）：`removed: [daily_tasks, netplan, tender_radar]`，**8 failed、989 passed、9 skipped**，exit 1。

| 非預期紅 | 說明 |
|---|---|
| `test_menu_parity.py::test_every_legacy_item_is_declared_identically`、`::test_rendered_menu_matches_for_every_single_permission` | B 在 6b0c8fdd 寫明：已在 wip/b-m08 修（依 sidebar MODULE_PAGES 扣掉沒裝的），不在這裡重做 |
| `test_case_read_scope.py::test_reverse_controls_absent_module_routes_are_exempt_present_ones_still_compared` | **G-M1**：題名寫「在的模組照樣比對」⇒ 需要至少一個模組在；沒有處理、也沒有分派 |
| `test_integration_points_registered.py::test_absent_module_green_present_module_still_red` | **G-M1**：同一種形狀（正對照要一個「在的模組」） |
| `test_dep_scan_module_files.py::test_dep_scan_and_source_tree_agree_on_module_files` | **G-M1** |
| `test_pii_forms_notice.py::test_every_pii_form_has_a_decision_and_it_still_holds` | **G-M1**：網路規劃的告知端點隨 M10 進了 `modules/netplan`，拿掉之後 `ack_api` 找不到（AUDIT-D-pii-notice O-1／O-3 那一類） |

- **工具判定的缺口（G-S1）**：`ok` 只看「失敗扣掉允許清單是否為空」，不看 pytest 的結束碼，也不看跑了幾題。D 實測：pytest 一題都沒收到（exit 5）時，產生的 junit 裡沒有任何 testcase，`failed_ids` 回空集合，`classify` 判定 **ok＝True**。

## 3. ③PLAYBOOK

- §G3 新增一條：「每一班列車都跑一次 core-only 反向控制……除了 §B-11 允許的兩題以外必須全綠」。✅
- 註：D 一開始用兩點 diff（`origin/platform..6b0c8fdd`）看 PLAYBOOK，看起來像是 B 刪掉了主持 07:53 加的兩條（列車長等全量、清 `__pycache__`）。改用合併基底比對之後，確認那兩條是基底之後才加進 origin 的，**B 沒有刪**。記錄在這裡，免得下一個人犯同樣的錯。

## 4. 發現

### 必修

**G-M1　工具在自己的 commit 上不綠：4 題非預期紅沒有處理、也沒有分派**
- 為什麼是必修：這一包同時把「每一班都跑、除允許的 2 題外必須全綠」寫進了 PLAYBOOK §G3。照現況合回的話，第一班列車跑 core-only 就會紅，而且紅的原因沒有人負責；列車長只能擋車，或者略過這個步驟。後者等於工具形同虛設。
- 建議修法：這 4 題各自改成不綁真實模組，比照 6b0c8fdd 的作法：用合成樹做正對照；或者任取一個已載入的模組，沒有就 skip 並寫明。PII 那一題照 AUDIT-D-pii-notice O-3，用 `module_installed` 豁免不在的模組頁面與端點。如果不在這一包修，就在 RUN-PLAN 寫明每一題由誰修、何時修，並暫列為 core-only 的「已知、已分派」清單（要寫成機器讀得到的清單，不寫在散文裡）。
- 修完用 `core_only_rc.py` 重跑，附上 JSON 結果行。

### 建議

- **G-S1　一題都沒跑也算通過**：`ok` 要同時滿足三件事：`pytest_exit in (0, 1)`、junit 的 testcase 數大於 0（最好不少於一個下限，例如 tests/platform 目前的 90% 左右）、`unexpected` 為空。另補一題：exit 5 或空的 junit ⇒ ok＝False。
- **G-S2　宣告了不存在的名稱會被靜默忽略**：`__l1_public__` 裡的每個名稱都要在該檔頂層有定義（函式、類別、指派或 import），否則報錯。打錯字、或者函式改名後忘了改宣告，都應該被抓到。

### 觀察

- **O-1　`undeclared_uses` 仍然依賴 L2 用量**：拿掉模組只會讓用量變少，所以這一題只可能變綠、不會變紅，方向安全。但在 core-only 模式下，它守不到 L2 對 L1 私有名稱的使用。這一點要靠「全模組」那一輪守，列車上兩輪都要跑。
- **O-2　月台登記的 commit 與分支頭不同**：登記寫 `0d8b9caf`，那是 RUN-PLAN 的 commit，分支頭是 `6b0c8fdd`。建議月台登記一律寫分支頭的 SHA。

## 5. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| G-M1 | （B 以 commit 回覆，未填本欄）已知紅清單 `tools/platform/core_only_known_red.json`＋判定「紅 ⊆ 允許 ∪ 清單、清單轉綠未刪 ⇒ 不過」；4 題的修正分別在 h-corered、c-coreonly-depscan（2784140e）、c-m07（4a731b1f）；清單從空開始 | wip/b-g1 6e7ba250（range-diff：舊兩個 commit 內容不變、新增 6e7ba250） | ✅ 10:28 條件式關閉：D 突變 KR3（不看裁示）、KR4（不驗題存在）、KR2（轉綠不報）皆紅；dep_scan 那題 D 另驗 2784140e（DS1 只掃第一層、DS2 tests 也算 ⇒ 皆紅）；pii 那題 D 在 c-m07 驗（P7c／P7d 皆紅）。**條件**：b-g1 必須與 h-corered、c-coreonly-depscan、c-m07、b-m08-2 同一班，否則清單為空而 4 題仍紅 ⇒ 第一班擋車（主持已排） |
| G-S1 | exit 5 或 0 題 ⇒ 不過 | 6e7ba250 | ✅ 10:28 關閉（D 突變 KR1 ⇒ 3 紅） |
| G-S2 | | | 未處理（宣告不存在的名稱仍靜默忽略），維持開著 |
| O-1～O-2 | | | |

## 6. 6e7ba250 複核（D，2026-09-26 10:28）

- ③ sparse 拋棄式樹：D 實際執行 `core_only_rc.py --commit 6e7ba250`，執行中查看 `%TEMP%/motrix-coreonly-6e7ba250/backend/modules` ⇒ **只有 `__init__.py`**，三個 L2 從頭沒取出；`module_keys_at` 讀 git 而非工作樹；取出後斷言 `main.py` 在、`module_dirs()` 為空。
- **G-O3（觀察）　judge 只擋 exit 5**：pytest 異常結束（exit 2 中斷、3 內部錯誤、4 用法錯誤）而 junit 仍有部分結果時，只要紅燈 ⊆ 允許 ∪ 清單就判過。建議 `pytest_exit not in (0, 1)` 一律不過。
- **G-O4（觀察）　排隊時完全沒有輸出**：工具以 `capture_output` 跑 pytest，而 conftest 的全量測試鎖在別的視窗占用時會排隊等待（`[測試鎖] … 排隊中` 那一句也被收起來）。D 這一輪在 09:54 起跑，10:26 查時主 pytest 只用了 0.8 秒 CPU、沒有 worker——是在排隊，不是當掉，但從外面分不出來（MEMORY〈長時間沒有輸出的動作要有死線〉）。建議把 pytest 的 stderr 即時轉印，或者起跑前先印出鎖的持有者。
- **G-O5（觀察）　「只准縮短」實際是「新增要有 RUN-PLAN 裁示行」**：裁示行是 RUN-PLAN 裡的一行文字，被稽核者自己也寫得出來；守門驗的是「有沒有這一行」，不是「是不是主持寫的」。這是〈守門驗的是有沒有人做過決定〉的設計，可以接受；列車長合回時要看新增的那一行是誰寫的。

