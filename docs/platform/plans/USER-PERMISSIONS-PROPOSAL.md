# 使用者權限調整方案（提案；只有文件，未改程式）

作者：a3（hichan-a3）　日期：2026-10-03　狀態：路線已定（A 脫鉤→職責角色化→B 逐領域）；15 題預設答案與 5 件職責角色化方向**使用者已同意**（第 8 題「產生獎金單」維持現狀）；新增不變式：superadmin 全功能可用；實作排第 35 班起
基底：origin/wip/train-34-int1（2f027536）。明細盤點見同目錄 `ADMIN-DECOUPLE-INVENTORY.md`（案件／金流／核心三區，約 100 處判斷點）。

## 0. 一頁結論

- **目標（使用者原話）**：未來不要 admin；既有 admin 員工依各自負責項目調整；出納與財務不綁 admin、一般員工也能持有；只有 superadmin 全可見；「出納填寫」獨立勾選留未來。
- **現況關鍵**：後端「模組」這一層其實早已不讓 admin 直通（`require_any_module`、`user_has_module` 都只認 superadmin 或實際持有）。admin 之所以還什麼都能做，來自兩處：①**寫死的角色比較**（約 100 處 `role in ("superadmin","admin")`，其中金額／出納／財務相關約 70～80 處，主要在三個各自定義的 `_require_admin`、`cashier.py`、`accounting_export.py`、`can_see_financial`、案件額外支出／報價單遮蔽、前端按鈕）；②**角色樣板**——admin 樣板預設就含 `finance／financial_view／cashier／reports`，既有 admin 帳號在 DB v84 已被回填這些模組。
- **正式機形狀**：在職 11 人＝admin 4（**4 位都同時持有 cashier＋finance**）、superadmin 2（只有 finance，直通不受影響）、sales 2、viewer 2、engineer 1。⇒ 把財務／出納脫鉤後，**現有 4 位 admin 的實際行為完全不變**；日後把某人的勾拿掉，才會失去金額可見／出納。
- **硬性不變式（使用者 2026-10-03）**：superadmin 每個功能都要能使用，不因沒勾 cashier／finance 而被擋（見 §5 之前的「不變式」節與第 35 班守門）。
- **建議**：分兩班。**第 35 班做方案 A（財務／出納脫鉤）**——範圍清楚、可逐檔驗證、正式機零行為變動；**第 36 班起視需要做方案 B 的其餘部分（把 admin 的一般管理直通逐步換成模組權限）**，每班一個領域。

## 1. 現況

### 1.1 帳號模型
- `users.role`：`superadmin／admin／sales／engineer／viewer` 五種；`users.modules`：JSON 陣列（模組鍵清單，約 35 個可授權模組）。
- **角色樣板**（`helpers/module_registry.ROLE_TEMPLATES`，與 `users.html` 的 `ROLE_MODULES` 同源；`GET /api/modules/catalog` 提供給前端）：新增使用者或按「快速套用」時把該角色的預設模組填進勾選。admin 樣板含：`dashboard、quotation、case_manage、customer、procurement、inventory、equipment、finance、reports、project_approve_eng／biz、financial_view、work_log、daily_task、cashier`。
- **自訂角色**（`system_settings.custom_roles`，`/api/custom-roles`）：名稱＋基礎角色＋模組清單，出現在 users.html 的快速套用 chips（虛線 chip）。**自訂角色只是勾選樣板，不是權限實體**——套用後模組寫進該使用者的 `modules`，之後樣板改了不會回頭影響已套用的人。
- **模組狀態**（另一件事，與使用者權限正交）：`core.registry.module_states` 由載入器在啟動時決定 `loaded／disabled／unlicensed／failed`；管理者可在系統設定停用／啟用（`PUT /api/system/modules/{key}`，**重啟後生效**）。模組被停用時，即使使用者有勾也看不到、打不到。

### 1.2 後端各層如何交互
| 層 | 位置 | 對 admin 的行為 |
|---|---|---|
| 模組守門 | `helpers/auth.require_any_module(user, keys, label)`；`_require_user(..., module=)` | **只有 superadmin 直通**；admin 必須持有 keys 其一，否則 403（2026-09-14 裁示，v84 回填過既有 admin） |
| 模組判斷 | `user_has_module(user, key)` | 只看 `modules` JSON，不看角色 |
| 角色寫死 | 約 100 處 `role in ("superadmin","admin")`／`== "admin"`／各檔 `_require_admin`／`_is_manager` | **admin 直通**（不看模組） |
| 金額可見 | `helpers/auth.can_see_financial`：角色 `superadmin／admin／sales` **或** `financial_view` 模組；`helpers/financial_mask.money_visible`、`case_extra_expenses._amount_viewer`、`expense_types._is_cashier` | admin、sales 直通；簽核人（`is_document_approver`）另有例外 |
| 前端 | `case-management-core.js` 的 `canSeeFinancial／canMarkPayment`、`cashier.js`／`reports.js` 的 `isAdminPlus`、頁面按鈕的 `['superadmin','admin'].includes(session.role)` | 與後端寫死規則「逐字相同」，兩邊要一起改 |
| 資料列範圍 | `helpers/row_access.ADMIN_ROLES`、`approval_queue`（admin 看全部案件列／簽核單） | admin 看全部（金額另由 money_visible 遮） |

### 1.3 F／M 分類盤點摘要（明細在附錄）
- **F（金額可見／出納／財務／匯款／付款／成本毛利／應收應付／T100）**：金流區約 45 處（承攬匯款 16、開票 9、請款 9、出納 6、會計匯出 8）；案件區約 27 列（額外支出、報價單財務／收款／沖銷、叫料成本、dashboard 財務、reports）；核心區後端 4＋間接 4、前端 11 組。
- **M（一般管理）**：約 80 處（人員、設定、派工管理、案件編輯、行事曆…），本案不動。
- **?（模糊，需裁示）**：約 20 處，集中在 §5 的題目。
- 三個「各檔自己定義」的 `_require_admin`（`contractor_vouchers.py:142`、`invoice_vouchers.py:141`、`payment_requests.py:139`）合計約 27 個端點，是**改動量最大也最集中**的一處；`can_see_financial` 一處改動連動案件區約 10 處與金流區約 8 處。

## 2. 目標拆解
1. **不再有「admin 就能看金額／出納／財務」**：這些能力只靠 `cashier`／`finance`（及既有 `financial_view`）模組勾選；superadmin 全可見。
2. **既有 admin 依負責項目調整**：由使用者在 users.html 逐人調整勾選（不是程式自動猜）。
3. **出納、財務是一般員工也可持有的模組**：樣板與畫面都不能預設綁 admin 角色。
4. **「出納填寫」獨立勾選留未來**：今天仍用現有 `cashier／finance` 兩個勾，不新增權限鍵。
5. **最終不要 admin 角色**：一般管理功能（人員、設定、派工、案件編輯…）要有對應模組權限才能取代 admin 直通——屬較長期。

## 3. 方案比較

### 方案 A：先脫鉤財務／出納（建議第 35 班）
**做法**：新增單一入口（`helpers/auth.py`：`has_finance_access(user)`＝superadmin 或持有 `finance`／`financial_view`；`has_cashier_access(user)`＝superadmin 或持有 `cashier`）。F 類判斷全部改用它：三個 `_require_admin`、`cashier.py` 查看／付款／差額審核／銀行對帳、`accounting_export` T100、`can_see_financial`、`case_extra_expenses`／報價單遮蔽、`dashboard` 財務、前端 `canSeeFinancial／canMarkPayment／isAdminPlus`。M 類（一般管理）不動。
- **正面**：範圍收斂（F 約 70～80 處，且集中在少數檔）；正式機 4 位 admin 都已持有兩個模組，**上線後零行為變動**；可用「admin 無模組 ⇒ 403／看不到；admin 有模組 ⇒ 通過；superadmin（即使沒有 cashier）⇒ 通過」做一組守門測試；符合使用者「出納與財務先拉出來」。
- **反面／風險**：①**簽核人例外**必須保留（`_amount_viewer`／`is_document_approver`：被指定的簽核人本來就需要看金額，與 admin 無關，改時只拿掉 admin 那條）；②樣板仍含 finance／cashier：新建 admin 會預設有勾，需決定是否改樣板（不改＝新 admin 預設仍有；改＝新 admin 預設沒有，但既有帳號不受影響）；③`can_see_financial` 同行還有 `sales` 直通，需裁示保留與否；④前端與後端要同步（兩邊規則逐字一致）；⑤admin 仍可做 M 類（派工建立、發票日、叫料）——其中有些含金額（見 §5 題目）。
- **改動量**：後端約 35～45 個檔案點位（含 3 個 `_require_admin` 一次改完）＋前端約 11 組＋1 個 helper＋守門測試；估 1 班（約 1.5～2 人天含稽核）。
- **遷移步驟**：①加 helper 與測試（行為不變：先讓 helper 等價於舊規則＋模組並列）→ ②逐檔換用 helper（每批單檔測試）→ ③拿掉 admin 直通條件 → ④前端同步 → ⑤出一頁「套用後要做」給使用者（誰要勾出納／財務）→ ⑥正式機演練（帳號形狀＝上述 4＋2＋…，驗 admin 有模組照舊、拿掉勾後 403）。
- **能否分班**：可。35 班＝A；失敗可只回滾程式（沒有 schema 變動）。

### 方案 B：全面以權限取代 admin 直通
**做法**：在 A 之上，把 M 類約 80 處也逐一換成模組權限（人員管理＝新模組 `user_admin`？設定＝`settings`；派工管理＝`contractor_dispatch`…），最後把 admin 角色降為「樣板名稱」或移除，只留 superadmin＋模組。
- **正面**：真正達到「不要 admin」；權限語意統一（只剩模組）；日後新增角色只是勾選樣板。
- **反面／風險**：改動面廣（約 100～150 處＋所有前端按鈕＋所有測試以 admin 帳號通過的假設）；**最危險的失敗是「擋錯人」**（MODULE-AUDIT §5：測試多用 admin 帳號，直通消失後才暴露）；需要新增或拆分模組鍵（會動模組目錄、授權、`module_states`）；既有 4 位 admin 的勾選要逐人重排，才不會一夜之間少掉功能（v84 的教訓）。
- **改動量**：3～4 班（每班一個領域：①人員／設定 ②案件／叫料 ③承攬／供應 ④清尾與移除 admin 角色）。
- **遷移步驟**：先 A；之後每個領域「新增模組鍵或沿用現有 → 後端換 helper → 前端同步 → 對既有 admin 回填勾選（一次性遷移，仿 v84，補範圍＝直通原本給出去的）→ 演練」。
- **能否分班**：可，且必須分班。

### 方案 C（不建議）：只改前端
只把按鈕藏起來而後端不動——AUDIT 已證明「前端偏好不是權限邊界」（`financial_view` 曾只是顯示偏好），有手打 API 繞過風險。**不採。**

### 比較表
| | A 脫鉤財務／出納 | B 全面取代 admin | C 只改前端 |
|---|---|---|---|
| 達成使用者目標 | 財務／出納部分 | 全部 | 否（假象） |
| 改動量 | 約 1 班 | 3～4 班 | 小但無效 |
| 正式機行為變動 | 無（4 位 admin 都有勾） | 需逐人重排勾選 | — |
| 主要風險 | 簽核人例外、前後端不同步 | 擋錯人、模組鍵新增 | 可繞過 |
| 可否回滾 | 只回程式 | 回程式＋勾選回填需備份 | — |

## 4. 使用者編輯畫面與模組狀態的調整點（users.html／系統設定）
1. **角色樣板**（`ROLE_TEMPLATES`／`ROLE_MODULES`）：決定 admin 樣板是否仍含 `finance／financial_view／cashier／reports`。建議 A 班**不動既有帳號、只改樣板的預設**（新建 admin 預設不勾財務／出納），並在 users.html 的勾選區把「財務／出納」群組標示成「與角色無關、要另外勾」。
2. **快速套用 chips**：新增「出納（一般員工）」「財務（一般員工）」兩個系統預設 chip（基礎角色＝sales／engineer 皆可），讓一般員工能一鍵拿到 cashier／finance。自訂角色功能已存在，不必新機制。
3. **使用者清單**：在列表加「持有財務／出納」標籤（現有 `access-chip` 可沿用），便於使用者盤點誰有勾。
4. **模組狀態**：本案不改載入器。唯一關聯：`finance／cashier` 對應的後端模組（arap、accounting）若被停用，勾選無效——users.html 可在該勾選旁提示「模組目前停用」（資料來自 `GET /api/system/modules`）。
5. **防呆**：移除最後一位持有 `finance` 或 `cashier` 的非 superadmin 時提示（目前正式機 superadmin 沒有 cashier，出納實際靠 admin 的勾）。
6. **稽核**：變更使用者模組勾選已寫稽核；脫鉤後建議把「財務／出納勾選變更」標成高敏感事件。

## 不變式：superadmin 每個功能都要能使用（使用者 2026-10-03 裁示）

**規則**：superadmin 不因為沒有勾 `cashier`／`finance`／`financial_view` 等任何模組，而被任何功能擋下——含所有「財務／出納」判斷、頁面選單、API、PDF 產出、通知收件。理由：避免財務／出納無人可處理時系統卡死（正式機現況：superadmin 2 位只有 `finance`、沒有 `cashier`，出納實際靠 admin 的勾）。**脫鉤只拿掉 admin 的角色直通，不得影響 superadmin 直通。**

### 查證（基底 int1 2f027536）
| 層 | 現況 | 結論 |
|---|---|---|
| 側欄選單 | `frontend/static/sidebar.js`：`has = k => sa \|\| mods.indexOf(k) >= 0`；`_permOk(perm)` 對陣列 perm 用 `has`；module.json 的 `menu.perm`（例如 arap 的出納頁 `["cashier"]`） | **superadmin 看得到所有選單項目（包含 cashier）**，不因沒有 cashier 勾選而隱藏 ✔ |
| 後端模組守門 | `require_any_module`／`_require_user(module=)`：`role == "superadmin"` 直通 | ✔ |
| 後端「單獨用 `user_has_module`」 | `user_has_module` 只看 `modules` JSON，**不看角色**。全後端 54 處呼叫，其中**未同時帶 superadmin／admin 判斷**的至少有：`helpers/case_access.py:157,290`、`helpers/financial_mask.py:40`、`helpers/row_access.py:78`、`analytics/reports.py:101-102`、`arap/cashier.py:44-45`、`case/case_extra_expenses.py:252,652,1037`、`case/material_orders.py:205`、`case/quotations.py:2776`、`payroll/bonus.py:1772`、`payroll/bonus_correction.py:51`、`payroll/bank_account.py:90,98` | **這些處的前後文通常另有 superadmin 分支，但需逐一確認**；**脫鉤時若把「admin 直通」拿掉、只剩 `user_has_module`，會讓 superadmin（沒有該勾）被擋** ⇒ 新 helper 必須內含 superadmin 直通，且這批要逐一驗 |
| 前端按鈕／頁面條件 | `canSeeFinancial／canMarkPayment／isAdminPlus` 與頁面的 `['superadmin','admin'].includes(session.role)` | 目前含 superadmin；脫鉤改寫時 superadmin 必須保留 |
| PDF／通知 | 匯款申請 PDF 下載走 `_guard_voucher`＋`can_see_financial`；通知收件依角色／模組挑人（`email_notify` 的 `admins` 群組） | 通知改「依 cashier／finance 勾選挑人」時要**加上 superadmin**（否則沒勾的 superadmin 收不到）；PDF 路徑保留 superadmin |

### 守門（併入第 35 班 A 案）
1. **行為測試**：建立「superadmin、`modules=[]`」帳號，對**每個 F 類端點／判斷**（以盤點附錄 F 清單為準）都通過（含 API、PDF 下載、T100、差額審核、憑證建立／作廢／送審、報價單財務／收款、dashboard 財務、獎金金額端點）。正對照：同一請求用 `admin（modules=[]）` ⇒ 403／看不到；反向控制：把新 helper 的 superadmin 直通拿掉 ⇒ 此測試紅。
2. **靜態守門**：掃描 `has_finance_access`／`has_cashier_access`（新 helper）本體必含 `role == "superadmin"` 直通；掃描 F 類檔案內**單獨使用 `user_has_module(..., "cashier"|"finance"|"financial_view")` 而同一判斷式沒有 superadmin 直通**者 ⇒ 紅（基線＝目前的 15～20 處，只准減少；逐處在 A 班改成走新 helper）。新增的權限判斷若沒有 superadmin 直通也紅。
3. **前端**：側欄對 superadmin 顯示所有項目（現況已是，補一題 e2e：superadmin 無 cashier 勾選仍看得到「出納」選單並進得去）；F 類按鈕條件改寫後 superadmin 仍顯示（e2e 抽驗：標記已匯款、差額審核、T100、憑證建立）。
4. **正式機形狀演練**：以「superadmin 2 位只有 finance、沒有 cashier」的帳號形狀，在演練庫跑全部出納功能（待付款、標記已匯款、差額審核、銀行對帳）與財務功能，全部可用；admin 4 位（皆有 cashier＋finance）行為與上線前相同；再把某 admin 的勾拿掉，確認該 admin 403 而 superadmin 不受影響。
5. **盤點補欄**：`ADMIN-DECOUPLE-INVENTORY.md` 的 F 表每列加「superadmin 路徑已確認」欄（實作班填）。

## 5. 需要使用者裁示的題目（每題附「預設答案＋理由」；你只需改不同意的）

預設原則（bin-1c 2026-10-03）：最小權限；職務分離（建立／核可／匯款不由同一人完成；cashier 不核可自己匯的款）；金額與個資預設收緊；管理功能（看案件列、看簽核單本身）admin 可留 M 類；通知對象跟權限走；有疑義的標「需使用者」。

| # | 題目 | 預設答案 | 理由 |
|---|---|---|---|
| 1 | `sales` 直通成本毛利（`can_see_financial`／`canSeeFinancial`） | **改成須持有 `financial_view`**（樣板仍預設給 sales，所以現有 2 位 sales 勾選不變） | 最小權限：「角色直通」改成「看勾選」，樣板仍預設給；使用者之後能個別收回 |
| 2 | admin 樣板與既有 admin | 新建 admin 預設**不**勾 `finance／financial_view／cashier／reports`；既有 4 位 admin **不自動回收**，由使用者逐人調整；`reports` 的財務報表頁籤改認 `finance` | 不讓現有人一夜失去功能（v84 教訓），但新帳號從最小權限開始 |
| 3 | 三種憑證（匯款／開票／請款）的建立、作廢、送審（`_require_admin`，約 27 端點） | 建立／送審／作廢＝**`finance`**；**`cashier` 只能標已匯款**；`/api/remit-kinds` 下拉跟建立權限走（`finance`） | 職務分離：建立與匯款不同人；cashier 維持現狀（只執行付款） |
| 4 | 差額審核（`cashier.py:231`、匯款申請 paid-toggle 的核可／退回） | 核可者＝**superadmin＋`finance`**，**不含 `cashier`**；`remit.py` 通知對象跟著改成這兩者 | 避免出納自匯自核 |
| 5 | 派工金額、成本、發票日（派工建立／修改、發票附件、發票日、`COST_VIEW_MODULES`） | **發票日與含金額欄位的修改＝F（`finance`）**；派工建立、狀態、驗收＝M（維持） | 發票日會影響應付認列，屬財務；派工本身是工務管理 |
| 6 | 叫料體系（`material_orders`／`material_guard`／`material_approval`／`material_change`） | **取消已核准叫料單、改成本單價＝F**；建立／送審／到貨確認＝M（金額另靠 `money_visible` 遮蔽） | 影響成本與總帳者收緊，日常作業不動 |
| 7 | T100 傳票匯出／設定 | 匯出預覽／下載＝`finance`；**confirm／unconfirm（寫入）＝僅 superadmin**；設定＝僅 superadmin | 寫入總帳狀態風險高，最小權限 |
| 8 | 獎金 `_is_manager`（產生獎金單、看基數、預覽／下載 PDF） | 讀金額的端點收成 **superadmin＋`finance`**；「產生」維持現有角色（需使用者確認是否也收回） | 金額與個資收緊；產生屬人事流程，**需使用者** |
| 9 | 年度營運目標（`routers/system.py:239`） | 視為 **F**（`finance`／superadmin 可讀） | 含營收／毛利目標，屬財務金額 |
| 10 | 進貨批次（含進價）、承攬商頁／派發上傳報價 | 進價欄位可見性＝F（`finance`／`financial_view`）；上傳報價檔、建立批次本身＝M | 金額欄位收緊、作業不動 |
| 11 | 資料列範圍（`ADMIN_ROLES` 看全部案件列、簽核佇列看全部簽核單） | **維持 admin 可看（M）**；金額欄位另由 `money_visible` 遮蔽 | 使用者原則：管理功能 admin 可留；金額已另有遮蔽 |
| 12 | 稅額沖銷申請（`quotations` 約 4174／4206） | 申請＝**`finance`**；核准維持現有（僅 superadmin） | 職務分離：申請與核准不同人 |
| 13 | 通知收件群組（`email_notify` 的 `admins` 群組中的付款／匯款類通知） | 付款／匯款／差額審核類通知改依 **`cashier`／`finance` 勾選**挑人；其餘通知不動 | 通知跟權限走；哪些 mail_type 用 admins 群組需實作時查實 |
| 14 | 「出納填寫」獨立勾選 | **留未來**，第 35 班不做、不新增權限鍵 | 使用者已裁示 |
| 15 | B 案時程與新模組鍵 | 方案 A→職責角色化→B 逐領域；**B 的新模組鍵（如 `user_admin`）到第 36 班前再議**（先沿用 `settings`） | 先看 A 上線後的實際問題再決定，避免一次拆太多鍵 |

> 標「需使用者」者：第 8 題「產生獎金單是否收回」。其餘為預設答案，使用者不同意才改（對照表另一頁：`USER-PERMISSIONS-DEFAULTS.md`）。

## 6. 建議順序與分班
| 班別 | 內容 | 前置 |
|---|---|---|
| 第 35 班 | **方案 A**：`has_finance_access`／`has_cashier_access`、F 類全換、前端同步、守門測試（admin 無模組⇒403／看不到；有模組⇒通過；superadmin 無 cashier⇒通過；簽核人例外不變；正對照＋反向控制）、樣板與 chips（§4）、「套用後使用者要做」一頁、演練 | §5 的 1–13 題裁示 |
| 第 36～37 班 | 職責角色化（§9：R1 資料模型＋遷移＋稽核、R2 季度報表／回收）；之後方案 B 逐領域：①人員／設定 ②案件／叫料 ③承攬／供應 ④清尾、評估移除 admin 角色 | A 上線穩定、15 題裁示 |
| 一律 | 每班獨立稽核（權限類）；演練含「admin 有模組／無模組」兩種帳號形狀；正式機只回程式即可回滾 | — |

## 7. 驗證策略（A 案）
- 守門測試：對每個 F 類端點／判斷，三種帳號——`admin（無模組）`⇒403／看不到；`admin（有 cashier 或 finance）`⇒通過；`superadmin（不持有任何模組）`⇒通過；另含「簽核人例外仍可看」與反向控制（把 helper 換回舊規則 ⇒ 第一種帳號變成可通過 ⇒ 測試紅）。
- 靜態守門：禁止新增 `role in ("superadmin","admin")` 出現在標記為金額／出納／財務的檔案（掃描式，類似 page_paths 棘輪：基線只准減少）。
- 演練（drill）：以正式機帳號形狀（admin 4 皆有 cashier＋finance、superadmin 2 只有 finance）驗上線前後逐帳號行為相同。

- **superadmin 不變式**：見「不變式」節的守門 1～5（行為測試、靜態守門、前端 e2e、正式機形狀演練），併入 A 案驗收。

## 8. 不在本提案範圍
「出納填寫」獨立勾選、移除 admin 角色本身、模組載入器／授權機制的改動、正式機帳號的實際調整（由使用者在 users.html 操作）。

## 9. 職責角色化與權限變更稽核（草案；方案 A 之後）

### 9.1 為什麼
今天「角色」只是五種粗分類（superadmin／admin／sales／engineer／viewer），真正的權限在每人一份 `modules` 勾選；自訂角色只是勾選樣板（套用後與使用者脫鉤）。結果：①admin 一詞承載太多職責；②出納、財務這類**職務**無處表達；③樣板改了不影響已套用的人，無法統一調整；④誰改了誰的權限只有一般稽核日誌，沒有「前後差異」與定期盤點。

### 9.2 職責角色（一組權限）
- 預設職責角色：**出納**（`cashier`＋日常）、**財務會計**（`finance`＋`financial_view`＋`reports`＋會計模組）、**業務**（報價、案件、客戶）、**採購**（`procurement`、叫料）、**工務**（案件執行、派工、設備）、**專案管理**（案件總覽、簽核）、**系統管理**（人員、設定；仍不含金額）。名稱與內容可由使用者在畫面調整。
- **使用者綁角色**（可綁多個；個別加減勾選另記為「例外」）：生效權限＝角色權限聯集＋例外。users.html 的快速套用 chips 升級為真角色：改角色定義 ⇒ 同步所有已綁使用者（背景計算，不是複製）。
- 相容：舊 `users.role`（superadmin／admin…）保留為「基礎類別」，第一階段**只用來決定預設綁哪些職責角色**；現有 `modules` 轉成「例外」，上線瞬間每個人的生效權限不變（用遷移驗證：遷移前後逐人權限集合相等）。
- 職務分離規則（可設定檢查）：同一人不可同時持有「建立匯款」與「核可差額」等衝突組合；綁定時提示，嚴格模式可擋。

### 9.3 權限變更稽核
- 每次變更（綁／解角色、改角色定義、個別勾選、停用帳號）寫一筆**結構化稽核**：誰（操作者）、改誰、變更前後的**生效權限差異**（新增了哪些、移除了哪些）、原因（必填欄位，可短）、時間、來源 IP。
- 高敏感權限（`finance`、`cashier`、`financial_view`、使用者管理、superadmin）的變更額外通知 superadmin。
- 稽核不可由被稽核者自己刪改（沿用既有稽核日誌的保護）。

### 9.4 定期盤點與回收
- **季度權限清單報表**：每人／每職責角色的生效權限、最後登入日、持有高敏感權限者標示、近 90 天未登入者標示；使用者逐項確認或回收，結果存檔。
- **離職／調職回收**：停用帳號時自動移除所有角色與例外並記稽核；調職＝換綁角色，舊角色權限即時消失；停用／調職清單每月提醒。
- **break-glass**：superadmin 保留作緊急帳號（正式機現 2 位，只有 `finance`；superadmin 直通不看勾選）。建議：帳號保管與使用要記錄（使用即通知）、日常作業不用 superadmin、第二位 superadmin 作備援。

### 9.5 分階段
| 階段 | 內容 | 風險 |
|---|---|---|
| A（第 35 班） | 財務／出納脫鉤、`has_finance_access`／`has_cashier_access`、樣板與 chips（§4） | 低（正式機行為不變） |
| R1（第 36 班） | 職責角色資料模型（角色表、使用者綁定、例外）、遷移（生效權限逐人相等）、users.html 角色畫面、權限變更稽核 | 中（新表＋遷移；回滾＝回程式＋資料備份） |
| R2（第 37 班） | 季度報表、離職／調職回收、職務分離檢查、高敏感變更通知 | 低 |
| B（之後逐領域） | 以職責角色取代 admin 直通（人員／設定 → 案件／叫料 → 承攬／供應），最後評估移除 admin 角色 | 中～高（擋錯人，需逐領域演練） |

### 9.6 需要使用者確認（本節）
1. 職責角色清單與各角色內容是否照 §9.2（可先給草稿，之後在畫面改）。
2. 使用者可綁**多個**角色，是否接受（建議是：兼任很常見）。
3. 權限變更「原因」欄是否必填（建議必填，一句話）。
4. 季度盤點由誰執行（建議 superadmin；結果存檔）。
5. superadmin 第二位的使用規範（日常禁用、使用即通知）是否採用。
