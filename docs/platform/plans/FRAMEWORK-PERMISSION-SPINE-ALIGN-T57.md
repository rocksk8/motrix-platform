# 權限模型與脊柱（spine）對齊 — T57 r1（自 FRAMEWORK-PERMISSION-MODEL-T57 §4.6 拆出）

> 作者 hichan-98；依 2b（1d）對 `0a59fb6a3` 的審查 1～10；僅文件。

### 4.6 與脊柱（spine）對齊（2b／1d 審查 1～10；r3 新增）
1. **`blocks[]` 需要脊柱驗證器**：目前 `module.json` 的未知頂層鍵會被拒絕。做法：在脊柱註冊 `blocks` 的驗證器（`register_validator`，name＋covers），並讓 `features[].blocks: [鍵]` 引用區塊（與 `features[].capabilities` → `_MANIFEST_CAPS` 同形）。**能力與區塊的狀態隨功能狀態**：`planned` ⇒ 在權限頁以灰色『開發中 MSn』列出、格子不可編輯（409）；`hidden` ⇒ 不列出（404）。
2. **失敗方向與脊柱相反（重要）**：脊柱對『未驗證／未知』是**開放**（fail open）；但 `sensitivity=money|personal` 的區塊，只要宣告壞掉、未驗證、被隱藏或驗證失敗，**必須在資料來源端維持遮蔽（種子＝legacy 條件），絕不揭露**。測試：故意弄壞 `blocks[]` ⇒ 該鍵仍不出現在任何回應。
3. **`surfaces` 用脊柱的鍵格式** `module:<擁有者>.<名稱>`（本稿 §4.4 的範例 `case-quotation-form` 不合格，應為例如 `module:case.quotation_form`），並遵守 `surface_not_owned`（模組只能宣告自己的畫面）；與 `catalog.surfaces` 同一個鍵空間，使『規則發布的閘』與『區塊清單』共用同一個畫面登記。
4. **鍵的所有權**：能力／區塊鍵前綴必須等於宣告它的模組；同一鍵被兩個擁有者宣告 ⇒ 兩者皆失敗（同 `_CLAIMS`）。**涵蓋核心資料的區塊**（`financial_mask.QUOTATION_MONEY_COLS`、`bank_mask`）由 **core** 以類似 `core/features_l1.json` 的宣告檔宣告，**鍵必須是 core 擁有的**（例 `core.money.quotation_cost`；`core/capabilities.py` 要求第一段＝宣告它的擁有者，不能用 `case.` 前綴）；或由 `case` 宣告區塊並用 `masks:` 引用 core 的遮蔽鍵。
5. **註冊函式只在 L1**（`register_kind_gate`／`register_managed_kind`／`register_health_source` 有 AST 守門）；權限頁讀取各模組宣告時必須經一個 **L1 helper**，不得呼叫模組程式。
6. **單一開關來源**：`multi_unit_enabled` 不另設設定旗標，**就是已宣告功能 `org_units` 的狀態**（`planned`→`open`）。**注意 fail-open**：`spine.feature_enabled(code)` 對未宣告的功能回傳 True，所以單位強制的判斷是『已宣告（`core/features_l1.json`）且狀態＝open』，刪除宣告必須使過濾保持關閉（有測試）。
7. **單位範圍的宣告**：每個業務物件在 `module.json` 宣告 `scope: "via_case" | "own" | "global"`，由脊柱驗證；新業務表若沒有宣告（或 `global` 沒附理由）⇒ 紅（與 `_spine_scan` 允許清單同形的棘輪）。
8. **設定的 `scope`**：`SettingDef.scope: global | unit`；**`group_stamp(group)` 以及任何規則／快取鍵必須含 `unit_id`**（新增 `unit` 引數），否則繼承值會過期；放寬判斷以『相對於繼承值』為準，`loosen="both"` 的數值設定在每個單位各自適用；E-b 的功能狀態維持全域。
9. **權限頁的寫入端點**用 `register_kind_gate`／`register_managed_kind` 的模式，使通用 `/api/definitions` 永遠無法編輯權限格；金額／個資區塊的放寬發布＝`loosen up`＋核准（§6.2 已有）。
10. **字面值掃描**：**目前 `_spine_scan` 只掃 `mail_register` 與 `settings_group` 的字面值**；待它延伸到能力／區塊鍵之後，字串字面值才會被命中，計畫為（a）逐筆登記允許清單，或（b）改由登記表讀取。優先（b）。
**實作提議**：2b 表示可在機器開放時加脊柱支援（`blocks` 驗證器、`capability_status`／`block_status`、`group_stamp` 的 `unit` 引數）約 **1.5 人日**；列入 PM-1，不重複計。

