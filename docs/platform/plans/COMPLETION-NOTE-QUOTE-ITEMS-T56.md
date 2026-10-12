# 完工單自動帶入報價單項目——設計筆記（僅文件，未跑任何測試）

> 2026-10-12；委託：hichan-1c（使用者新需求：「完工單要能自動帶入報價單項目」）。底：`origin/platform` c14f0a1df（內容＝正式機 M1-a `4eb521384`；**M2／M3 尚未上線**）。
> 標記：**【需使用者回答】**＝會改變行為或對外輸出，回答前不實作該部分；**【PM 預設】**＝我給預設值，不需問，使用者可事後調。**UNKNOWN**＝沒查到證據。
> 框架優先（記憶 `feedback_framework_first_no_hardcode`）：行為開關放設定中心，程式內只有「安全底線」（不帶金額、守門權限）。

## 0. 結論（先講）

1. **今天完全沒有這個功能**：新建完工單只會從報價單帶「客戶、專案名稱、送貨地址、聯絡人、電話」（`completion-note-form.html::prefillFromCase`，約 413–434 行）；**完成項目明細是空的**，畫面寫「尚無項目，按上方『＋ 項目』開始」。（查過：`completion_notes.py`、`case-management-completion.js`、README、出貨單 `supply/api/shipping_notes.py`——沒有任何報價單→完工單的帶入程式。）
2. **欄位幾乎天然對得上**：完工單項目 `description／qty／unit／status／notes`（＋分段 `type=header`）；報價單項目 `id／description／brand／qty／unit／…／notes`（＋`type=header`）。**不需要資料庫遷移**——項目存在 `items_json`、加性欄位即可（比照出貨單 `materialLink` 的加性做法）。
3. **建議做法**：新增一支**唯讀**「可帶入項目」端點（後端白名單只回非金額欄位）＋ 完工單表單「從報價單帶入」（新建時自動執行一次、草稿可再按）。帶入後**全部可編輯**；每列記住來源品項編號，分批完工時顯示「報價 N／已完工 M／本次預設 剩餘」。擇一方案報價**只帶已回簽選定的品項**。
4. **金額不進完工單**（預設）：後端白名單 `{id, type, description, brand, qty, unit, notes}`，**任何金額鍵（`cost／margin／unitPrice／amount`）一律不出**，守門測試鎖住。完工單要不要印金額是【需使用者回答】Q1。
5. **工量 ≈ 4.5–5.5 pd**（§7），主要風險＝擇一方案相依 M3、報價單事後變動的對帳（§8）。

## 1. 完工單現況（資料模型、誰編輯、狀態、PDF）

| 面向 | 現況（檔案：行） |
|---|---|
| 資料表 | `completion_notes`：`note_no`(CN…)、`quote_no`、`status`、客戶/專案/地址、`start_date`、`completion_date`、`site_manager`、`recipient`、`contact_phone`、`items_json`、`work_summary`、`test_result`、`warranty_months`、`pending_items`、`notes`、`data_json`（`labels` 標題覆寫、`approval` 簽核）、簽收欄位。一張報價單可對多張完工單（`completion_notes.py` 檔頭）。 |
| 項目形狀 | `{description, qty, unit, status(完成/部分完成/未施作), notes}`，分段標題 `{type:'header', description}`。`_validate`（203–218）只檢 `status`，其餘鍵不限制。**沒有金額欄、沒有來源連結。** |
| 誰能編輯 | 建立／修改／刪除皆 `_require_admin`＝`superadmin`／`admin`（120–122、278、320、367）；**僅草稿可編輯**（329–330）；樂觀鎖 `expected_updated_at`（335–337）。讀取：`guard_case_access(… allow_module="case_manage")`（單筆 `_readable_note`）。 |
| 狀態與簽核 | 草稿 → 申請完工（`/submit`：至少 1 項完工項目＋完工日期必填）→ 分層簽核（`unified_approval_flow`，類型 `completion`）→ 已核准；退回→草稿；客戶回簽（`signed-toggle`／上傳回簽檔）。無庫存扣減。 |
| PDF | `completion_pdf.py`：列出項目 `description／qty／unit／status／notes`（56–76 行），**不印任何金額**。客戶簽章聯，屬客戶可見文件。 |
| 前端 | `frontend/pages/completion-note-form.html`（項目列 200–224；`addItem`／`addHeader`／`removeItem` 479–481）；清單在 `case-management-completion.js`（只留清單與狀態動作）。 |
| 標題可自訂 | `data_json.labels`＋5 組預設用語（工程/系統/供應/網路/維運）；`itemColumn` 等欄名可改（本功能不動，沿用）。 |

## 2. 報價單項目在哪裡

- 存於 `quotations.data_json.items[]`（`GET /api/quotations/{no}` 回 `data.items`；`modules/case/api/quotations.py:1267`）。項目鍵：`id`(數字)、`description`、`brand`、`qty`、`unit`、`cost`、`margin`、`unitPrice`、`unitPriceOverride`、`amount`、`notes`、`type`(`header`)（`quotation-form.html:2273`、2534；`profit_guard.item_amount` 118–122）。
- **金額遮蔽**：`helpers/financial_mask.py`——`ITEM_MONEY_KEYS = (cost, margin, unitPrice, amount)`；`quote_money_visible()`＝superadmin／admin／sales／財務角色看得到報價單層級單價；其餘角色後端剔除（`mask_quotation_data`）。**完工單編輯者（admin+）本來就看得到單價**，但完工單讀取者（`case_manage` 模組持有者）不一定。
- **擇一方案（M3，尚未上線）**：`M3-ALTQUOTE-WORK-BREAKDOWN-T56.md`（分支 `wip/t56-1d-m3-altquote-plan-r1`）——品項 `altGroup`、報價單 `altPicks={組:品項id}`、`profit_guard.counted_items(q)`＝非擇一項＋各組**已選**項；回簽必須選定、回簽後品項鎖定、取消回簽清除選定。M3 前的報價單沒有這些鍵＝全部計入。

## 3. 提案：自動帶入的行為

### 3.1 帶入什麼（來源集合）
- **來源＝「這張報價單目前計入的品項」**：呼叫 `counted_items(q)`（M3 後）；M3 前 `counted_items` 不存在 ⇒ 降級為「全部品項」（`getattr` 保護，無 `altGroup` 的單逐位元同今日）。
- 擇一單：**只帶回簽選定的品項**（`altPicks` 完整）。有未選定組別（未回簽）⇒ 只帶非擇一品項，並在畫面白話提示「方案尚未選定，這幾組沒有帶入」（Q3 決定是否直接擋）。
- 分段標題（`type=header`）一併帶入（設定可關）。數量為 0 或空的品項照帶（現場可改），不靜默丟棄。

### 3.2 怎麼帶
- 新建完工單進表單時：**自動帶入一次**（取代空白列表）；之後草稿狀態有「從報價單重新帶入」按鈕。帶入是**前端先取預覽、使用者看得到並可改、按儲存才寫入**，後端不偷偷改單據。【PM 預設】
- 每列：`description` ← 報價品名（`brand` 預設併入「品牌 品名」，設定可關）、`qty` ← 預設值見 3.3、`unit` ← 報價單位、`status` ← 預設「完成」（設定可改）、`notes` ← 空白（報價備註不帶：常含內部提醒）。
- 加性來源欄位（存在 `items_json` 每列）：`quoteItemId`（報價品項 `id`）、`quoteQty`（帶入當下的報價數量）。舊單／手動新增列沒有這兩鍵＝完全照舊。

### 3.3 部分完工與分批
- 一張報價單多張完工單 ⇒ 每個報價品項算**累計**：已完工數＝其他完工單（狀態 待審核／簽核中／已核准；草稿與退回不計，**比照出貨單 `RESERVED_STATUSES`／`SHIPPED_STATUSES` 的作法**）中，同一 `quoteItemId` 且狀態為「完成」的 `qty` 合計；`部分完成` 列計入其填的數量。
- 預設 `qty` ＝ 報價數量 − 已完工數（最少 0）；0 的列預設不帶入（畫面提示「已全數完工」，可手動加回）。表單每列顯示小字：「報價 10／已完工 6／本次 4」。
- 超量（本張＋他單 > 報價數量）：預設**警告不擋**（設定可改為擋）；理由＝現場多做、報價單後來增補都是真實情況。

### 3.4 帶入後可編輯嗎
- **全部可編輯**（品名、數量、單位、狀態、備註、刪列、加列）。完工單記的是「現場實際完成了什麼」，報價只是起點。
- 唯一不可變：來源標記 `quoteItemId`（畫面不顯示代碼；使用者看到的是「來自報價第 3 項」白話標籤）。手動新增列沒有來源，也允許。

### 3.5 報價單事後變動（重新同步政策）
- 完工單存 `data_json.quoteSync = {syncedAt, itemsFingerprint}`；`itemsFingerprint` ＝ 來源集合的**非金額欄位**（`id/description/qty/unit/type`＋擇一選定）雜湊。**金額變動不觸發**（也不洩漏金額變動）。
- 草稿開啟時比對：不同 ⇒ 黃色提示「報價單的項目有更動（新增 N、移除 M、數量改 K），要看差異嗎？」。差異視窗**逐項勾選**加入／移除／更新數量，**絕不自動覆寫**使用者已改過的列。
- 非草稿（已送審／核准）：只顯示唯讀提示「報價單在核准後有更動」，不提供改動入口（要改須退回草稿，沿用既有流程）。
- M3 後報價單回簽即鎖定品項 ⇒ 回簽後帶入的來源是穩定的；回簽前帶入視為暫估（Q3）。**取消回簽會清除選定** ⇒ 指紋改變 ⇒ 提示重新比對。

### 3.6 金額可見度（必守底線）
- **後端白名單、非黑名單**：端點只組出 `{id, type, description, brand, qty, unit, notes}`；以後報價單新增任何欄位都**預設不出**。
- 端點守門＝完工單讀取規則 `guard_case_access(…, allow_module="case_manage")`（與 `_readable_note` 同）；**不要求財務權限，因為不回金額**，所以 `case_manage` 持有者與 admin 結果相同，不因角色而有價格差異。
- 完工單**不存、不印任何金額**（預設）。若 Q1 決定要印：金額**不寫進完工單**，PDF／畫面讀取時以 `money_visible(user)` 即時由報價單取（遮蔽帳號得 `null`＋`moneyMasked`，比照 `financial_mask`），並新增守門測試。
- 順手收斂（【PM 預設】）：`prefillFromCase` 目前讀整張 `GET /api/quotations/{no}`（含單價）只為取地址聯絡人 ⇒ 改讀新端點回的 `header` 區（客戶/專案/地址/聯絡人），讓完工單頁面從此**不載入報價單金額**。

## 4. 畫面行為（白話，畫面不出現代碼）

- 新建完工單：載入後自動出現項目列，頂端一行小字「已從報價單帶入 12 項（分段標題 3 個）。可直接修改；只做完一部分請把狀態改成『部分完成』。」
- 按鈕：「從報價單重新帶入」（草稿才有；點了先問「這會把尚未編輯的項目換成最新報價內容，已改過的列保留，要繼續嗎？」→ 開差異視窗）。
- 每列右側小字：「報價 10 · 已完工 6」；本次數量超過剩餘時該列加黃底＋「超過報價數量 2」。
- 擇一單：頂端提示「此報價單為多方案，已帶入客戶選定的方案（A 組：方案二；B 組：方案一）」；未選定時「尚有 1 組方案客戶還沒選定，該組品項沒有帶入」。
- 報價單有更動：黃色橫幅「報價單的項目有更動，要看差異嗎？」＋「看差異」。
- 全部數字只有數量；沒有任何價格欄。

## 5. 設定（框架優先；預設＝建議值；管理者可調，不寫死）

設定中心群組「完工單」（M2 的 `settings_registry` 註冊樣式；**M2 的設定中心目前只能看、不能改，S1 以後的班才可編輯**——在那之前一律用預設值，行為不變）：

| 白話問句 | 預設 | 範圍 |
|---|---|---|
| 新建完工單時自動從報價單帶入項目？ | 是 | 是／否（否＝只留按鈕） |
| 帶入時預設數量 | 剩餘未完工數量 | 剩餘／報價全數 |
| 帶入的項目預設狀態 | 完成 | 完成／部分完成／未施作 |
| 一併帶入分段標題？ | 是 | 是／否 |
| 品名前面加品牌？ | 是 | 是／否 |
| 本次數量超過報價數量時 | 警告 | 警告／擋下 |
| 報價單尚未回簽時能不能帶入？（Q3） | 能，加提示 | 能／不能 |

硬規則（不進設定，程式常數＋守門題）：**不帶金額**；擇一單只帶選定品項；不自動覆寫已改的列。

## 6. 依檔案的變更清單

| 檔案 | 變更 |
|---|---|
| `backend/modules/case/completion_sync.py`（新） | 純函式：`quote_source_items(q)`（白名單＋`counted_items` 降級）、`completed_qty_by_item(conn, quote_no, exclude_note)`、`fingerprint(items)`、`diff(note_items, source_items)`。不寫庫。 |
| `backend/modules/case/api/completion_notes.py` | 新端點 `GET /api/completion-notes/quote-items?quote_no=&exclude_note=`（`guard_case_access(case_manage)`；回 `header`、`items[]`（含 `alreadyCompleted`、`remaining`）、`sourceState`（`signed`/`unsigned`/`alt_unselected` 白話欄位）、`fingerprint`）。`_validate` 加：`quoteItemId` 若存在須為整數、`quoteQty` 為數字；**不加必填**。`create`／`update` 保留 `data_json.quoteSync`（read-modify-write，現行 update 已是此模式）。 |
| `backend/modules/case/api/quotations.py` | 不改（唯讀引用 `data_json`）。若 M3 已併入，`completion_sync` 才呼叫 `profit_guard.counted_items`。 |
| `backend/modules/case/completion_pdf.py` | 不改（項目額外鍵被忽略）；加守門測試確認 PDF 不含金額。 |
| `frontend/pages/completion-note-form.html` | `prefillFromCase` 改用新端點；`autoFillItems()`、`openSyncDiff()`；項目列加「報價/已完工」小字與超量底色；橫幅。 |
| `frontend/js/case-management-completion.js` | 不改（清單）；若清單要顯示「已帶入」不需要。 |
| 設定登錄（`helpers/settings_registry.py`，M2 才有） | 註冊「完工單」群組 7 項（§5）；程式內讀取走註冊表，缺列＝預設。 |
| `backend/modules/case/CHANGELOG.md`、`backend/version_manifest.json`、`docs/quick/changelog.md`、`INTEGRATION-POINTS.md`（新端點） | 版本紀錄；`FORM_VERSION` **不動**（不碰 `quotation-form.html`）。 |
| `backend/modules/case/README.md` | 補一行 `completion_sync.py`。 |

不動：資料庫 schema、簽核流程、`completion_pdf` 版面、報價單端點、出貨單。

## 7. 測試與工量

**測試（新增，後端為主）**
1. `test_completion_quote_items_*`：白名單——回應鍵集合 ⊆ `{id,type,description,brand,qty,unit,notes}`，且**不含** `ITEM_MONEY_KEYS` 任何鍵（含報價單新增未知金額鍵的反向案例）；`case_manage` 非 admin 與 admin 回應相同；無權限 404（與 `_readable_note` 同句）。
2. 來源集合：一般單全帶；含 header；擇一單（M3 後）只帶選定、未選定組別不帶＋`sourceState`；M3 前 `counted_items` 缺席降級。
3. 分批：多張完工單累計、草稿/退回不計、`部分完成` 計入、`exclude_note` 排除自己、剩餘 0 不預設帶入、超量警告／擋下（設定）。
4. 指紋：金額變動不改指紋；數量/品名/選定變動改指紋；diff 三類（新增/移除/改量）。
5. 不覆寫：update 保留 `quoteSync`；帶入不改非草稿單。
6. PDF 不含金額（含 Q1 預設）。
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
| 測試（含 e2e） | 1.25 |
| 版本紀錄／IP 登錄／README／收尾 | 0.25 |
| **合計** | **5.0**（範圍 4.5–5.5；不含 Q1 若要印金額 +1.0、不含 M3 相依整合） |

## 8. 風險

1. **金額洩漏**：最大風險。緩解＝白名單、守門測試、不存金額。
2. **擇一方案相依 M3**：M3 未上線前無 `altPicks`；以降級處理，M3 併入後須加整合題（工量已含）。若 M3 改了 `counted_items` 簽章，`completion_sync` 是唯一接點。
3. **報價單事後變動**：指紋只是提示不是約束；使用者仍可能帶出過期內容——靠橫幅與差異視窗，不做自動覆寫。
4. **分批累計的口徑**：「完成」才計、`部分完成` 以所填數量計；現場若把數量亂填，累計會偏——警告而不擋，並在差異視窗顯示。
5. **樂觀鎖／同時編輯**：沿用 `expected_updated_at`；自動帶入發生在載入階段、未寫庫，無新增競態。
6. **不改簽核**：本功能不碰 `unified_approval_flow`；沒有新的審批或通知。
7. **舊單相容**：沒有 `quoteItemId` 的列＝手動列，行為不變；舊單不會被自動回填。

## 9. 待使用者確認

| # | 問題 | 需使用者？ | 我的預設／建議 |
|---|---|---|---|
| Q1 | 完工單（含客戶簽章用的 PDF）要不要印金額（單價／小計）？ | **【需使用者回答】** | 不印（今天就沒有；客戶簽收聯多半不需要）。要印則金額即時讀取、依財務權限遮蔽，+1.0 pd |
| Q2 | 報價單**尚未回簽**時能不能帶入？未回簽的擇一單怎麼辦？ | **【需使用者回答】** | 一般單：能，加提示；擇一單未選定組別：不帶該組＋提示（不擋）。回簽前的報價可能再變，所以提示而非靜默 |
| Q3 | 分批完工的預設數量：剩餘數量，還是報價全數？ | 【PM 預設】可事後在設定調 | 剩餘數量 |
| Q4 | 超量時警告還是擋？ | 【PM 預設】可事後調 | 警告 |
| Q5 | 新建時自動帶入，還是只留按鈕？ | 【PM 預設】可事後調 | 自動帶入＋可重新帶入 |
| Q6 | 業務（非管理員）能不能建立完工單？今天只有管理員／最高管理者 | **【需使用者回答】**（若要改，屬權限變更，不在本案） | 維持不變 |
| Q7 | 報價單「備註」要不要帶進完工單備註？ | 【PM 預設】 | 不帶（報價備註常含內部提醒） |

## 10. 依據與限制

- 讀過：`completion_notes.py`（全檔結構、1–400 行細讀）、`completion_pdf.py`（項目區）、`completion-note-form.html`（項目區、prefill、`addItem`）、`financial_mask.py`、`quotations.py::get_quotation`、`supply/material_link.py`（加性連結與保留/已出貨作法）、M3 工作分解（`wip/t56-1d-m3-altquote-plan-r1`）。
- **沒讀**：`completion_notes.py` 400 行之後（核准/退回/回簽細節）、`unified_approval_flow`、設定中心 `settings_registry` 實際註冊 API（M2 樹，未在本底上）——§5/§6 對應項標為「依 M2 登錄樣式」，實作前重核。
- 沒有跑任何測試或工具；行號取自 `origin/platform` c14f0a1df，實作前重核。
