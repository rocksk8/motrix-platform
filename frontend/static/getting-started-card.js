/* 「開始使用」進度卡（系統總覽首頁；批次「開始使用清單面板」，2026-11-13）
 * 讀 GET /api/getting-started（只有最高管理者；其他角色或讀不到時整塊隱藏、不顯示任何錯誤）。
 * 用法：頁面放 <div data-getting-started-card></div> 並載入本檔。文字全部用 textContent。
 */
(function () {
  'use strict'
  function session() { try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) { return {} } }
  function el(tag, text) { var n = document.createElement(tag); if (text != null) n.textContent = text; return n }

  function render(host, d) {
    host.textContent = ''
    if (!d || !d.progress || d.allDone) { host.style.display = 'none'; return }
    host.style.display = ''
    var box = el('div')
    box.setAttribute('data-testid', 'gs-card')
    box.style.cssText = 'display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin:0 0 14px;padding:12px 16px;border:1px solid var(--tone-info-border,#BFDBFE);background:var(--tone-info-bg,#EFF6FF);color:var(--tone-info-fg,#1E3A8A);border-radius:var(--radius-lg,10px);font-size:13px'
    var left = el('div')
    var todo = d.progress.total - d.progress.done - d.progress.skipped
    var t = el('div', todo > 0 ? '開始使用　已完成 ' + d.progress.done + '／' + d.progress.total + (d.progress.skipped ? '，略過 ' + d.progress.skipped : '')
                              : '開始使用　還有 ' + d.progress.skipped + ' 項略過，可隨時回來完成')
    t.style.cssText = 'font-weight:700;font-size:14px'
    left.appendChild(t)
    if (d.next) {
      var n = el('div', '下一步：' + d.next.title + '（' + d.next.minutes + '）')
      n.setAttribute('data-testid', 'gs-card-next')
      n.style.cssText = 'margin-top:2px;font-size:12.5px'
      left.appendChild(n)
    }
    box.appendChild(left)
    var a = el('a', '查看完整清單 →')
    a.href = 'getting-started.html'
    a.setAttribute('data-testid', 'gs-card-link')
    a.style.cssText = 'font-weight:600;white-space:nowrap;text-decoration:underline;color:inherit'
    box.appendChild(a)
    host.appendChild(box)
  }

  function load(host) {
    var s = session()
    if (!s.token || (s.role && s.role !== 'superadmin')) { host.style.display = 'none'; return }
    fetch('/api/getting-started', { headers: { Authorization: 'Bearer ' + s.token } })
      .then(function (r) { return r.ok ? r.json() : null })
      .then(function (d) { render(host, d) })
      .catch(function () { host.style.display = 'none' })
  }

  function auto() { Array.prototype.forEach.call(document.querySelectorAll('[data-getting-started-card]'), load) }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', auto); else auto()
})()
