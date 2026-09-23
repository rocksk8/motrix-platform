# MOTRIX ERP — 模組：出貨單（§5.8、§7.8）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

---

### §5.8 · 出貨單（案件管理子項目，2026-08-01）

```
草稿 → 待審核 → 簽核中 → 已核准
  ↑______________________|（退回，清空 approval，回草稿）
已核准 ⇄ 已回簽（is_signed toggle，獨立於狀態機，僅已核准可切換）
```

- 一個案件（`quote_no`）可對應多張出貨單（分批出貨）；分頁對所有能開案件管理的人可見，**新增/編輯/送審/簽核/匯出 PDF/勾選回簽等操作限 admin+**（與承攬商分頁一致：分頁可見、寫入操作後端擋權限）
- 品項純出貨用途，**不含金額欄位**；可從報價單一鍵匯入品項（前端純轉換，去除 cost/margin/unitPrice/amount），或手動新增/編輯，支援段落標題列（`type:'header'`）
- **簽核流程**：2026-08-24 起預設與報價單／發票開立簽核單／請款單共用 `system_settings.unified_approval_flow`；2026-08-28 起可在「簽核設定」頁（`approval-settings.html`）的套用範圍選單勾掉，改成出貨單自己獨立的 `system_settings.shipping_approval_flow`（同一頁面內展開編輯，不再有獨立的 `shipping-approval-settings.html`，見 §12 2026-08-28）；tiers 依序簽核，有設定流程時申請人可自簽；**無流程時僅 superadmin 可簽（含自簽）**——與報價單「無流程時禁止申請人自簽」的規則刻意不同（2026-08-01g 調整，見 §12）
- 全部簽核完成 → 狀態 `已核准`，背景觸發 PDF 存檔（`pdf_gen.py _generate_shipping_pdf`）
- **已回簽**：`已核准` 狀態才可切換；`signed-toggle` 為嚴格 toggle（已回簽不可重複標記，需先取消），每次切換完整記錄至 `signed_log`（誰、何時、動作、備註），案件管理 UI 可展開查看完整歷程
- PDF 匯出與報價單同一套機制：`GET .../pdf-download` 產生 bytes（不記錄），`POST .../export` 另外累計 `export_count`/`export_log`
- **預覽**：`GET .../pdf-download` 無狀態限制，任何狀態皆可預覽（案件管理 UI「預覽」按鈕，iframe+blob 顯示，不呼叫 `/export`）；預覽 Modal **不提供下載選項**（避免與已核准後的正式匯出/記錄流程混淆），要下載仍須回到列表上已核准狀態的「下載 PDF」按鈕；非已核准狀態下 PDF 本身（`pdf_gen.py _build_shipping_html`）會帶浮水印＋警告橫幅（比照報價單預覽稿樣式，文案「出貨單預覽稿／尚未正式核准」），已核准後乾淨無浮水印
- **收件人聯絡人快選**：新增/編輯 Modal 內若案件所屬客戶（`quotations.data_json.customerId`，或退而用 `customer_name` 比對客戶清單）有登記聯絡人，顯示「選聯絡人」下拉快選；點選僅覆寫欄位值，收件人欄位本身仍可自由輸入
- 刪除僅限 `草稿` 狀態（保留已進入簽核/已回簽的歷程）
- Demo 模式 PDF 隔離目錄：`backend/_demo_shipping_pdf_archive`

---

### §7.8 · 出貨單（DB v34）

| Method | Path | 說明 |
|--------|------|------|
| GET | /shipping-notes?quote_no= | 依案件列出出貨單摘要（需登入，不含完整品項） |
| GET | /shipping-notes/{note_no} | 完整明細（含 items/approval/signed_log/export_log） |
| POST | /shipping-notes | 建立草稿（admin+）；`note_no` 由 `next_entity_code(...,'DN',code_col='note_no')` 產生 |
| PUT | /shipping-notes/{note_no} | 更新（admin+；非草稿 409） |
| DELETE | /shipping-notes/{note_no} | 刪除（admin+；非草稿 409） |
| POST | /shipping-notes/{note_no}/submit | 送出審核（admin+；產生 tiers 快照，狀態→待審核） |
| POST | /shipping-notes/{note_no}/approve | 簽核（當層簽核人依序；無流程時僅 superadmin 且禁止申請人自簽） |
| POST | /shipping-notes/{note_no}/reject | 退回草稿（當層成員或 superadmin；簡化版，不改版號） |
| GET | /shipping-notes/{note_no}/pdf-download | Edge PDF（不記錄匯出） |
| POST | /shipping-notes/{note_no}/export | 記錄匯出人/時間/次數（`export_count`/`export_log`） |
| POST | /shipping-notes/{note_no}/signed-toggle | `{action:'sign'|'unsign', note?}`；已核准才可切換，嚴格 toggle（409 若狀態不符） |
| （無專屬 settings 端點） | | 簽核流程走統一設定 `/settings/approval-flow` 或（獨立時）`/settings/approval-flow/shipping`，見 §7.3／§12 2026-08-28 |
