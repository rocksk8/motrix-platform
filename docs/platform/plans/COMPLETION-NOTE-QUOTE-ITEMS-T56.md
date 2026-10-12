# 完工單自動帶入報價單項目——設計筆記（僅文件，未跑任何測試）

> **r2 修訂（依 0d 稽核）**：①端點權限收斂為「管理員＋案件頁可讀」，不新增讀取者；②`quoteItemId` 為字串；③白名單移除 `notes`；④報價單狀態閘；⑤累計口徑；⑥`quoteSync` 儲存；⑦M3 相依；⑧表頭範圍同閘。
> **r4 修訂（依使用者表單與更正）**：表單答案**不是固定行為，而是設定項的預設值**（框架優先：管理者在設定中心可調，程式內只留不可變的安全底線）。①Q1 印金額＝設定（預設關；開啟仍受財務權限約束）；②Q2 回簽前能否帶入＝設定（預設：已送出未回簽可帶入並提示）；③Q6 **開放有案件權限的業務建立／編輯完工單＝權限變更**，閘門重新設計（§6b），**實作前需另行的非作者權限審查**；④M3 側使用者已定：整張報價鎖定、成案／PO 後禁止取消回簽。
> 2026-10-12；委託：hichan-1c（使用者新需求：「完工單要能自動帶入報價單項目」）。底：`origin/platform` c14f0a1df（內容＝正式機 M1-a `4eb521384`；**M2／M3 尚未上線**）。
> 標記：**【需使用者回答】**＝會改變行為或對外輸出，回答前不實作該部分；**【PM 預設】**＝我給預設值，不需問，使用者可事後調。**UNKNOWN**＝沒查到證據。
> 框架優先（記憶 `feedback_framework_first_no_hardcode`）：行為開關放設定中心，程式內只有「安全底線」（不帶金額、守門權限）。

## 0. 結論（先講）

1. **今天完全沒有這個功能**：新建完工單只會從報價單帶「客戶、專案名稱、送貨地址、聯絡人、電話」（`completion-note-form.html::prefillFromCase`，約 413–434 行）；**完成項目明細是空的**，畫面寫「尚無項目，按上方『＋ 項目』開始」。（查過：`completion_notes.py`、`case-management-completion.js`、README、出貨單 `supply/api/shipping_notes.py`——沒有任何報價單→完工單的帶入程式。）
2. **欄位幾乎天然對得上**：完工單項目 `description／qty／unit／status／notes`（＋分段 `type=header`）；報價單項目 `id`(**字串**：`crypto.randomUUID()` 或 `id-<時間>-<亂數>`，`quotation-form.html` `genId()` 約 2524–2528；舊資料可能無 id)`／description／brand／qty／unit／…／notes`（＋`type=header`）。**不需要資料庫遷移**——項目存在 `items_json`、加性欄位即可（比照出貨單 `materialLink` 的加性做法）。
3. **建議做法**：新增一支**唯讀**「可帶入項目」端點（後端白名單只回非金額欄位，且只給**能建立／編輯完工單草稿的管理員＋讀得到該案件頁的人**）＋ 完工單表單「從報價單帶入」（新建時自動執行一次、草稿可再按）。帶入後**全部可編輯**；每列記住來源品項編號（字串），分批完工時顯示「報價 N／已完工 M／本次預設 剩餘」。擇一方案報價**只帶已回簽選定的品項**。
4. **金額不進完工單**（預設）：後端白名單 `{id, type, description, brand, qty, unit}`，**任何金額鍵（`cost／margin／unitPrice／amount`）一律不出**，守門測試鎖住。完工單要不要印金額是**設定項（預設關；開啟時仍依 `money_visible` 約束）**。
5. **工量 ≈ 7.0–8.5 pd（約 7.75）**（§7；含印金額開關與權限閘重新設計；不含另行的權限審查），主要風險＝擇一方案相依 M3、報價單事後變動的對帳（§8）。

## 1. 完工單現況（資料模型、誰編輯、狀態、PDF）

| 面向 | 現況（檔案：行） |
|---|---|
| 資料表 | `completion_notes`：`note_no`(CN…)、`quote_no`、`status`、客戶/專案/地址、`start_date`、`completion_date`、`site_manager`、`recipient`、`contact_phone`、`items_json`、`work_summary`、`test_result`、`warranty_months`、`pending_items`、`notes`、`data_json`（`labels` 標題覆寫、`approval` 簽核）、簽收欄位。一張報價單可對多張完工單（`completion_notes.py` 檔頭）。 |
| 項目形狀 | `{description, qty, unit, status(完成/部分完成/未施作), notes}`，分段標題 `{type:'header', description}`。`_validate`（203–218）只檢 `status`，其餘鍵不限制。**沒有金額欄、沒有來源連結。** |
| 誰能編輯（今天） | 建立／修改／刪除皆 `_require_admin`＝`superadmin`／`admin`（120–122、278、320、367）；**僅草稿可編輯**（329–330）；樂觀鎖 `expected_updated_at`（335–337）。讀取：`guard_case_access(… allow_module="case_manage")`（單筆 `_readable_note`）。 |
| 狀態與簽核 | 草稿 → 申請完工（`/submit`：至少 1 項完工項目＋完工日期必填）→ 分層簽核（`unified_approval_flow`，類型 `completion`）→ 已核准；退回→草稿；客戶回簽（`signed-toggle`／上傳回簽檔）。無庫存扣減。 |
| PDF | `completion_pdf.py`：列出項目 `description／qty／unit／status／notes`（56–76 行），**不印任何金額**。客戶簽章聯，屬客戶可見文件。 |
| 前端 | `frontend/pages/completion-note-form.html`（項目列 200–224；`addItem`／`addHeader`／`removeItem` 479–481）；清單在 `case-management-completion.js`（只留清單與狀態動作）。 |
| 標題可自訂 | `data_json.labels`＋5 組預設用語（工程/系統/供應/網路/維運）；`itemColumn` 等欄名可改（本功能不動，沿用）。 |

## 2. 報價單項目在哪裡

- 存於 `quotations.data_json.items[]`（`GET /api/quotations/{no}` 回 `data.items`；`modules/case/api/quotations.py:1267`）。項目鍵：`id`(字串，見上)、`description`、`brand`、`qty`、`unit`、`cost`、`margin`、`unitPrice`、`unitPriceOverride`、`amount`、`notes`、`type`(`header`)（`quotation-form.html:2273`、2534；`profit_guard.item_amount` 118–122）。
- **金額遮蔽**：`helpers/financial_mask.py`——`ITEM_MONEY_KEYS = (cost, margin, unitPrice, amount)`；`quote_money_visible()`＝superadmin／admin／sales／財務角色看得到報價單層級單價；其餘角色後端剔除（`mask_quotation_data`）。**完工單編輯者（admin+）本來就看得到單價**，但完工單讀取者（`case_manage` 模組持有者）不一定。
- **擇一方案（M3，尚未上線）**：`M3-ALTQUOTE-WORK-BREAKDOWN-T56.md`（分支 `wip/t56-1d-m3-altquote-plan-r1`）——品項 `altGroup`、報價單 `altPicks={組:品項id}`、`profit_guard.counted_items(q)`＝非擇一項＋各組**已選**項；回簽必須選定、回簽後品項鎖定、取消回簽清除選定。M3 前的報價單沒有這些鍵＝全部計入。

## 3. 提案：自動帶入的行為

### 3.1 帶入什麼（來源集合）

**報價單狀態閘（先於一切）**：報價單 `status`（欄位值 `草稿／待審核／簽核中／已送出／已取消／已拒絕`；`已成案／已結案` 是 `deal_tag`，不是 `status`）——
- `已送出`（含已成案／已結案）⇒ 可帶入。
- `草稿／待審核／簽核中` ⇒ **拒絕帶入**（409，白話：「報價單還在編輯或簽核中，項目可能還會變，請等報價送出後再帶入」）——品項此時還在改動，帶入的內容沒有依據。（Q2 只剩「已送出但尚未回簽」要不要擋。）
- `已取消／已拒絕` ⇒ 拒絕帶入（409）。注意 `reject_quotation` 會把被拒的單**改號**成 `-R{n}` 新版（`_next_revision_no`，`quotations.py:209-215`）：累計查詢與帶入一律只看**目前這個 `quote_no`**，舊號底下既有的完工單不會被併進新號的累計（現行行為，不另處理）。
- **來源＝「這張報價單目前計入的品項」**：呼叫 `counted_items(q)`（M3 後）；M3 前 `counted_items` 不存在 ⇒ 降級為「全部品項」（`getattr` 保護，無 `altGroup` 的單逐位元同今日）。
- 擇一單：**只帶回簽選定的品項**（`altPicks` 完整）。有未選定組別（未回簽）⇒ 只帶非擇一品項，並在畫面白話提示「方案尚未選定，這幾組沒有帶入」（Q3 決定是否直接擋）。
- 分段標題（`type=header`）一併帶入（設定可關）。數量為 0 或空的品項照帶（現場可改），不靜默丟棄。

### 3.2 怎麼帶
- 新建完工單進表單時：**自動帶入一次**（取代空白列表）；之後草稿狀態有「從報價單重新帶入」按鈕。帶入是**前端先取預覽、使用者看得到並可改、按儲存才寫入**，後端不偷偷改單據。【PM 預設】
- 每列：`description` ← 報價品名（`brand` 預設併入「品牌 品名」，設定可關）、`qty` ← 預設值見 3.3、`unit` ← 報價單位、`status` ← 預設「完成」（設定可改）、`notes` ← 空白（報價備註不帶：常含內部提醒）。
- 加性來源欄位（存在 `items_json` 每列）：`quoteItemId`（**字串**，報價品項 `id`，≤64 字元）、`quoteQty`（帶入當下的報價數量，**僅供顯示**，不參與累計）。舊單／手動新增列沒有這兩鍵＝完全照舊。**報價品項本身沒有 `id`（舊資料）⇒ 無法追蹤：該列仍可帶入（預設數量＝報價數量），但不算入累計**，畫面小字標「無法追蹤已完工數」。

### 3.3 部分完工與分批
- 一張報價單多張完工單 ⇒ 每個報價品項算**累計**（**每次載入即時算，不快取、不存進單據**）：已完工數＝其他完工單（狀態 待審核／簽核中／已核准；草稿與退回不計，**比照出貨單 `RESERVED_STATUSES`／`SHIPPED_STATUSES` 的作法**）中，同一 `quoteItemId` 且狀態為「完成」的 `qty` 合計；`部分完成` 列計入其填的數量。
- 預設 `qty` ＝ 報價數量 − 已完工數（最少 0）；0 的列預設不帶入（畫面提示「已全數完工」，可手動加回）。表單每列顯示小字：「報價 10／已完工 6／本次 4」。
- - **累計的算法（鎖定口徑）**：依 `quoteItemId`（字串全等）分組；同一 id 在同一張或多張完工單出現多列 ⇒ **全部相加**；`type=header` 列忽略；`qty` 非數字、非有限、負數 ⇒ 當 0；`status=未施作` ⇒ 不計；`quoteQty` 不參與。
- **為什麼要即時**：`revoke-approval`（`completion_notes.py:613-650`）會把「已核准」退回「草稿」，草稿不計 ⇒ 其他單的「已完工數」可能縮小；表單載入與重新帶入時才算，畫面標示計算時間，不顯示過期數字。
- 超量（本張＋他單 > 報價數量）：預設**警告不擋**（設定可改為擋）；理由＝現場多做、報價單後來增補都是真實情況。

### 3.4 帶入後可編輯嗎
- **全部可編輯**（品名、數量、單位、狀態、備註、刪列、加列）。完工單記的是「現場實際完成了什麼」，報價只是起點。
- 唯一不可變：來源標記 `quoteItemId`（畫面不顯示代碼；使用者看到的是「來自報價第 3 項」白話標籤）。手動新增列沒有來源，也允許。

### 3.5 報價單事後變動（重新同步政策）
- 完工單存 `data_json.quoteSync = {syncedAt, itemsFingerprint}`（**儲存路徑**：`CompletionNoteIn` 目前沒有這個欄位、`create` 只寫 `{"labels":…}`——需新增模型欄位 `quote_sync: Optional[dict]` 並在 `create`／`update` 寫入；**指紋只在「明確帶入／重新帶入」時改變，一般存檔不碰它**：用戶端帶入時把它從 quote-items 端點拿到的 `fingerprint` 連同單據一起送回（`quote_sync.fingerprint`）；伺服器**只在它等於「此刻」伺服器自己重算的指紋時才接受並寫入**，否則 **409「報價單剛有更動，請重新帶入」**（防止載入到存檔之間發生的報價變動被誤蓋成已同步）；沒有帶 `quote_sync` 的一般更新**維持原儲存值不動**（所以按「存檔」不會悄悄清掉「報價單已更動」橫幅）；`update` 已是 read-modify-write 保留 `approval`，同樣保留／更新 `quoteSync`；`DataJsonApproval("completion_notes","note_no")` 只讀改寫 `data["approval"]` 再整包寫回（`helpers/approval_queue.py:166-167`），不會洗掉 `quoteSync`，實作時加回歸題）；`itemsFingerprint` ＝ 來源集合的**非金額欄位**（`id/description/qty/unit/type`＋擇一選定）雜湊。**金額變動不觸發**（也不洩漏金額變動）。
- 草稿開啟時比對：不同 ⇒ 黃色提示「報價單的項目有更動（新增 N、移除 M、數量改 K），要看差異嗎？」。差異視窗**逐項勾選**加入／移除／更新數量，**絕不自動覆寫**使用者已改過的列。
- 非草稿（已送審／核准）：只顯示唯讀提示「報價單在核准後有更動」，不提供改動入口（要改須退回草稿，沿用既有流程）。
- M3 後報價單回簽即鎖定品項 ⇒ 回簽後帶入的來源是穩定的；回簽前帶入視為暫估（Q3）。**取消回簽會清除選定** ⇒ 指紋改變 ⇒ 提示重新比對。

### 3.6 金額可見度（必守底線）
- **後端白名單、非黑名單**：端點只組出 `{id, type, description, brand, qty, unit}`（**`notes` 不在白名單**：報價備註常含內部提醒，預設不帶）；以後報價單新增任何欄位都**預設不出**。
- **端點守門（r4）＝「可建立完工單」權限（§6b：`can_author_completion`，預設＝管理員＋有案件權限的業務；設定可改為僅管理員）**，**且**要通過 `case_page_readable(conn, quote_no, user)`（`helpers/case_access.py:238-248`；與 `GET /api/quotations/{no}` 同一支，「可見範圍＝原單據，不寬也不嚴」）。查無與讀不到回同一個 404（比照 `_readable_note`）。
- **不新增任何讀取者**：持 `case_manage` 模組的非管理員（例如工程師）今天**讀不到報價單本體**（`case_page_readable` 不放行 case_manage），所以也**拿不到**本端點的品項與表頭；他們仍可像今天一樣列出／讀取完工單（`guard_case_access(case_manage)`，不變）。不能用 `case_manage` 當本端點的閘，否則等於讓他們用可列舉的 `quote_no` 撈任何報價單的品項與客戶資料。
- 回應不含金額，故不需財務權限；但資料範圍（品項**與表頭**：客戶、專案、地址、聯絡人、電話）都受上面同一道閘約束。
- 完工單**不存任何金額**（永遠）。「完工單印金額」是設定項（預設**關**，Q1 使用者答案＝不印）：開啟時，金額**不寫進完工單**，PDF／畫面讀取當下以 `money_visible(user)` 即時由報價單取（遮蔽帳號得 `null`＋`moneyMasked`，比照 `financial_mask`；客戶簽收聯的 PDF 是否印出另受此設定控制），並有守門測試。
- 順手收斂（【PM 預設】）：`prefillFromCase` 目前讀整張 `GET /api/quotations/{no}`（含單價）只為取地址聯絡人 ⇒ 改讀新端點回的 `header` 區（客戶/專案/地址/聯絡人），讓完工單頁面從此**不載入報價單金額**（表頭同樣只在上述閘通過時回；非管理員新建不了完工單，所以不影響現有操作）。

## 4. 畫面行為（白話，畫面不出現代碼）

- 新建完工單：載入後自動出現項目列，頂端一行小字「已從報價單帶入 12 項（分段標題 3 個）。可直接修改；只做完一部分請把狀態改成『部分完成』。」
- 按鈕：「從報價單重新帶入」（草稿才有；點了先問「這會把尚未編輯的項目換成最新報價內容，已改過的列保留，要繼續嗎？」→ 開差異視窗）。
- 每列右側小字：「報價 10 · 已完工 6」；本次數量超過剩餘時該列加黃底＋「超過報價數量 2」。
- 擇一單：頂端提示「此報價單為多方案，已帶入客戶選定的方案（A 組：方案二；B 組：方案一）」；未選定時「尚有 1 組方案客戶還沒選定，該組品項沒有帶入」。
- 報價單有更動：黃色橫幅「報價單的項目有更動，要看差異嗎？」＋「看差異」。
- 全部數字只有數量；沒有任何價格欄。

## 5. 設定（框架優先；表單答案＝預設值，管理者可調，不寫死）

設定中心群組「完工單」（M2 的 `settings_registry` 註冊樣式；**登錄只在 M2 樹上，此底（platform）沒有**——登錄落地前一律用**常數預設值**，行為＝下表「預設」欄；**M2 的設定中心目前只能看、不能改，編輯是 S1 以後的班**）。每項在畫面上是白話問句，**選項旁有「影響」說明面板**，畫面不出現任何代碼。

| 白話問句 | 預設（＝使用者決定值／建議值） | 可選 | 選項的影響（顯示在選項旁） | 變更規則 |
|---|---|---|---|---|
| 誰可以建立、編輯完工單？ | **有案件權限的業務與管理員**（使用者 10-12 決定） | 僅管理員／有案件權限的業務與管理員 | 前者＝與今天相同，業務只能看；後者＝業務可替自己經手的案件開單、改草稿、送審（核准仍由簽核人） | **權限類**：放寬（改成業務也能）＝設定中心放寬規則（原因＋變更帳本＋核准＋確認期間）；收緊（改回僅管理員）立即生效並留帳本。預設值出貨即為基準 |
| 完工單要不要印金額？ | **不印** | 不印／印（仍受財務檢視權限） | 印＝客戶簽收聯會出現單價與小計；沒有財務檢視權限的人看到的單與列印都不含金額 | 放寬類（印出金額）：原因＋帳本＋確認期間 |
| 報價單還沒回簽時能不能帶入項目？ | **能，並提示「尚未回簽，項目可能再變」**；未選定的擇一組別不帶並提示 | 能（加提示）／要回簽後才能 | 「要回簽後」＝品項已鎖定、不會再變，但現場要先開完工單時會被擋 | 收緊類即時、放寬類走確認期間 |
| 新建完工單時自動帶入項目？ | 是 | 是／否（否＝只留按鈕） | — | 即時 |
| 帶入時預設數量 | 剩餘未完工數量 | 剩餘／報價全數 | 剩餘＝分批完工時不會重複計 | 即時 |
| 帶入的項目預設狀態 | 完成 | 完成／部分完成／未施作 | — | 即時 |
| 一併帶入分段標題？ | 是 | 是／否 | — | 即時 |
| 品名前面加品牌？ | 是 | 是／否 | — | 即時 |
| 本次數量超過報價數量時 | 警告 | 警告／擋下 | 擋下＝多做的部分要先改報價 | 即時 |
| 重新帶入時，已改過的列 | 保留（只列差異讓人選） | 保留／以最新報價覆蓋 | 覆蓋＝你改過的數量會被換掉 | 即時（覆蓋為放寬類時走確認） |

**不是選項的硬規則**（程式常數＋守門題）：伺服器端權限檢查（含 `case_page_readable`）、**不存、不帶任何金額欄位**（白名單鎖在程式）、報價備註不帶、擇一單只帶選定品項、不自動覆寫已改的列、每次設定變更與每次建立／編輯都寫稽核。

## 6. 依檔案的變更清單

| 檔案 | 變更 |
|---|---|
| `backend/modules/case/completion_sync.py`（新） | 純函式：`quote_source_items(q)`（白名單＋`counted_items` 降級）、`completed_qty_by_item(conn, quote_no, exclude_note)`、`fingerprint(items)`、`diff(note_items, source_items)`。不寫庫。 |
| `backend/modules/case/api/completion_notes.py` | 新端點 `GET /api/completion-notes/quote-items?quote_no=&exclude_note=`（`_require_admin` ＋ `case_page_readable`；報價單狀態閘見 §3.1；回 `header`、`items[]`（`id/type/description/brand/qty/unit` ＋ `alreadyCompleted`、`remaining`）、`sourceState`（`signed`/`unsigned`/`alt_unselected` 白話欄位）、`fingerprint`）。`CompletionNoteIn` 加 `quote_sync`；`_validate` 加：`quoteItemId` 若存在須為**字串且 ≤64 字元**、`quoteQty` 為有限數字；**不加必填**。`create` 寫入 `data_json.quoteSync`、`update` 僅在帶 `quote_sync` 且指紋等於伺服器當下指紋時才更新，否則 409；不帶則保留原值。 |
| `backend/modules/case/api/quotations.py` | 不改（唯讀引用 `data_json`）。若 M3 已併入，`completion_sync` 才呼叫 `profit_guard.counted_items`。 |
| `backend/modules/case/completion_pdf.py` | 不改（項目額外鍵被忽略）；加守門測試確認 PDF 不含金額。 |
| `frontend/pages/completion-note-form.html` | `prefillFromCase` 改用新端點；`autoFillItems()`、`openSyncDiff()`；項目列加「報價/已完工」小字與超量底色；橫幅。 |
| `frontend/js/case-management-completion.js` | 不改（清單）；若清單要顯示「已帶入」不需要。 |
| 設定登錄（`helpers/settings_registry.py`，M2 才有） | 註冊「完工單」群組 10 項（§5）；程式內讀取走註冊表，缺列或模組缺席＝常數預設（不得在模組載入時 import）。 |
| `frontend/pages/case-management.html`（約 3352、3399、3419 行） | 把寫死的 `['superadmin','admin'].includes(session.role)` 換成伺服器回的能力旗標 `canAuthorCompletion`／`canRevokeCompletion`（見 §6b）；前端不再自己判角色。 |
| `backend/modules/case/CHANGELOG.md`、`backend/version_manifest.json`、`docs/quick/changelog.md`、`INTEGRATION-POINTS.md`（新端點） | 版本紀錄；`FORM_VERSION` **不動**（不碰 `quotation-form.html`）。 |
| `backend/modules/case/README.md` | 補一行 `completion_sync.py`。 |

不動：資料庫 schema、簽核流程、`completion_pdf` 版面、報價單端點、出貨單。

## 6b. 權限變更：開放有案件權限的業務建立／編輯完工單（Q6）——**須另行的非作者權限審查後才可實作**

**這是權限變更**（涉及硬排除 X2 權限與 X9 簽核流程，走完整車道＋非作者完整稽核，不得走快速車道）。

### 6b.1 今天的閘門（`backend/modules/case/api/completion_notes.py`，行號取自 c14f0a1df）
| 端點 | 行 | 今天 | 提案 |
|---|---|---|---|
| `POST /api/completion-notes`（建立） | 278 | `_require_admin` | `can_author_completion` |
| `PUT /{note_no}`（改草稿） | 320 | `_require_admin` | `can_author_completion`（仍僅草稿；樂觀鎖不變） |
| `DELETE /{note_no}`（刪草稿） | 367 | `_require_admin` | `can_author_completion` 且「自己建的草稿」；他人建立的草稿仍須管理員（待確認 Q-A1） |
| `POST /{note_no}/submit`（申請完工） | 402 | `_require_admin` | `can_author_completion`（送審人＝申請人；簽核鏈與自簽防護不變） |
| `POST /{note_no}/approve`／`reject` | 462／571 | 簽核人（`check_approve_permission`／`check_reject_permission`） | **不變**（核准仍由簽核人） |
| `POST /{note_no}/revoke-approval` | 624 | `_require_admin` | **不變**（仍僅管理員） |
| `GET /{note_no}/pdf-download` | 659–670 | 管理員或簽核人 | 加上 `can_author_completion`（作者要能看自己的單） |
| `POST /{note_no}/export` | 689 | `_require_admin` | `can_author_completion` |
| `POST /{note_no}/signed-toggle` | 720 | `_require_admin` | **不變**（回簽狀態仍僅管理員） |
| `POST /{note_no}/privacy-notice/ack` | 847 | `_require_admin` | `can_author_completion` |
| 讀取／回簽檔上傳／清單 | 223–270、767–793 | `guard_case_access(case_manage)` | **不變**（不新增讀取者） |
| 新端點 `quote-items` | 新 | — | `can_author_completion` ＋ `case_page_readable`（不比報價單本體的讀者更寬） |

### 6b.2 `can_author_completion(conn, user, quote_no)`（新；放 `helpers/case_access.py` 旁，L1 共用）
1. `superadmin`／`admin` ⇒ 真。
2. 設定＝「有案件權限的業務與管理員」且 `user.role == 'sales'` 且 `case_page_readable(conn, quote_no, user)`（＝案件擁有者／協作成員；**不放行 `case_manage` 模組持有者**，也不因 cashier 而放行）⇒ 真。
3. 其餘 ⇒ 假。設定缺席／讀取失敗 ⇒ 用常數預設（＝使用者決定值）。**fail closed 例外**：任何例外 ⇒ 假。
- 草稿的編輯範圍：同一案件上有權限的業務**都可編輯該案件的草稿**（協作情境；樂觀鎖防覆蓋）；若要限「只能改自己建的」是 Q-A1。

### 6b.3 前端
- `case-management.html` 的新增／編輯／申請按鈕不再寫死角色，改用伺服器隨完工單清單回傳的 `canAuthorCompletion`（每案件一個布林），與後端同一函式算出；`canRevokeCompletion` 同理（維持管理員）。
- 表單頁 `completion-note-form.html` 進入時若 `canAuthorCompletion` 為假 ⇒ 唯讀（今天是後端 403）。

### 6b.4 稽核與通知
- 既有 `completion.create／update／delete／submit` 稽核**不變名稱**；`detail` 加 `via`（`admin`／`case_sales`）與操作者角色，讓事後能分辨權限來源。
- 設定變更走設定中心帳本（原因、前後值、核准人、確認期間）。
- 簽核通知：申請人是業務時，`completion_approval_request`／`completed_approved`／`returned` 的收件對象與文案需確認不假設申請人是管理員（`notify_org_chain_notice`、`cascade_self_tiers` 的行為需逐一核對，列為審查項）。

### 6b.5 測試（權限矩陣）
業務（案件擁有者）可建立／改草稿／送審；業務（非該案件）404；業務對他人案件 404；`case_manage` 工程師仍不可建立（與 quote-items 一律 404/403）；admin／superadmin 不變；設定＝僅管理員 ⇒ 業務 403 且按鈕不顯示；核准／退回／撤銷核准／回簽切換對業務仍 403；業務同時是簽核層時自簽防護仍生效（`check_no_tier_self_approval`）；稽核 `via` 正確；設定放寬需核准、收緊即時；前端旗標與後端一致（同一函式）；舊單／既有流程回歸（管理員全部不變）。

### 6b.6 受影響測試與文件
`backend/tests/test_completion_notes_2026_09_12.py`、`test_e2e_completion_form_2026_09_12.py`（現有以管理員為前提）、權限守門 `test_module_no_admin_bypass`／`finance_role` 系列需確認不被新函式誤判；`INTEGRATION-POINTS.md`（新 L1 函式）、`docs/platform/CORE-SPEC.md` 的權限裁示記錄（需使用者書面裁示的紀錄：10-12 表單答案＋更正）。

### 6b.7 審查閘
本節是**權限變更提案**，實作前須有獨立的非作者權限審查（對象：6b.1 表格每一列的前後差異、6b.2 函式、6b.4 通知假設）。審查通過前，只實作與權限無關的部分（帶入、指紋、累計），建立／編輯閘維持今天的 `_require_admin`。

## 7. 測試與工量

**測試（新增，後端為主）**
1. `test_completion_quote_items_*`：白名單——回應 `items[]` 鍵集合 ⊆ `{id,type,description,brand,qty,unit,alreadyCompleted,remaining}`（**不含 `notes`**），且**不含** `ITEM_MONEY_KEYS` 任何鍵（含報價單新增未知金額鍵的反向案例）；**負向題：持 `case_manage` 的非管理員 ⇒ 404（讀不到報價單本體者拿不到品項／表頭），同一人仍可列出／讀取完工單**；非案件成員的 admin 以外角色 404；admin 但 `case_page_readable` 為假 ⇒ 404 同句。
2. 狀態閘：`草稿/待審核/簽核中/已取消/已拒絕` ⇒ 409 白話；`已送出` ⇒ 200；被拒改號後舊號不併入新號累計。
2b. 來源集合：一般單全帶；含 header；擇一單（M3 後）只帶選定、未選定組別不帶＋`sourceState`；M3 前 `counted_items` 缺席降級。
3. 分批：多張完工單累計（同 `quoteItemId` 多列相加、header 忽略、非數字/負數/未施作計 0、`quoteQty` 不參與、無 id 舊列不算入）、撤銷核准後他單累計縮小（即時）、草稿/退回不計、`部分完成` 計入、`exclude_note` 排除自己、剩餘 0 不預設帶入、超量警告／擋下（設定）。
4. 指紋：金額變動不改指紋；數量/品名/選定變動改指紋；diff 三類（新增/移除/改量）。
5. 不覆寫：`quoteSync` 協議兩條都要有題：(i) 帶入後存檔，送回的指紋等於當下伺服器指紋 ⇒ 寫入；載入到存檔之間報價單品項被改 ⇒ 送回舊指紋 ⇒ 409，儲存值不變；偽造指紋 ⇒ 409；(ii) 一般更新（不帶 `quote_sync`）⇒ 儲存的 `quoteSync` 逐位元不變，橫幅仍在；`DataJsonApproval` 核准/退回後 `quoteSync` 仍在；帶入不改非草稿單。
6. PDF 預設不含金額；設定＝印時，有財務檢視權限者含金額、遮蔽帳號不含（金額取自報價單即時讀取，單據本身不存）。
7. 前端守門（靜態）：表單不再呼叫 `GET /api/quotations/{no}` 取整張；頁面不含價格欄位字樣。
8. e2e（單頁）：新建→自動帶入→改一列→存→重開→報價單被改→看到橫幅→差異視窗。
9. 設定：預設值＝上表；缺列＝預設（不寫庫＝零行為變更）。

**工量（pd）**
| 任務 | pd |
|---|---|
| `completion_sync.py`＋端點＋白名單守門 | 1.0 |
| 分批累計＋超量政策 | 0.75 |
| 表單：自動帶入、小字、橫幅、差異視窗 | 1.25 |
| 設定群組註冊（依 M2 登錄）＋讀取 | 0.5 |
| 測試（含 e2e、負向權限、狀態閘） | 1.5 |
| 版本紀錄／IP 登錄／README／收尾 | 0.25 |
| 印金額開關（讀取當下取價、遮蔽、PDF／畫面） | 1.0 |
| 權限閘重新設計（§6b：函式、端點改接、前端旗標、稽核、通知核對、矩陣測試） | 1.5 |
| **合計** | **7.75**（範圍 7.0–8.5；不含另行的非作者權限審查、不含 M3 相依整合） |

## 8. 風險

1. **金額洩漏**：最大風險。緩解＝白名單、守門測試、不存金額。
2. **擇一方案相依 M3**：M3 未上線前無 `altPicks`；以降級處理，M3 併入後須加整合題（工量已含）。若 M3 改了 `counted_items` 簽章，`completion_sync` 是唯一接點。
3. **報價單事後變動**：指紋只是提示不是約束；使用者仍可能帶出過期內容——靠橫幅與差異視窗，不做自動覆寫。
4. **分批累計的口徑**：「完成」才計、`部分完成` 以所填數量計；現場若把數量亂填，累計會偏——警告而不擋，並在差異視窗顯示。
5. **樂觀鎖／同時編輯**：沿用 `expected_updated_at`；自動帶入發生在載入階段、未寫庫，無新增競態。
6. **不改簽核**：本功能不碰 `unified_approval_flow`；沒有新的審批或通知。
7. **舊單相容**：沒有 `quoteItemId` 的列＝手動列，行為不變；舊單不會被自動回填。

## 8b. 與 M3 擇一方案的交集（待 M3 設計者／使用者決定）

完工單可能是依「回簽選定」的品項建立的（狀態 待審核／簽核中／已核准）。M3 的「取消回簽會清除選定」（T9 的取消回簽守門只涵蓋已開票／已請款／已精算）不會知道有完工單依賴那份選定。兩個選項：
- (a) **接受並提示**：取消回簽照舊允許；完工單頁面以指紋偵測到來源改變，顯示唯讀提示「報價單的選定方案已被取消，這張完工單是依舊的選定建立的」，由人處理。（我的建議：完工單不做金流，不必擋。）
- (b) 把「有待審核／簽核中／已核准的完工單」加入 M3 T10／Q9 的下游清單，取消回簽時警告或阻擋。
**M3 側使用者已定**：整張報價鎖定，且成案／PO 之後禁止取消回簽 ⇒ 成案後依選定建立的完工單不會失去來源；**成案之前**取消回簽仍可能發生，本案維持 (a)（唯讀提示，不擋）。

## 9. 決定與待確認

### 9.1 已決定（現在都是設定的預設值，見 §5；不再是問題）
| 原問題 | 使用者決定（＝預設） |
|---|---|
| Q1 完工單印金額？ | 不印（設定項，可改；開啟仍受財務權限約束） |
| Q2 已送出未回簽可否帶入？ | 能，並提示；未選定的擇一組別不帶（設定項） |
| Q6 業務可否建立／編輯完工單？ | 開放給**有案件權限的業務**（設定項可改回僅管理員）——**權限變更，須另行審查（§6b.7）** |
| Q3／Q4／Q5／Q7 | 剩餘數量／警告／自動帶入＋可重新帶入／備註不帶（PM 預設，皆為設定項） |

### 9.2 仍待確認
| # | 問題 | 需誰？ | 預設／建議 |
|---|---|---|---|
| Q-C1 | 成案**之前**取消回簽時，若已有依該選定建立的完工單，要不要警告／阻擋？（§8b） | M3 設計者或使用者 | 接受並在完工單提示，不擋 |
| Q-A1 | 業務能否編輯／刪除**他人**建立的完工單草稿（同案件協作者）？ | **使用者** | 可編輯同案件草稿；刪除只限自己建的，他人建立的須管理員 |
| Q-A2 | 簽核通知文案與收件人：申請人是業務時，是否沿用今天的簽核鏈與通知（§6b.4）？ | 權限審查者 | 沿用，審查時逐項核對 |

## 10. 依據與限制

- 讀過：`completion_notes.py`（全檔結構、1–400 行細讀）、`completion_pdf.py`（項目區）、`completion-note-form.html`（項目區、prefill、`addItem`）、`financial_mask.py`、`quotations.py::get_quotation`、`supply/material_link.py`（加性連結與保留/已出貨作法）、M3 工作分解（`wip/t56-1d-m3-altquote-plan-r1`）。
- **沒讀**：`completion_notes.py` 400 行之後（核准/退回/回簽細節）、`unified_approval_flow`、設定中心 `settings_registry` 實際註冊 API（M2 樹，未在本底上）——§5/§6 對應項標為「依 M2 登錄樣式」，實作前重核。
- 沒有跑任何測試或工具；行號取自 `origin/platform` c14f0a1df，實作前重核。
