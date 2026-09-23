# MOTRIX ERP — 模組：承攬商（§5.7、§5.9、§7.4、§7.11）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

---

### §5.7 · 承攬商派發狀態機

```
草稿(draft) → 已送出(sent) → 已確認(confirmed)
                                   ↓
                              待驗收(pending_acceptance)   ← 快速按鈕：「待驗收」
                                   ↓
                              已驗收(accepted)             ← 快速按鈕：「✓ 確認驗收」
                                   ↓                         記錄 accepted_by + accepted_at
                              完工(completed)

任意非終態 → 已取消(cancelled)
```

- 狀態轉換：`PATCH /api/contractor-dispatches/{id}/accept`（`action=pending_acceptance` 或 `action=accepted`）
- 流程違規（如跳過待驗收直接已驗收）→ **409**
- 已驗收後：卡片底部顯示綠色橫條，含驗收人姓名 + 時間
- 狀態亦可透過 Modal 下拉直接設定（彈性操作，不走 `/accept` endpoint）
- **外包名單人員（DB v36，2026-08-03e）**：新增派發 Modal 內可從外包名冊（`contractors` 表，
  `GET /api/contractors/selectable`，比照 `vendor-contractors/selectable` 慣例，任何登入者可讀）
  多選人員並各自填金額，存為 `personnel_json` 快照 `[{id,name,amount,note}]`（不隨 `contractors`
  表後續變動連動，即使該人員之後被刪除或改名，既有派發紀錄的金額與姓名仍完整保留）；
  `_dispatch_row()` 額外回傳 `personnelTotal`（人員金額加總）與 `grandTotal`
  （`totalWithTax + personnelTotal`，承攬商含稅金額 + 外包人員金額不計稅）；`已取消` 的派發
  不計入 `grandTotal` 彙總（見案件管理承攬商 tab 的「外包總成本」與 §5.5 精算 `dispatchTotal`）
- **承攬商欄位改為選填（DB v37，2026-08-03f）**：部分案件屬純外包名單人員點工，沒有對應承攬商，
  `vendor_id` 從 `NOT NULL` 改為可為空（SQLite 需整表重建，見 `_m037_dispatch_vendor_optional`）；
  後端驗證改為「承攬商與外包名單人員至少擇一」，兩者皆空才擋 400；前端 Modal 拿掉必填星號、
  預設選項改「— 無承攬商（純外包名單人員點工）—」；卡片列表標題無承攬商時顯示「外包人員（點工）」，
  金額改用 `grandTotal` 統一顯示（含稅承攬商 + 外包人員），並新增外包人員明細表格；精算頁「三、
  承攬商派發成本」明細列無承攬商時不再顯示佔位的「（未命名承攬商）」空列，改由外包人員第一筆
  頂替顯示派發狀態
- **外包名冊「參與案件」聯動（2026-08-03g）**：`contractors.html`（外包名冊）詳情面板比照
  `vendor-contractors.html` 承攬商詳情的「派發紀錄」區塊，新增「參與案件」——選中人員時前端
  抓 `GET /api/contractor-dispatches`（無 `quote_no` 參數，同承攬商頁一樣受限於「最新 200 筆」），
  用 `d.personnel.some(p => p.id === c.id)` 篩出該人員實際參與的派發，逐筆顯示案號連結（導向
  案件管理承攬商 tab）、狀態徽章、所屬承攬商（無承攬商時顯示「（無承攬商，純點工）」）與該人員
  個人金額（`_myDispatchAmount(d)`，非整筆派發總額）

---

### §5.9 · 承攬商匯款申請／發票開立簽核單（2026-08-20）

兩個獨立於報價單/出貨單的財務憑證流程，架構直接沿用 §5.8 出貨單的 tiers 簽核＋PDF＋匯出紀錄模式，`routers/contractor_vouchers.py`／`routers/invoice_vouchers.py`。

**承攬商匯款申請**（案件管理承攬商 tab，`contractor_payment_vouchers`）：

```
草稿 → 待審核 → 簽核中 → 已核准
                            ↓
                      已匯款（財務勾選，獨立於 status，比照出貨單「已核准」跟「已回簽」，
                              可取消回已核准；已匯款不可撤銷核准）
```

- `status='accepted'`（已驗收）或 `status='completed'`（完工）的派發可產生申請（2026-08-20 使用者實測後放寬，原本僅完工可申請），且**一筆派發僅能對應一張申請**（`dispatch_id` UNIQUE，雙重保護：DB 層 + API 層檢查）
- 建立當下把承攬商名稱/統編/銀行帳戶（代碼/名稱/分行/戶名/帳號/存簿影本，讀自 `vendor_contractors.data_json`）/派發品項/`invoice_no`/金額**全部快照**進 `snapshot_json`，之後來源資料異動不會回頭改變已產生的憑證
- **外包名單人員的銀行帳戶／存簿影本**（2026-08-20 起）：派發本身的 `personnel_json` 只快照 id/name/amount/note，不含銀行資訊；建立憑證當下另外查一次 `contractors` 表（外包名冊）取得每位人員目前的 `bank_code`/`bank_name`/`bank_branch`/`bank_account_name`/`bank_account_number`/`bank_passbook_image`，一併寫入 snapshot；查無資料（例如人員已被刪除）就留空，不擋建立。PDF 上每位外包人員各自一張帳戶卡片＋存簿縮圖，供財務逐一核對匯款
- `routers/vendor_contractors.py` `delete_dispatch()` 新增守門：已產生憑證的派發不可刪除，回 409（避免撞上 FK 約束產生原始 500）
- 獨立簽核設定：`system_settings.contractor_voucher_approval_flow`（`contractor-voucher-approval-settings.html`，superadmin）
- 全部簽核完成 → 狀態 `已核准`，背景觸發 PDF 存檔（`pdf_gen.py _generate_contractor_voucher_pdf`）；PDF 含銀行匯款資訊＋簽核歷程表格
- Demo 模式 PDF 隔離目錄：`backend/_demo_contractor_voucher_pdf_archive`

**發票開立簽核單**（案件管理案件資訊 tab／款項明細，`invoice_vouchers`）：

```
草稿 → 待審核 → 簽核中 → 已核准（定稿，無額外財務結案節點）
```

- **scope='amount'（自訂金額）或 scope='items'（自訂品項+數量）**（2026-08-20 重新設計，取代原本只能挑既有款項期別的 `single`/`all` 模式）：使用者反映很多案件是「先開發票才能收款」，需要能自訂任意金額或自訂品項+數量申請，不受限於報價單既有的款項排程分期
- **剩餘可申請額度追蹤，防止重複/超額請款**：`GET /invoice-vouchers/remaining?quote_no=` 即時計算「合約總額 - 這張報價單所有既有 invoice_vouchers 的 `amount` 加總（**含草稿**，草稿就鎖額度，2026-08-20 使用者明確選擇，避免同時建立造成超額，見 `routers/invoice_vouchers.py _quote_remaining()`）」= 剩餘可申請金額；`scope='items'` 額外逐品項追蹤已申請數量／剩餘數量（同樣含草稿）。建立時後端會二次驗證（金額超過剩餘 409、品項數量超過剩餘 409），不只是前端擋
- `amount`（DB v47 新增的真實 SQL 欄位）是唯一權威金額數字，不論哪種 scope 都會寫入，`_quote_remaining()` 用 `SUM(amount)` 直接算，不必解析全部 snapshot_json
- 建立當下把客戶名稱/統編/案件名稱**全部快照**進 `snapshot_json`；`scope='items'` 時額外快照 `selectedItems`（實際要開的品項+數量+金額，金額可由使用者自行調整，不強制等於數量×單價）
- **報價單品項參考**（`scope='amount'` 時顯示，`scope='items'` 時因為 `selectedItems` 本身就是實際品項不重複顯示）：`snapshot_json.quoteItems` 快照報價單 `items[]`，**只帶客戶看得到的欄位**（description/brand/qty/unit/unitPrice/amount/notes），刻意排除 `cost`/`margin`/`unitPriceOverride` 等內部機密欄位，避免成本/毛利外流到這份財務單位使用的文件；PDF 對應顯示「三、申請品項明細」（items 模式）或「三、申請金額」+「四、開票品項參考」（amount 模式）
- **簽核流程**：2026-08-24 起預設與報價單／出貨單／請款單共用 `system_settings.unified_approval_flow`；2026-08-28 起可在「簽核設定」頁套用範圍選單勾掉，改成自己獨立的 `system_settings.invoice_voucher_approval_flow`（同一頁面內展開編輯，不再有獨立的 `invoice-voucher-approval-settings.html`，見 §12 2026-08-28）
- 全部簽核完成 → 狀態 `已核准`，背景觸發 PDF 存檔（`pdf_gen.py _generate_invoice_voucher_pdf`）
- Demo 模式 PDF 隔離目錄：`backend/_demo_invoice_voucher_pdf_archive`

**共同點**：兩者的簽核 tiers 純邏輯共用 `helpers/tiered_approval.py`（2026-08-22 起，見 §12 同日 changelog）；PDF 預覽（`GET .../pdf-download`）任何狀態皆可看、未核准帶浮水印警告橫幅；下載才計入 `export_count`/`export_log`（`POST .../export`）；刪除僅限草稿狀態；`audit-log.html`／`users.html` 通知偏好已比照出貨單補齊對應項目；跟報價單一起整合進統一簽核佇列頁 `approval-queue.html`（2026-08-20j，見 §12）；`approve`/`reject` 端點不限定 admin/superadmin 角色才能操作，改成純粹依「是否為當層簽核人員」判斷（2026-08-20k 修正，比照報價單原本就有的做法）。**簽核逾期催辦**（2026-08-21b，見 §12）：三種文件共用同一套規則，卡在簽核柱列超過工作日 1/3/5 天分級寄信催辦（1/3 天各一次，3 天起同步通知 superadmin，5 天以上每個工作日重複寄），`routers/daily_tasks.py _check_approval_reminders()`，掛在既有每日 08:00 排程裡。

---

### §7.4 · 承攬商管理（DB v22–v25）

| Method | Path | 說明 |
|--------|------|------|
| GET | /vendor-contractors | 承攬商列表（admin+；`?q=` 搜尋 name/tax_id/phone/contact、`?active_only=` 篩選） |
| POST | /vendor-contractors | 新建承攬商（admin+；`data{}` 存 category/tags/notes/visits） |
| GET | /vendor-contractors/selectable | 輕量下拉（需認證，非 admin 亦可；供案件管理下拉） |
| GET/PUT | /vendor-contractors/{id} | 單筆查詢／更新（PUT admin+；PUT 合併 data_json 保留 visits） |
| DELETE | /vendor-contractors/{id} | 刪除（有派發紀錄 → 409，建議改停用） |
| PATCH | /vendor-contractors/{id}/active | 停用／啟用切換（admin+） |
| PATCH | /vendor-contractors/{id}/visits | 往來紀錄更新（樂觀鎖 `expectedUpdatedAt` → 409） |
| GET | /contractor-dispatches | 派發列表（`?quote_no=` 過濾；無參數返回最新 200 筆；回傳含 `personnelTotal`/`grandTotal`，見 §5.7） |
| POST | /contractor-dispatches | 新建派發（需認證；`vendor_id` 選填，DB v37——承攬商與外包名單人員至少擇一，兩者皆空 → 400；自動計算 total_amount；`personnel_json` 外包名單人員快照，見 §5.7） |
| GET/PUT/DELETE | /contractor-dispatches/{id} | 單筆操作（DELETE admin+） |
| GET | /contractors/selectable | 外包名冊輕量下拉（需認證，非 superadmin/`contractor_list` 亦可；供承攬商派發「外包名單人員」選擇，DB v36） |
| PATCH | /contractor-dispatches/{id}/accept | 驗收流程：`action=pending_acceptance`（draft/sent/confirmed→待驗收）或 `action=accepted`（待驗收→已驗收，記錄 accepted_by/accepted_at）；違規轉換 → 409 |
| POST | /contractor-dispatches/{id}/import-to-quote | 回推品項至報價單 `items[]`（報價單非草稿 → 409） |

---

### §7.11 · 承攬商匯款申請／發票開立簽核單（DB v45/v46，見 §5.9，2026-08-20）

| Method | Path | 說明 |
|--------|------|------|
| GET | /contractor-vouchers?quote_no= | 依案件列出承攬商匯款申請摘要（需登入，不含 snapshot） |
| GET | /contractor-vouchers/{voucher_no} | 完整明細（含 snapshot/approval/paid_log/export_log） |
| POST | /contractor-vouchers | `{dispatch_id}` 建立草稿（admin+）；僅 `completed` 派發且尚無憑證可建立；`voucher_no` 由 `next_entity_code(...,'PV',code_col='voucher_no')` 產生 |
| DELETE | /contractor-vouchers/{voucher_no} | 刪除（admin+；非草稿 409） |
| POST | /contractor-vouchers/{voucher_no}/submit | 送出審核（admin+） |
| POST | /contractor-vouchers/{voucher_no}/approve | 簽核（當層簽核人依序；無流程時僅 superadmin） |
| POST | /contractor-vouchers/{voucher_no}/reject | 退回草稿 `{note?}` |
| POST | /contractor-vouchers/{voucher_no}/revoke-approval | 撤銷已核准 `{note?}`；已匯款不可撤銷 |
| GET | /contractor-vouchers/{voucher_no}/pdf-download | Edge PDF（不記錄匯出） |
| POST | /contractor-vouchers/{voucher_no}/export | 記錄匯出人/時間/次數 |
| POST | /contractor-vouchers/{voucher_no}/paid-toggle | `{action:'pay'|'unpay', note?}`；僅已核准可標記，獨立於 status |
| GET/PUT | /contractor-vouchers/settings/approval-flow | 專屬簽核流程設定（PUT 限 superadmin）；讀寫的 key 固定是 `contractor_voucher_approval_flow`，跟送審當下實際生效與否無關（生效與否看 §12 2026-08-28 的套用範圍設定） |
| GET | /invoice-vouchers?quote_no= | 依案件列出發票開立簽核單摘要 |
| GET | /invoice-vouchers/remaining?quote_no= | **建立申請前查剩餘額度**（含合約總額/已申請/剩餘金額＋各報價品項的已申請/剩餘數量）；⚠️ 註冊順序必須在 `/{voucher_no}` 之前，否則會被當成 voucher_no 吃掉 |
| GET | /invoice-vouchers/{voucher_no} | 完整明細（含 snapshot/approval/export_log） |
| POST | /invoice-vouchers | `{quote_no, scope:'amount'\|'items', amount?, items?:[{itemId,qty,amount}]}` 建立草稿（admin+，2026-08-20 重新設計）；金額或選取品項超過剩餘可申請額度會 409；`voucher_no` 由 `next_entity_code(...,'IV',code_col='voucher_no')` 產生 |
| DELETE | /invoice-vouchers/{voucher_no} | 刪除（admin+；非草稿 409；刪除即釋放其佔用的額度，因為剩餘額度是即時從既有列加總算出） |
| POST | /invoice-vouchers/{voucher_no}/submit | 送出審核（admin+） |
| POST | /invoice-vouchers/{voucher_no}/approve | 簽核（同上規則） |
| POST | /invoice-vouchers/{voucher_no}/reject | 退回草稿 `{note?}` |
| POST | /invoice-vouchers/{voucher_no}/revoke-approval | 撤銷已核准 `{note?}` |
| GET | /invoice-vouchers/{voucher_no}/pdf-download | Edge PDF（不記錄匯出） |
| POST | /invoice-vouchers/{voucher_no}/export | 記錄匯出人/時間/次數 |
| （無專屬 settings 端點） | | 簽核流程走統一設定 `/settings/approval-flow` 或（獨立時）`/settings/approval-flow/invoice_voucher`，見 §7.3／§12 2026-08-28 |
