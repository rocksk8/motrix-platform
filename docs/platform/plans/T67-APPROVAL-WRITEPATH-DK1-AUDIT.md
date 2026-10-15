# T67 稽核（靜態讀碼）：簽核相關設定的所有寫入路徑 × D-K1

基底：origin/train/t65-int @4de2ac1f8。方法：列舉寫入簽核門檻／簽核流程／簽核範圍的所有程式路徑，逐一讀碼確認是否經過「放寬 ⇒ 待生效＋第二位最高管理者核准」。**未跑任何測試、未動執行環境。**
D-K1 條文（`docs/platform/CORE-SPEC.md:309`）：報價簽核門檻（毛利 30%、有效天數 30、折扣）與 `finance_cashier.receivable_grace_days` 往放寬方向修改 ⇒ 第二位最高管理者核准；收緊不需要；預設不變、讀不到取最嚴格、伺服器仍重算原因。

## 結論
- **D-K1 字面範圍（4 個欄位）：全部寫入路徑都經核准，沒有發現繞過。**
- **字面範圍之外、性質相同的簽核流程設定：4 條寫入路徑完全沒有放寬分類、第二人核准或確認期間（G1）。** 任一位超管可立即移除簽核層級、關掉部門主管自動簽核層、或切換套用範圍。是否納入 D-K1 屬 PM／使用者裁示（現況是「設計上就沒有」，不是漏接，但與 D-K1 精神不一致）。
- 另有 3 個次要觀察（G2–G4）。

## 寫入路徑表
| # | 路徑 | 寫什麼 | 權限 | 放寬判斷／第二人 | 判定 | 證據 |
|---|---|---|---|---|---|---|
| W1 | `POST /api/settings-center/groups/quote_approval` | `min_item_margin_pct`（loosen=down）、`max_valid_days`（up）、`discount_review_above`（up） | 超管 | **有**：`_split` 判放寬 ⇒ 待生效＋`approvals_required=1`；申請人不可核准自己的、同人不可投兩票；未達票數到時間也不生效 | **OK** | `settings_groups.py:406-418`；`settings_registry.py:640-650,818-840`；`config_ledger.py:221-237,270-276` |
| W2 | `POST /api/settings-center/groups/finance_cashier`（`receivable_grace_days`） | 應收寬限天數 | 超管 | 有（`loosen="up"`，risk=money） | OK | `settings_groups.py:480`；`finance_params.py:131` |
| W3 | `…/groups/{g}/reset`、`…/restore/{version}`、`…/profiles/{name}/apply` | 同上欄位（還原預設／舊版／預設組） | 超管 | 有：三者都落到 `publish()`（reset→`_do_publish`；restore→`ledger.restore_version`→`_restore`→`publish`；profile→`apply_profile`→`publish`） | OK | `settings_center.py:165-196,231-266,399-410`；`settings_registry.py:940-975` |
| W4 | `POST /api/definitions/setting_group/{key}/publish｜restore`、`PUT …/draft` | 通用定義端點寫設定群組 | 超管 | 被擋：`setting_group` 為受管 kind，通用寫入一律 409 | OK（讀到訊息與常數；`_managed_guard` 函式本體未逐行讀） | `routers/definitions.py:134-148`，呼叫點 `:485-488,:587-590` |
| W5 | 讀取端：`quote_terms._strict_number`／`min_item_margin_pct`／`max_valid_days`／`discount_review_above`；`finance_params.receivable_grace_days` | 讀不到取最嚴格；伺服器重算原因 | — | 符合 D-K1「讀不到取最嚴格」 | OK | `modules/case/quote_terms.py:161-215`；`helpers/finance_params.py:131` |
| W6 | `PUT /api/settings/approval-flow` | `unified_approval_flow`（層級、簽核人、`includeSubmitterManagerTier`） | 超管 | **無**：直接寫入、無原因欄、無待生效、無第二人；稽核只記層數與人數，不記前後內容 | **GAP G1** | `routers/system.py:119-135` |
| W7 | `PUT /api/settings/approval-flow/{doc_type}` | `{doc_type}_approval_flow`（單據獨立流程） | 超管 | 同 W6 | **GAP G1** | `system.py:215-232` |
| W8 | `PUT /api/settings/approval-flow-scope` | 各單據走統一或獨立流程 | 超管 | 同 W6；另：獨立→統一會把該單據改走另一把 key 的流程，兩把內容不比較寬嚴 | **GAP G1** | `system.py:176-212` |
| W9 | `PUT /api/contractor-vouchers/settings/approval-flow` | 與 W7（`contractor_voucher`）同一把 key；**無 UI 入口**，僅舊書籤／腳本 | 超管 | 同 W6 | **GAP G1（第二條路徑）** | `subcontract/api/contractor_vouchers.py:1248-1264`（說明 `:1236-1242`） |
| W10 | `PUT /api/overhead/settings`（`defaultPct`、`ruleMode`、`charityMode`） | 管銷％與口徑 | 超管 | 無第二人；`ruleMode`→v2 要 `confirm:true`＋遷移完成；退回 legacy 無核准 | 次要 **G2**（金額類，非簽核門檻） | `case/api/overhead.py:55-110` |
| W11 | `POST /api/approval-delegates`、`PATCH …/deactivate` | 簽核代理人 | 一般登入者（本人）／超管（代人） | 無期限上限、無範圍、無核准；代理人能否簽核受其他規則限制（本稿未逐一驗） | 觀察 **G3**（不屬 D-K1；屬簽核授權放寬） | `routers/approval_delegates.py:56-125` |
| W12 | `POST /api/approval-queue/reassign` | 單筆待簽轉簽 | 超管 | 原因必填、與換人同交易稽核、操作者與受轉者都不可為送審人 | OK（單筆處置，非設定） | `routers/approval_queue.py:456-480` |

## 缺口說明
**G1 簽核流程四條寫入路徑（W6–W9）**
- 放寬樣態：減少／清空層級、換成權限較低的簽核人、`includeSubmitterManagerTier=false`、W8 切換套用範圍。
- 影響：立即影響之後送出的單據（報價單、開票申請憑據、出貨單、請款單、承攬商匯款與模組登記的單據類型）；寫入無原因、稽核無前後值，事後難以回溯誰把哪一層拿掉。
- 與規格的關係：`features_l1.json:13` 把「放寬簽核須經最高管理者核准流程與確認期」列為 `workflow_builder`（MS6，planned）；備忘 t55 也記為「僅 6 項鎖死、其餘做成超管選項」。現況＝尚未做，不是回歸。
- 建議（需 PM／使用者裁示，T67 候選）：
  1. 把簽核流程以「受管 kind」納入同一引擎：寫入走 `config_ledger`，放寬＝待生效＋第二人核准，收緊即時；稽核存前後值（層數、簽核人集合、旗標）。
  2. 放寬分類規則（純函式，易測）：層數減少、任一層簽核人集合變大或換成較低職級、`includeSubmitterManagerTier` true→false、範圍 獨立→統一且統一流程較寬。「無法判斷 ⇒ 放寬」（沿用 `attachment_slots._classify`／`notify_actions` 的做法，`helpers/attachment_slots.py:198-242`）。
  3. W9 舊端點：改為與 W7 共用同一個服務函式（現在是兩份複製的程式碼，行為恰好相同），之後只需修一處；或回 410 並保留 GET。
  4. 只有一位超管時沿用設定中心的降級（原因＋確認期間＋警告）。
- 必須先確認的前提：D-K1 是否延伸到流程設定；延伸則屬「資料形狀為結構、非純量」，不能直接用 `register_group` 純量欄位——需要 kind adapter 或結構化 diff（見 `def_pipeline`／`notify_actions` 的 `old_body→new_body` 分類模式）。

**G2 管銷設定（W10）**：`defaultPct` 調低 ⇒ 營業利益／獎金基數變大；目前單人即時生效。已寫在設定中心切片稿 SO-S1，建議併入 `register_group` 並標 `loosen="down"`。

**G3 簽核代理人（W11）**：任一登入者可為自己指定代理人、起訖日不限長度；若代理人可代簽高風險單，等同簽核層級的放寬。建議納入權限矩陣 PM-S4（代理語意統一、期間上限、範圍）。

**G4 單超管降級**：設定中心在只有一位超管時，放寬改為「原因＋確認期間」後生效，**沒有第二人核准**（`settings_registry.py:822-840`）。這是已記載的設計（附警告），但代表 D-K1 在單超管環境形同確認期間而已。若正式機只有一位超管，需讓使用者知道。

## 未涵蓋／未驗證
- `helpers/expense_types.py:196-220`（新增單據類型時如何決定預設走統一或獨立流程）與 def_pipeline 的 `workflow_builder` 路徑：本稿未讀完。
- `_managed_guard` 函式本體、`config_ledger.promote_due` 的排程實際觸發：只讀到契約與註解。
- 沒有檢查資料庫是否已存在繞過路徑（例如直接寫 `system_settings` 的維運腳本 `tools/`）；只掃了 `backend/` 下的 `_set_setting` 呼叫（簽核相關僅 W6–W9）。
- 前端未驗證；沒有跑任何測試。
