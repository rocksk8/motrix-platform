# 檔案中心 更新紀錄

## (next) — 2026-10-01（fix/filehub-guards：守門三紅）
- `api.py`：類別清單合併改用 `{"type": t, **meta}`（不以 `**` 當呼叫引數，守門 `test_case_summary_purpose`）；補 `SPEC.md`（FHB1～FHB8，模組檔案齊全守門）。行為與介面不變。

## 1.0.0 — 2026-09-30（暫用號，列車取號；wip/w1-attach-p3 附件目錄 P3）
- 新增：`GET /api/filehub/search`（關鍵字、類別、副檔名、上傳日期區間、上傳者、案件號／單號、客戶；合併各 `attachments.catalog` 提供者的 `search`／`count`，依上傳時間由新到舊、`page ≤ 20`、`size ≤ 50`；回 `items`／`facets`／`categories`／`unavailable`；項目沒有 path，看不到的不列也不回個數；模組不在或提供者失敗明說）。
- 新增：頁面 `file-center.html`（系統群組「檔案中心」，權限／模組開關 `file_center`）：左側分類樹（模組→單據類別＋命中數）、條件列（條件寫進網址）、結果表、點列用共用預覽元件（◀ ▶ 在結果內切換）、「開啟原單據」；預設只查近 90 天（可改）。
- 案件管理頁「全部附件」頁籤（檔案中心在才出現）呼叫同一支 API 固定 `quote_no`。
