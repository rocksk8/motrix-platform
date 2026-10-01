# 叫料管控的審核機制——設計（第 31 班；2026-10-01；**狀態：已全部裁示、可開工（Q1–Q6 見 §6；Q1 的付款解讀已由主持定案＝每單可多張匯款申請，各自簽核）**；唯讀分析，**未跑任何測試**）

使用者原話（2026-10-01）：「叫料管控也需要審核跟派工一樣」。基底：包 47db5613。引用格式 `檔:行`＝該 commit 的行號。
對照文件：`origin/wip/dispatch-approval-2e:docs/platform/plans/DISPATCH-APPROVAL-DESIGN.md`（承攬商派發；下稱「派發設計」）。
標記：**【已讀】**＝讀過程式；**【推論】**＝由程式推得、沒執行；**【未驗】**＝沒查證。

> **「叫料」在系統裡是兩份互不相連的資料**（§0 表）；使用者已裁示審核對象＝金額那份（`materialOrders`）。

## A. 已裁示（使用者 2026-10-01，經主持轉達）
| # | 項目 | 決定 |
|---|---|---|
| Q1 | 審核對象 | **金額那份（`materialOrders`）**；物流旗標（`ordered／arrived`）**只能對著「已核准的叫料單」勾** |
| Q5 | 實作方式 | **疊加審核表（方案 X，`case_material_approvals`）**，**不**改走 A2 請購／採購單 |
| Q8 | `case-record` 後門 | **關閉：所有寫入都過閘**；上線前列出誰在依賴（無正式機存取 ⇒ §7 給使用者自己跑的唯讀查詢） |
| 付款 | 叫料付款 | **比照派發：匯款申請單＋出納流程**，不是單純「登記已付」 |
| 共用機制 | `approval_gate` | **選配的第二階段重構**；先各自出貨（疊加＋派發），除非 hichan-2e 同意共用 `GateSubject`（§4） |
| Q1（付款） | 款別與分期 | **可部分付款，累計不得超過；沒有款別（訂金／進度）。解讀已定案（使用者授權主持）：一張叫料單可開「多張」匯款申請，每張各自分層簽核＋出納，累計受叫料單小計限制** |
| Q2（供應商） | 供應商與帳戶（主持預設） | **要求 `supplierId`；收款帳戶取供應商主檔，沒有就在匯款申請上填、存進申請快照；第一版不改供應商主檔結構** |
| Q3 | 到貨 | **不走分層簽核**；同一人可確認；**必須記錄到貨日期與確認人（稽核、顯示在叫料單上）**；旗標只能對著已核准的叫料單勾 |
| Q4 | 沒有金額的物流項目（客供／庫存領用） | **開一張 $0 叫料單，走同一個流程** |
| Q5（舊單） | 既有未付叫料 | **一律走新的匯款申請流程**（不溯及既往補核准）；**上線後不再有「登記已付」** |
| Q6 | `case-record` 後門的呈現（主持預設） | **只拒有問題的項目，其餘照存；回應 `rejected[]`（逐項原因）** |
| 沿用派發的裁示 | 簽核／完工／舊單／報表 | 分層簽核（部門主管→組織鏈→最高管理者；無簽核層＝自動核准；不能自核）；**建立要審；完成（到貨）不簽核、只記日期與確認人（叫料 Q3）**；進行中舊單寬限（灰徽章、實質編輯後重新送審）；報表：草稿與退回不計、待審核計入並標示；送審者＝創建者／負責人／協作者／admin 以上；取消已核准＝admin 以上＋理由；單號格式 |


## 0. 兩份「叫料」資料（事實）

| | 叫料管控（物流追蹤）`caseRecord.materials[]` | 叫料（財務應付）`caseRecord.materialOrders[]` |
|---|---|---|
| 畫面 | 案件管理 →「執行進度」→ **「叫料管控」**子頁（`case-management.html:813`、區塊 `:1034`） | 案件管理 →「財務」→ `#fin-material-orders`（`case-management.html:2323`）；文件 `docs/quick/mod-inventory.md §7.20` 講的是這份 |
| 欄位 | `name／model／qty／unit／ordered／arrived／supplier／expectedDate／devices[]（SN、MAC）／files／invoiceFiles／note` | `itemId／itemName／quantity／unit／unitPrice／totalPrice／paidStatus(pending/partial/paid)／paidAmount／paidDate／invoiceDate／notes` |
| 金額 | **沒有任何金額欄位**（`voucher_summary.py:219-221` 自己寫「物流追蹤不是支出記錄」） | 有；單價／小計／已付金額受 CM13 金額遮蔽 |
| 「狀態」 | 待叫料 → 已叫料（`ordered`）→ 已到料（`arrived`）：**兩個布林**（`case-management.html` 約 `:1060-1070` 的標籤；`dashboard.py:695` 把它們折成 pending／ordered／arrived） | `paidStatus` 三值＋`invoiceDate`；**沒有「已叫／已到貨」狀態** |
| 兩者的關聯 | **無**（沒有任何共同鍵；`materials[].id`＝時間戳，`materialOrders[].itemId`＝UUID） | 同左 |
| 下游 | 到料後可產生 `devices[]`（序號）→ 案件存檔時 `_sync_device_stock` **認領庫存序號**（`quotations.py:2472`）；首頁／採購頁的叫料進度（`dashboard.py:694`）；執行報告 PDF（`pdf_gen.py:2915`）；附件（`attachments.py:50-51`） | 營運報表成本（權責＝小計，歸月＝發票日否則付款日；現金＝已付金額，`recognition.py:276-296`）；總帳 E12 應付／E12b 付款（`case/gl_events.py:100-125`） |

結論：**「叫料管控」這個畫面名稱指第一份（物流）；「叫料」文件／財務指第二份（金額）**。派發的審核是「承諾支出」的那一步，落在金額上 ⇒ 真正對應的是第二份；但使用者說的「管控」又指第一份。建議的處理見 §3.0。

## 1. 現況：狀態機、誰能改、洞（**【已讀】**）

### 1.1 叫料（財務）`materialOrders[]`
- **沒有狀態機**，只有 `paidStatus` 與一個驗證函式。整份清單**整包覆蓋**。
- 唯一專屬寫入口 `PATCH /api/quotations/{no}/material-orders`（`modules/case/api/material_orders.py:58`）：
  - 權限：admin 以上**或**模組 `project_manage`（`:102`）＋有財務檢視（`:104`，CM13）；已結案 400（`:111`）；驗證只有「小計＝數量×單價」「paidStatus 與已付金額／日期一致」（`:116-133`）。**沒有任何簽核、沒有「已叫料／已到貨」概念；`paidStatus` 可由送出者直接設成 `paid`**（`:128-133` 只驗內部一致）。稽核 `material_orders.update`（`:153`）。
  - 另有 `PATCH …/{item_id}/invoice-date`（`:166-203`）：只登發票日，admin／專案經理／出納／財務，任何案件狀態（含已結案）都可登；**發票日決定權責歸月與 E12 的日期**。
- **第二個寫入口（真正的洞）：`PATCH /api/quotations/{no}/case-record`**（`quotations.py:2750`）。它**整包取代 `caseRecord`**（只保留 `stages`；`:2909-2913`）。呼叫者只要是「案件成員」（業務、協作者、案件角色、階段負責人）或管理員（`_is_case_member`，`:427`）：
  - 這支端點**對 `materialOrders` 完全沒有驗證**——不檢查小計、不檢查 paidStatus 一致性、不檢查已結案（已結案走半解鎖審核 `_gate_case_edit`，`:2888`，但那是整個案件的閘，不是叫料的）。
  - 也就是：**任何案件成員（不需 `project_manage`、不需 admin）都能新增叫料列、改單價／小計、把 `paidStatus` 設成 `paid` 並填已付金額與日期**；金額遮蔽帳號則由 `restore_case_record`（`financial_mask.py:142`）以資料庫現值覆蓋 `materialOrders`（所以只有「看得到金額」的成員能蓋掉）。目前畫面刻意不走這條（`mod-inventory.md §7.20`：「存檔刻意不併進 `saveCase()`」），但 **API 是通的**，這是「畫面沒入口≠沒洞」。
  - 第三個入口：`PUT /api/quotations/{no}`（整份報價單存檔；`quotations.py:1671`；草稿階段才可存，`_LOCKED`）與 `POST` 建立（`:1471`）都會寫 `data_json.caseRecord`，同理未驗 `materialOrders`。
- 結論（洞的精確版）：**今天可以不經任何第二個人，把叫料建立出來、標成已付、填發票日，並立刻進營運報表成本與總帳 E12／E12b 草稿**；而且這條路徑**不限於 `project_manage` 持有者**。

### 1.2 叫料管控（物流）`materials[]`
- 沒有專屬端點：**增刪、`ordered`、`arrived`、供應商、預計到貨日、序號全部隨 `PATCH /case-record` 一起存**（同上，案件成員即可）。
- 附件（到貨憑證、發票）有專屬上傳端點，**「任何登入使用者皆可」**（`quotations.py:4035` 註解；`:3062-3081` 寫入）——到貨證據誰都能附。
- **到料（`arrived`）不是純標記**：到料後前端展開 `devices[]`（SN／MAC，`onMaterialArrived`）；案件存檔時 `_sync_device_stock`（`quotations.py:2472`）對序號 diff，**認領／釋放庫存序號**（經 IP-19 `stock.serial`，與存檔同一交易）。⇒ **到貨登載會在沒有任何審核下動到庫存序號的狀態**（序號對得上才動；找不到就略過、不擋存檔）。
- 沒有金額，所以**不直接進成本／應付**；但「已叫料」是對外採購的事實，目前零控管。

### 1.3 下游（誰在讀、會被未審資料影響）
| 下游 | 規則 | 位置 | 後果 |
|---|---|---|---|
| 營運報表／權責成本 | 所有 `materialOrders` 小計計入，日期＝發票日，否則付款日（標「暫用」） | `recognition.py:276-296` | 未審的叫料直接進成本 |
| 營運報表／現金 | `paidStatus≠pending` 且有付款日 ⇒ 計 `paidAmount` | `recognition.py:281-288` | 同上 |
| 總帳 E12／E12b | 所有 entries 都產生事件（需日期） | `case/gl_events.py:100-125` | 未審叫料入帳草稿 |
| 付款 | **沒有付款流程**：`paidStatus` 是登記，不是出納付款；E12b 直接由它產生 | 同上 | 與派發不同：派發付款要走匯款申請（分層簽核＋出納），叫料**沒有**這道 |
| 庫存 | `materials[].devices[].sn` → `stock.serial` 認領 | `quotations.py:2472` | 見 1.2 |
| 首頁／採購頁叫料進度 | 讀 `materials[].ordered/arrived` | `dashboard.py:694` | 未核准的「叫料中」會被當真 |

### 1.4 與派發的差異（為什麼不能照抄）
- 派發有**獨立資料表與狀態機**（`contractor_dispatches.status`＋`/accept`）；叫料是 `data_json` 裡的**陣列、無狀態機、整包覆蓋**。
- 派發的付款有「匯款申請」這道天然閘；叫料**沒有**——這使「付款前審核」不夠，**建立當下的審核**更關鍵，而且「已付」登記本身就是洞（§3.4）。
- 叫料沒有單據編號、沒有佇列提供者、沒有信件類型（派發設計要新建的東西，這裡全要新建）。

## 2. 「完成」對叫料是什麼（回答要點 2）
派發的完成＝驗收→完工；叫料沒有對應狀態。依資料推得三個候選的「完成」節點（**【推論】**；已依派發「建立與完成都要審」解讀，細節見 §6 問 3）：
1. **到料（`arrived`）**：物流上「叫的料到了」；會觸發設備序號登載與庫存認領（1.2）。**最像派發的「驗收」**。
2. **已付（`paidStatus=paid`）**：財務上結清；目前無付款流程。
3. **發票日登錄（`invoiceDate`）**：權責認列的日期來源（決定成本歸月與 E12 日期）。
**審核前已被動到的東西**：成本（建立當下就計入）、總帳草稿（E12 見 1.3）、庫存序號（到料登載後存檔當下，若序號對得上）、應付／付款登記（`paidStatus`）——**四項都在沒有審核下發生**。
**（已裁示後的解讀）**：叫料的「完成」＝**到貨確認**（Q3：不簽核，記錄日期與確認人）；付款是另一道（叫料匯款申請，每單可多張、各自簽核、累計上限）。

## 3. 實作設計（方案 X：疊加審核表；已依全部裁示改寫）

### 3.0 審核的對象與物流旗標的閘（裁示 Q1）
- **審核單位＝`materialOrders[]` 的一列（金額承諾；叫料單）**。**金額為 0 的叫料單也走同一個流程**（裁示 Q4：客供料／庫存領用／免採購的料，開一張 $0 叫料單走審核；$0 單不需要匯款申請，報表與總帳本來就略過 0 元，`recognition.py:285／291`）。
- **物流旗標只能對著「已核准的叫料單」勾**：`materials[]` 項目新增選填鍵 `orderItemId`（指向 `materialOrders[].itemId`）；**`ordered`＝true 要求 `orderItemId` 指到一張已核准的叫料單**（舊單不算）。**`arrived`＝true 也要求同一張已核准的單**，但**到貨不需要簽核**（裁示 Q3）：同一個人可以確認，**必須記錄到貨日期與確認人**（見 3.2）。沒有 `orderItemId` 的既有物流項目維持現狀（不溯及既往），但**不能再把狀態往前推**（`ordered／arrived` 由 false→true 一律要連結）。

### 3.1 儲存：疊加審核表（裁示 Q5：方案 X）
`materialOrders` 住在 `data_json`、沒有資料表；審核欄位**不塞進每列**（佇列要掃全部案件 JSON、整包覆蓋會蓋掉審核狀態、沒有單號可引用）。新增薄表（case migration `0004`，只加不改）：
```
case_material_approvals(
  quote_no TEXT, item_id TEXT,                    -- 鍵＝(案件, materialOrders.itemId)
  doc_code TEXT UNIQUE,                           -- 叫料單號 MO-YYYYMMDD-NNNN（next_entity_code）
  status TEXT,                                    -- 草稿／待審核／簽核中／已核准／已退回
  approval_json TEXT, submitted_by TEXT, submitted_at TEXT, approved_at TEXT,
  content_hash TEXT,                              -- 核准當時的實質欄位雜湊（品名、數量、單位、單價、小計、supplierId）
  received_on TEXT, received_by TEXT, received_at TEXT,   -- 到貨確認（裁示 Q3）：到貨日期、確認人、確認時間；不簽核
  version INTEGER, created_at TEXT,
  PRIMARY KEY(quote_no, item_id))
```
- **沒有疊加列＝舊單**（自動寬限；不回填、不標記遷移）；畫面標灰色「舊單（未經審核）」徽章。實質欄位被改 ⇒ 該單視為新規則適用，**要先送審**（同派發 Q5）。
- 實質欄位雜湊：核准時存；之後任何寫入使實質欄位與雜湊不符 ⇒ 自動回「待重新送審」。**風險**：雜湊欄位清單要與前端一致，數字要正規化（浮點）。

### 3.2 狀態：一個簽核階段＋到貨確認（裁示 Q3：到貨不走分層簽核）
```
新增叫料單（金額可為 0；不得標已叫／已到／已付）
  └送審→ 待審核 → 簽核中 → 已核准
                 └退回（必填理由）→ 已退回 →（修改後再送）
已核准後：連結的物流項目可標「已叫料」→ 到貨時勾「已到料」
          ＝ 必填到貨日期＋記錄確認人與時間（不簽核；同一人可確認）→ 寫 received_on／received_by／received_at、寫稽核、顯示在叫料單上
          → 設備序號才會被存檔流程認領庫存 → 付款走 3.4 的匯款申請（不以到貨為前置）
```
- 簽核流程：重用 `helpers/tiered_approval.py` 既有原語：**申請人部門主管→組織鏈→最高管理者；沒設簽核層＝直接核准；不能自己簽自己**（派發 Q1）；**不設金額門檻**（派發決定）。`register_doc_type('material_order', '叫料')`；預設跟統一流程。
- 預設（沿用派發的授權預設，未再問）：送審者＝創建者／該案負責業務／協作者／admin 以上；核准後實質欄位變動 ⇒ 重新送審（備註、日期、發票欄位免審）；取消已核准＝admin 以上＋必填理由＋稽核，**已有匯款申請者限 superadmin**。
- 到貨確認的權限：案件成員（業務、協作者、案件角色）、admin 以上；**沒有「不能自己確認」限制**（裁示）；取消／更正到貨日期留稽核（`material_orders.receive／.receive_undo`）。

### 3.3 寫入口的閘——**關掉 `case-record` 後門（裁示 Q8）：所有寫入都過閘**
一支共用驗證 `material_orders_guard(conn, quote_no, old_cr, new_cr, user)` 於**四個**寫入口一律呼叫（突變測試逐一拿掉）：
1. `PATCH /material-orders`（`material_orders.py:58`）：保留既有驗證；新增：新列強制未核准（`paidStatus` 必須 `pending`、已付金額／日期清空）；**`paidStatus／paidAmount／paidDate` 不再由此端點寫入**（只有 3.4 的付款寫回函式能寫；**上線後舊單也一樣：不再有「登記已付」**，裁示 Q5）；實質欄位變更 ⇒ 待重新送審。
2. **`PATCH /case-record`（`quotations.py:2750`，真正的洞）**：`materialOrders` 與 `materials[]` 的 `ordered／arrived／orderItemId／devices／到貨欄位` 以**資料庫現值為準**（比照 `restore_case_record` 對金額的處理，`financial_mask.py:112/142` 已有先例）；body 帶的差異只有「閘函式放行的」才寫入。**裁示 Q6：只拒絕有問題的項目，其餘照存；回應帶 `rejected[]`（逐項：`itemId／欄位／原因碼／中文說明`），畫面逐項提示**（不整筆拒絕——與 `payment` 的「整筆拒絕」不同，理由：叫料頁籤與其他分段共用同一支存檔）。分段存（`segments`）同樣過閘。已結案半解鎖的 `_gate_case_edit` 路徑不變（閘在它之前執行）。
3. `PUT／POST /api/quotations`（`:1671／:1471`）：同上，剝掉 body 的 `caseRecord.materialOrders` 與物流旗標變更（以現值為準；同樣回 `rejected[]`）。
4. 發票日端點 `…/invoice-date`（`:166`）：只動發票日；若該單**待審核／簽核中**則拒（避免審核中改日期），其他維持現行權限（含已結案）。
- **靜態守門 G-M1**：掃 `modules/case` 內所有對 `caseRecord.materialOrders`／`.materials` 的寫入，只准在 `material_orders_guard` 與付款寫回函式內出現（突變：別處加一條 ⇒ 紅）。
- **誰在依賴後門**：沒有正式機存取，無法由我查；§7 給唯讀查詢供使用者自己跑（找出「叫料列不是由專屬端點建立」的案件與帳號）。上線公告要列影響面。

### 3.4 付款：比照派發＝「叫料匯款申請」＋出納（裁示：可部分付款、累計上限；**定案解讀：每單可多張申請，每張各自簽核＋出納**）
現況「已付」只是登記（§1.1），E12b 直接由它產生。改成**與承攬商匯款申請同一套模式**（`contractor_payment_vouchers`：申請→分層簽核→出納「已匯款」→實付／手續費／差額審核）：
- **每張叫料單可開多張匯款申請**（主持定案，使用者授權；理由：與派發匯款單一致，**每一次動錢都經過簽核**）：唯一鍵 `UNIQUE(quote_no, item_id, seq)`（`seq`＝該叫料單的第幾張，從 1 起）；**無款別（不分訂金／進度／完工）**。每張申請各自有金額（預設＝叫料單小計扣掉「已申請累計」；> 0；superadmin 可覆寫上限＋必填理由）。
- **累計上限（跨申請）**：同一叫料單所有**未作廢**申請（含草稿與待審核，**鎖額度**，同發票開立單 §5.9 的作法）的 `amount_approved` 合計 ≤ 叫料單小計；畫面顯示「已申請 X／剩餘 Y」；超過 ⇒ 409。作廢／退回後額度釋出。
- **每張申請各自走完整流程**：分層簽核（同上鏈）→ 核准 → 出納「已匯款」。出納對**每張申請**可分次登錄付款（每次一筆「付款明細」：日期、實付、手續費、差額審核），**該申請累計實付不得超過該申請金額**；累計＝申請金額 ⇒ 該申請結清、從待付款消失；未滿則留在待付款並顯示剩餘額。叫料單整體的 `paidStatus` 由各申請的付款明細合計推得（0＝`pending`；0＜合計＜小計＝`partial`；＝小計＝`paid`）。
- 新表（case `0004` 同一支 migration）：
  - `case_material_payments`：`id、doc_code（MP-YYYYMMDD-NNNN，每張申請一個單號）、quote_no、item_id、seq、supplier_id、amount_approved、snapshot_json（凍結叫料單、供應商資料與**收款帳戶**）、status（草稿／待審核／簽核中／已核准／已退回／作廢）、approval_json、submitted_by／at、approved_at、created_by、created_at`，`UNIQUE(quote_no, item_id, seq)`。
  - `case_material_payment_lines`：`id、payment_id（屬於哪一張申請）、paid_at、amount、fee、remit_review、paid_by、created_at`（出納每次付款一列；`remit_review` 沿用「差額待審核」）。
  - doc type `material_payment`（叫料匯款）另登記，簽核鏈同上。
- **建立門檻**：對應叫料單已核准（**舊單例外**：舊單未付餘額要付款，一律走本流程，**不要求補核准**＝不溯及既往，裁示 Q5）；**不要求到貨確認**（沿用派發「完工審核不是匯款前置」的預設）。**$0 叫料單不可開匯款申請**。
- **上線後不再有「登記已付」**：舊單與新單一律只能由匯款流程寫 `paid*`；已付的歷史資料不動。
- **出納整合走 IP-100／IP-102 現成名稱空間**（`INTEGRATION-POINTS.md` IP-100：「之後其他模組的請款可登記同一個名稱空間，出納不用改」）：`("payables.pending","case_material")`、`("remit.reviews","case_material")` 兩個提供者（owner＝case，`modules/case/payables.py` 旁新檔）；出納頁「請款待付款」自動出現。**契約為加法**：`key`＝申請 id（每張申請一列）；`pending()` 回該申請的「剩餘應付」（`amount`＝申請金額−該申請累計）、`mark_paid` 每次記一筆付款明細並回累計與剩餘。出納 `mark_paid` 沿用 `remit`（實付／手續費／差額審核）與付款科目選填。
- **供應商（裁示 Q2 的預設）**：叫料單**要求 `supplierId`**（新增選填鍵 `materialOrders[].supplierId`，指向 `suppliers`；**新建的叫料單必填**；舊單在開匯款申請時選）。**收款帳戶**：優先取供應商主檔；**唯讀查證結果【已讀】**：`suppliers` 表欄位是 `id／code／name／tax_id／phone／lead_time_days／data_json／created_at／updated_at`（`db.py:553`、`modules/supply/api/suppliers.py:41`），`SupplierIn`＝`name／tax_id／phone／data／lead_time_days`，**供應商頁沒有任何銀行帳號欄位**（`suppliers.html` 查無 bank／帳號／匯款輸入；`data` 只存聯絡人與拜訪紀錄之類）⇒ **第一版一律在匯款申請上填收款帳戶（銀行代碼、戶名、帳號），存進申請的 `snapshot_json`**；**第一版不改供應商主檔結構**。日後若供應商主檔加帳戶欄位，申請改預填即可。
  - **F2（個資）**：供應商可能是個人 ⇒ 帳戶欄位比照 A2 收款人（`archive._F2_FIELDS['案件額外支出']`）處理：一般備份拿掉、完整列只進個資資料夾（`case_material_payments` 加一個 `_F2_FIELDS` 條目＋測試）；不進佇列詳情與信件；畫面遮蔽比照 `bank_mask`。
  - **實作提醒（非裁示）**：`GET /api/suppliers` 對非 admin 回空陣列（`suppliers.py:37-38`）⇒ 案件成員／專案經理選供應商需要一支輕量的「供應商選單」端點（只回 `id／code／name`，需登入＋案件模組權限），不可直接放寬現有列表。
- **寫回與報表**：`mark_paid` 經**單一內部寫入函式**把「各申請付款明細合計」寫回 `materialOrders[].paidStatus／paidAmount／paidDate`（`partial／paid`、累計實付、最後付款日），維持畫面與舊讀法。**但分次付款後，現金口徑不能再用「一列一個日期」**：`recognition.material_entries` 現金分支（`recognition.py:281-288`）與 E12b（`case/gl_events.py:117-126`）**需要改讀付款明細**——有匯款申請的叫料單，每筆付款明細一列（日期＝該筆付款日、金額＝該筆實付）；沒有申請的舊單（已付歷史）維持讀 JSON。E12b 的 `source_key` 要含明細 id（`<案件>::<itemId>::<lineId>`；明細屬於哪一張申請由 `payment_id` 追溯）以保持冪等；實付≠應付的差額與手續費沿用 IP-102 既有 `expense.entries` 做法（`remit_fee_case` 類）。

### 3.5 報表／總帳（派發 Q6 決定，原樣套用）
| 面向 | 規則 |
|---|---|
| 營運報表成本（權責） | **草稿與已退回不計；待審核／簽核中計入並標「待審核」；已核准正常；舊單照舊**。位置：`recognition.py:290-296`（讀疊加表狀態）。**上線公告數字變動**（派發同）。 |
| 營運報表（現金） | 有匯款申請者改讀付款明細（見 3.4）；舊單歷史照舊（`:281-288`）。 |
| 總帳 E12 | 只在「叫料單已核准」或舊單才產生（`case/gl_events.py:102-116`）。 |
| 總帳 E12b | 來源改為付款明細（每筆一個事件）；舊單歷史維持現狀。 |
| 首頁／採購頁叫料進度 | `dashboard.py:694` 讀 `ordered／arrived` 前先看閘：未核准的不顯示為「叫料中／到料」。 |
| 庫存 | `_sync_device_stock`（`quotations.py:2472`）只對「已核准叫料單＋已記錄到貨確認」的物流項目的序號認領；其餘跳過並回 notice。 |

## 4. 共用機制 `approval_gate`：**選配的第二階段重構**（裁示）
- **不阻擋、不綁在一起**：先**各自出貨**——派發（2e，`wip/dispatch-approval-2e`，subcontract）與叫料疊加（本文，case）各寫各的，**沿用既有 `tiered_approval` 原語**，不新增 L1 共用檔。理由：派發尚未動工、兩邊資料形狀不同（資料表 vs 疊加表＋JSON），過早抽象的風險大於收益；而且共用檔屬 L1，需全量班與兩個消費者同步。
- **為了日後重構「機械式」**：兩邊遵守同一組慣例（寫進兩份設計）：①審核狀態值固定 `''(舊單)／草稿／待審核／簽核中／已核准／已退回`；②`approval_json` 形狀＝既有 tiers 歷程格式；③單號欄 `doc_code`＋`next_entity_code`；④佇列項目鍵（`type／typeLabel／quoteNo／docCode／subject／total／openUrl／approveUrl／rejectUrl／rejectField／caseless`）；⑤信件類型命名 `<doc>_submitted／_next_tier／_approved／_returned`（信內不放金額）；⑥稽核動作 `<owner>.<doc>.<submit|approve|reject|withdraw|cancel>`；⑦「只有閘函式寫狀態」的靜態守門命名 G-D1／G-M1。
- **何時才抽**：兩邊上線後各自穩定、第三個需求出現時，再抽 `helpers/approval_gate.py`（`GateSubject` 描述＋一致性測試台）；**與 hichan-2e 協調**：若 2e 同意在派發實作時直接寫成 `GateSubject`，叫料班就當第二個消費者（共用檔由派發班落地）；否則維持各自出貨。**【請主持向 2e 確認】**（證據：分層簽核邏輯已手抄約 13 處——`case_extra_expenses.py:740/840/1336/1422`、`completion_notes.py:415/508`、`contractor_vouchers.py:450/551`、`shipping_notes.py:365/469`、`invoice_vouchers.py:507/607`、`payment_requests.py:600/699`、`vouchers.py:687`、`bonus.py:1187/2218`、`quotations.py:539/4880`、`custom_modules.py:1281/1388`、`vendor_contractors.py:760`）。

## 5. 佇列、信件、稽核、金額、測試、工量
- **佇列**：`approval.queue_items` 新提供者（owner＝case）：`material_order`（叫料）、`material_payment`（叫料匯款）；**沒有「到料審核」項目**（裁示 Q3）。`routers/approval_queue.py:203` 的 `_ITEM_TYPE_LABELS` 與 `approval-queue.html` 的 `docTypeLabel` 同步（守門 `test_approval_labels_match` 抓）。
- **信件**：`mail_types.register`（owner＝case）兩組各四種＋個人通知偏好；**信內不放金額**；站內通知照舊。
- **稽核**：`material_orders.submit／approve／reject／withdraw／cancel／receive／receive_undo`、`material_payment.*`（detail 帶 tier、理由、品名／單號／到貨日期，不含帳號與完整金額）；既有 `material_orders.update／.invoice_date` 保留；寫入端點稽核守門（`tests/test_write_endpoints_are_audited_2026_09_24.py`）涵蓋新端點。
- **金額可見**：簽核人在佇列看得到金額（共用 `routers/approval_queue.py:302` `_can_see_queue_money`）；沒有財務檢視者沿用 CM13 遮蔽，且**無法建立／送審有金額的叫料列**（`material_orders.py:104`，並補到 `case-record` 路徑）；供應商帳戶不進佇列詳情。
- **測試（不跑；計畫）**：四個寫入口矩陣（新列強制未核准、直送 `paidStatus=paid` 被拒——**含舊單**、整包覆蓋不能蓋掉審核狀態與物流旗標）；**`case-record` 只拒有問題的項目、其餘照存、`rejected[]` 內容**；狀態逐格；簽核（單層／多層／自簽層／無簽核層／退回重送／撤回）；$0 叫料單走流程但不能開匯款；到貨確認（必填日期、記錄確認人、同一人可確認、未核准不可勾、稽核）；庫存認領時機；匯款申請（**每單多張、各自簽核、跨申請累計上限鎖額度、作廢釋出額度**、每張申請分次付款、舊單走本流程、差額審核、`paid*` 唯一寫入點、F2 備份）；出納提供者（列出剩餘額／分次登錄後消失／反向控制＝移除模組）；報表（權責三態、現金改讀付款明細）與總帳（E12 核准或舊單、E12b 每筆明細一個事件且冪等）。
- **守門**：G-M1；`approval labels match`；`case_read_scope`（新端點帶案件號）；F2 備份守門；頁面守門（前端動到時）。
- **突變（固定守門題，比照 G5，每項含正向控制）**：拿掉四個入口任一的 guard 呼叫、guard 放行新列帶 `paid`、付款寫回函式以外的路徑可寫 `paid*`（含舊單）、跨申請累計上限拿掉、疊加表不影響報表、`gl_events` 不看核准、E12b 仍讀 JSON 而非付款明細、`orderItemId` 閘拿掉、到貨確認不記錄人／日期、雜湊比對拿掉、自簽檢查拿掉、庫存認領不看到貨確認。
- **e2e（瀏覽器＋截圖）**：新增叫料（核准前「已叫料」「已付」disabled）→送審→簽核人核准→連結物流項目標已叫料→勾已到料（填日期、畫面顯示確認人）→序號認領→開叫料匯款申請（填收款帳戶）→簽核→出納分兩次登錄付款（第一次部分）→報表與總帳數字（兩筆付款各自歸月）；反向：API 直送 `paidStatus=paid`／`case-record` 直改（舊單也一樣）⇒ 被拒並回 `rejected[]`、其餘欄位照存；退回→修改→再送；核准後改金額 ⇒ 待重新送審；$0 叫料單；舊單徽章與舊單走匯款；金額遮蔽帳號。
- **工量（粗估，【推論】）**：疊加表＋閘＋四入口＋佇列／信件／稽核（後端）約 **2 班**；物流旗標與連結（`orderItemId`）、到貨確認、庫存時機、前端徽章／按鈕／供應商欄／供應商選單約 **1 班**；叫料匯款申請（兩張表、簽核、額度鎖、出納提供者、付款明細與報表／總帳改讀、F2）約 **1.5～2 班**；測試＋e2e＋突變約 **1 班**；合計約 **5.5～6 班**（比先前少一個到料審核階段、多了付款明細與現金口徑改讀）。層級：case（L2）＋前端；arap 出納**不改**（走既有名稱空間）⇒ **全量班**；不動 L0、**不新增 L1 共用檔**（`approval_gate` 為選配第二階段）。

## 6. 使用者裁示結果（Q1–Q6 全部已答；2026-10-01）
| # | 問題 | 決定 | 落在本文 |
|---|---|---|---|
| Q1 | 付款款別與分期 | **可部分付款，累計不得超過；沒有款別（訂金／進度）。解讀已定案（使用者授權主持）：一張叫料單可開「多張」匯款申請，每張各自分層簽核＋出納，累計受叫料單小計限制** | §3.4 |
| Q2 | 供應商與收款帳戶 | （主持預設）**要求 `supplierId`；收款帳戶優先取供應商主檔，沒有就在匯款申請上填、存進申請快照；第一版不改供應商主檔結構**（唯讀查證：主檔沒有帳戶欄位 ⇒ 第一版一律在申請上填） | §3.4 |
| Q3 | 到貨 | **不走分層簽核**；同一人可確認；**必須記錄到貨日期與確認人（稽核、顯示在叫料單上）**；旗標只能對著已核准的叫料單勾 | §3.0、§3.2 |
| Q4 | 沒有金額的物流項目（客供／庫存領用） | **開一張 $0 叫料單，走同一個流程** | §3.0 |
| Q5 | 上線後既有未付叫料 | **一律走新的匯款申請流程**（不溯及既往補核准）；**上線後不再有「登記已付」** | §3.3、§3.4 |
| Q6 | `case-record` 後門的呈現 | （主持預設）**只拒有問題的項目，其餘照存；回應 `rejected[]`（逐項原因）** | §3.3 |

## 7. 唯讀盤點查詢（給使用者在正式機自己執行；**不連線、不寫入**；以 `sqlite3 -readonly` 或「唯讀」開啟資料庫檔）
目的：看影響面，以及誰「不是經叫料專屬端點」建立／修改叫料（後門依賴的線索；稽核表只記到動作層級，無法精確證明，僅作線索）。
```sql
-- A. 叫料列總覽：案件數、列數、金額、已付
SELECT COUNT(DISTINCT q.quote_no) AS cases, COUNT(*) AS rows_,
       ROUND(SUM(COALESCE(json_extract(m.value,'$.totalPrice'),0))) AS total_amount,
       ROUND(SUM(COALESCE(json_extract(m.value,'$.paidAmount'),0))) AS paid_amount
FROM quotations q, json_each(COALESCE(json_extract(q.data_json,'$.caseRecord.materialOrders'),'[]')) m;

SELECT json_extract(m.value,'$.paidStatus') AS paid_status, COUNT(*) AS n
FROM quotations q, json_each(COALESCE(json_extract(q.data_json,'$.caseRecord.materialOrders'),'[]')) m GROUP BY 1;

-- A2. 未付清的舊單（上線後只能走匯款申請）：筆數與未付餘額
SELECT COUNT(*) AS unpaid_rows,
       ROUND(SUM(COALESCE(json_extract(m.value,'$.totalPrice'),0) - COALESCE(json_extract(m.value,'$.paidAmount'),0))) AS unpaid_amount
FROM quotations q, json_each(COALESCE(json_extract(q.data_json,'$.caseRecord.materialOrders'),'[]')) m
WHERE COALESCE(json_extract(m.value,'$.paidStatus'),'pending') <> 'paid';

-- B. 有叫料列、但稽核表從沒有「專屬端點」更新紀錄的案件（線索：叫料可能是經案件存檔或報價單存檔寫入）
SELECT q.quote_no,
       json_array_length(COALESCE(json_extract(q.data_json,'$.caseRecord.materialOrders'),'[]')) AS n_rows,
       (SELECT COUNT(*) FROM audit_log a WHERE a.action='material_orders.update' AND a.target_id=q.quote_no) AS via_endpoint
FROM quotations q
WHERE json_array_length(COALESCE(json_extract(q.data_json,'$.caseRecord.materialOrders'),'[]')) > 0
ORDER BY via_endpoint, n_rows DESC;

-- C. 誰用過專屬端點；以及誰存過案件記錄（後門的潛在使用者，範圍很大，僅看分布）
SELECT username, COUNT(*) AS n, MIN(at) AS first_at, MAX(at) AS last_at FROM audit_log
WHERE action IN ('material_orders.update','material_orders.invoice_date') GROUP BY username;
SELECT username, COUNT(*) AS n FROM audit_log WHERE action='case.update' GROUP BY username ORDER BY n DESC LIMIT 30;

-- D. 物流旗標現況：已叫料／已到料筆數（目前沒有任何連結鍵，全部都「沒連結」）
SELECT SUM(COALESCE(json_extract(m.value,'$.ordered'),0)) AS ordered, SUM(COALESCE(json_extract(m.value,'$.arrived'),0)) AS arrived, COUNT(*) AS items
FROM quotations q, json_each(COALESCE(json_extract(q.data_json,'$.caseRecord.materials'),'[]')) m;

-- E. 供應商主檔的 data_json 有哪些鍵（確認有沒有帳戶資料；只看鍵名，不印內容）
SELECT DISTINCT j.key FROM suppliers s, json_each(s.data_json) j ORDER BY 1;
```
**【未驗】** 這些查詢我沒有執行（沒有資料庫、也不跑測試）；欄位名稱取自程式（`audit_log.action／target_id／username／at`、`quotations.data_json`、`suppliers.data_json`），上線前請先在開發庫上確認語法。

## 8. 狀態：**已裁示，可開工（ready for implementation）**
- Q1–Q6 全部已答（Q1 的解讀已由主持定案：多張申請、各自簽核、跨申請累計上限），**沒有任何待答或待確認事項阻擋開工**。
- **建議實作順序（可分班）**：①疊加表＋`material_orders_guard`＋四入口＋叫料核准（佇列／信件／稽核）＋報表／總帳閘＋靜態守門與突變；②物流旗標連結＋到貨確認＋庫存時機＋前端；③叫料匯款申請（表、簽核、出納提供者、付款明細、現金口徑與 E12b 改讀、F2）；④e2e 與整套守門。
- 與派發的接點：派發設計附錄 A（款別）仍待使用者回答，叫料**不採款別**（裁示 Q1），與派發互不影響；兩邊共用的「累計上限鎖額度」「差額審核」沿用既有機制。

### 8.1 上線公告要寫的行為（31-C 實作後的已知效果；**不是缺陷，但數字會動**）
- **舊單（沒有審核單）照舊計入權責成本**；但舊單的**實質欄位**（品名、數量、單位、單價、總價、供應商）一經修改，即建立審核單並回到草稿，**重新送審並核准前，不計入權責成本**（草稿不計），營運報表該月叫料成本會**暫時變小**。待審核／簽核中則計入並標「待審核」。
- 總帳 E12 同理：只有已核准與舊單入帳；審核中不入帳並在 notice 說明筆數。現金口徑與 E12b 不受影響（付出去的錢是事實）。
- 公告建議：「修改既有叫料單的金額／數量／品名／供應商後需重新送審；送審核准前該筆不計入權責成本與總帳 E12。」上線首週請財務留意報表月數字變動。

## 9. 與派發設計的差異（只列差異）
| 項目 | 派發 | 叫料（本文） |
|---|---|---|
| 資料位置 | 資料表 `contractor_dispatches`（加欄位） | `data_json` 陣列 ⇒ **疊加審核表**（無疊加列＝舊單） |
| 現有狀態機 | 有（`/accept`） | 無（兩個布林＋`paidStatus`） |
| 洞 | `POST／PUT` 寫 `status` | **`case-record` 整包覆蓋**＋`material-orders` 可直接標已付 ⇒ 四個入口一律過閘 |
| 完成（驗收／到貨） | 完工要分層簽核（派發 Q4） | **到貨不簽核**，只記錄日期與確認人（叫料 Q3） |
| 付款 | 匯款申請（可有款別，附錄 A 待答） | 匯款申請，**無款別**，**每單可多張、各自簽核＋出納，跨申請累計上限**；每張可分次付款 |
| 付款後帳務 | 一申請一次付款 | **付款明細**；現金口徑與 E12b 改讀明細 |
| 庫存 | 無 | 已核准＋已記錄到貨確認才認領序號 |
| 共用機制 | — | 各自出貨，慣例對齊，`approval_gate` 為選配第二階段 |

## 10. 不做（本期）
金額門檻分流、跨案件批次送審、叫料範本、行動版簽核、把既有 13 處簽核遷入共用閘、改走 A2 請購／採購單（方案 Y，已裁示不採）、供應商主檔加銀行欄位（日後再議）、款別（訂金／進度）。
