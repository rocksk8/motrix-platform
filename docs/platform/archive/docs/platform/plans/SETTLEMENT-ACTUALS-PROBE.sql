-- 唯讀：只回計數（不含任何客戶或金額內容）。正式機以唯讀方式執行（sqlite3 -readonly 或 file:...?mode=ro）。
-- 報價單品項（type<>'header'）缺 id 或缺說明的筆數，以及涉及幾張報價單；33-A2 以暫時鍵納入（da S3）。
SELECT COUNT(*)                              AS items_missing_id_or_desc,
       COUNT(DISTINCT q.quote_no)            AS quotations_affected,
       SUM(COALESCE(TRIM(json_extract(j.value,'$.id')),'')='')          AS missing_id,
       SUM(COALESCE(TRIM(json_extract(j.value,'$.description')),'')='') AS missing_desc
FROM quotations q, json_each(q.data_json, '$.items') j
WHERE COALESCE(json_extract(j.value,'$.type'),'') <> 'header'
  AND (COALESCE(TRIM(json_extract(j.value,'$.id')),'')='' OR COALESCE(TRIM(json_extract(j.value,'$.description')),'')='');
-- 另：精算存檔的品項沒有 adoptSystem 鍵（第 32 班前存的）且案件有精算草稿的張數（A2 預設不採用，歷史相容）。
SELECT COUNT(DISTINCT q.quote_no) AS drafts_with_legacy_items
FROM quotations q, json_each(q.data_json, '$.settlement.items') j
WHERE COALESCE(json_extract(q.data_json,'$.settlement.status'),'') <> 'finalized'
  AND json_extract(j.value,'$.adoptSystem') IS NULL;
