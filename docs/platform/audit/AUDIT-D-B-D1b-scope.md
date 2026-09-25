# 稽核：B 的 D1b 選題縮小——介面不變不遞移＋名稱層級選題（合回前稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。**合回前稽核，安全攸關**：選題變小，就代表少跑了一些題。
> 對象：`wip/b-scope` `63a47f4e`（**只在本機分支，origin 上沒有**；主持說的 `origin/wip/b-scope` 不存在，D 以 commit 為準）。本份審 `3553034b`（§C-11a ①②⑥ 介面不變只到直接依賴、統計）與 `63a47f4e`（§C-11a ③ 名稱層級）。同一分支上的 `ccc474f7`（rebase 簿記檔）以及對 `AUDIT-D-B-env-guards` 的回覆（`f14ee6db`、`4d0808a0`、`3a62d617`）另行確認。
> 規格：PLAYBOOK 附錄 C-11a（origin/platform）。稽核樹 `D:\MOTRIX-PLATFORM-D`（detached `63a47f4e`），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：`MT`＝`tools/platform/modtest.py`、`SN`＝`tools/platform/scope_names.py`、`G1`＝`backend/tests/platform/_l1_interface.py`。

## 0. 結論

- **必修 1 項，未關閉前不可合回。**
  - S-M1：名稱層級選題**看不到同一個模組裡的呼叫關係**。改的是私有函式（或任何被同模組其他函式呼叫的名稱）時，只 import 呼叫端函式的使用者和它們的題目，全部被拿掉。
  - D 用真突變實證：`helpers/legal_params._as_date` 把年份固定成 2026。
    - 新選題挑 48 檔、678 題（15.0%），在突變下**全綠**。
    - 被它拿掉的 `tests/test_legal_params_r1_2026_09_25.py` 在同一個突變下 **6 題紅**。
    - 舊規則（`--transitive`）會挑到這一檔（381 檔、75.6%）。
  - 結論：這一類錯誤從「會被抓到」變成「完全漏掉」，也沒有契約題接住。
- 主持點名的三件事：
  1. **名稱層級會不會漏**：會，見 S-M1。
  2. **「介面不變就不遞移」的判定**：G1 的描述刻意不含預設值與常數的值（G1:74），行為改變而簽名不變時一律判成「介面不變」。依設計，間接使用者要靠契約題接住。但 §C-11a ⑤ 要求的反向控制（在 helper 做「只影響間接使用者」的突變，抓不到就補契約題）**沒有落實成任何題目**（S-S1）。
  3. **conftest 的保守處理**：只在 conftest **直接**用到被改的名稱時才不過濾。它與 S-M1 同一個盲區：conftest 呼叫 `db.get_db()`，改的是 `get_db` 內部的 `_connect` ⇒ 判成「沒用到」⇒ 293 個測試檔被拿掉（D 實測，見 §2 第二列）。
- D 對選題程式本身做了突變 4 項：3 紅、1 存活（S-S2）。
- 建議 2 項、觀察 2 項。

## 1. 逐項驗收（PLAYBOOK 附錄 C-11a）

| 設計 | 驗收 | 證據 |
|---|---|---|
| ① 直接依賴選題 | ✅ | MT `direct_dependents`；`test_interface_unchanged_stops_at_direct_dependents` |
| ② 介面不變規則（G1 描述比對；非 .py／讀不到保守） | ⚠ | MT:304 `interface_changed`；突變 Q04（永遠判定不變）紅。盲區見 §0 第 2 點、O-1 |
| ③ 名稱層級（`from X import a`、模組別名、`import *`＝ALL、模組層級改動＝ALL） | ❌ | SN:32-94、MT:349 `name_filter`、MT:543 `_test_name_filter`；突變 Q02 紅。**同模組呼叫關係沒有處理**（S-M1） |
| ③ conftest 用到被改名稱 ⇒ 不過濾 | ⚠ | MT:543-557；突變 Q03 紅；只看直接用到（S-M1） |
| ⑤ 反向控制：「只影響間接使用者」的突變 | ❌ 沒有題目 | `test_scope_names.py`、`test_modtest_scope.py` 都是合成原始碼題，沒有一題是在真實 helper 做突變後驗證選題（S-S1） |
| ⑥ 統計附加到 `modtest_stats.jsonl` | ✅ | `test_stats_row_is_appended` |
| 全量政策不變（fixture 層、發版前、每批合回後） | ✅ | 文字與程式一致 |

## 2. 實證（D 在稽核樹做的真突變；每一項做完都用 `git checkout` 還原並核對）

| 真突變 | 新選題（預設規則） | 被拿掉的題在突變下 | 舊規則 `--transitive` |
|---|---|---|---|
| `helpers/legal_params.py::_as_date` 回傳值 `.replace(year=2026)`（私有函式；`rules_for_date` 呼叫它） | `names: ['_as_date']`，拿掉 3 個測試檔；挑 48 檔、678 題，**實跑 678 passed（全綠）** | `test_legal_params_r1_2026_09_25.py`：**6 failed**（`test_rules_are_picked_by_effective_date`、`test_a_slip_dated_before_the_first_version_is_refused`、`test_new_slip_uses_the_version_of_its_date_and_stores_it` 等） | 挑到該檔（381 檔、75.6%） |
| `db.py::_connect` 的 `row_factory` 改成 None（私有函式；`get_db` 呼叫它） | `names: ['_connect']`，`names_conftest: None`（conftest 用 `get_db`，被判成沒用到）；**拿掉 293 個測試檔**，剩 54 檔、747 題 | 未實跑（這個突變幾乎讓所有碰 DB 的題都紅，剩下的 54 檔多半也會紅，不能用來證明漏選）。此列只用來證明 conftest 的保守條件沒有觸發 | — |
| （作廢）`db.py::_m002_sessions_expires` 改成不做事 | — | 等價突變：建表時 `sessions` 就已經有 `expires_at`，不算數 | — |

對選題程式本身的突變（跑 `test_scope_names.py`、`test_modtest_scope.py`，基準 26 passed）：

| 突變 | 結果 |
|---|---|
| Q01 `name_filter` 判斷不了（ALL、找不到 import）也照樣過濾 | 🟢 **存活**（S-S2） |
| Q02 模組層級敘述有變時不當成 ALL | 🔴 `test_rc_module_level_statement_change_is_all` |
| Q03 conftest 用到被改名稱時仍過濾 | 🔴 `test_rc_conftest_using_the_changed_name_disables_test_filtering` |
| Q04 `interface_changed` 永遠回「沒變」 | 🔴 `test_rc_signature_change_is_detected` |

## 3. 發現

### 必修

**S-M1　名稱層級選題看不到同模組的呼叫關係：私有函式一改，呼叫它的公開函式的使用者與題目全部被拿掉**
- 位置：SN:32-39 `changed_names` 只回「定義本身有變」的頂層名稱。MT:349 `name_filter` 與 MT:543 `_test_name_filter` 只保留**直接**用到這些名稱的使用者與測試。conftest 的保守條件（MT:547-552）也只看直接用到。
- 為什麼是必修：
  - 「只改私有函式」正是最常見的修 bug 方式，也最符合「介面不變」。
  - 實測的結果是整個錯誤沒有任何一題抓到（§2 第一列），而且舊規則抓得到。
  - D1b 的目的是縮小範圍而不漏；這裡縮掉的是真的會紅的題。
  - 以 `_connect` 來說，所有 `get_db()` 的使用者都被當成「沒用到」。
- 建議修法：
  - `changed_names` 之後，在**同一個模組內**依呼叫與引用關係做閉包：任何頂層定義的本體引用了被改的名稱（`ast.Name`／`ast.Attribute` 指向同模組名稱），就把它也列為被改。反覆做到不再增加為止。
  - `_test_name_filter` 的 conftest 條件也改用閉包後的集合。
  - 補反向控制題：用合成模組驗證「改 `_a`、使用者只用 `b`、`b` 呼叫 `_a`」⇒ 使用者被選到。另外至少補一題真實 helper 的突變題（例如本份 §2 的 `_as_date`），把 §C-11a ⑤ 落實成題目。
  - 閉包之後，重量 PLAYBOOK 附錄 C-11a 的比例表，確認目標是否仍然達成（legal_params 的比例會上升；這是正確的代價）。

### 建議

- **S-S1　§C-11a ⑤ 的反向控制沒有落實成題目**：規格寫「在一個 helper 做只影響間接使用者的突變，新選題若抓不到 ⇒ 補契約題，不擴大選題」。現有的題目都是合成原始碼題，驗的是「選題程式照設計運作」，沒有一題驗「選出來的題能抓到錯誤」。建議把「真實 helper 突變 → 選題 → 實跑選中的題 → 必須有紅」寫成一支可以重跑的檢查（不必每次跑，列入發版前或每批合回後），並把結果記進 `modtest_stats.jsonl`。
- **S-S2　`name_filter` 的保守分支沒有題目（突變 Q01 存活）**：MT:349 起「判斷不了（`ALL`、`not used` 找不到 import）⇒ 保留」這條分支，被改成「也過濾」之後題目照樣綠。這條分支是整個名稱層級的安全網，建議補兩題：使用者把模組物件傳出去（`ALL`）、使用者以 dep_scan 認得但 AST 找不到的方式 import（`not used`）⇒ 兩者都被保留。

### 觀察

- **O-1　「介面不變」的判定刻意不含預設值與常數的值**：G1:74 寫明「預設值的內容不納入——預設值語意改變要自己升版並寫 CHANGELOG」；常數只記成 `const`。所以改預設值或常數的值，一律判成「介面不變」、只到直接依賴（名稱層級會把那個名稱列為被改，直接使用者會被選到）。這符合設計，但只經過直接使用者傳下去的影響（A 的常數 → B 的行為 → C）要靠契約題接住，與 S-S1 是同一個缺口。
- **O-2　`interface_changed` 不含跨模組在用的底線名稱**：MT:304 呼叫 `G.interface_of(src)` 時沒有帶 `extra_public`（G1 的 `cross_boundary_public`，稽核 G-1 之後才有）。所以 `_require_user`、`_get_setting` 這類跨模組在用的私有名稱改了簽名，也會被判成「介面不變」。名稱層級仍會選到直接用到它們的使用者，所以不致漏選直接使用者；但介面判定與 G1 守門的範圍不一致。建議帶入同一份 `extra_public`。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| S-M1 | | | |
| S-S1 | | | |
| S-S2 | | | |
| O-1～O-2 | | | |

### D 確認（2026-09-26 04:18；對象：origin/wip/b-scope `50058b45`，修正 `62e319b9`、`736196e2`）

回覆欄在 b-scope 分支上；D 把確認寫在這裡，合併時不會與回覆欄的表格衝突。

| # | D 確認 | 證據 |
|---|---|---|
| S-M1 | ✅ 關閉 | `scope_names.expand_internal`（模組內引用閉包）。D 突變 SX1（拿掉閉包）⇒ `test_scope_names`／`test_modtest_scope` 5 紅；SX2（`name_filter` 不呼叫閉包）⇒ 2 紅，含 `test_rc_private_change_reaches_users_of_its_public_caller`。**B 沒見過的新真突變**（主持建議）：`email_notify._users_emails` 拿掉個人退訂過濾 ⇒ 閉包把被改的名稱擴到所有收件人函式與 `notify_*`，選中 444 檔（約 89%，寬扇出的正確代價）；抓得到錯誤的 `test_mail_registry::test_personal_mute_only_removes_and_list_shows_receivable`、`test_notification_prefs_coverage::test_case_change_requested_respects_mute_preference` **都被選到，而且實跑都紅** ⇒ 閉包在第二個模組也成立 |
| S-S1 | ✅ 關閉 | D 實際執行 `tools/platform/scope_rc.py`：`legal_params._as_date` 選到＝True、紅＝True（選中 64 檔）；`auth._require_user` 選到＝True、紅＝True（342 檔）；結束後稽核樹乾淨。建議把上面的 `email_notify._users_emails` 加進它的清單（第三項） |
| S-S2 | ✅ 關閉 | D 重做 Q01（原本存活）⇒ 2 紅（`test_rc_user_passing_the_module_around_is_kept` 等） |
| O-1 | ✅ 接受 | 依回覆 |
| O-2 | ✅ 關閉 | D 突變 O2b（不帶 extra_public）⇒ `test_rc_cross_boundary_private_signature_change_is_an_interface_change` 紅 |

基準：`test_scope_names`＋`test_modtest_scope` **38 passed**。⇒ 本檔必修全部關閉；b-scope 依主持指示在閘門綠了之後才上月台。
