# 稽核：T79 凍結前四組變更（train/t79-int 73672373a 對正式機基準 55835216）（hichan-10，2026-11-12）

> 範圍：`git diff 55835216..73672373a`（155 個 commit）中的四組：① 報價單草稿併發編輯保護　② webauthn-config 404／case.access_denied 誤擋／N7 簽核中唯讀橫幅　③ versions 修改紀錄遮金額改走 `field_policy.tier_allowed`　④ 勞報單建立寫鎖洩漏。
> 方法：讀碼＋在自己的 worktree（`D:\Claude-pm\h10-audit\wt`，train 尖端）實跑：各組既有測試、**突變**（改壞一處看有沒有題轉紅）、**差異探針**（我寫的、不進 tests/，放在 `AUDIT-hichan10-t79batch.probes/`）。**沒有改任何產品程式碼**；探針與突變都在我自己的 worktree，突變後已還原。
> 行號以 73672373a 為準。全量測試我沒跑（交給整合者的凍結閘門）。

## 0. 獨立性聲明（先看這段）

| 組 | 我的角色 | 本份稽核的性質 |
|---|---|---|
| ② webauthn／case.access_denied／N7 | 沒寫、沒審 | **獨立稽核** |
| ③ versions 遮金額 | 沒寫、沒審（K 審是 hichan-11） | **獨立稽核** |
| ① 草稿併發編輯保護 | **作者**（`cd2d76bf2`／`70f97456b`／merge `6f538f3b1`；99 路由鎖稽核文件） | **作者自審，非獨立**——只當「對自己的東西再攻擊一次」，不能當 §G7-3 的獨立稽核；獨立的那份由 hichan-12 做 |
| ④ 勞報單寫鎖 | **作者**（`adde4ceb7`／merge `850f3d3e2`；K 審 hichan-9） | 同上，**作者自審，非獨立** |

## 1. 結論

- **獨立組（②③）：沒有必修。** 功能行為都成立：差異探針證明六支被放寬的唯讀端點對「案件頁本體」的放行／拒絕完全一致（8 種身分×5 端點，零差異）；N7 在三種簽核模式、當層／下一層／已簽過的簽核人、最高管理者、申請人身上都照設計鎖唯讀。
- **但有 1 個既有的金額外洩洞**（不是 T79 引入、基準就有；T79 讓 ③ 號稱「與案件頁同一條」，而案件頁自己也有這個洞）：完結精算的修改紀錄本身帶 `netProfit`／`totalActualCost`，三個出口（`/versions`、案件頁 GET、case-bundle）都原樣回給沒有金額檢視權的協作者。見 G3-F1。我分級為**建議（優先）**——因為不是迴歸；是否要在凍結前補由整合者裁。
- **有 4 題「綠燈但證明的是別件事」**（突變存活）：見各組 c 節。
- **作者自審組（①④）有 1 個必修**（我自己的測試不穩：約每 5～6 次有 1 次紅，會讓凍結閘門隨機紅）：見 §4。其餘無。

| 級別 | 項目 |
|---|---|
| 必修（測試穩定性，作者自審發現） | H10-M1（§4.1） |
| 建議 | G3-F1 修改紀錄的完結精算金額鍵未遮；G2-F1 兩支被放寬的端點沒有任何題；G3-F2 versions 遮蔽缺「看得到的人照樣看得到」正對照；G2-F2 簽核佇列預覽白名單只有靜態字串檢查 |
| 觀察 | G2-F3 N7 對「代理簽核人」的橫幅用字；G2-F4 勞報單預覽走不留稽核的 PDF 端點；G2-F5 殘留的重複 V3.41 註解；G3-F3 棘輪基準與現況；§4.3 寫鎖線索清單 |

---

## 2. 組 ②：webauthn-config 404／case.access_denied／N7（獨立稽核）

範圍 commit：`9b5b9ee29`、`a84379a42`、merge `fe6c73834`。

### a. 照規格逐條驗收

| # | 規格（commit message／CHANGELOG） | 證據 | 判定 |
|---|---|---|---|
| 1 | 公司設定頁不再以 `/api/settings/webauthn-config` 的 404 當 Passkey 開關；改問 `/api/system/webauthn-config-status`，停用時不再打 | `frontend/pages/company-profile-settings.html:1478` `loadWebauthnConfig`；`tests/test_e2e_webauthn_config_no_404_2026_11_11.py` 2 題（停用態：無任何 config 請求、無 4xx/5xx、卡片隱藏；啟用態：卡片出現、config 讀到 200）。重現：`python -m pytest tests/test_e2e_webauthn_config_no_404_2026_11_11.py -q` ⇒ 通過 | 成立（啟用態那題是正對照，證明「不打」不是「整張卡壞掉」） |
| 2 | 財務（cashier）開別人案件頁時，close-gates／PDF 版本清單／PDF 下載／材料審核摘要不再被擁有者規則靜默擋下；沒資格的人照舊 404 | `helpers/case_access.py:169,180`（`allow_read` ⇒ `row_access.visible("case", …, scope="read")`）；呼叫點 `modules/case/api/quotations.py:3092`（close-gates `scope="read"`）、`:6166`（pdf-download）、`:6233`（versions）、`:6298`（versions/{seq}/download）、`modules/case/api/material_approvals.py:95`。`tests/test_case_read_rule_denials_2026_11_11.py` 5 題 | 成立；探針見 b |
| 3 | `case.access_denied` 的 audit detail 補 `method／path／role／case_manage`（只加鍵，reason 不變） | `db.py` `set_request_ctx／get_request_ctx`；`main.py:571`；`helpers/case_access.py:37` `_audit_case_denial`（在呼叫端執行緒算好再交給背景緒）；題 `test_denial_audit_records_endpoint_and_role` | 成立。`user_has_module(…,"case_manage")` 只解析使用者 JSON、不碰 DB（WAL 模式下也不會被寫鎖卡住） |
| 4 | 簽核佇列「預覽」改白名單：勞報單走 `/api/payslips`；無 PDF 端點的類型不再落到報價單端點 | `frontend/pages/approval-queue.html:1312`（payslip 分支）、`:1379`（`hasPreview`）；`/api/payslips/{slip_no}/pdf-download` 存在（`modules/payroll/api/payslips.py:686`，要 `payroll.payslip.export`） | 成立，但**只有靜態字串題**——見 c |
| 5 | N7（V3.42，使用者確認）：待審核／簽核中，非簽核人整張唯讀＋橫幅「僅簽核人可編輯」，簽核人本人不變 | `frontend/pages/quotation-form.html:4078`（`isApproverLocked`）、`:4082`（`pendingReadOnlyBanner`）、`:1112`（橫幅）；`autoSave` 最上面的早退擋住必 403 的 PUT。`tests/test_e2e_pending_readonly_for_non_approvers_2026_11_11.py` 3 題 | 成立；探針見 b |

基準實跑（train 尖端，5 個檔）：`22 passed`。

### b. 反向控制（對方不在時／失敗路徑／回滾路徑）

**差異探針 `probe_g2`**：同一張別人業務的已成案案件，9 種身分各打 5 支端點，與案件頁本體（`GET /api/quotations/{no}`）比「放行／404」：

```
who               page  close-gates  mat-approvals  versions  pdf  pdf-internal
collab            200   200          200            200       200  403(成本版：無金額權)
fin_cashier+cm    200   200          200            200       200  200
fin_cashier_only  200   200          200            200       200  200
engineer_cm       404   404          404            404       404  404
other_sales       404   404          404            404       404  404
admin / superadmin 200  全 200
MISMATCH vs page: []
```
⇒ 放寬的範圍＝案件頁本體，不寬不嚴；內部版（含成本）PDF 仍被金額權擋住（協作者 403）。重現：把 `AUDIT-hichan10-t79batch.probes/probe_g2.py.txt` 複製成 `backend/tests/test_zz_audit_probe_h10_g2.py`，`python -m pytest tests/test_zz_audit_probe_h10_g2.py -q -s`（不要 commit）。

**「對方不在時」**：案件模組不在 ⇒ `case_access_allowed` 開頭就 `return False`（`helpers/case_access.py:173-174`，`allow_read`〔:180〕排在它後面，不能繞過）。

**N7 探針 `probe_n7`**（真 Chromium）：

| 身分 | 橫幅 | 欄位唯讀 | 簽核鈕 |
|---|---|---|---|
| 最高管理者（非簽核人），簽核模式 0／1／2 | 有 | 是 | 無 |
| 下一層簽核人（還沒輪到） | 有 | 是 | 無 |
| 已簽過的簽核人 | 有 | 是 | 無 |
| 申請人 | 有（收回草稿鈕在） | 是 | 無（既有測試） |
| 當層簽核人 | 無 | 是（V3.39 本來就鎖） | 有（既有測試） |

**突變（改壞一處，看既有題有沒有轉紅）**——目標檔：`test_case_read_rule_denials` ＋ `test_doc_versions`：

| 突變 | 結果 |
|---|---|
| M5 versions 拿掉 `allow_read` | 紅（cashier 題） |
| M7 close-gates 改回擁有者規則 | 紅 |
| M8 材料審核摘要改回擁有者規則 | 紅 |
| M9 拿掉 `set_request_ctx` | 紅（audit 診斷鍵題） |
| **M6 pdf-download 拿掉 `allow_read`** | **綠（沒有任何題守）** |

### c. 假綠燈

- **G2-F1（建議）** `pdf-download`（`quotations.py:6166`）與 `versions/{seq}/download`（`:6298`）也被放寬了，但 `READ_ONLY_ENDPOINTS`（`tests/test_case_read_rule_denials_2026_11_11.py` `:74`）只列 3 支——這兩支既沒有「財務放行」題，也沒有「無資格者 404」題。M6 突變存活即證明。建議把這兩支加進該清單（下載版本需要先有一筆 docVersions，PDF 端點用 `internal=false` 即可，只驗權限不驗內容）。
- **G2-F2（建議）** `tests/test_frontend_ops_guards_2026_11_11.py::test_approval_queue_preview_is_whitelisted…` 只讀原始碼字串。突變：把 `hasPreview` 的 `.includes(item.type)` 改成 `.includes(item.typo)`（**預覽鈕對所有類型都不再出現**）——2 題仍綠，因為它只抽取函式本體裡被引號圍起來的類型名。這題證明「字串在」，不證明「預覽鈕對勞報單真的出現、點了打到 `/api/payslips/…`」。建議補一題 e2e（塞一筆待審核勞報單進佇列，點預覽，斷言請求網址）；或至少把靜態題改成執行 `hasPreview` 本體。
- N7 的靜態題（同檔 `test_quotation_form_locks_every_non_approver…`）同樣是字串題，但 N7 另有 3 題 e2e 守行為，所以那題只是輔助，不算假綠。
- webauthn 兩題：停用態斷言「無 config 請求且無 4xx」，啟用態斷言「卡片出現、config 200」——**兩邊都有**，不是假綠。

### d. 改善建議

| 級別 | 項目 |
|---|---|
| 建議 | G2-F1、G2-F2（見 c） |
| 觀察 | **G2-F3** `isCurrentTierApprover()`（`quotation-form.html:3186`）只比 `firstPending.username`，不認代理簽核人（後端 `check_approve_permission` 認）。N7 之後代理人也會看到「僅簽核人可編輯」橫幅（並唯讀）——表單本來就沒給代理人簽核鈕（同一個函式決定），所以行為一致，只是橫幅用字對代理人略不準。不影響功能。 |
| 觀察 | **G2-F4** 簽核佇列的勞報單預覽現在會打 `GET /api/payslips/{no}/pdf-download`（`payslips.py:686`）：①要 `payroll.payslip.export`，簽核鏈上沒有這個權限的人會看到預覽鈕、點了得 403 提示（修之前是 404，不是新退步）；②該端點不寫稽核，最高管理者看到完整收款帳號（非最高管理者遮成末四碼），與佇列詳情「身分證／收款帳號只經 `approval-reveal`、每次檢視留稽核」（`payslip_approval.py` 2026-10-07 裁示）是兩套規則。payslips 頁自己的預覽早就是這個端點，所以不是 T79 新開的口——但值得讓產品端知道有兩套。 |
| 觀察 | **G2-F5** `quotation-form.html:2558` 殘留一行 `V3.41（…ops）…自動存檔不再送 PUT…改提醒一次`——那是 N7 之前被換掉的作法（toast 提醒），N7 已把它改成 V3.42（:2566）。表單版本清單裡有兩條 V3.41、且第一條描述的行為已不存在。純註解，不影響版本守門（`test_form_version_bumped` 綠）。 |

---

## 3. 組 ③：versions 修改紀錄遮金額改走 `field_policy.tier_allowed`（獨立稽核）

範圍 commit：`b9b508092`、merge `eca7086c9`；遮蔽本身是更早的 `826e7bbb3`（K 審 N1）。

### a. 照規格逐條驗收

| # | 規格 | 證據 | 判定 |
|---|---|---|---|
| 1 | 行為不變：`quote_money_visible` 直接呼叫 ⇒ `_tier_allowed('quote_money', user)` | `helpers/field_policy.py:32-33`：`tier_allowed("quote_money")` 直接 `return bool(FM.quote_money_visible(user))`；`helpers/financial_mask.py:44-50` ⇒ **同一支函式、逐位元等價** | 成立 |
| 2 | t65 出口棘輪基準 6→5，不調基準 | `backend/tests/platform/field_policy_exits_baseline.json:14` `"modules/case/api/quotations.py": 5`（與正式機基準相比該檔**沒有變動**：`git diff 55835216..73672373a -- …baseline.json` 為空）；實跑 `tests/platform/test_field_policy_exits_t65.py` ⇒ `5 passed`（含 `test_baseline_is_not_stale`，現況 5＝基準 5，沒有空隙） | 成立 |
| 3 | 沒有 `quote_money` 的帳號，修改紀錄裡金額／毛利欄位值一律「—」；沒有 `finance_money` 的帳號，修改紀錄的自由文字理由被拿掉 | `modules/case/api/quotations.py:6259-6267` | 成立（見 b、c） |

### b. 反向控制

探針 `probe_g3`（協作者工程師＝無金額權；財務＝有金額權），同一份帶三種紀錄的 editHistory：

- 協作者：`含稅總額` 1000→2000 ⇒ `—/—`；`備註` a→b 照常；`reason`（重開理由）被拿掉 ✔
- 財務：金額與理由都在 ✔（**這個方向探針有驗；repo 的題沒有**，見 c）

突變（目標檔同組 ②）：

| 突變 | 結果 |
|---|---|
| M1 versions 永遠不遮金額 | 紅（協作者題） |
| **M2 versions 永遠遮金額（連看得到的人也遮）** | **綠** |
| **M3 versions 永遠不拿掉理由** | **綠** |
| **M4 versions 永遠拿掉理由（連有財務檢視權的人也拿）** | **綠** |

### c. 假綠燈與洞

- **G3-F1（建議，優先）完結精算的修改紀錄金額鍵沒遮。** `modules/case/api/settlement_api.py:145`：完結精算寫的 editHistory 項目帶頂層 `netProfit`、`totalActualCost`（基準 55835216 就有）。`helpers/financial_mask.py:67-73 strip_history_reasons` 只拿掉 `reason`；`:132-136` 與 `quotations.py:6263-6267` 只遮 `changes[*]` 裡欄位名在 `HISTORY_MONEY_FIELDS` 的值。結果：沒有金額檢視權的協作者（`engineer`＋`case_manage`，被指派到該案）打：
  - `GET /api/quotations/{no}/versions` ⇒ `history[1].netProfit=123456、totalActualCost=654321`
  - `GET /api/quotations/{no}` ⇒ `data.editHistory[1].netProfit／totalActualCost`
  - `GET /api/quotations/{no}/case-bundle` ⇒ `quotation.data.editHistory[1]…`
  重現：`probe_g3.py.txt`（兩題）。**不是 T79 引入、基準就如此**；T79 的 ③ 沒讓它變差，但也沒補上，而 ③ 的註解說「與案件頁 GET 同一條」——同一條就同樣有洞。建議：在 `strip_history_reasons` 旁（或兩個遮蔽點）一併 `pop("netProfit")／pop("totalActualCost")`（對沒有 `quote_money`／`finance_money` 的人），並補一題；順手把這兩個鍵登進 `field_catalog`。是否在 T79 凍結前補，由整合者裁；我不認為它擋凍結（非迴歸）。
- **G3-F2（建議）** 見 b 的 M2／M3／M4：repo 只有「無金額權的人被遮」這一個方向的題，沒有「有金額權／有財務檢視權的人照樣看得到」的題，也完全沒有理由被拿掉的題。這使得把遮蔽改成「一律遮」或「一律不拿理由」都會綠。建議補三題：財務／業務擁有者看得到金額（`含稅總額` 1000→2000 原樣）；有財務檢視權者的 `reason` 保留；無財務檢視權者的 `reason` 被拿掉（協作者那題順便斷言）。

### d. 改善建議

| 級別 | 項目 |
|---|---|
| 建議 | G3-F1、G3-F2 |
| 觀察 | **G3-F3** 遮蔽欄位清單來自 `field_catalog.history_labels()`＝`{含稅總額, 未稅金額, 淨利率, 營業利益率, 直接毛利率, 管銷分攤比率}`（執行期確認），與 `_TRACKED_QUOTE_FIELDS`（`quotations.py:111-136`）的金額類欄位逐一對上；新增追蹤欄位時要記得同步登 `field_catalog`——目前沒有守門把兩邊綁在一起（建議在 T80 補一題：`_TRACKED_QUOTE_FIELDS` 裡「看起來像金額／比率」的標籤都在 `history_labels()`）。 |

---

## 4. 組 ① 與 ④：作者自審（**非獨立**；獨立稽核另由 hichan-12 做）

### 4.1 組 ①　草稿併發編輯保護（V3.41）

我重跑了 `tests/test_e2e_draft_edit_conflict_2026_11_11.py`（train 尖端）：**間歇性紅**。

**H10-M1（必修，測試穩定性）** `test_failed_reload_keeps_banner_and_dirty_and_other_loads_clear_the_banner` 在 `tests/test_e2e_draft_edit_conflict_2026_11_11.py:227` 會隨機失敗：`assert not page_a.is_visible('[data-testid="qf-save-conflict"]')` 緊接在 `wait_for_function(…!saveConflictBanner…)` 之後，輸給 Alpine `x-if`／`x-show` 的一個影格（橫幅還沒從 DOM 拿掉）。同型的 `:109` 風險相同。
- 重現：`for i in 1 2 3 4 5 6; do python -m pytest tests/test_e2e_draft_edit_conflict_2026_11_11.py -q -k "failed_reload or banner"; done`——我這邊約 14 次執行紅了 3 次（單獨跑某一題 3/3 綠、整檔 1/3 紅、`-k` 迴圈第 5 次紅）。不是產品 bug（橫幅最終會消失），是題目寫法。
- 後果：凍結閘門會隨機紅；`known_flakes` 政策是保持空，所以要修題而不是登記。
- 修法（一行一處）：改成 `page_a.wait_for_selector('[data-testid="qf-save-conflict"]', state="hidden", timeout=5000)`（或 `locator.wait_for(state="hidden")`）。**我沒改**（依你的要求）；你說一聲我 5 分鐘內改好、單獨重跑迴圈驗證。

其他自審結論：
- 行為仍成立（該檔其餘 6 題＋勞報單／寫鎖 11 題全綠，共 17 綠 1 隨機紅）；橫幅只在「既有單 PUT 的 409」才出、新單 POST 的 409 不出、載入最新版失敗不清橫幅／isDirty、`loadQuote()` 成功才清——各有題。
- 已知、已記錄、本次**不改**：`expectedUpdatedAt` 仍是選填（舊呼叫端與非表單呼叫端仍是後寫覆蓋；強制化已定分階段）；`material-orders` 的 PATCH 沒有樂觀鎖（另案）。見 `docs/platform/WRITE-ENDPOINT-LOCK-AUDIT-T79.md`。

### 4.2 組 ④　勞報單建立寫鎖洩漏

- `modules/payroll/tests/test_payslip_create_releases_write_lock_on_error_2026_11_11.py` 與 `tests/test_write_lock_released_on_error_2026_09_25.py` 在尖端全綠。
- 同類檢查：`modules/payroll/api/payslips.py` 其餘的 `BEGIN IMMEDIATE`（`delete_payslip`:519）與 `payslip_approval.py`（:130、:223、:291）都有 `try/finally: conn.close()`——close 會丟棄未提交交易，不洩漏。`create_payslip`（:330）與另一處（:443）走 `write_txn`。

### 4.3 同類洞的線索清單（**未驗證**，給 T80）

我用 AST 掃全 backend（排除 tests）：函式內有 `begin_write(`／`BEGIN IMMEDIATE`，卻沒有 `try/finally` 也沒有 `write_txn` 的函式共 **37 個**（清單可重現：見下）。這是啟發式——很多是呼叫端負責關連線，或用 `except BaseException:` 手動 rollback＋close（我抽查的 `delete_quotation`、`review_edit_quotation` 都是後者，**不是洩漏**），所以多半是假陽性。與 hichan-9 先前那份線索（case_action_items.approve_case_action_item、quotations.review_edit_quotation、netplan.create_network_plan、subcontract update_contractor、supply inventory/suppliers、routers auth／customers／org_structure／module_versions）有交集。建議 T80 針對「例外路徑會不會留著寫鎖」另開一張票逐一確認，而不是現在動。

```
core/definitions.py        save_draft submit_draft decide_submitted publish publish_direct restore
helpers/list_view_prefs.py save_page_size
modules/accounting        ledger/requests._load_pending ledger/tax401.generate_settlement voucher.post_voucher
modules/case              api/quotation_stages.apply_stage_template api/quotations(_load_material_item _load_payment_item
                          _sync_stages_to_json delete_quotation review_edit_quotation) material_payment_cashier(3) payables.set_planned_pay_date
modules/permmatrix/service  8 個函式；modules/recyclebin/service  delete/purge/restore
modules/subcontract/api/contractor_vouchers.set_planned_pay_date；modules/supply/api/shipping_notes.delete_shipping_note
tools/duty_roles_rollback.apply_rollback；core/txn.py（本體）
```
（掃描腳本：`ast.walk` 找函式內 `begin_write()`／`execute("BEGIN IMMEDIATE")`，再排除含 `Try.finalbody` 或 `write_txn` 的函式；約 40 行，需要的話我附上。）

---

## 5. 重現索引

| 要做什麼 | 指令（在 `backend/` 下、用專案 venv） |
|---|---|
| 組 ②③ 既有題基準 | `python -m pytest tests/test_case_read_rule_denials_2026_11_11.py tests/test_e2e_webauthn_config_no_404_2026_11_11.py tests/test_frontend_ops_guards_2026_11_11.py tests/test_form_version_bumped_2026_09_24.py tests/test_e2e_pending_readonly_for_non_approvers_2026_11_11.py -q`（22 passed） |
| 棘輪 | `python -m pytest tests/platform/test_field_policy_exits_t65.py -q`（5 passed） |
| 探針（複製成 `tests/test_zz_audit_probe_h10_*.py` 後 `-s`，不要 commit） | `probe_g2.py.txt`、`probe_g3.py.txt`、`probe_n7.py.txt` |
| 突變 | `AUDIT-hichan10-t79batch.probes/mut.sh.txt`（把 `<file>` 的某字串換掉、跑指定測試、還原） |
| H10-M1 | 見 §4.1 的迴圈 |

## 6. 關閉紀錄

（group1 獨立稽核者 hichan-12，PLAYBOOK §E-6）

- ✅ H10-M1 關閉（08a641492）——`tests/test_e2e_draft_edit_conflict_2026_11_11.py` 的 :109／:227 改 `wait_for_selector(…, state="hidden")`（:223 補 `state="visible"`），修在 ad695f661、已併入 train（merge 08a641492）。複驗：該檔 5 次整檔連跑各 7 passed；程式只改測試、產品碼未動；剩餘的 `is_visible()` 立即斷言（:90、:94、:116、:208）都是「橫幅尚未出現／已確定消失」的負向斷言，晚一個影格只會假綠、不會隨機紅。
