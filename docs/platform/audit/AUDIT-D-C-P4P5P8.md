# 稽核：C 的 P4 自訂欄位、P5 定義文件庫、P8 自訂模組引擎（後端）＋缺口 #1／#2（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象（origin/platform，add39465..23b04b74 之中屬於 P4／P5／P8 的部分）：`6c3748c4`、`e3c19563`、`f9b72da5`（P4／P5）、`d1272c9f`、`136ec74d`、`0a890315`、`186f2368`、`b9b12d20`（P8）、`d4fdefc2`（#1 動態權限 key、#2 讀單帶回該版定義）。A8d、N-1 不在本份範圍。
> 規格：CUSTOMIZATION-SPEC §3.5、§3.6、§3.7。稽核樹 `D:\MOTRIX-PLATFORM-D`（detached，origin/platform `26d8af8b`），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：`CM`＝`backend/helpers/custom_modules.py`、`FX`＝`backend/helpers/formula.py`、`CF`＝`backend/helpers/custom_fields.py`、`DF`＝`backend/core/definitions.py`、`CR`＝`backend/routers/custom_records.py`。

## 0. 結論

- 規格的主幹都有實作也有題目：定義的草稿、發布、版本、差異、還原（歷史不改）；公式的空值不是 0、除以 0 回報、循環引用擋下；流程可達性驗證；轉換不能跳過簽核；通知與事件在 commit 之後才送；權限；#1 動態權限 key（來源失敗 ⇒ 擋下新授權）；#2 讀單帶回該版定義。
- 基準 **53 passed**。D 自做突變 14 項**全紅**（§2）。
- 主持點名的五項，有四處不成立，都是規格文字裡沒有想到的邊界：
  - 「簽核不可跳過」：條件 `when` 算出空值時，那一層被**跳過**（C-M1）。
  - 「流程驗證」：通過發布驗證的定義，送審時 500：`when` 執行期錯誤（C-M2）、自動通過的狀態互相指向造成無限遞迴（C-M3）。
  - 公式 `round` 是銀行家捨入（C-M4）。
  - 另外，數字欄位收下 `NaN`，寫進資料庫之後，整個模組的列表對所有人都 500（C-M5）。
- **必修 5 項**。建議 5 項、觀察 4 項。

## 1. 逐項驗收（主持點名的五項）

| 項目 | 驗收 | 證據 |
|---|---|---|
| 定義文件庫：已發布版本不可改、發布、差異、還原 | ✅ | DF:62-136（草稿 version 0 可改；發布＝新增一列＋刪草稿；還原＝舊內容再發布成新版，並用目前的驗證器重驗）；突變 C11、C12 見 §2。邊界見 C-O1 |
| 自訂欄位命名空間 | ✅ | CF:17-53（key 格式、不可與核心欄位同名、型別目錄、預設值型別）；突變 C08 |
| 送審時凍結 `customFieldsVersion` | ⏳ 未接 | 沒有任何內建模組呼叫 `custom_fields.clean`，也沒有記 `customFieldsVersion`（grep 產品碼 0 筆）。ROADMAP P4 已如實寫「未做：接進第一個內建模組」⇒ 觀察 C-O2，不算缺陷 |
| 公式：null 不是 0 | ✅ | FX:175-180；突變 C03 |
| 公式：除以 0 | ✅ | FX:200-201 ⇒ 那一欄空值並回報；突變 C04 |
| 公式：循環 | ✅ | FX:263-282；突變 C05 |
| 公式：`round` | ❌ | C-M4 | 修正：公式 `round` 改用 R 的 L1 `helpers.legal_params.round_half_up`（不另寫一份）：乘 10^位數、四捨五入到整數、再除回來。題：2.5⇒3、3.5⇒4、-2.5⇒-3、738.5⇒739、`round(1.005, 2)`⇒1.01、`round(10/3, 2)`⇒3.33、負位數 `round(1234, -2)`⇒1200，並驗型別（整數位數回 int）；規格 §3.7 寫明「round＝四捨五入」。突變：改回內建 round ⇒ 4 紅 | wip/c-audit-d-2 bf80789f | |
| 流程驗證 | ⚠ | CM:138-231 驗了孤立狀態、終點、出路、條件語法；**沒有驗**條件的執行期型別（C-M2）、自動通過的循環（C-M3）、起始狀態掛簽核（C-S3） |
| 簽核不可跳過 | ⚠ | 轉換不能跳過簽核 ✅（CM 的 transition；突變 C02）；**條件算出空值 ⇒ 那一層被跳過** ❌（C-M1） |
| 通知在 commit 之後才送 | ✅ | `_Effects`：交易內只收集，`flush()` 在 commit 之後；突變 C01（改成當場送）⇒ 紅 2 題，而且跑了 6.6 分鐘（卡在鎖上，正好印證原設計的理由） |
| 權限 | ✅（範圍見 C-O3） | CR:29-40；突變 C13 |
| #1 動態權限 key | ✅（範圍見 C-S4） | `module_registry.known_keys()`；來源失敗 ⇒ key 不認得 ⇒ 擋新授權；突變 C14 |
| #2 讀單帶回該版定義 | ✅ | CM:395-403 `rec["definition"]`；meta `?version=`；突變 C10 |

## 2. 突變（D 自做；每項都用 `git checkout` 還原並核對內容）

| 突變 | 結果 | 題數 | 轉紅的題（前 2） |
|---|---|---|---|
| C01-通知在交易內送 | 🔴 | 2 failed, 51 passed | `test_custom_module_single_tier_approval_notifies_and_emits_event`、`test_custom_module_reject_revise_and_content_freeze` |
| C02-轉換可跳過簽核 | 🔴 | 1 failed, 52 passed | `test_custom_module_approval_cannot_be_skipped_by_a_transition` |
| C03-空值當0 | 🔴 | 1 failed, 52 passed | `test_formula_engine_null_is_not_zero_and_division_by_zero_is_reported` |
| C04-除以0不攔 | 🔴 | 1 failed, 52 passed | `test_formula_engine_null_is_not_zero_and_division_by_zero_is_reported` |
| C05-循環不偵測 | 🔴 | 1 failed, 52 passed | `test_custom_module_formula_cycle_is_reported` |
| C06-必填不驗 | 🔴 | 2 failed, 51 passed | `test_custom_module_bad_values_are_reported_per_field`、`test_custom_fields_clean_coerces_reports_and_drops` |
| C07-參照不驗 | 🔴 | 1 failed, 52 passed | `test_custom_module_bad_values_are_reported_per_field` |
| C08-可與核心欄位同名 | 🔴 | 2 failed, 51 passed | `test_custom_fields_definition_problems_carry_positions`、`test_definitions_api_publish_with_problems_is_422_and_keeps_the_draft` |
| C09-送出後可改 | 🔴 | 1 failed, 52 passed | `test_custom_module_reject_revise_and_content_freeze` |
| C10-讀單不帶該版定義 | 🔴 | 1 failed, 52 passed | `test_custom_module_old_record_comes_with_its_own_definition` |
| C11-還原不驗證 | 🔴 | 1 failed, 52 passed | `test_definitions_restore_is_validated_against_the_current_environment` |
| C12-發布不驗證 | 🔴 | 3 failed, 50 passed | `test_custom_module_publish_is_blocked_by_problems`、`test_definitions_validator_blocks_publish_and_returns_positions` |
| C13-模組權限不驗 | 🔴 | 2 failed, 51 passed | `test_custom_module_permissions`、`test_custom_module_permission_can_be_granted_on_the_users_page` |
| C14-授權不認得的key | 🔴 | 2 failed, 51 passed | `test_custom_module_permission_can_be_granted_on_the_users_page`、`test_custom_module_permission_source_failure_refuses_new_grants` |

14 項全紅（C01 跑 6.6 分鐘：通知在交易內送出時卡在寫鎖上，正好證明原設計的理由）。

## 3. 探針（暫存題 `tests/test_zz_auditD_probe_c.py`，用 C 的 `loan` 夾具；跑完已刪，不 commit）

| 探針 | 結果 |
|---|---|
| 單價欄位沒有 default、不填；數量 50 ⇒ `total` 是 null；第二層條件 `total > 10000` | `TOTAL None`、送審後 **只有 1 層** ⇒ C-M1 |
| 第二層條件 `item > 5`（item 是文字），發布 | 發布 200；送審 ⇒ **未處理的 FormulaError（500）**，單據維持草稿 ⇒ C-M2 |
| 兩個簽核狀態的條件都不成立、`on_approved` 互相指向，發布 | 發布 200；送審 ⇒ **RecursionError（500）** ⇒ C-M3 |
| `round(2.5)`、`round(3.5)`、`round(1.005, 2)`、`round(738.5)` | `2`、`4`、`1.0`、`738` ⇒ C-M4 |
| 數字欄位送 `"nan"` | 建立 ⇒ 500（回應序列化失敗），但**資料已經寫進 DB**（`"qty": NaN`）；之後讀單與**整個模組的列表**都 500 ⇒ C-M5 |
| 同樣有模組權限的另一個人：改別人的草稿、替別人送審 | 200、200 ⇒ C-O3 |
| 代理人讀單據 | `_is_approver` 只看 approvers ⇒ 代理人可以簽，卻讀不到單 ⇒ C-S2 |
| 自訂模組的 `permission` 設成內建模組的 key `cashier` | 驗證通過 ⇒ C-S4 |

## 4. 發現

### 必修

**C-M1　簽核條件算出空值時，那一層被跳過（fail-open）**
- 位置：CM:512 `if not t.get("when") or _fx.evaluate(t["when"], rec["data"])`。空值參與比較時，`total > 10000` 回 `None`（FX:226-227），當成 false，於是那一層不列入。
- 規格：§3.7「簽核不可跳過」，以及同一節「空值不等於 0」。這裡的空值卻被當成「條件不成立」。
- 後果：申請人只要不填金額或單價（沒有 default 的數字欄位），高金額單據就不會進到第二層簽核。全部層都是條件式時，還會「直接視為通過」（CM:518-524）。
- 重現：見 §3 第一個探針。
- 建議修法：條件結果是 `None` ⇒ **那一層列入**（fail-closed），並在單據上記「條件無法判斷（欄位 total 沒有值），依規定列入」；或者直接擋下送審，要求填齊條件引用的欄位（`formula.references`）。規格要寫明採用哪一種。補反向控制題。

**C-M2　簽核條件在執行期出錯 ⇒ 500**
- 位置：CM:512 呼叫 `_fx.evaluate` 時沒有接 `FormulaError`。發布驗證（CM:213-215）只檢查語法與欄位是否存在，不檢查型別（文字和數字比大小）。
- 後果：通過驗證、已經發布的定義，每一次送審都 500，畫面沒有訊息，使用者無法往下做。狀態因交易回滾而維持草稿（D 確認）。
- 建議修法：接住 `FormulaError` ⇒ 409／422，訊息指出是哪一層條件、哪一個欄位；同時依 C-M1 的原則決定這一層列入或擋下。發布驗證可以用 `sample_view` 的樣本值試算一次條件，先抓出型別錯誤。

**C-M3　自動通過的狀態互相指向 ⇒ 無限遞迴（500）**
- 位置：CM:518-524。全部層的條件都不成立時，會遞迴呼叫 `_enter_state(on_approved)`。流程驗證的可達性檢查（CM:217-230）不檢查「只經過自動通過的邊就繞回來」的循環。
- 重現：見 §3 第三個探針（發布 200，送審 RecursionError）。
- 建議修法：`_enter_state` 帶一個「本次已經自動通過的狀態」集合，重複進入就擋下並回 422；或者在發布驗證時找出 `on_approved` 構成的環並擋下。

**C-M4　公式 `round` 是銀行家捨入**
- 位置：FX:254 `round(nums[0] + 0.0, digits)`。Python 的 `round` 是 round-half-even，而且浮點誤差會讓 `round(1.005, 2)` 得到 `1.0`。
- 為什麼是必修：建構器給業務使用者算金額（單價×數量、稅額、補助），一般人和法規都預期四捨五入（同一類問題見 `AUDIT-D-R1-R3-legal.md` D-1：補充保費）。`round(2.5)` 得到 2，而且畫面上沒有任何說明。
- 建議修法：用 `Decimal(str(x)).quantize(…, ROUND_HALF_UP)`，並在規格 §3.7 寫明「round＝四捨五入」。補 2.5、-2.5、1.005 三題。建議與 D-1 共用同一個 L1 捨入函式。

**C-M5　數字欄位收下 `NaN`／`inf`：寫進資料庫之後，整個模組的列表都壞掉**
- 位置：CF:66-70 `float(v)` 接受 `"nan"`、`"inf"`、`"1e400"`。寫入時 `json.dumps` 預設允許 NaN（產生非標準 JSON 的 `NaN`）；回應時 FastAPI 的 JSON 編碼拒絕 NaN ⇒ 500。
- 後果（D 實測）：
  1. 建立回 500，但單據**已經 commit**，使用者以為失敗，重送就多一張。
  2. 之後讀那張單 500。
  3. **`GET /api/custom/<key>/records` 對所有人 500**，一個輸入就讓整個模組的列表無法使用。
- 建議修法：`_coerce` 拒絕非有限數（`math.isfinite`）；寫入端 `json.dumps(..., allow_nan=False)` 做第二道防線。補題：`"nan"`、`"inf"`、`"1e400"` ⇒ 400。已經寫進 DB 的壞資料要有修復路徑（例如 `rebuild_index` 旁邊加一支檢查）。

### 建議

- **C-S1　條件、公式的型別錯誤應該在發布時就抓到**：延伸 C-M2。`check()` 只做語法與欄位檢查。可以用欄位型別做靜態推斷（text 與 number 比大小、number 加 text），或用 `sample_view` 的樣本資料試算一次，讓建構器在 ④ 流程就標出錯誤位置。
- **C-S2　代理人可以簽，卻讀不到單據**：CR:43-47 `_is_approver` 只比對 `approvers`。`tiered_approval` 允許代理人簽核（`check_approve_permission`），代理人卻沒有讀單、讀輸出的權限（沒有模組權限時 403），執行頁打不開。建議 `_is_approver` 改用 `tiered_approval` 的同一套判準（含代理人）。
- **C-S3　起始狀態掛簽核不會生效**：`create_record` 以起始狀態建立、`approval_json` 是 `{}`，transition 的「簽核中不能轉換」判斷依賴 `rec["approval"]`，因此掛在起始狀態上的簽核永遠不會展開，也沒有任何提示。建議在流程驗證擋下「起始狀態不可以有 approval」。
- **C-S4　自訂模組的 `permission` 可以設成內建模組或別的自訂模組的 key**：CM:68-70 只驗格式。設成 `cashier` ⇒ 所有出納都能用這個自訂模組；兩個自訂模組共用同一個 key ⇒ 使用者管理頁只顯示第一個模組的名稱（`dynamic_modules` 去重）。建議限制在 `custom.` 開頭，或明確列出可共用的內建 key 並在畫面說明。
- **C-S5　發布時沒有拿寫鎖**：DF:112-123 依序讀草稿 → 驗證 → 算下一個版號 → 插入 → 刪草稿，中間沒有 `begin_write`。兩個人同時發布 ⇒ UNIQUE 衝突 ⇒ 500。發布的同時有自動存檔 ⇒ 刪掉的是較新的草稿（前端的 `flushSave` 會先等存檔，但 API 本身不保證）。建議整段包在寫交易裡，刪草稿時比對讀到的那一份。

### 觀察

- **C-O1　還原不動草稿**：還原成新版之後，舊的草稿還在。下一次「發布」會把那份舊草稿蓋在還原的結果上。建議還原時提示「目前有未發布的草稿」，或一併把草稿換成還原的內容。
- **C-O2　P4「送審時凍結」還沒有呼叫端**：`custom_fields.clean` 與 `customFieldsVersion` 沒有接進任何內建模組（ROADMAP P4 已如實標「未做」）。依〈兩個都對而路不存在〉，第一個接的模組要附一題「定義改版之後舊單仍依舊版顯示與輸出」。
- **C-O3　同一個模組權限的人可以改、送別人的草稿**：規格 §3.7 的權限只到「模組」層，所以符合規格。但這是使用者看得到的權限範圍，依 PLAYBOOK §F 應由使用者裁示是否需要「只有建立者可以改、送自己的草稿」（或者用 `requester_only` 讓定義者自己選）。
- **C-O4　`when` 為空值時的處理需要寫進規格**：不論 C-M1 採用哪一種修法，規格 §3.7 都應該寫明，並同步到建構器的說明文字。

## 5. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| C-M1 | 修正（fail-safe）：條件只有明確不成立（False／0）才跳過該層；算出空值 ⇒ 那一層照簽，notices 寫明「條件無法判斷，依規定列入」。規格 §3.7 已寫。突變 2 項紅 | 第二批 wip/c-p2-legal b757ac26 |✅ 2026-09-26 04:18 關閉（在 `wip/c-audit-d` d132336f 驗證）：D 原探針（單價未填、數量 50）⇒ 送審後 **2 層**；D 突變 CX1（空值改回跳層）⇒ 紅 |
| C-M2 | 修正：執行期出錯（FormulaError）⇒ 那一層照簽並說明，不再 500；型別錯誤另由 C-S1 在發布時抓 | 同上 |✅ 2026-09-26 04:18 關閉：D 原探針（`item > 5`）現在在**發布時**被樣本試算擋下（422，指出 `tiers[1].when`）；執行期出錯的照簽：D 突變 CX2 ⇒ 紅 |
| C-M3 | 修正：發布時找出 on_approved 構成的環並擋下（指出位置）；執行時自動通過最多連跳 20 次（`_MAX_AUTO_HOPS`），超過回 409、單據維持原狀 | wip/c-audit-d d132336f（疊在第二批 bec40ee5 之上）→ rebase 後 wip/c-audit-d-2 bf80789f |✅ 2026-09-26 04:18 關閉：D 原探針（互相指向）⇒ 發布 422「簽核狀態互相指向，形成循環：approved → pending → approved」；D 突變 CX4（不查循環）⇒ 紅。執行期上限 `_MAX_AUTO_HOPS` D 沒有另外驗 |
| C-M4 | 待 R 的 `helpers.legal_params.round_half_up` 合回後接上（主持裁示不另寫一份）；補 2.5／-2.5／1.005 三題＋突變 | （待） |⏳ 2026-09-26 04:18 未關：d132336f 上 `round(2.5)`＝2、`round(738.5)`＝738、`round(1.005, 2)`＝1.0，仍是銀行家捨入；等 R 的 `round_half_up` 接上後再確認 |
| C-M5 | 修正：`custom_fields._coerce` 用 `math.isfinite` 擋 NaN／inf（400、指出欄位）；第二道防線 `_dump_values` 寫入時 `allow_nan=False`（交易內擋下、什麼都不寫）；舊資料讀出時非有限值換成空值（讀單、列表不 500）；公式結果非有限 ⇒ 報錯。突變 3 項紅 | wip/c-audit-d d132336f（疊在第二批 bec40ee5 之上）→ rebase 後 wip/c-audit-d-2 bf80789f |✅ 2026-09-26 04:18 關閉：D 原探針 `qty="nan"` ⇒ 400「必須是有限的數字」，列表 200；D 突變 CX3（拿掉 isfinite）⇒ 5 紅 |
| C-S1～S5 | 全部修正：S1 發布時用樣本值試算公式與條件（`sample_values`／`_validate_by_sample`）；S2 `_is_approver` 認得代理人（讀單與輸出）；S3 起始狀態不可以掛簽核；S4 permission 不可以是內建模組 key、不可以與已發布的自訂模組共用；S5 發布／還原先 `begin_write`。突變各 1～2 項紅 | wip/c-audit-d d132336f（疊在第二批 bec40ee5 之上）→ rebase 後 wip/c-audit-d-2 bf80789f |✅ 2026-09-26 04:18 接受：S1 見 C-M2 的探針；S3 D 突變 CX5（起始狀態可掛簽核）⇒ 紅；S4 D 探針 `permission=cashier` ⇒ 驗證擋下。S2、S5 依回覆（C 的突變），D 未另驗 |
| C-O1～O4 | O1 修正：還原回應帶 `draftPending`，規格 §3.5 同步（突變 1 項紅）；O2 不在本批：P4 送審凍結要等第一個接 `custom_fields.clean` 的內建模組，屆時附「定義改版後舊單仍用舊版」一題（ROADMAP P4 已標未做）；O3 已由使用者裁示 U14：草稿只有建立者與超級管理員可以修改、送出（後端 403，讀單回 `canEdit`，前端依此隱藏按鈕；突變 2 項紅）；O4 規格 §3.7 已寫明空值／出錯的處理 | wip/c-audit-d d132336f（疊在第二批 bec40ee5 之上）→ rebase 後 wip/c-audit-d-2 bf80789f |✅ 2026-09-26 04:18 接受（O2 維持 ROADMAP 追蹤；O3 依使用者裁示 U14） |

> D 確認的依據（2026-09-26 04:18）：在 `wip/c-audit-d` d132336f 上跑 `test_custom_modules_engine`＋`test_definitions_store`（基準綠），D 的原探針 6 項重跑，D 突變 CX1～CX5 全紅。⚠ 修正還在分支上（第二批＋c-audit-d），合回 origin 後本檔的關閉才在 platform 上生效；C-M4 仍開著。
