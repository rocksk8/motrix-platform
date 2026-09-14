# 模組權限盤點：狀態、對接、邏輯（2026-09-13）

> 範圍：「模組」這個機制本身——`users.modules` 有哪些值、側欄依它顯示什麼、
> 後端依它擋什麼，以及三者對不對得起來。
> 互補文件：`MOTRIX-ERP-QUICK.md` §3.4（角色與模組）、§9（前端規範）、
> `WEEKLY-AUDIT-2026-09-07_2026-09-10.md`（依時間軸的缺陷索引）。
>
> **本次已修的在 §3，沒修、留給人決策的在 §4。**

---

## §1 · 機制現況

| 層 | 現況 |
|---|---|
| 全域門檻 | `main.py::auth_middleware`：`/api/*` 除 **10 條白名單**（登入流程、`ping`、`version`、`deployed-version`、`webauthn-config-status`）外一律要有效 session；閒置逾時 admin+ 2h／其餘 8h |
| 可授權模組 | `users.html` 權限目錄 **35 個 key**（本次補回 `project_manage` 後）。同一頁下方另有 40 個通知偏好 key，那是不同的東西 |
| 側欄讀取 | **23 個**，形式一律是 `mods.indexOf(x) >= 0 \|\| ad`（admin+ 幾乎全部直通） |
| 後端讀取 | **33 個**（稽核前是 19，其中 7 個還是 `*_guide_edit`）。仍沒讀的只剩 `dashboard`／`inventory` 兩類情境，理由見 §4 |
| 實際授權主力 | **四層**：全域 session → 模組（`require_any_module`）→ 擁有者（`guard_case_access`）→ 角色與簽核流程。稽核前只有第一層與第四層 |
| 前端頁面守門 | 稽核前**沒有**（`auth-guard.js` 只驗 session）；2026-09-13 起沿用側欄自己的顯示條件就地擋下，見 §3.10 ③ |

> 「沒有模組＝側欄看不到」這件事本身不是漏洞，但**不能當成權限**。任何真的不該被
> 看到的資料，必須在端點上擋。

---

## §2 · 盤點方式（可重跑）

三份清單都是從原始碼解析出來的，不是人工抄的：

| 來源 | 取法 |
|---|---|
| 權限目錄 | `frontend/pages/users.html` 的 `{key:…,label:…,group:…}`（切在通知偏好清單之前） |
| 側欄 | `frontend/static/sidebar.js` 的 `mods.indexOf('…')` |
| 後端 | `user_has_module(user,'…')`／`module='…'`／`'…' in mods`／`_EDIT_MODULE = '…'` |
| 角色樣板 | `users.html::ROLE_MODULES`、`backend/helpers/auth.py::_SUPERADMIN_MODULES` |
| 實際持有 | 開發機 db 副本 `backend/motrix_erp.db`（2026-09-12 01:16 那份） |

同一組判斷已固化成 `backend/tests/test_module_keys_consistency_2026_09_13.py`，
每次跑測試都會重算，不需要再手動盤一次。

⚠️ **持有人數是開發機副本的數字**。正式機可能不同——那需要讀正式機（唯讀查詢
即可），本次沒有做。

---

## §3 · 這次修掉的

### 3.1 🔴 精算 IDOR（唯一的「寫入」缺口）

`GET/PUT /api/quotations/{quote_no}/settlement` 與 `GET …/finance-summary` 原本
只呼叫 `_require_user()`。`quote_no` 是可列舉的（`MQ-YYYYMM-NNN`），所以**任何已
登入帳號**——包含 `viewer` 與 `automation` 服務帳號——都能讀、甚至覆寫**任何**
案件的成本精算；只有 `status == "finalized"` 之後才收斂成「僅 superadmin」。

這跟 2026-08-24 修掉的報價單 IDOR 是同一種洞，只是漏在這三支。修法沿用既有慣例
`helpers/quotations.py::_check_quotation_owner()`（admin+ 直通，否則必須是該案業務
或 `assigned_user_ids` 裡的協作者），與額外支出、叫料、單筆報價單完全一致。

測試：`test_module_permission_fixes_2026_09_13.py` 四題——外人讀 403／外人寫 403
**且資料真的沒被改到**（觀測點放在下游的 `data_json`，不是只看回傳碼）／業務、被
指派的工程師、admin 三種人照常可用。

### 3.2 🟠 `reports`／`finance` 模組形同虛設

權限目錄給得出「營運報表」，側欄依 `cRpt || cCash || cFi` 顯示入口，但 `reports.py`
的 11 支端點**全部只認 `admin+`**——勾給業務的結果是：看得到選單、點進去每一支
API 都 403，畫面上只有一片載入失敗。

修法：新增 `_require_reports_access()`（admin+ 或 `reports` 或 `finance`），取代那
11 處重複的 role 判斷。作法比照同一個財務區既有的
`routers/cashier.py::_require_view_access()`（admin+ 或 `cashier` 或 `finance`）。
`bank-reconcile` 維持 admin+／`cashier` 不變——那是對帳**動作**，不是報表查閱。

> 這是「讓後端認得目錄一直在賣的東西」，不是放寬：目前 `reports`／`finance` 的
> 持有者全部都是 admin+，實際可存取範圍**沒有任何變化**。

### 3.3 🔴 `project_manage`：後端在擋、UI 卻發不出來

`routers/material_orders.py:95` 用 `project_manage` 擋「修改叫料」，但這個 key 在
2026-08-26（專案管理併入案件管理）從權限目錄移除了。後果：**新建帳號永遠拿不到
這個權限**，一改叫料就 403，而管理員在畫面上找不到任何地方可以勾。目前持有者全靠
歷史殘值（開發機副本 9 個，含 2 個非 admin）。

修法：把 key 補回目錄，標籤改成它今天實際在管的事——**「案件叫料－修改」**。
刻意不改 key 名稱：改名要跑 migration，而且那 9 個帳號會在部署的瞬間失去權限。

### 3.4 🟠 網路架構規劃書：前端放行 admin、後端不放行

`network-plans.html` 的 `canEdit` 含 `role === 'admin'`，後端是
`require_superadmin=True, module='netplan_edit'`。而 `netplan_edit` **目前 0 人持有**
→ 四個 admin 帳號看得到「新增規劃書」，按下去必定 403。

修法：前端改成 `superadmin || netplan_edit`，與後端逐字對齊，也跟七個選型導覽的
`canEdit = superadmin || *_guide_edit` 同一個慣例（那七個前後端本來就對得很齊，
是這次盤點中唯一完全沒問題的一組，值得當範本）。要讓某個 admin 能編，去使用者管理
勾「網路架構規劃書－新增修改刪除」。

### 3.5 🟡 死 key `sales`／`_SUPERADMIN_MODULES` 不同步

- `sales` 只存在於角色樣板與 `_SUPERADMIN_MODULES`，**側欄、後端、其他前端都沒有
  任何地方讀它**。已從兩份樣板移除；既有帳號身上那幾筆不動（沒有任何行為依賴它，
  為它跑一次 migration 不划算）。
- `_SUPERADMIN_MODULES`（首次安裝建立的管理員）缺 `case_manage`／`reports`／
  `cashier`／`work_log`／`daily_task` 與七個選型導覽，卻多一個 `sales`。已改成
  前端 superadmin 樣板的鏡像，並由測試釘住兩邊相等。

### 3.6 🟡 `finance` 模組的紅點永遠不會亮

後端 `_MODULE_ACTION_PREFIXES['finance']` 一直在算 `payment.`／`sales_order.`／
`settlement.` 三種異動的數量，但前端要顯示它的 `sb-mod-finance`／
`sb-mod-sales-orders` 兩個元素，隨著應收帳款／銷售訂單兩個側欄項目在 2026-08-31
（`87e16cb`）退役後就再也沒有被渲染過——數字算了一整個月沒有人看得到。

修法：紅點掛回內容現在所在的「營運報表」項目（`sidebar.js` 與 `notif.js` 兩張表
一起改，它們本來就互為鏡像）。

### 3.7 🟡 `sales-orders.html` 退役只做一半

`87e16cb`「退役重複頁面（應收帳款/銷售訂單）」把 `receivables.html` 改成導向頁，
**但這頁只移除了側欄連結**：216 行的完整頁面留著、API 也還活著，舊書籤進得去，
顯示全部已成案／已結案的金額與毛利率，而且從那天起就沒人維護（例如 2026-09-12
「已收款改看收款日期」的口徑調整只改了營運報表，這頁仍是舊邏輯）。

修法：比照 `receivables.html` 改成導向頁（導向案件管理），不刪檔、不回 404。

> 附帶：這頁本來也在同日深色模式修正的 15 頁名單裡，改成導向頁後已沒有側欄，
> 已從 `test_e2e_dark_mode_sidebar_2026_09_13.py` 的量測清單移除——留著的話測試會
> 在導向後量到案件管理的側欄，然後綠燈給一個根本沒測到的頁面。


### 3.8 🔴 第二輪（使用者裁示後）：其餘每案 IDOR、`financial_view`、模組後端檢查

§4 原本列的五項待決策，使用者於同日裁示：①其餘 IDOR 一起收 ②viewer／engineer
不該看到金額 ③`/api/sales-orders` 加模組檢查 ④16 個模組逐一補後端檢查
⑤`cashier` 模組保留。實作如下。

**① 其餘每案端點的擁有者檢查（28 支）**

新增共用守門 `routers/quotations.py::_guard_case()`，套用於案件階段（11）、拜訪
紀錄、動態更新、案件鎖定/解鎖、協作者指派、簽回檔案、款項與叫料附件、匯出紀錄、
三支 PDF。規則同既有的 `_check_quotation_owner()`。兩個例外：

- **三支 PDF 加 `allow_approver=True`**：簽核人要看得到單據才簽得下去，而他通常
  既不是業務也不在協作者名單裡（含目前有效的簽核代理人，比照 `check_approve_permission()`）。
- **案件執行面加 `allow_module="case_manage"`**——這條是實測後改的：

  > 開發機資料庫 26 張報價單裡，`assigned_user_ids` 有值的是 **0 張**，也就是
  > 「指派協作者」這個機制**實務上從來沒被使用過**。純擁有者規則下，`engineer`
  > 角色（永遠不會是 sales_person）對全部 26 張案件的存取權是 **0**——現場工程師
  > 會完全打不開任何案件的執行進度與拜訪紀錄。所以執行面（階段、拜訪、動態、
  > 叫料附件、案件鎖定、案件報表 PDF）額外放行 `case_manage` 模組；**金額面
  > （精算、應收應付、發票檔案）維持純擁有者規則**。
  >
  > 等「指派協作者」真的被落實，就可以把這條放行拿掉回到純擁有者規則。那天之前
  > 拿掉，等於停掉工程師的案件管理。

**② `financial_view` 從顯示偏好變成真的權限**

新增 `helpers/auth.py::can_see_financial()`，規則與前端
`case-management.js::canSeeFinancial()` **逐字相同**（`superadmin`／`admin`／`sales`
或持有 `financial_view`），套用在成本精算 GET/PUT、應收應付總覽、銷售訂單清單。
`viewer`／`engineer` 沒有 `financial_view` 就拿不到金額，即使他碰得到該案件。

⚠️ 額外支出與三種憑證流（承攬商付款／開票／請款）**維持原樣**：那些端點上有
非管理員的簽核人，直接套這條會把簽核人擋在門外。要動得先理清「簽核人是否一定
看得到金額」，仍列在 §4。

**③ `/api/sales-orders`**：補上 `finance` 模組（或 admin+）＋財務金額可視兩道。

**④ 16 個「後端不讀」的模組——逐一補上檢查**

新增 `helpers/auth.py::require_any_module(user, keys, label)`（admin+ 直通）。
`keys` 是**該 API 所有消費頁面所屬模組的聯集**，這份聯集是從前端原始碼實測出來的
（掃 `frontend/pages/*.html` 與 `frontend/js/*.js` 的 `/api/…` 與 `${API}/…` 兩種寫法，
再對 `sidebar.js::_FILE_MODULE` 的頁面→模組表）：

| API | 允收模組 | 為什麼不是單一模組 |
|---|---|---|
| `/api/parts` | procurement, case_manage | 案件管理的叫料也讀料號 |
| `/api/inventory/*` | procurement, case_manage, netplan_edit | 叫料與規劃書都查庫存 |
| `/api/customers` | customer, case_manage, dev_crm, procurement | 四個模組的頁面都撈客戶 |
| `/api/suppliers` | customer, procurement | 客戶頁也用供應商清單 |
| `/api/vendor-contractors` | procurement, case_manage | 案件派工 |
| `/api/work-logs` | work_log, case_manage | 案件動態合併工作日誌 |
| `/api/daily-tasks` | daily_task, case_manage | 案件階段會同步每日工作事項 |
| `/api/devices`、`/api/materials-summary` | equipment／procurement（＋case_manage） | — |
| 七個 `*-guide` 讀取端點 | `<x>_guide` **或** `<x>_guide_edit` | 只認檢視模組的話，正式機那個只有編輯模組的 `claude` 帳號會變成「改得動卻讀不到」 |
| `/api/network-plans-quick` | netplan_edit, case_manage | 側欄把規劃書開給 engineer |

`/api/parts` 與 `/api/parts/categories` 另外補了 `authorization` 參數——它們原本
**連參數都沒有**，只靠 main.py 的 middleware 擋未登入，所以也無從做模組判斷。

**刻意不套的例外**：`routers/network_plans_quick.py` 的兩支端點（快速拓樸圖
preview／pdf）是**無狀態繪圖工具**——吃前端傳來的 JSON、回 SVG/PDF，不讀也不寫任何
資料表。擋它不會保護到任何資料，只會擋掉使用者畫圖。模組檢查的目的是資料可見性，
不是「凡是端點都要掛一道」。原有測試 `test_network_plans_quick.py` 就是這個規格
（「純預覽不需要 netplan_edit」），保持不變。

**因此更新的既有測試**：`test_automation_guide.py` 兩題原本釘的是「檢視只要登入」
——那正是後端沒有讀檢視模組的狀態。改成釘新規格，並補兩個方向的反向斷言：沒有任何
導覽模組的帳號 403、只有 `*_guide_edit` 的帳號仍讀得到（否則變成改得動卻讀不到）。

### 3.9 🔴 第三輪（巡視補漏）：同一種 IDOR 還散在另外 7 支 router

§3.8 ① 只掃了 `quotations.py`。再巡一次（掃全部 router 裡「吃 quote_no 卻沒有擁有者
檢查」的端點）發現**同一種形狀還在別處**：

| Router | 端點 | 原本 |
|---|---|---|
| `case_action_items.py` | 案件代辦 list／create／update | 只要求登入 |
| `completion_notes.py` | `GET /api/completion-notes?quote_no=` | 只要求登入 |
| `shipping_notes.py` | `GET /api/shipping-notes?quote_no=` | 只要求登入 |
| `invoice_vouchers.py` | 清單＋`/remaining` | 只要求登入 |
| `payment_requests.py` | 清單＋`/remaining` | 只要求登入 |
| `contractor_vouchers.py` | 清單 | 只要求登入 |
| `network_plans.py` | `GET /api/quotations/{quote_no}/network-plan` | 只要求登入 |
| `search.py` | 全域搜尋的客戶／料號分類 | 只要求登入 |

處理方式：

- 守門從 `routers/quotations.py` **搬到 `helpers/quotations.py::guard_case_access()`**
  ——需要它的地方橫跨八支 router，留在 router 裡就是等著下一支新端點再忘一次
  （`_check_quotation_owner()` 2026-09-10 搬進 helpers 的理由完全相同：當時是叫料
  API 忘了加，把同一個 IDOR 又開了一次）。
- 五種單據的清單端點：**帶 `quote_no` 走擁有者規則**（＋`case_manage`），
  **不帶就是跨案件總覽**，改為管理員或具相關模組（案件管理／財務／出納）才看得到。
- `case_action_items` 不能直接套一般規則：它的兩階段簽核對象是該案業務的**部門主管
  與處主管**，這些人幾乎不會是該案業務、也不在協作者名單裡。改成
  `_guard_action_item_case()`——先判斷「是不是這張案件的簽核對象」，是就直通，
  其餘才走一般守門。⚠️ 順序不可顛倒：一般守門擋下來時會順手關掉連線，先呼叫它
  就沒有連線可以再查主管是誰。
- **全域搜尋**是最容易被忘記的側門：它自己一套查詢，不經過任何 router 的檢查。
  客戶與料號兩個分類補上同一組模組判斷，沒權限回**空清單**而不是 403
  （搜尋框是多分類的，其中一類沒權限不該讓整個框壞掉）——比照檔案裡既有的
  supplier 寫法。

**因此更新的既有測試**：`test_case_project_merge.py::test_action_item_two_stage_approval`
與 `test_case_action_item_edit_reset_2026_08_28.py` 的帳號補上 `case_manage`
（原本釘的是「新增代辦事項任何登入者皆可」）、`test_completion_notes_2026_09_12.py`
的清單斷言（原本釘「列表只要求登入」）。三處都補了反向斷言：沒有模組的帳號會 403。

### 3.10 🔴 第四輪（照裁示順序收尾）：憑證流金額、單據 IDOR、頁面層守門

**① 三種憑證流與額外支出的金額可視**（原 §4 第一項）

原本的顧慮是「這些端點上有非管理員的簽核人，套 `financial_view` 會把簽核人擋在
門外」。解法不是不做，而是**把例外寫清楚**：

| 對象 | 看得到 |
|---|---|
| `can_see_financial()`（admin／sales／具 `financial_view`） | 全部 |
| **本單簽核人**（含代理人） | 自己要簽的那幾張——看不到金額就沒辦法判斷該不該簽 |
| **額外支出的填寫人** | 自己報的那幾筆——現場花錢的人本來就該看得到自己報的帳 |
| 其他人 | 看不到 |

清單端點採**過濾**而不是整支 403（`_visible_rows()`）：整支擋掉會讓非管理員的
簽核人連簽核佇列都打不開。額外支出的合計同步只算看得到的那幾筆，避免「清單 3 筆、
合計卻是 8 筆金額」這種更難解釋的畫面。

`is_document_approver()` 一支函式吃兩種存法：報價單與三種憑證流存在
`data_json.approval`，案件額外支出存在獨立欄位 `approval_json`（內容就是 approval
物件本身）。

**② 單據詳情的 IDOR**：`GET /{voucher_no}`、PDF 下載、已開立發票附件上傳/刪除
先前都只要求登入，而單號是可預測的（前綴＋年月＋流水號）。全部改走
`_guard_voucher()`：案件層（擁有者／案件管理模組／本單簽核人）＋金額層。
找不到母案件時**不回 404**（單據本身存在、只是母案件被刪或資料異常，對使用者顯示
「報價單不存在」只會更難查），退回模組層級判斷。

**③ 前端頁面層守門**（原 §4 第三項）：`auth-guard.js` 只驗 session，沒有某個模組
的人手打網址照樣打得開那一頁——這一輪後端擋住之後，症狀會變成「頁面開得起來、
資料一片 403」，看起來像壞掉而不是像沒權限。

守門刻意**沿用側欄自己的顯示條件**：`ni()` 判定不顯示某個項目時把該頁記進
`_deniedPages`，渲染完再看使用者是不是正站在其中一頁上。不另外維護一份頁面→模組
對照表——那份表一旦漂移就是這次盤點抓到的那類錯配。

> ⚠️ **實測時發現不能導轉**：原本寫成「導回 index.html」，但 `index.html` 自己也有
> 一道守門（非 admin 且沒有 finance／quotation 模組就導去 case-management.html），
> 兩邊一搭就是無限迴圈——只有「儀表板」模組的檢視者會在兩頁之間一直跳。改成
> **就地顯示「你沒有這個頁面的權限」**，不導轉，沒有迴圈的可能。
>
> 順手修掉 `index.html` 那道守門漏了 `dashboard` 模組的問題（側欄的 `canDash` 有、
> 它沒有 → 勾了「儀表板」的人照樣被踢去案件管理）。

### 3.11 🟠 第五輪：解鎖（半解鎖）流程複查

使用者要求把「解鎖讓人員上傳/修改」這條路再走一次。流程本身沒壞（`test_case_semi_unlock.py`
14 題全綠、核准仍限 superadmin），但複查抓到三件事：

**① `GET /api/case-changes/{change_id}` 只要求登入** — `change_id` 是**小整數流水號**，
比 `quote_no` 更好猜，而它回的是 `SELECT *`：那張案件的完整變更內容（案件資訊快照、
款項金額）。已改成走 `_guard_case()`，另外放行**提出這筆申請的人**。核准／駁回本來
就限 superadmin，不受影響。

**② 解鎖／上鎖被我一起收斂了——使用者裁示後已還原**

複查時發現這兩支的 docstring 還寫著「任何登入使用者皆可觸發（2026-08-26 使用者
透過 AskUserQuestion 確認）」，而模組權限稽核已經把它收成擁有者規則。

**使用者 2026-09-13 裁示：「誰都可以改動，但都需要審核」** —— 維持全開。理由成立：
半解鎖期間的每一筆變更/上傳都會排進待審核由 superadmin 決定，**把關點在審核、
不在入口**，入口再擋一層只是讓補資料的人做不了事。已還原，並在 docstring 寫明
這是這波收斂裡刻意保留的例外、不要再收第二次（測試也釘住了）。

對應地，半解鎖期間的附件上傳/刪除改用
`_guard_case(..., skip_if_semi_unlocked=True)`——**已結案且半解鎖**時放行任何人，
**未結案**的案件沒有那道審核，仍維持擁有者規則。這條分界線是這次唯一需要動腦的
地方：同一支端點在兩種案件狀態下該有不同的鬆緊。

**③ 同一個排隊審核家族內部不一致** — 叫料附件上傳/刪除放行 `case_manage`，款項
發票附件卻是純擁有者。兩者都是半解鎖期間「補資料」的動作，沒有理由一嚴一鬆；
已統一為 `case_manage`（仍擋掉外人與 viewer）。

---

## §4 · 決策結果與仍未收的

**2026-09-13 使用者裁示**（原五項待決策）：

| 項目 | 決定 | 狀態 |
|---|---|---|
| 其餘每案 IDOR | 一起收 | ✅ §3.8 ①（28 支）＋ §3.9（另外 8 支 router）＋ §3.10 ②（單據詳情） |
| `financial_view` | viewer／engineer 不該看到金額 | ✅ 案件財務總覽 §3.8 ②；憑證流與額外支出 §3.10 ①（簽核人與填寫人例外） |
| `/api/sales-orders` | 加模組檢查 | ✅ §3.8 ③ |
| 16 個後端不讀的模組 | 逐一補後端檢查 | ✅ §3.8 ④（15 個 router、94 處） |
| `cashier` 模組 | 保留 | ✅ 不動 |
| 前端頁面層守門 | （順序上的下一項） | ✅ §3.10 ③ |

**2026-09-13 第二批裁示（解鎖複查之後）**

| 項目 | 使用者決定 | 狀態 |
|---|---|---|
| 已結案案件的解鎖權限 | **「誰都可以改動，但都需要審核」——維持全開** | ✅ 已還原（§3.11 ②），測試釘住 |
| 指派協作者 | **目前還沒放入，維持現狀** | ✅ 案件執行面繼續放行 `case_manage`；日後落實再收 |
| `/api/quotations` 再疊模組 | **不做** | ✅ 維持擁有者＋角色＋簽核三層 |
| `dashboard` 模組後端檢查 | **不做** | ✅ 維持現狀 |
| 部署 | **先跟同仁講三件行為變更再部署** | ⏳ 待執行 |

**仍未收的**

| 優先 | 項目 |
|---|---|
| 🟠 | **「指派協作者」尚未落實**（使用者 2026-09-13 決定維持現狀）。因此案件執行面繼續額外放行 `case_manage` 模組。日後若開始落實指派，把 `guard_case_access(..., allow_module="case_manage")` 的參數拿掉就回到純擁有者規則 |
| 🟡 | **`/api/quotations` 系列刻意沒有套模組檢查**（使用者 2026-09-13 決定不做）。那 59 支已經有擁有者＋角色＋簽核三層；再疊一層模組只是重複，而報價單的簽核人不一定持有 `quotation` 模組，擋錯人的代價比多擋一層的收益高 |
| 🟡 | **`dashboard` 模組後端仍沒有讀**（使用者 2026-09-13 決定不做）。首頁是每個人的落地頁，擋錯代價高（見 §3.10 ③ 的迴圈事故），金額已由內部 `can_finance` 分流 |

## §5 · 這次留下的自動化守門

| 測試 | 守什麼 |
|---|---|
| `test_module_keys_consistency_2026_09_13.py`（7 題，非 e2e） | ①後端擋得住的 key 必須勾得到 ②側欄用的 key 必須勾得到 ③目錄裡的 key 至少要有一邊讀它 ④角色樣板不能含目錄外的 key ⑤`_SUPERADMIN_MODULES` 必須等於前端 superadmin 樣板 ⑥**模組檢查不能擋掉自己的頁面** ⑦**側欄承諾的模組必須打得開該頁的 API** |
| `test_module_permission_fixes_2026_09_13.py`（26 題，非 e2e） | 擁有者規則（含「403 了資料也真的沒被改到」）、模組真的打得開報表、沒模組仍被擋、對帳不跟著放寬、`financial_view` 對 viewer／engineer 生效、案件執行面認 `case_manage`、跨模組消費者不會被打死、單據詳情的 IDOR、憑證清單的過濾（簽核人看得到自己要簽的）、額外支出填寫人看得到自己報的帳、全域搜尋不繞過模組檢查 |
| `test_e2e_page_module_guard_2026_09_13.py`（2 題，e2e） | 沒有模組的人手打網址會看到「沒有權限」且頁面內容被換掉；有模組的人不受影響（反向控制） |

**⑥⑦ 是這批裡最重要的兩題**：模組檢查最危險的失敗模式不是「該擋沒擋」，而是
**擋錯人**——某個模組的頁面呼叫到一支不接受該模組的 API，使用者看到一片 403，而
後端測試全綠（測試多半用 admin 帳號，admin 直通所有模組檢查）。這兩題當天就抓到
三個實例：簽核佇列讀不到待簽單據、`/api/materials-summary` 被設成採購以外的模組、
`inventory` 模組打不開庫存管理頁。

> ⚠️ **這兩題一開始是假綠燈**：寫進檔案時混進兩個看不見的退格字元（``），
> 讓 `re.findall(r"c\w+", ...)` 永遠匹配不到、測試永遠綠。修掉之後用
> 「把 bug 種回去」實測過：兩題都會紅，還原後又全綠。**新寫的守門測試一定要
> 先證明它會紅**，否則它只是讓人安心而已。

用 HEAD（修正前）的檔案內容重跑守門測試的判斷，①④⑤三題確實會紅；②③是預防性的。
行為測試的觀測點刻意放在下游資料（資料有沒有真的被改到、清單實際回哪幾筆），
不是只看回傳碼。
