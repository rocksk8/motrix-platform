# 一條龍：開工前清單實測結果

> 2026-11-13，hichan-1。基底 T81（`adc6bd58d`）＋ `feat/onepipe-p0-p1`（程式讀碼為主；每項附檔案與行號，行號為本基底）。
> 標註：**已驗**＝讀過程式並對過資料欄位；**未實測**＝沒有開瀏覽器逐項操作。

## 1a 材料卡到貨日是否隨「確認到貨」同步？ → **不同步（兩個獨立欄位）**【已驗】

| 欄位 | 在哪 | 誰寫 |
|---|---|---|
| `case_material_approvals.received_on`（確認到貨） | 材料申請（財務分頁） | `material_approval.record_receipt`（`moReceive`，只寫這張表） |
| `materialOrders[].poLink.arrivedOn`（材料卡到貨日） | 材料卡（執行管理→材料申請） | `material_recognize.py` 約 209–223 行：**只在用戶端送來 `arrivedOn` 且勾「已到料」時**寫 |

- 全庫 grep `arrivedOn`：沒有任何程式把 `received_on` 複製到 `poLink.arrivedOn`。
- 兩者的**關係**是「前置條件」而非同步：`material_guard.py` 約 399 行 `flag=="arrived" and not row["received_on"]` ⇒ 駁回「請先在材料申請上確認到貨」。即**必須先確認到貨，才能勾已到料**；但勾的時候到貨日要使用者再填一次（認列採購單的卡）。
- 後果：同一批料可能出現「確認到貨 11/10」「材料卡到貨日 11/12」兩個日期，且沒有任何畫面把兩者並排。
- **對一條龍的意義**：P1' 時間軸「到貨格」以 `received_on` 為準（已是這樣做的）；P2 一站式到貨若要「一次填、兩邊都寫」，須走既有閘（`material_guard`）而不是直接改 `poLink`。**建議**：P2 才處理，P0／P1 不動。

## 1b 專案報告「叫料管控」欄位是否空白？ → **是，三欄固定空白**【已驗】

- 報表：`pdf_gen.py` 3130–3137 讀 `caseRecord.materials[]` 的 `name／spec／qty／status／eta`，畫面「二、材料申請」表（3242–3249）。
- 材料卡實際建立時只有 `{id, name, model, qty, unit, ordered, arrived, devices, note}`（`case-management-exec.js:1076 addMaterial`），**沒有 `spec`、`status`、`eta`**；前端與後端也沒有任何地方寫這三個鍵。
- 結果：PDF 的「規格」欄永遠空白、「狀態」「預計到貨」永遠顯示「—」；只有「料件」「數量」有值。同時該報表**完全沒讀** `materialOrders[]`（真正有核准流程的材料申請）與 `ordered／arrived` 旗標。
- 附帶：報表標題已是「材料申請」，但程式／註解／docstring 多處仍稱「叫料管控」（`quotations.py` 4609、4626、4690、6467）；用語統一屬 P0 另案，不在本批。
- **建議**：不在 P0／P1 修。P1' 時間軸上線後，把報表改讀同一份「材料流程資料」（`stock.case_summary` 的材料格）即可一次解掉；先記為 P2 之後的清理項，避免報表與畫面兩套口徑。

## 1c 預設「工務」角色看不到支出申請？ → **案件頁分頁看不到（其實只有財務角色與最高管理者看得到）；API 看得到有限資料**【已驗】

「工務」＝帳號角色 `engineer`（預設模組見 `conftest._ROLE_DEFAULT_MODULES`：`dashboard／case_manage／project_approve_eng／equipment／work_log／daily_task／netplan`；**沒有 `financial_view`、`expense_forms`**）。

- 前端：案件頁「支出」分頁 `x-show="canSeeFinancial() && tShown('xexp')"`（`case-management.html:664、1580`）；`canSeeFinancial()`＝`canFinanceRole()`＝**只有 superadmin 與「財務」角色**（`case-management-core.js:79–82`；第42班起 admin／sales 直通與 `financial_view` 勾選都拿掉；後端 `has_finance_access`／`can_see_financial` 同規則）。**不只 engineer——admin、sales 也看不到這個分頁**；engineer 預設當然也看不到，連直達 `?tab=xexp` 也會被 `case-management-close.js:19` 導回 `biz`。
- 後端：`list_extra_expenses`（`case_extra_expenses.py:385`）不擋 engineer，但 `can_see_financial` 為否時，舊式列（`kind=''`）只回「自己建立／自己簽核」的；**費用單據（請購單等，`kind≠''`）會列出但金額、明細、收款人整列遮蔽**（`_amount_viewer`＋`_mask_row`），**申請人本人與本單簽核人例外看得到**。
- 另一個入口：獨立頁 `payment-request.html`（側欄「支出申請」）沒有 `financial_view` 門檻，工務可以從這裡開請購單；只是開完回到案件頁看不到自己的單。
- **結論**：推測成立，但要換個說法——不是「工務看不到」，而是「除財務與最高管理者外**所有人**在案件頁都看不到支出分頁」；請購單**可以開、自己的單看得到金額**，別人的單只看到狀態。
- **對一條龍的意義**：P0a「開請購單」連結對工務可用（走獨立頁）；P1' 時間軸不顯示金額（已是），不受影響；P5a 設計工務對請購單的可視範圍時，沿用 `_amount_viewer` 的「申請人／簽核人／財務角色／最高管理者」規則，不另立。

## 2 `case_deadlines.py` 去重與節流 → **有去重、無節流；有三個要注意的洞**【已驗】

| 項目 | 現況 |
|---|---|
| 執行機制 | 由 L1 `daily.check` 提供者每日跑一次（模組 docstring） |
| 階段到期（`_check_case_stage_deadline`） | 只在**到期前 3 天**與**到期當天**各一次。去重鍵 `casestage_notif.{案號}.{階段id}.{帳號}.{3d｜deadline}` 寫進 `system_settings`；**先寫鍵再發送**（發送失敗不會重試） |
| 部門主管通知 | 跟著每位負責人各發一則（同階段三位負責人、同一主管 ⇒ 主管一天收三則） |
| 專案逾期（`_check_case_project_timeline_deadline`） | 每 7 天一次（桶＝逾期天數 ÷ 7），鍵 `caseproj_notif.*`，**每次掃描會修剪**不再需要的鍵 |
| 保固（`_check_warranty_expiry`） | 每台設備 × 門檻（預設 7／30 天）各一次 |
| **洞 1** | `casestage_notif.*` **沒有任何修剪**（grep 全庫只有寫入），階段數 × 負責人數 × 2 只增不減；同檔 `caseproj_notif` 的 docstring 已記載這種模式曾讓 `module_versions` 長到 626,725 列 |
| **洞 2** | 沒有「同一人同一天」彙整：一人同日有 N 個階段到期＝ N 則站內通知＋ N 封信 |
| **洞 3** | 先寫鍵再發送、且發送在 daemon thread ⇒ 程式中途被關閉會**永遠漏發**，沒有補發 |

- **對一條龍的意義（D11 通知「下一個人」，P6）**：新通知**不得**照抄階段到期的寫法。要求：
  1. 去重鍵放獨立前綴（如 `onepipe_notif.*`），並在同一支掃描尾端做修剪（照 `_prune_case_project_guard_keys`）；
  2. 同一收件人同日多筆 ⇒ 一則彙整（摘要列數），不逐筆發；
  3. 發送成功後再寫鍵，或寫鍵與送出同交易；
  4. 預設只發站內通知，信件走 `helpers/mail_types.py` 的註冊型別，讓使用者能在「信件與通知收件設定」關掉。
- 洞 1～3 是**既有行為**，不屬本專案範圍；僅記錄，建議由 PM 決定是否另開票（洞 1 影響最大、修法最小）。

## 3 請購單對單價欄的權限 → **沒有「欄位級」權限；權限在「整張單據」層**【已驗】

- 表單定義：`helpers/expense_types.py:103–108`——`qty` 與 `unitCost` **必須成對出現**（只有 `qty` 沒有 `unitCost` 的表單定義會被驗證擋下），且兩者必為數字欄；金額＝`round_half_up(qty × unitCost)`（302–325）。
- 可視：整張單據用 `_amount_viewer`（`case_extra_expenses.py:277`）判斷——財務存取（`has_finance_access`＝superadmin 與財務角色）／申請人（建立者或 `data.applicant`）／本單簽核人（含變更簽核鏈）；**其他人（含 admin、sales）只看到狀態**（函式 docstring 仍寫「管理員以上」，是第42班前的舊字句，以程式為準），金額、明細、資料、收款人、付款資訊一律遮蔽（`_mask_row`）。
- 「從請購單帶入」挑選器（`purchase_items.pr_lines_view`）：`unitCost` 只在 `can_see_financial(user)` 為真時回傳（`case_extra_expenses.py:476、493`、`material_links.py:32、45`）。
- **結論**：「工務填請購單時看不到單價」**做不到**——申請人永遠看得到自己填的單價；反過來「別人的請購單單價不外洩」**已經做到**。若老闆要「現場人員只填品名／數量、不碰價格」，需要新增「欄位可由申請人隱藏」的表單規則，且要放寬 `qty／unitCost` 成對的驗證——這是**表單定義層的新功能**，不在目前任一批次（含 P5a）內，需另行決策。
- 對照 P1'：時間軸不回任何金額（旗標開／關的 e2e 都驗過 `98765／424242／400000` 不出現），與本節一致。

## 彙總（給 PM）

| 項 | 結論 | 影響批次 |
|---|---|---|
| 1a | 不同步，兩欄位獨立；「確認到貨」是「已到料」的前置條件 | P2 處理；P0／P1 不動 |
| 1b | 報表三欄固定空白，且沒讀 `materialOrders` | 記清理項；P1' 後一次解 |
| 1c | 工務案件頁看不到支出分頁；請購單可開、自己的單看得到金額 | P0a 可用；P5a 沿用 `_amount_viewer` |
| 2 | 有去重、無節流、`casestage_notif.*` 不修剪、不彙整 | P6 新通知需照 §2 四點；洞 1～3 是否另開票待裁 |
| 3 | 無欄位級單價權限；「工務看不到單價」做不到 | 若要做＝新功能，需另案決策 |
| 4 | 點擊基準已凍結 `ONEPIPE-CLICK-BASELINE.md`（S1～S7） | 各批驗收引用；S3 起點不同要同起點比 |
