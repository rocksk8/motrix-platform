/* menu-editor.js — 選單建構器（BP-1）：側欄項改名、換到另一個既有群組、調順序／隱藏，發布前預覽整份選單。
 *
 * 只在「設定 builder_menu.enabled 開啟 ＋ 最高管理者」時，由 sidebar.js 在 /api/platform/menu 回 builderMenu:true 後載入（關著 ⇒ 這支檔案不會被載入）。
 * 不碰頁面內排版器（layout-editor.js／layout-runtime.js 屬排版器）：這裡自己是一個浮動面板，資料經既有的版面定義（kind=layout，key=module:<模組>，scope=company）
 * 發布，所以版本、稽核、還原都沿用定義文件庫；非側欄的版面操作（排版器存的）原樣保留。
 *
 * 只是顯示：改名與換群組不改任何人的權限（href、perm 不變）；沒有權限的項目不會出現在預覽。
 * 發布前一定要先預覽「同一份」草稿（POST /api/platform/menu/preview）；草稿一改就要重新預覽。
 * 所有文字用 textContent 寫入（名稱是使用者輸入，不用 innerHTML）。
 */
;(function () {
  if (window.MotrixMenuEditor) return
  var LABEL_MAX = 20
  var st = { open: false, busy: false, msg: '', msgBad: false, decl: [], base: {}, work: {}, order: {}, mods: {}, previewKey: '', preview: null, who: '' }

  function session() {
    try { return JSON.parse(localStorage.getItem('motrix_session') || 'null') || {} } catch (e) { return {} }
  }
  function api(method, url, body) {
    var h = { Authorization: 'Bearer ' + (session().token || '') }
    if (body !== undefined) h['Content-Type'] = 'application/json'
    return fetch(url, { method: method, headers: h, body: body === undefined ? undefined : JSON.stringify(body) }).then(function (r) {
      return r.json().catch(function () { return {} }).then(function (j) {
        if (!r.ok) { var e = new Error(msgOf(j) || ('HTTP ' + r.status)); e.status = r.status; e.body = j; throw e }
        return j
      })
    })
  }
  function msgOf(j) {
    var d = j && (j.detail !== undefined ? j.detail : j)
    if (d && d.problems) return d.problems.map(function (p) { return (p.path ? p.path + '：' : '') + p.message }).join('；')
    if (j && j.problems && j.problems.length) return j.problems.map(function (p) { return (p.path ? p.path + '：' : '') + p.message }).join('；')
    return typeof d === 'string' ? d : ''
  }
  function el(tag, attrs, kids) {
    var n = document.createElement(tag)
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] === null || attrs[k] === undefined) return
      if (k === 'text') n.textContent = attrs[k]
      else if (k.indexOf('on') === 0) n.addEventListener(k.slice(2), attrs[k])
      else n.setAttribute(k, attrs[k])
    })
    ;(kids || []).forEach(function (c) { if (c) n.appendChild(c) })
    return n
  }
  function pid(it) { return it.module ? it.module + ':' + it.href + '/sidebar' : null }
  function labelProblem(v) {
    if (!v.trim()) return '名稱不可空白'
    if (v.trim().length > LABEL_MAX) return '最多 ' + LABEL_MAX + ' 字'
    if (/[<>&"'`\\\x00-\x1f\x7f]/.test(v)) return '不可含 < > & 引號、反斜線'
    return ''
  }

  // ── 狀態：宣告版（base）＋ 已發布的公司層側欄操作 ⇒ 工作副本（work：每個群組的項目順序、名稱、隱藏）────────────────
  function load() {
    st.busy = true; st.msg = '讀取中…'; render()
    return api('GET', '/api/platform/menu').then(function (d) {
      st.decl = d.groups || []
      st.base = {}; st.order = {}; st.work = {}
      st.decl.forEach(function (g) {
        st.order[g.key] = g.items.map(function (it) { return it.module ? pid(it) : 'l1:' + it.href })
        g.items.forEach(function (it) {
          var id = it.module ? pid(it) : 'l1:' + it.href
          st.base[id] = { id: id, group: g.key, label: it.label, href: it.href, module: it.module || null }
          st.work[id] = { label: it.label, hidden: false }
        })
      })
      var mods = {}
      Object.keys(st.base).forEach(function (id) { if (st.base[id].module) mods[st.base[id].module] = true })
      return Promise.all(Object.keys(mods).map(function (m) {
        return api('GET', '/api/definitions/layout/module:' + encodeURIComponent(m) + '?scope=company').then(function (r) {
          var cur = r.draft || r.latest
          st.mods[m] = { ops: (cur && cur.body && cur.body.ops) || [], etag: (r.draft && r.draft.etag) || '' }
        }).catch(function () { st.mods[m] = { ops: [], etag: '' } })
      }))
    }).then(function () {
      Object.keys(st.mods).forEach(function (m) { st.mods[m].ops.forEach(applyExisting) })
      st.busy = false; st.msg = ''; st.previewKey = ''; st.preview = null; render()
    }).catch(function (e) { st.busy = false; st.msg = '讀取失敗：' + e.message; st.msgBad = true; render() })
  }
  function applyExisting(op) {
    if (!op || typeof op.target !== 'string' || !/\/sidebar$/.test(op.target) || !st.work[op.target]) return
    var w = st.work[op.target]
    if (op.op === 'relabel') w.label = op.label
    else if (op.op === 'hide') w.hidden = true
    else if (op.op === 'show') w.hidden = false
    else if (op.op === 'move') {
      var to = typeof op.to === 'string' && op.to.indexOf('group:') === 0 ? op.to.slice(6) : st.base[op.target].group
      if (st.order[to]) {
        Object.keys(st.order).forEach(function (k) { st.order[k] = st.order[k].filter(function (x) { return x !== op.target }) })
        var idx = typeof op.index === 'number' ? Math.min(op.index, st.order[to].length) : st.order[to].length
        st.order[to].splice(idx, 0, op.target)
      }
    }
  }
  function groupOf(id) {
    var found = null
    Object.keys(st.order).forEach(function (k) { if (st.order[k].indexOf(id) >= 0) found = k })
    return found
  }

  // ── 工作副本 ⇒ 側欄 ops（對每個『最終順序與宣告不同』的群組，依最終順序發出每個模組項目的 move）─────────────────────
  function buildOps() {
    var ops = []
    Object.keys(st.base).forEach(function (id) {
      var b = st.base[id], w = st.work[id]
      if (!b.module) return
      if (w.label !== b.label) ops.push({ op: 'relabel', target: id, label: w.label })
      if (w.hidden) ops.push({ op: 'hide', target: id })
    })
    st.decl.forEach(function (g) {
      var finalIds = st.order[g.key]
      var declIds = g.items.map(function (it) { return it.module ? pid(it) : 'l1:' + it.href })
      if (finalIds.join('|') === declIds.join('|')) return
      finalIds.forEach(function (id, i) {
        var b = st.base[id]
        if (!b.module) return
        var op = { op: 'move', target: id, index: i }
        if (b.group !== g.key) op.to = 'group:' + g.key
        ops.push(op)
      })
    })
    return ops
  }
  function dirtyKey() { return JSON.stringify(buildOps()) }

  // ── 動作 ───────────────────────────────────────────────────────────────────────────────────────────────
  function doPreview() {
    var bad = Object.keys(st.work).filter(function (id) { return labelProblem(st.work[id].label) })
    if (bad.length) { st.msg = '「' + st.work[bad[0]].label + '」：' + labelProblem(st.work[bad[0]].label); st.msgBad = true; return render() }
    var ops = buildOps(), key = JSON.stringify(ops)
    st.busy = true; st.msg = '產生預覽…'; st.msgBad = false; render()
    var body = { ops: ops }
    if (st.who.trim()) body.user = st.who.trim()
    api('POST', '/api/platform/menu/preview', body).then(function (d) {
      st.preview = d; st.previewKey = key; st.busy = false
      st.msg = d.skipped && d.skipped.length ? '有 ' + d.skipped.length + ' 項操作對這位使用者不適用（沒有權限或看不到目的群組），已略過。' : '預覽完成。'
      render()
    }).catch(function (e) { st.busy = false; st.msg = '預覽失敗：' + e.message; st.msgBad = true; render() })
  }
  function doPublish() {
    if (!st.preview || st.previewKey !== dirtyKey()) { st.msg = '草稿已變更，請先重新預覽'; st.msgBad = true; return render() }
    var ops = buildOps()
    var mods = Object.keys(st.mods)
    st.busy = true; st.msg = '發布中…'; st.msgBad = false; render()
    var chain = Promise.resolve(), done = 0, pend = 0
    mods.forEach(function (m) {
      var mine = ops.filter(function (o) { return o.target.indexOf(m + ':') === 0 })
      var keep = st.mods[m].ops.filter(function (o) { return !(o && typeof o.target === 'string' && /\/sidebar$/.test(o.target) && o.target.indexOf(m + ':') === 0) })
      var next = keep.concat(mine)
      if (JSON.stringify(next) === JSON.stringify(st.mods[m].ops)) return
      chain = chain.then(function () {
        var url = '/api/definitions/layout/module:' + encodeURIComponent(m)
        return api('PUT', url + '/draft?scope=company', { body: { ops: next }, base_etag: st.mods[m].etag || undefined }).then(function (r) {
          return api('POST', url + '/publish?scope=company', { note: '選單建構器', base_etag: r.etag })
        }).then(function (pr) { if (pr && pr.pending === true) pend++; else done++ })      // T60 S2：放寬的變更不會立刻發布，回 pending:true（需第二位最高管理者核准）
      })
    })
    chain.then(function () {
      var pm = pend ? '；另有 ' + pend + ' 個模組的放寬變更待第二位最高管理者核准，核准前不會生效。' : ''
      st.busy = false; st.msg = '已發布（' + done + ' 個模組的版面）。重新整理頁面即可看到新的側欄。' + pm; st.msgBad = false
      return load().then(function () { st.msg = '已發布（' + done + ' 個模組的版面）。重新整理頁面即可看到新的側欄。' + pm; render() })
    }).catch(function (e) { st.busy = false; st.msg = '發布失敗：' + e.message + '（已發布的模組不會回復，可在版本清單還原）'; st.msgBad = true; render() })
  }
  function move(id, dir) {
    var g = groupOf(id), arr = st.order[g], i = arr.indexOf(id), j = i + dir
    if (j < 0 || j >= arr.length) return
    arr.splice(i, 1); arr.splice(j, 0, id); changed()
  }
  function toGroup(id, key) {
    var g = groupOf(id)
    if (g === key) return
    st.order[g] = st.order[g].filter(function (x) { return x !== id })
    st.order[key].push(id); changed()
  }
  function changed() { st.msg = ''; render() }

  // ── 畫面 ───────────────────────────────────────────────────────────────────────────────────────────────
  var btn, panel
  function css() {
    if (document.getElementById('menu-editor-css')) return
    var s = el('style', { id: 'menu-editor-css', text:
      '#me-btn{position:fixed;left:12px;bottom:12px;z-index:1150;padding:6px 12px;font-size:12px}' +
      '#me-panel{position:fixed;top:0;right:0;bottom:0;width:420px;max-width:100vw;z-index:1190;background:var(--bg-card,#fff);border-left:1px solid var(--border-light,#ddd);box-shadow:-8px 0 24px rgba(0,0,0,.08);display:flex;flex-direction:column;font-size:12px}' +
      '#me-panel .me-h{padding:10px 14px;border-bottom:1px solid var(--border-light,#ddd);display:flex;gap:8px;align-items:center}' +
      '#me-panel .me-b{flex:1;overflow:auto;padding:10px 14px}#me-panel .me-f{padding:10px 14px;border-top:1px solid var(--border-light,#ddd);display:flex;gap:8px;flex-wrap:wrap}' +
      '#me-panel .me-g{font-weight:600;margin:10px 0 4px}#me-panel .me-i{display:flex;gap:4px;align-items:center;padding:3px 0}' +
      '#me-panel .me-i input[type=text]{flex:1;min-width:0}#me-panel .me-i.is-hidden{opacity:.5}#me-panel .me-msg{padding:6px 14px}#me-panel .me-bad{color:#c0392b}' +
      '#me-panel .me-pv{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px}#me-panel .me-pv ul{margin:2px 0 6px 16px;padding:0}#me-panel .me-chg{background:#fff3cd}' +
      '@media (max-width:1023px){#me-btn{display:none!important}}' })
    document.head.appendChild(s)
  }
  function groupSelect(id) {
    var cur = groupOf(id)
    var sel = el('select', { title: '群組', onchange: function (e) { toGroup(id, e.target.value) } })
    st.decl.forEach(function (g) {
      // T60：含 hub 項的群組（系統中心）導覽列會收成單一連結，搬進去看不到 ⇒ 不當目的地（項目本來就在裡面時才保留，免得下拉選不到現值）
      if (g.items.some(function (it) { return it.hub }) && g.key !== cur) return
      var o = el('option', { value: g.key, text: g.label }); if (g.key === cur) o.selected = true; sel.appendChild(o)
    })
    return sel
  }
  function itemRow(id) {
    var b = st.base[id], w = st.work[id]
    if (!b.module) return el('div', { class: 'me-i', 'data-id': id }, [el('span', { style: 'flex:1;color:#888', text: b.label + '（固定項目）' })])
    var inp = el('input', { type: 'text', maxlength: String(LABEL_MAX), value: w.label, title: '顯示名稱',
      onchange: function (e) { w.label = e.target.value; changed() } })
    var row = el('div', { class: 'me-i' + (w.hidden ? ' is-hidden' : ''), 'data-id': id }, [
      el('input', { type: 'checkbox', title: '顯示', onchange: function (e) { w.hidden = !e.target.checked; changed() } }),
      inp, groupSelect(id),
      el('button', { type: 'button', title: '上移', text: '↑', onclick: function () { move(id, -1) } }),
      el('button', { type: 'button', title: '下移', text: '↓', onclick: function () { move(id, 1) } })])
    row.firstChild.checked = !w.hidden
    var pr = labelProblem(w.label)
    if (pr) row.appendChild(el('span', { class: 'me-bad', text: pr }))
    return row
  }
  function groupsList(groups, ref) {
    var root = el('div')
    groups.forEach(function (g) {
      var refG = (ref || []).filter(function (x) { return x.key === g.key })[0]
      root.appendChild(el('div', { class: 'me-g', text: g.label }))
      var ul = el('ul')
      g.items.forEach(function (it) {
        var same = refG && refG.items.some(function (r) { return r.href === it.href && r.label === it.label && r.module === it.module })
        ul.appendChild(el('li', { class: ref && !same ? 'me-chg' : '', text: it.label }))
      })
      root.appendChild(ul)
    })
    return root
  }
  function render() {
    css()
    if (!btn) { btn = el('button', { id: 'me-btn', type: 'button', class: 'btn btn-ghost btn-sm', 'data-testid': 'me-open', text: '調整選單', onclick: function () { st.open = !st.open; if (st.open && !st.decl.length) load(); else render() } }); document.body.appendChild(btn) }
    if (panel) { panel.remove(); panel = null }
    if (!st.open) return
    var dirty = !!st.previewKey && st.previewKey === dirtyKey()
    var body = el('div', { class: 'me-b' })
    body.appendChild(el('div', { style: 'color:#666;margin-bottom:6px', text: '只改側欄怎麼顯示，不改任何人的權限；沒有權限的項目不會出現在預覽。範圍：公司預設。' }))
    st.decl.forEach(function (g) {
      body.appendChild(el('div', { class: 'me-g', text: g.label }))
      ;(st.order[g.key] || []).forEach(function (id) { body.appendChild(itemRow(id)) })
    })
    if (st.preview) {
      body.appendChild(el('div', { class: 'me-g', text: '預覽（' + st.preview.user + '／' + st.preview.role + '）：左＝目前已發布，右＝套用草稿後（黃底＝有變）' }))
      body.appendChild(el('div', { class: 'me-pv', 'data-testid': 'me-preview' }, [groupsList(st.preview.current), groupsList(st.preview.preview, st.preview.current)]))
    }
    var who = el('input', { type: 'text', placeholder: '預覽身分（帳號；空白＝我自己）', value: st.who, style: 'flex:1', onchange: function (e) { st.who = e.target.value; st.previewKey = ''; render() } })
    panel = el('div', { id: 'me-panel', 'data-busy': st.busy ? '1' : '0' }, [
      el('div', { class: 'me-h' }, [el('b', { text: '調整選單' }), who, el('button', { type: 'button', text: '✕', onclick: function () { st.open = false; render() } })]),
      body,
      el('div', { class: 'me-msg' + (st.msgBad ? ' me-bad' : ''), text: st.msg }),
      el('div', { class: 'me-f' }, [
        el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-testid': 'me-preview-btn', text: '預覽', disabled: st.busy ? 'disabled' : null, onclick: doPreview }),
        el('button', { type: 'button', class: 'btn btn-primary btn-sm', 'data-testid': 'me-publish', text: '發布', title: dirty ? '' : '請先預覽同一份草稿', onclick: doPublish }),
        el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '重新載入', onclick: load })])])
    var pub = panel.querySelector('[data-testid=me-publish]')
    if (pub && (st.busy || !dirty)) pub.setAttribute('disabled', 'disabled')
    document.body.appendChild(panel)
  }

  window.MotrixMenuEditor = { open: function () { st.open = true; return load() }, _state: st, _buildOps: buildOps }
  render()
})()
