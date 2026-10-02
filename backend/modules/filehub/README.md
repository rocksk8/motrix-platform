# 檔案中心（filehub）

全系統上傳檔案的分類搜尋頁＋案件頁「全部附件」。**不建表、不存檔案、不做權限判斷**：
每個擁有模組自己以 `attachments.catalog` 提供者（`CATEGORIES`／`search`／`count`／`open`）回答「這個人看得到哪些檔」，本模組只合併、排序、分頁。

- 開檔：L1 `GET /api/attachments/open`（提供者驗權；看不到＝404）；預覽：L1 `static/file-preview.js`（`MotrixFilePreview`）
- 看不到的檔不列、也不回「因權限未列出 N 個」（`q` 可任意輸入，回個數本身就是外洩）
- 模組不在／提供者壞掉 ⇒ 回應 `unavailable` 明說那一類沒有列入（不是 0 筆）
- 新增一種上傳點：照 proposal-attachments-search-preview §4-5 在擁有模組登記提供者；本模組不用改
