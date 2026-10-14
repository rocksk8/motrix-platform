/* export-guard.js — 瀏覽器端產檔的匯出（SheetJS）的稽核紀錄（BP-3；只記錄，不擋）
 *
 * 客戶、料號、供應商三頁以 SheetJS 在瀏覽器產 xlsx，原本沒有 `export.xlsx` 稽核。
 * 用法：`if (!(await MotrixExport.guard('customers', rows.length))) return`（在 XLSX.writeFile 之前；永遠回 true，保留寫法以便日後加限制）。
 * - 只有 builder_exports 開啟時才送：sidebar.js 會在 /api/platform/menu 回 exportAudit:true 時設 window.MOTRIX_EXPORT_AUDIT；
 *   沒設 ⇒ 完全不發請求（行為與今天相同）。
 * - fire-and-forget：不等回應、不看狀態碼、錯誤只寫 console；永遠不會擋住匯出。
 * 這是『自報』紀錄：伺服器無法證明檔案真的產生。資料本身已在 API 層依權限遮蔽。
 */
;(function () {
  if (window.MotrixExport) return
  function token() {
    try { return (JSON.parse(localStorage.getItem('motrix_session') || 'null') || {}).token || '' } catch (e) { return '' }
  }
  function guard(name, rows) {
    if (window.MOTRIX_EXPORT_AUDIT === true) {
      try {
        Promise.resolve(fetch('/api/exports/client-log', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + token(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name, rows: rows | 0 }),
          keepalive: true
        })).catch(function (e) { console.warn('[export-guard] 稽核紀錄沒送出（不影響匯出）：', e) })
      } catch (e) { console.warn('[export-guard] 稽核紀錄沒送出（不影響匯出）：', e) }
    }
    return Promise.resolve(true)
  }
  window.MotrixExport = { guard: guard }
})()
