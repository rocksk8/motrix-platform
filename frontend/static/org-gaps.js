/* 組織設定缺口檢查橫幅（批次 5a，2026-11-13）
 * 讀 GET /api/org/gaps（只有管理者以上能讀；沒權限或沒缺口時什麼都不顯示）。
 * 用法：頁面放 <div id="org-gaps" data-org-gaps></div> 並載入本檔；本檔載入後自動掛上。
 *   MotrixOrgGaps.mount(el)    掛到指定元素（重複呼叫會重新查詢）
 *   MotrixOrgGaps.refresh()    重新查詢所有已掛上的橫幅（例如新增使用者之後）
 * 文字全部由後端提供（白話），這裡只負責畫；人名一律用 textContent，不會被當成 HTML。
 */
(function () {
  'use strict'
  var mounted = []

  function session() {
    try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) { return {} }
  }
  function token() { return session().token || '' }
  // 只有管理者以上看得到；已知不是管理者就不發請求（沒存角色的舊登入照舊發，由後端擋）
  function canSee() {
    var r = session().role
    return !r || r === 'superadmin' || r === 'admin'
  }

  function el(tag, props, text) {
    var n = document.createElement(tag)
    if (props) Object.keys(props).forEach(function (k) { n.setAttribute(k, props[k]) })
    if (text != null) n.textContent = text
    return n
  }

  function names(items, count) {
    if (!items || !items.length) return ''
    var shown = items.slice(0, 5).map(function (i) { return i.note ? i.name + '（' + i.note + '）' : i.name })
    return shown.join('、') + (count > shown.length ? ' 等 ' + count + ' 項' : '')
  }

  function render(host, data) {
    host.textContent = ''
    if (!data || data.ok || !data.gaps || !data.gaps.length) { host.style.display = 'none'; return }
    host.style.display = ''
    var box = el('div', { 'data-testid': 'org-gaps-box', role: 'status' })
    box.style.cssText = 'border:1px solid #F59E0B;background:#FFFBEB;color:#78350F;border-radius:8px;padding:12px 14px;margin:0 0 16px'
    box.appendChild(el('div', { 'data-testid': 'org-gaps-head' }, '組織設定還有 ' + data.gaps.length + ' 項需要補齊'))
    box.firstChild.style.cssText = 'font-weight:700;font-size:14px;margin-bottom:6px'
    data.gaps.forEach(function (g) {
      var row = el('div', { 'data-testid': 'org-gap-' + g.key })
      row.style.cssText = 'display:flex;gap:10px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;padding:6px 0;border-top:1px solid rgba(245,158,11,.35)'
      var left = el('div')
      left.style.cssText = 'flex:1 1 260px;min-width:0'
      var t = el('div', null, g.title); t.style.cssText = 'font-weight:600;font-size:13px'
      var d = el('div', null, g.detail); d.style.cssText = 'font-size:12px;margin-top:2px'
      left.appendChild(t); left.appendChild(d)
      var nm = names(g.items, g.count)
      if (nm) { var n = el('div', { 'data-testid': 'org-gap-names-' + g.key }, nm); n.style.cssText = 'font-size:12px;margin-top:2px;opacity:.85;word-break:break-all'; left.appendChild(n) }
      row.appendChild(left)
      if (g.fix && g.fix.href) {
        var a = el('a', { href: g.fix.href, 'data-testid': 'org-gap-fix-' + g.key }, g.fix.label + ' →')
        a.style.cssText = 'font-size:12px;font-weight:600;color:#92400E;white-space:nowrap;text-decoration:underline;align-self:center'
        row.appendChild(a)
      }
      box.appendChild(row)
    })
    host.appendChild(box)
  }

  var seq = 0   // 連續重查時，只認最後一次發出的回應（晚到的舊回應不可蓋掉新的）
  function load(host) {
    var tk = token()
    if (!tk || !canSee()) { host.style.display = 'none'; return Promise.resolve() }
    var mine = ++seq
    host.setAttribute('data-org-gaps-seq', String(mine))
    return fetch('/api/org/gaps', { headers: { Authorization: 'Bearer ' + tk } })
      .then(function (r) { return r.ok ? r.json() : null })
      .then(function (d) { if (host.getAttribute('data-org-gaps-seq') === String(mine)) render(host, d) })
      .catch(function () { if (host.getAttribute('data-org-gaps-seq') === String(mine)) host.style.display = 'none' })
  }

  function mount(host) {
    if (!host) return Promise.resolve()
    if (mounted.indexOf(host) < 0) mounted.push(host)
    return load(host)
  }

  function refresh() { return Promise.all(mounted.map(load)) }

  function auto() { Array.prototype.forEach.call(document.querySelectorAll('[data-org-gaps]'), mount) }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', auto); else auto()

  window.MotrixOrgGaps = { mount: mount, refresh: refresh }
})()
