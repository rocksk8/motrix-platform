/* export-guard.js — 瀏覽器端產檔的匯出（SheetJS）先過伺服器的稽核與冷卻（BP-3）
 *
 * 客戶、料號、供應商三頁以 SheetJS 在瀏覽器產 xlsx，原本沒有 `export.xlsx` 稽核、也沒有匯出冷卻。
 * 用法：`if (!(await MotrixExport.guard('customers', rows.length))) return`（在 XLSX.writeFile 之前）。
 * - 伺服器回 429（冷卻中）⇒ 顯示白話訊息並回 false（不產檔）；
 * - 網路錯誤／伺服器暫時不可用 ⇒ 回 true（不因為稽核端點故障而讓人匯不出檔案；錯誤只寫 console）；
 * - 其他錯誤（401 等）⇒ 回 true（登入失效由頁面自己的守門處理）。
 * 這是『自報』紀錄：伺服器無法證明檔案真的產生。資料本身已在 API 層依權限遮蔽。
 */
;(function () {
  if (window.MotrixExport) return
  function token() {
    try { return (JSON.parse(localStorage.getItem('motrix_session') || 'null') || {}).token || '' } catch (e) { return '' }
  }
  function toast(msg) {
    try {
      var n = document.createElement('div')
      n.textContent = msg
      n.setAttribute('style', 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#111827;color:#fff;padding:8px 14px;border-radius:8px;font-size:13px;z-index:9999')
      document.body.appendChild(n)
      setTimeout(function () { if (n.remove) n.remove() }, 3500)
    } catch (e) { /* 沒有 DOM（測試）就算了 */ }
  }
  function guard(name, rows) {
    return fetch('/api/exports/client-log', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + token(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, rows: rows | 0 })
    }).then(function (r) {
      if (r.status === 429) {
        return r.json().catch(function () { return {} }).then(function (j) {
          toast(typeof j.detail === 'string' ? j.detail : '請稍等幾秒後再匯出')
          return false
        })
      }
      return true
    }).catch(function (e) { console.warn('[export-guard] 稽核端點讀不到，仍繼續匯出：', e); return true })
  }
  window.MotrixExport = { guard: guard }
})()
