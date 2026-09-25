/* custom-modules-nav.js — 已發布的自訂模組出現在主選單（CUSTOMIZATION-SPEC §8.1、P8）。
 *
 * 🔴 疊加，不改寫既有選單：sidebar.js 的 sec()/ni()/renderMainNav() 一行都不動，
 *    本檔在它渲染好的 #app-mainnav 上**追加**項目（同一套 mnav__ 樣式）。
 *    sidebar.js 只在檔尾多一段「載入本檔」（不影響它自己的流程）。
 * - 清單來源：GET /api/custom-modules（後端已依權限過濾：superadmin 全部、其他人只看有權限的）。
 * - 選單位置：定義的 menu.group（與既有分組同名 ⇒ 併進那一組；否則新開一組，預設「自訂模組」），
 *   同組內依 menu.order 排序。
 * - superadmin 另外在「系統」組追加「模組建構器」入口。
 * - sidebar.js 的 _refreshSession() 會整個重建選單（bar.innerHTML 重寫）⇒ 用 MutationObserver 補回。
 */
;(function () {
  var s = {}
  try { s = JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) { s = {} }
  if (!s.token) return

  var inPg = location.pathname.indexOf('/pages/') >= 0
  function pg(f) { return inPg ? f : 'pages/' + f }
  function esc(t) { return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;') }
  var file = location.pathname.split('/').pop()
  var curKey = new URLSearchParams(location.search).get('key') || ''
  var DEFAULT_GROUP = '自訂模組'
  var MARK = 'data-custom-nav'

  var mods = null
  var observer = null

  function items() {
    var out = []
    ;(mods || []).forEach(function (m) {
      var menu = m.menu || {}
      out.push({
        group: (menu.group || '').trim() || DEFAULT_GROUP,
        order: typeof menu.order === 'number' ? menu.order : 1000,
        label: m.name || m.key,
        href: pg('custom-records.html?key=' + encodeURIComponent(m.key)),
        active: file === 'custom-records.html' && curKey === m.key,
        key: m.key,
      })
    })
    if (s.role === 'superadmin') {
      out.push({ group: '系統', order: -1, label: '模組建構器', href: pg('module-builder.html'),
                 active: file === 'module-builder.html', key: '$builder' })
    }
    out.sort(function (a, b) { return a.order - b.order || String(a.label).localeCompare(String(b.label)) })
    return out
  }

  function linkHtml(it, cls) {
    return '<a class="' + cls + (it.active ? ' is-on' : '') + '" ' + MARK + '="' + esc(it.key) + '" href="' + esc(it.href) + '">'
      + (cls === 'mnav__item' ? '<span>' + esc(it.label) + '</span>' : esc(it.label)) + '</a>'
  }

  function groupLabel(grp) {
    var top = grp.querySelector(':scope > .mnav__top')
    return top ? top.textContent.trim() : ''
  }

  function render() {
    var bar = document.getElementById('app-mainnav')
    if (mods === null) return
    if (!bar) {
      // sidebar.js 還沒渲染選單（或這一頁沒有選單）⇒ 等它出現再補
      var wait = new MutationObserver(function () {
        if (document.getElementById('app-mainnav')) { wait.disconnect(); render() }
      })
      wait.observe(document.body, { childList: true, subtree: true })
      return
    }
    var inner = bar.querySelector('.mnav__in')
    if (!inner) { inner = document.createElement('div'); inner.className = 'mnav__in'; bar.appendChild(inner) }
    bar.querySelectorAll('[' + MARK + ']').forEach(function (el) { el.remove() })

    var byGroup = {}
    var order = []
    items().forEach(function (it) {
      if (!byGroup[it.group]) { byGroup[it.group] = []; order.push(it.group) }
      byGroup[it.group].push(it)
    })
    order.forEach(function (g) {
      var list = byGroup[g]
      // 既有分組（sidebar.js 渲染的下拉）：併進它最後一欄
      var existing = Array.prototype.find.call(inner.querySelectorAll(':scope > .mnav__grp'), function (el) { return groupLabel(el) === g })
      if (existing) {
        var cols = existing.querySelectorAll('.mnav__col')
        var col = cols[cols.length - 1]
        list.forEach(function (it) { col.insertAdjacentHTML('beforeend', linkHtml(it, 'mnav__item')) })
        if (list.some(function (it) { return it.active })) existing.classList.add('is-on')
        return
      }
      if (list.length === 1 && g !== DEFAULT_GROUP) {
        // 與 sidebar.js 一致：只有一項的分組直接當連結
        inner.insertAdjacentHTML('beforeend', linkHtml(list[0], 'mnav__top').replace(MARK + '="', MARK + '="' + esc(g) + ':'))
        return
      }
      var cols2 = []
      for (var i = 0; i < list.length; i += 6) cols2.push(list.slice(i, i + 6))
      var html = '<div class="mnav__grp' + (list.some(function (it) { return it.active }) ? ' is-on' : '') + '" tabindex="0" ' + MARK + '="group:' + esc(g) + '">'
        + '<span class="mnav__top">' + esc(g)
        + '<svg viewBox="0 0 10 6" fill="none" aria-hidden="true"><path d="M1 1l4 4 4-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'
        + '</span><div class="mnav__panel"><div class="mnav__cols">'
        + cols2.map(function (c) { return '<div class="mnav__col">' + c.map(function (it) { return linkHtml(it, 'mnav__item') }).join('') + '</div>' }).join('')
        + '</div></div></div>'
      inner.insertAdjacentHTML('beforeend', html)
    })

    if (!observer && window.MutationObserver) {
      // sidebar.js 重建選單會把整個 bar.innerHTML 換掉 ⇒ 我們的項目消失 ⇒ 補回（有標記就不動，避免迴圈）
      observer = new MutationObserver(function () {
        if (mods !== null && mods.length + (s.role === 'superadmin' ? 1 : 0) > 0 && !bar.querySelector('[' + MARK + ']')) render()
      })
      observer.observe(bar, { childList: true })
    }
  }

  function start() {
    fetch('/api/custom-modules', { headers: { Authorization: 'Bearer ' + s.token } })
      .then(function (r) { return r.ok ? r.json() : [] })
      .then(function (d) { mods = Array.isArray(d) ? d : []; render() })
      .catch(function () { mods = []; render() })
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start)
  else start()
})()
