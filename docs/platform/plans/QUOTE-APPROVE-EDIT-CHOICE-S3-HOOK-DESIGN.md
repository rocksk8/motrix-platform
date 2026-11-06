# 簽核二擇一 S3 — `reconcile_in_memory` 掛鉤設計（**送 K 審；未寫碼**）

> 日期：2026-11-06　作者：hichan-8（S0／S1 執行窗）　基於：提案 §H2、§I2、§I7；S0 盤點（`QUOTE-APPROVE-EDIT-CHOICE-S0-RECORD.md`）；S1 分支 `s0/fp-write-path-inventory`。
> 全文標註：【已讀碼】看過程式；【推論】未實測。**S3 開工前 K 必須審過本檔（I7）。**

## 1. 要審的結論（先講）

1. 7 條 `CONTENT_DIRECT` **不是 7 條都要掛**：`alt_sign.sign`、`alt_sign.clear_signed_selection` 在待審核／簽核中**進不去**（有狀態閘），不需要掛鉤，改以「不可達」測試取代；其餘 5 條要掛。
2. 通知**不用「commit 之後」佇列**，改成**同一條連線、同一個交易內**寫站內通知列（`notifications` 表）。這比 §I2 的 after-commit 更簡單、不丟通知、也沒有寫鎖凍結問題——但**與 §I2 字面不同，需 K 明確同意**（§5）。
3. 漏斗（`save_quotation_json`）需要知道單據狀態才能判斷「在不在簽核中」，有兩個做法（§3-A），**需 K 選**。
4. 設定要三態（off／shadow／on）才容納「影子模式一週」（§4），與 H4 的布林不同，**需 K 選**。

## 2. 7 條直接寫入的可達性（§I2 要求逐條證明）

| # | 函式 | 簽核中（待審核／簽核中）可達？ | 依據 | S3 處置 |
|---|---|---|---|---|
| 1 | `alt_sign.sign` | **不可達** | 【已讀碼】`_toggle_alt_signed`：`status != "已送出"` ⇒ 409「僅已送出狀態可標記回簽」（api/quotations.py 約 1501） | 不掛；寫測試證明 409 |
| 2 | `alt_sign.clear_signed_selection` | **不可達** | 【已讀碼】`UNSIGN_STATES = ("已送出","草稿","已取消","已拒絕")` 與 `IN_APPROVAL_MSG`（409） | 不掛；寫測試證明 409 |
| 3 | `profit_guard.change_pct` | **可達** | 【已讀碼】`PUT /api/quotations/{no}/overhead-pct`，限超管；只擋已精算／結案、非 v2 口徑；**不擋待審核／簽核中**。它自己有更新 `updated_at` | **掛** |
| 4 | `material_change._apply` | **未驗證，視為可達** | 【已讀碼】只要求 `caseRecord.materialOrders` 裡有該項；叫料端點只擋「已結案」（material_orders.py 約 135），不要求已成案 | **掛**＋測試證明待審核下能／不能走到 |
| 5 | `material_payment.sync_order_paid` | 同上 | 【已讀碼】由登錄付款（需匯款申請已核准）、`material_change` 呼叫 | **掛**＋同上 |
| 6 | `recycle_adapter.MaterialOrderAdapter.delete_in_tx` | 同上 | 【已讀碼】刪除已核可叫料走暫存區 | **掛**＋同上 |
| 7 | `…restore_in_tx` | 同上 | 還原 | **掛**＋同上 |

⚠ 4～7 的「可達」不論證明結果如何都先掛（掛了對不可達的路徑是 no-op，成本只有一次指紋比對）；測試只負責把事實記下來，避免之後狀態閘被改掉時掛鉤缺席。

**S0 守門升級（修正 §I2 的字面）**：`CONTENT_DIRECT` 清單的函式本體必須含 `reconcile_in_memory(` 呼叫；新增處置類別 `UNREACHABLE_IN_APPROVAL`（#1、#2）——必須在測試裡引用對應的狀態閘 409 測試。拿掉狀態閘 ⇒ 該測試紅 ⇒ 強迫回頭補掛鉤。

## 3. 介面

```python
# modules/case/content_fp.py（純函式，不碰資料庫、不發通知）
def reconcile_in_memory(data: dict, now: str, *, status: str, mode: str, source: str, actor: dict | None) -> ReconcileResult
```
- 只改 `data["approval"]`（排除鍵 ⇒ 不影響自己算的指紋）。`status` 不在（待審核／簽核中）或 `mode == "off"` 或沒有 `approval.tiers` ⇒ 直接回「沒事」。
- 流程：`fp = content_fingerprint(data)`；若 `fp == approval.contentFp` ⇒ 沒事。否則找出 `signedFp` 有值且 ≠ fp 的已簽條目（沒有 `signedFp` 的不動＝舊單相容）：
  - `mode == "on"`：條目回 pending＋`reconfirm=True`＋`prevSignedFp／prevApprovedAt`；`currentTier` 退回第一個 pending 層；`approval.contentFp = fp`；`contentRev += 1`；`reconfirmRounds += 1`。
  - `mode == "shadow"`：**不改 approval 的簽核狀態**，只回報「本會作廢誰、哪些區塊」（`changed_blocks(條目.signedKeyHashes, key_hashes(data))`）。
  - 輪次上限：`reconfirmRounds >= 5`（H9）⇒ 不再作廢，回「需通知超管」一次（`approval.capNotifiedFp` 去重）。
- 回傳 `ReconcileResult(changed, invalidated: [username…], blocks: [..], notices: [Notice…], audit: dict | None)`。`Notice = {to, type, refId, label, message, link}`，訊息**不含金額**（與既有核准通知一致，也讓遮罩變成 no-op）。
- 純函式 ⇒ 可以在任何已經讀進記憶體的 `data` 上、於 UPDATE 之前呼叫（§I2 的「各加一行」）。

### 3-A 漏斗怎麼知道狀態（**需 K 選**）
`save_quotation_json(conn, no, data, status=None, …)` 的 `status` 參數只在狀態要改時才給，而 `data["status"]` 可能過期（`GET` 註解：DB 欄位才是權威）。
- **選項 A（建議）**：`mode != "off"` 時漏斗多讀一次 `SELECT status FROM quotations WHERE quote_no=?`（同交易、同連線）。正確；代價＝`unscoped_reads_baseline.json` 再 +1（我在 S1 已為 `rebaseline_fingerprint` +1，上限 850→851）。`mode == "off"`（預設）完全不多一次查詢。
- 選項 B：從 `approval` 推導（有 tiers 且 `approval.status` 不是 approved／rejected）。零新查詢，但 `approve` 全簽完那一刻 `approval.status` 與 DB 狀態的先後、舊單沒有 `approval.status` 的情況要另外證明，**我不建議**。
- 其餘 4 條直接寫入各自已有讀到 `status`（`change_pct` 的 SELECT 有）或只需把 `status` 加進既有 SELECT 欄位（`_order_of`），**不新增查詢**。

## 4. 設定（**需 K 選**）
H4 寫的是布林 `reconfirm_on_change`（預設關），H9 另規定「影子模式一週後才可開旗標」。兩者合成一個設定最單純：`quote_approval.reconfirm_mode ∈ {off, shadow, on}`，預設 `off`＝與今天逐位元相同（含不多一次查詢）。
- `off→shadow`、`shadow→on`：緊縮方向（簽核變嚴），照一般設定流程。
- `on→off`、`on→shadow`：**放寬**，比照 D-K1 要第二位最高管理者核准（H9-2）；`shadow→off` 不算放寬（本來就沒作廢）——**請 K 確認這條**。
- `off→on` 直接跳過 shadow：程式上不擋，但設定中心顯示「尚未跑影子模式」警示並寫稽核（H9-3 是流程要求，不是技術限制）。
- 影子紀錄：寫稽核 `quotation.reconfirm_shadow`（同交易），detail＝`{fp, blocks, wouldInvalidate, source}`；`approval.shadowFp` 去重（同一指紋只記一次），供一週後統計「來源區塊」（§I4 判 `dealTag` 用）。

## 5. 通知時機（**與 §I2 字面不同，需 K 同意**）
§I2：通知一律 after-commit，避免「寫鎖內 `_notify` 另開連線」的凍結（W3）。【已讀碼】`helpers/audit._notify` 的確是**另開連線**、INSERT 一列 `notifications`、自己 commit；它沒有其他副作用（不寄信、不推播）。
- **問題不在「寫鎖內寫通知」，在「另開連線」**。同一條連線在同一個交易裡 INSERT 同一張表：沒有鎖衝突、與簽核資料**原子**（交易回滾 ⇒ 通知一起消失；after-commit 方案反過來可能「資料已 commit、通知沒發出」而且不可重送）。
- 做法：把 `_notify` 的 INSERT 邏輯抽成 `helpers/audit._notify_in_txn(conn, …)`（`_notify` 改成開連線→呼叫它→commit，行為不變），`reconcile` 的呼叫點用同一條 `conn` 寫。這是 L1 加性介面（`helpers/audit`），需照 PLAYBOOK §G 的 L1 規則（介面快照、CORE 佔位版號）。
- 合併通知（H6-1②）：「同一 `(type, ref_id, username)` 同時只留一列**未讀**」——`INSERT … WHERE NOT EXISTS (… AND is_read=0)`（比照既有 `_approved` 去重的單一陳述寫法）。連續改很多次 ⇒ 簽核人只看到一則「內容有更新」，已讀後再有變動才有新的一則。
- 若 K 仍要 after-commit：需要 `core.txn.after_commit(conn, fn)`（L0 加性介面；`write_txn` 離開時 commit 成功才執行），而且 5 條直接寫入裡有幾條不是 `write_txn` 包的（`change_pct` 是；其餘【推論】多為 `begin_write`），要逐條補。**成本明顯較高，不建議。**

通知對象（H2／H6-2）：被作廢的已簽層簽核人、送審人、後續層（尚未簽的）；訊息含「誰改（稽核操作者）」與 `changed_blocks` 區塊名，不含內容。`type="approval_reconfirm"`。

## 6. 呼叫點一覽（S3 的施工清單）

| 位置 | 呼叫 | `source` | 備註 |
|---|---|---|---|
| `save_quotation_json`（漏斗結尾、序列化之前） | 是 | `funnel` | 涵蓋 25＋1 個走漏斗的呼叫端；`approve` 自己蓋章後走漏斗，指紋相符 ⇒ no-op |
| `change_pct` | 是 | `overhead_pct` | UPDATE 之前；已更新 `updated_at` |
| `material_change._apply` | 是 | `material_change` | 之前；刻意不補 `updated_at`（§I3） |
| `material_payment.sync_order_paid` | 是 | `material_paid` | 同上 |
| `recycle_adapter` 刪除／還原 | 是 | `material_recycle` | 有更新 `updated_at` |
| `approve`（S1 已有 `expectedFp`） | 是（先 reconcile 再判斷） | `approve` | 兩人同時操作以 `expectedFp` 擋後到者 |
| `review-edit`（S4） | 是 | `review_edit` | S4 才做 |
| `alt_sign.sign`／`clear_signed_selection` | **否** | — | 不可達，測試證明 |
| 解鎖編輯 PUT、`update_status`、`recall`／`reject`、新單 INSERT、批次案件變更、日曆回寫、`_record_doc_version` | 否 | — | S0 登記：整份重建簽核／離開簽核／只動排除鍵／只已成案 |

讀路徑（佇列、GET）**只** `effective_approval()` 純推導，不呼叫 `reconcile`、不寫入（§I2）。

## 7. 驗收（S3 測試清單）
1. `mode=off`：全套既有簽核／報價單測試逐位元不變；漏斗不多一次查詢（用 SQL 計數斷言）。
2. 五條掛鉤各一題：B 已簽 → 該路徑改內容 → B 回 pending＋`reconfirm`、送審人與後續層收到一則通知、`changed_blocks` 正確、稽核寫了。
3. 突變：拿掉任一處 `reconcile_in_memory(` ⇒ S0 守門紅；把 `UNREACHABLE_IN_APPROVAL` 的狀態閘拿掉 ⇒ 不可達測試紅。
4. 只動排除鍵（approval／statusLog／docVersions…）⇒ 不作廢；`dealTag` 變動 ⇒ 作廢（從嚴）。
5. 三層：T1、T2 已簽、T3 的人改內容 ⇒ T1、T2 依序複查才輪 T3。
6. 輪次上限 5：第 6 次不作廢、超管收到一則。
7. 合併通知：連改 5 次 ⇒ 簽核人未讀列只有 1 則；已讀後再改 ⇒ 新的一則。
8. 交易回滾（例外）⇒ 資料與通知都不在。
9. `shadow`：簽核狀態不變、稽核有 `quotation.reconfirm_shadow`、同一指紋只記一次。
10. 舊單（條目沒有 `signedFp`）：任何內容變動都不作廢。
11. 放寬方向的設定變更走 D-K1（第二位最高管理者）。

## 8. 需要 K 回答（共 5 題）
- Q1 漏斗讀狀態：選項 A（多一次 SELECT，棘輪 +1）還是 B？
- Q2 設定：三態 `reconfirm_mode`，還是維持布林＋獨立影子開關？
- Q3 `alt_sign` 兩函式以「不可達＋測試」取代掛鉤，可否？（這與 §I2 的「`CONTENT_DIRECT` 每個函式都必須含呼叫」字面不同。）
- Q4 通知：同交易同連線（建議）還是 after-commit 佇列？（§5）
- Q5 `shadow→off` 是否不算放寬？

## 9. 已知限制（S3b 實作後；K 審 ① 要求寫明）

1. **沒有緊急關閉開關**：`quote_approval.reconfirm_mode` 往小調（開→影子、開→關、影子→關）一律是**放寬**——需要**第二位最高管理者核准**，並經**確認期間**才生效（`change_control.confirm_period_days`，**預設 7 天、程式下限 1 天**）。K 的字面是「影子→關不算放寬」，但設定欄位只有數字型能掛放寬管制，單一數字表達不了「開→影子要管、影子→關不管」，所以影子→關也走同一流程（較嚴的一邊）。旗標開了之後若出問題，**最快也要等第二位超管核准＋確認期間**才能關；期間內只能靠輪次上限（5 輪後自動不再作廢並通知超管）止血。
2. **列表列的「快速核准」不綁版本**：它不載入詳情，沒有 `expectedFp` ⇒ 稽核記 `fpBound:false`；`EXPECTED_FP_REQUIRED` 翻成 True 之前要處理。（approve 的對帳不受影響：簽核層被作廢仍會 409。）
3. **對帳只掛在已知的寫入點**：漏斗與 5 條直接寫入由 S0 守門釘住（新增寫 `data_json` 的函式 ⇒ 守門紅）。直接以 SQL 改庫（維運手動、舊分頁以外的未登記路徑）不會立刻對帳；下一次經過上述任一寫入點、或簽核人按核准時才補上（approve 先對帳）。讀路徑（GET、佇列詳情）只純推導、不寫入。
4. **模式快取最長 5 秒**：設定發布立即作廢（設定世代）；到期的待生效值（放寬後的新值）最多晚 5 秒被看到。讀不到設定一律當 `on`（最嚴）、不快取。
5. **`change_pct`、`material_change._apply` 沒有各自的行為測試**：只有 S0 守門（函式內有 `reconcile_txn(` 呼叫，且行號早於寫 `data_json` 的 `execute`）；`sync_order_paid`、`recycle_adapter` 刪除／還原有行為測試。
6. **觸發對帳的人不會收到自己的通知**：簽核人自己按核准而被對帳作廢時，只得到 409「簽核狀態已重算」；其他層與送審人照常收到通知。

## 10. S4（複查編輯端點）實作記錄與偏離

1. **順序（PM 交辦的判斷題）**：review-edit 與 approve 有**同一個過期狀態問題**（資料庫裡「已簽但簽在舊內容」的人，在對帳之前不是「當層待簽人」）⇒ 同樣**先對帳、再查權限**。對帳用 `source="review-edit-pre"`、不掛操作者：那不是他改的，也不能觸發他自己的重簽。沒權限 ⇒ 連線不 commit，對帳痕跡消失（測試：`test_stale_approved_approver_can_review_edit…`、`test_denied_review_edit_leaves_no_trace…`；拿掉對帳呼叫前者翻紅）。
2. **偏離 ①（需 PM／K 確認）：`reconfirm_mode` 不是 on 時 review-edit 一律 409。** off／shadow 不會作廢任何簽，開放編輯＝簽核人改完內容卻沒人複查，是新的繞過。
3. **偏離 ②：K3 只在 on 時強制。** off／shadow 維持與今天逐位元相同；否則 S5 彈窗上線前，轉簽／代理的核准會被鎖死。稽核照記旗標。**S5 上線前不得把模式開成 on。**
4. **偏離 ③：編輯者是最後一個未簽完的人 ⇒ 不自動簽**（S3a 新增分支，`changeLog.editorPending`）。否則舊單（其他層沒有 `signedFp`、永不作廢）上整單全 approved、狀態卻停在簽核中，沒走核准收尾（已送出、PDF、核准通知）。
5. **範圍**：`caseRecord` 不可由 review-edit 改；`salesPerson` 釘資料庫（簽核人不能藉複查改案件擁有者）；代理人編輯不替本人重簽。
6. **J1**：`stamp_signed(…, reason_entries)` 與 `reconcile_in_memory(…, reason_entries=)`；`reconcile_txn` 只在 `source==review-edit` 且 on 時才算（純函式維持不讀設定）。

