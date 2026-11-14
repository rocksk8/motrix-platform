// 自訂報表頁（T87 B2-S4）。設計：D:\Claude-pm\t87-design\B2-custom-reports.md；樣稿：B2-custom-reports-mock.html（r2，h5 審過）。
// 原則：①哪些來源、欄位、運算子、選項全部來自 GET /api/custom-reports/sources，頁面不寫死任何欄位；
//       ②欄位／列的可見性只由後端決定，這裡只畫「無權限」與通用說明，不推論原因；
//       ③預覽與匯出一律由後端以「目前登入者」的權限重算；④文字一律用 textContent，不拼 HTML。
// 頁面不使用 Alpine：矩陣每次操作整張重畫，焦點靠 data-fk 找回（keepFocus）。
(function () {
  'use strict'

  var API = '/api/custom-reports'
  var PERIODS = [['this_month', '本月'], ['last_month', '上月'], ['this_quarter', '本季'], ['this_year', '今年'], ['last_year', '去年'], ['last_30_days', '近 30 天']]
  var OPNAME = { eq: '等於', neq: '不等於', contains: '包含', 'in': '屬於', gte: '大於等於', lte: '小於等於', between: '介於', relative: '期間', empty: '未填', not_empty: '有填', is_me: '是我' }
  var DATE_OPNAME = { eq: '等於', gte: '不早於', lte: '不晚於' }
  var AGG_NAME = { sum: '合計', avg: '平均', min: '最小', max: '最大', count: '筆數' }
  var BUCKET_NAME = { month: '月', quarter: '季', year: '年' }
  var KIND_NAME = { show: '顯示', f: '篩選', g: '分組', agg: '彙總', sort: '排序' }
  var TYPE_NAME = { text: '文字', 'enum': '選項', date: '日期', money: '金額', percent: '比率', number: '數字' }
  var LOCK_TEXT = '無權限：您的帳號沒有這些欄位的檢視權限；它們不會顯示在報表與匯出檔中，也不能用於篩選、分組或排序。'
  var EXPORT_MAX = 10000

  var SRC = {}, ORDER = [], LIM = { previewRows: 50, columns: 20, filters: 6, groupBy: 2, aggregates: 6, sort: 1 }
  var CAN_EXPORT = false
  var LIST = { mine: [], shared: [], sharingEnabled: false, recycleDeleted: false, max: 30, nameMax: 40 }
  var S = { source: '', cols: [], filters: [], groups: [], aggs: [], count: false, sort: null, layout: 'detail', loaded: null, base: '', picked: {} }
  var UNDO = null
  var P = { state: 'idle' }                      // 預覽狀態：idle／loading／ok／local／error
  var pv = { seq: 0, timer: null }

  function $(id) { return document.getElementById(id) }
  function h(tag, attrs, kids) {
    var e = document.createElement(tag)
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k]
      if (k === 'text') e.textContent = v
      else if (k === 'class') e.className = v
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v)
      else if (v === true) e.setAttribute(k, '')
      else if (v !== false && v != null) e.setAttribute(k, v)
    });
    (kids || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c) })
    return e
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild) }
  function has(a, v) { return a.indexOf(v) >= 0 }
  function toggle(a, v, on) { var i = a.indexOf(v); if (on && i < 0) a.push(v); if (!on && i >= 0) a.splice(i, 1) }
  function clone(x) { return JSON.parse(JSON.stringify(x)) }
  function num(x) { try { return window.MotrixFormat ? window.MotrixFormat.num(x) : String(x) } catch (_e) { return String(x) } }

  // ───────── 後端呼叫 ─────────
  function token() { try { return (JSON.parse(localStorage.getItem('motrix_session') || '{}')).token || '' } catch (_e) { return '' } }
  function api(method, path, body, headers) {
    var opts = { method: method, headers: { Authorization: 'Bearer ' + token() } }
    if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body) }
    Object.keys(headers || {}).forEach(function (k) { opts.headers[k] = headers[k] })
    return fetch(path, opts).then(function (res) {
      return res.text().then(function (t) {
        var d = null
        try { d = t ? JSON.parse(t) : null } catch (_e) { d = null }
        return { ok: res.ok, status: res.status, data: d }
      })
    }, function () { return { ok: false, status: 0, data: null } })
  }
  function detailOf(r) { var d = r && r.data && r.data.detail; return d && typeof d === 'object' && !Array.isArray(d) ? d : {} }
  function errMsg(r, fallback) {
    var d = r && r.data && r.data.detail
    if (d && typeof d === 'object' && !Array.isArray(d) && typeof d.message === 'string') return d.message
    if (typeof d === 'string' && d) return d
    if (r && r.status === 0) return '連線失敗，請檢查網路後再試。'
    if (r && r.status === 429) return '操作太頻繁，請稍等幾秒後再試。'
    return fallback || '操作失敗，請稍後再試。'
  }

  // ───────── 目錄（來源／欄位）存取 ─────────
  function curSrc() { return SRC[S.source] || { id: S.source, label: S.source, fields: [], defaults: {}, defaultFilters: [], unavailable: true } }
  function FIELDS() { return curSrc().fields }
  function FBY(id) { return FIELDS().filter(function (f) { return f.id === id })[0] }
  function ok(f) { return !!(f && f.visible) }
  function srcLabel(id) { return SRC[id] ? SRC[id].label : '（無權限的資料來源）' }
  function orderOf(id) { var i = FIELDS().map(function (f) { return f.id }).indexOf(id); return i < 0 ? 9999 : i }
  function byCatalog(a, b) { return orderOf(a) - orderOf(b) }
  function defaultFn(f) { var l = f.aggregate || []; return f.type === 'percent' && has(l, 'avg') ? 'avg' : has(l, 'sum') ? 'sum' : l[0] }

  // ───────── 草稿狀態 ─────────
  function blank(src) {
    var s = SRC[src] || { defaults: {}, defaultFilters: [] }
    var d = s.defaults || {}
    return { source: src, columns: (d.columns || []).slice(), filters: clone(s.defaultFilters || []), groupBy: [], aggregates: [], sort: d.sort ? [{ field: d.sort.field, dir: d.sort.dir }] : [], layout: 'detail', version: 1 }
  }
  function setState(def) {
    S.source = def.source
    S.cols = (def.columns || []).slice()
    S.filters = clone(def.filters != null ? def.filters : (SRC[def.source] ? SRC[def.source].defaultFilters || [] : []))
    S.groups = (def.groupBy || []).map(function (x) { return { field: x.field, bucket: x.bucket || null } })
    S.aggs = (def.aggregates || []).filter(function (x) { return x.field !== '*' }).map(function (x) { return { field: x.field, fn: x.fn } })
    S.count = (def.aggregates || []).some(function (x) { return x.field === '*' })
    S.sort = def.sort && def.sort[0] ? { field: def.sort[0].field, dir: def.sort[0].dir } : null
    S.layout = def.layout === 'summary' ? 'summary' : 'detail'
  }
  function pack() { return JSON.stringify({ source: S.source, cols: S.cols, filters: S.filters, groups: S.groups, aggs: S.aggs, count: S.count, sort: S.sort, layout: S.layout }) }
  function unpack(js) { var o = JSON.parse(js); S.source = o.source; S.cols = o.cols; S.filters = o.filters; S.groups = o.groups; S.aggs = o.aggs; S.count = o.count; S.sort = o.sort; S.layout = o.layout }
  function filterDone(x) {
    var f = FBY(x.field), op = x.op, v = x.value
    if (op === 'is_me' || op === 'empty' || op === 'not_empty') return true
    if (op === 'relative') return PERIODS.some(function (p) { return p[0] === v })
    if (op === 'between') return Array.isArray(v) && v.length === 2 && v[0] !== '' && v[1] !== '' && v[0] != null && v[1] != null
    if (op === 'in') return Array.isArray(v) && v.length > 0
    if (f && (f.type === 'money' || f.type === 'percent' || f.type === 'number')) return v !== '' && v != null && isFinite(Number(v))
    return typeof v === 'string' && v !== ''
  }
  function wireValue(f, x) {                                 // 數字欄位的值在畫面上是字串，送出前轉成數字
    var v = x.value
    if (f && (f.type === 'money' || f.type === 'percent' || f.type === 'number')) v = Array.isArray(v) ? v.map(Number) : Number(v)
    return { field: x.field, op: x.op, value: v }
  }
  function curDef(onlyDone) {
    var fl = S.filters.filter(function (x) { return !onlyDone || filterDone(x) }).map(function (x) {
      var f = FBY(x.field)
      if (x.op === 'is_me' || x.op === 'empty' || x.op === 'not_empty') return { field: x.field, op: x.op }
      return wireValue(f, x)
    })
    var aggs = S.aggs.slice().sort(function (a, b) { return byCatalog(a.field, b.field) }).map(function (a) { return { field: a.field, fn: a.fn } })
    if (S.layout === 'summary' && S.count) aggs.push({ field: '*', fn: 'count' })
    return {
      version: 1, source: S.source, layout: S.layout,
      columns: S.cols.slice().sort(byCatalog), filters: fl,
      groupBy: S.groups.map(function (g) { var f = FBY(g.field); var o = { field: g.field }; if (f && f.type === 'date') o.bucket = g.bucket || (f.bucket && f.bucket[0]) || 'month'; return o }),
      aggregates: aggs,
      sort: S.layout === 'detail' && S.sort ? [{ field: S.sort.field, dir: S.sort.dir }] : []
    }
  }
  function snap() { return JSON.stringify(curDef(false)) }
  function dirtyCount() {
    var cur = snap()
    if (cur === S.base) return 0
    var b = JSON.parse(S.base), c = JSON.parse(cur), n = 0
    function sd(x, y) { var k = 0; x.forEach(function (v) { if (y.indexOf(v) < 0) k++ }); y.forEach(function (v) { if (x.indexOf(v) < 0) k++ }); return k }
    function ids(a) { return a.map(function (x) { return typeof x === 'string' ? x : x.field + ':' + (x.fn || x.bucket || '') }) }
    if (b.source !== c.source) return 1
    n += sd(b.columns, c.columns) + sd(ids(b.groupBy), ids(c.groupBy)) + sd(ids(b.aggregates), ids(c.aggregates))
    if (JSON.stringify(b.filters) !== JSON.stringify(c.filters)) n += Math.max(1, Math.abs(b.filters.length - c.filters.length))
    if (JSON.stringify(b.sort) !== JSON.stringify(c.sort)) n++
    if (b.layout !== c.layout) n++
    return n || 1
  }

  // ───────── 通用 UI ─────────
  function toast(msg) {
    var t = $('toast'); t.textContent = msg; t.classList.add('show')
    clearTimeout(toast._t); toast._t = setTimeout(function () { t.classList.remove('show') }, 3600)
  }
  function confirmDlg(title, body, yesLabel, yes) {
    $('cfTitle').textContent = title; $('cfBody').textContent = body; $('cfYes').textContent = yesLabel
    var d = $('dlgConfirm')
    $('cfYes').onclick = function () { d.close(); yes() }
    $('cfNo').onclick = function () { d.close() }
    d.showModal()
  }
  // 焦點保留：重畫前記下目前焦點元素的 data-fk，重畫後找回同一個元素；元素已消失（例如「移除」按鈕）就交給預覽區，不落到頁首
  function keepFocus(fn) {
    var a = document.activeElement, fk = a && a.getAttribute ? a.getAttribute('data-fk') : null
    fn()
    if (fk) {
      var el = null
      try { el = document.querySelector('[data-fk="' + fk.replace(/"/g, '\\"') + '"]') } catch (_e) { el = null }
      if (el && !el.disabled) el.focus(); else $('previewPanel').focus()
    }
  }
  function guard(go) {
    if (dirtyCount() > 0) confirmDlg('放棄未儲存的修改', '目前的報表有未儲存的修改，繼續將放棄這些修改。', '放棄修改', go); else go()
  }

  // ───────── 載入／套用 ─────────
  function apply(def, loaded) {
    setState(def); S.loaded = loaded || null; S.picked = {}; S.base = snap(); UNDO = null; $('batchMsg').textContent = ''
    try { history.replaceState(null, '', loaded ? '#' + loaded.id : location.pathname + location.search) } catch (_e) { /* 網址不能改只是重新整理後不記得 */ }
    render(); schedulePreview(true)
  }
  function firstSource() { return ORDER[0] || '' }
  function newReport(src) { apply(blank(src || S.source || firstSource()), null) }
  function openReport(id) {
    api('GET', API + '/' + encodeURIComponent(id)).then(function (r) {
      if (!r.ok) { toast(errMsg(r, '找不到這份報表。')); if (r.status === 404) refreshList(); return }
      var d = r.data
      if (!SRC[d.sourceId]) {                                // 沒有這個來源的模組權限：只能看到名稱，不能執行
        SRC[d.sourceId] = { id: d.sourceId, label: '（無權限的資料來源）', fields: [], defaults: {}, defaultFilters: [], unavailable: true }
      }
      var def = d.definition || {}
      def.source = def.source || d.sourceId
      apply(def, { id: d.id, name: d.name, etag: d.etag, isOwner: !!d.isOwner, partiallyHidden: !!d.partiallyHidden, ownerName: d.ownerName || '', lastExportedAt: d.lastExportedAt || '' })
    })
  }
  function refreshList() {
    return api('GET', API).then(function (r) {
      if (r.ok && r.data) {
        LIST = { mine: r.data.mine || [], shared: r.data.shared || [], sharingEnabled: !!r.data.sharingEnabled, recycleDeleted: !!r.data.recycleDeleted, max: r.data.max || 30, nameMax: r.data.nameMax || 40 }
      }
      renderList()
    })
  }

  // ───────── 預覽 ─────────
  function usedList() {
    var u = []
    S.filters.forEach(function (f) { u.push([f.field, '篩選條件']) })
    S.groups.forEach(function (g) { u.push([g.field, '分組']) })
    if (S.layout === 'detail' && S.sort) u.push([S.sort.field, '排序'])
    return u
  }
  function localCheck() {
    var cs = curSrc()
    if (cs.unavailable) return { unavailable: '您的帳號沒有這個資料來源的使用權限。請改選其他資料來源。' }
    var bad = []
    usedList().forEach(function (u) {
      var f = FBY(u[0]), t = (f ? '「' + f.label + '」' : '已不存在的欄位') + '（' + u[1] + '）'
      if ((!f || !f.visible) && !has(bad, t)) bad.push(t)
    })
    if (bad.length) return { refuse: bad }
    if (S.layout === 'detail' && !S.cols.length) return { note: '尚未選擇要顯示的欄位。請在矩陣勾選「顯示」。' }
    if (S.layout === 'summary' && !S.groups.length && !S.aggs.length && !S.count) return { note: '尚未選擇分組或彙總，請在矩陣勾選「分組」或「彙總」。' }
    return null
  }
  function schedulePreview(now) {
    clearTimeout(pv.timer)
    pv.seq++
    var lc = localCheck()
    if (lc) { P = { state: 'local', info: lc }; renderPreview(); return }
    P = { state: 'loading', prev: P.state === 'ok' ? P.data : null, skipped: 0 }
    renderPreview()
    pv.timer = setTimeout(runPreview, now ? 0 : 500)
  }
  function runPreview() {
    var seq = ++pv.seq
    var all = S.filters.length, def = curDef(true), skipped = all - def.filters.length
    api('POST', API + '/preview', def).then(function (r) {
      if (seq !== pv.seq) return                              // 已有更新的請求：丟棄舊結果
      if (r.ok) P = { state: 'ok', data: r.data, skipped: skipped }
      else {
        var d = detailOf(r)
        P = { state: 'error', message: errMsg(r, '預覽失敗，請稍後再試。'), status: r.status, action: d.action || '', reason: d.reason || '' }
      }
      renderPreview(); renderBar()
    })
  }

  // ───────── 使用中的格子 ─────────
  function groupOf(id) { return S.groups.filter(function (g) { return g.field === id })[0] }
  function aggOf(id) { return S.aggs.filter(function (a) { return a.field === id })[0] }
  function used(f, kind) {
    if (kind === 'show') return has(S.cols, f.id)
    if (kind === 'f') return S.filters.some(function (x) { return x.field === f.id })
    if (kind === 'g') return !!groupOf(f.id)
    if (kind === 'agg') return !!aggOf(f.id)
    return !!(S.sort && S.sort.field === f.id)
  }
  function dropAgg(id) { S.aggs = S.aggs.filter(function (a) { return a.field !== id }) }
  function removeUse(f, kind) {
    if (kind === 'show') { toggle(S.cols, f.id, false); dropAgg(f.id); if (S.sort && S.sort.field === f.id) S.sort = null }
    else if (kind === 'f') S.filters = S.filters.filter(function (x) { return x.field !== f.id })
    else if (kind === 'g') S.groups = S.groups.filter(function (g) { return g.field !== f.id })
    else if (kind === 'agg') dropAgg(f.id)
    else S.sort = null
  }
  function removeBlockedUses() {                              // 篩選／分組／排序用到無權限或已不存在的欄位：整批移除
    function blocked(id) { var f = FBY(id); return !f || !f.visible }
    S.filters = S.filters.filter(function (x) { return !blocked(x.field) })
    S.groups = S.groups.filter(function (g) { return !blocked(g.field) })
    if (S.sort && blocked(S.sort.field)) S.sort = null
  }
  function cellCap(f, kind) {
    if (kind === 'show') return !!f.select
    if (kind === 'f') return !!f.filter
    if (kind === 'g') return !!f.group
    if (kind === 'agg') return !!(f.aggregate && f.aggregate.length)
    return !!f.sort
  }
  function naReason(f, kind) {
    var numeric = f.type === 'money' || f.type === 'percent' || f.type === 'number'
    if (kind === 'show') return '此欄位不能顯示。'
    if (kind === 'f') return '此欄位不支援篩選。'
    if (kind === 'g') return numeric ? '金額與數值不能當作分組依據。' : '此欄位不支援分組。'
    if (kind === 'agg') return f.type === 'text' ? '文字欄位無法彙總。' : '此欄位不支援彙總。'
    return '此欄位不支援排序。'
  }

  // ───────── 畫面 ─────────
  function renderList() {
    var box = $('repList'); clear(box)
    $('repSummary').textContent = '我的報表（' + LIST.mine.length + '）'
    $('repNote').textContent = '每人最多 ' + LIST.max + ' 份。' + (LIST.sharingEnabled ? '' : '報表僅供本人使用。')
    function row(rp, mine) {
      var on = S.loaded && S.loaded.id === rp.id
      var kids = [h('button', { class: 'open', type: 'button', 'data-fk': 'rep:' + rp.id, 'data-testid': 'cr-report-' + rp.id, 'aria-current': on ? 'true' : null,
        onclick: function () { guard(function () { openReport(rp.id) }) } },
      [h('span', { class: 'nm', text: rp.name }), h('span', { class: 'src', text: srcLabel(rp.sourceId) + (mine ? '' : '　' + (rp.ownerName || '') + ' 分享') })])]
      if (mine) kids.push(h('button', { class: 'del', type: 'button', 'aria-label': '刪除報表 ' + rp.name, text: '刪除', 'data-testid': 'cr-del-' + rp.id, onclick: function () { deleteReport(rp) } }))
      return h('div', { class: 'cr-rep' + (on ? ' on' : '') }, kids)
    }
    if (!LIST.mine.length) box.appendChild(h('p', { class: 'cr-empty', text: '目前沒有報表。請按「新增報表」，設定後儲存。' }))
    LIST.mine.forEach(function (rp) { box.appendChild(row(rp, true)) })
    var sb = $('sharedBox'); clear(sb)
    if (LIST.shared.length) {
      sb.appendChild(h('h2', { text: '分享給我的（只能檢視與複製）' }))
      LIST.shared.forEach(function (rp) { sb.appendChild(row(rp, false)) })
    }
  }
  function renderTabs() {
    var box = $('srcTabs'); clear(box)
    ORDER.forEach(function (k) {
      box.appendChild(h('button', { class: 'cr-tab', type: 'button', 'data-fk': 'src:' + k, 'data-testid': 'cr-source-' + k, 'aria-current': S.source === k ? 'true' : null,
        onclick: function () { if (k !== S.source) guard(function () { newReport(k) }) } }, [SRC[k].label]))
    })
    if (S.source && !has(ORDER, S.source)) box.appendChild(h('button', { class: 'cr-tab', type: 'button', 'aria-current': 'true', disabled: true }, [srcLabel(S.source)]))
    $('srcNote').textContent = ORDER.length ? '' : '您的帳號目前沒有可用的資料來源。'
  }

  function renderMatrix() {
    var t = $('matrix'); clear(t)
    var summary = S.layout === 'summary'
    t.appendChild(h('caption', { class: 'cr-sr', text: '欄位矩陣：每列一個欄位，每欄一種用途（顯示、篩選、分組、彙總、排序）。' }))
    var sel = FIELDS().filter(function (f) { return ok(f) && f.select })
    var nShown = sel.filter(function (f) { return has(S.cols, f.id) }).length
    var allBox = h('input', { type: 'checkbox', 'data-fk': 'showAll', 'aria-label': '全部顯示或隱藏（只作用在可使用的欄位）', checked: sel.length > 0 && nShown === sel.length, disabled: summary || !sel.length,
      onchange: function (e) { batchShow(e.target.checked) } })
    allBox.indeterminate = nShown > 0 && nShown < sel.length
    t.appendChild(h('thead', {}, [h('tr', {}, [
      h('th', { class: 'fname', scope: 'col', text: '欄位' }), h('th', { class: 'ty', scope: 'col', text: '型別' }),
      h('th', { class: 'c', scope: 'col' }, [h('label', { class: 'hit' }, [allBox, ' 顯示'])]),
      h('th', { class: 'c', scope: 'col', text: '篩選' }), h('th', { class: 'c', scope: 'col', text: '分組' }), h('th', { class: 'c', scope: 'col', text: '彙總' }), h('th', { class: 'c', scope: 'col', text: '排序' })])]))
    var body = h('tbody', {}); t.appendChild(body)
    var anyLock = false
    FIELDS().forEach(function (f) {
      var good = ok(f)
      if (!good) anyLock = true
      var tr = h('tr', { 'aria-describedby': good ? null : 'lg-lock' }, [])      // 圖例掛在列層：鎖定列只在「顯示」格有一個 Tab 停駐點
      tr.appendChild(h('td', { class: 'fname' }, [h('label', { class: 'hit' }, [h('input', { type: 'checkbox', 'data-fk': 'm:' + f.id + ':pick', 'aria-label': '選取 ' + f.label, checked: !!S.picked[f.id],
        onchange: function (e) { S.picked[f.id] = e.target.checked; renderSel() } }), ' ' + f.label])]))
      tr.appendChild(h('td', { class: 'ty', text: TYPE_NAME[f.type] || f.type }))
      function lockedCell(kind) {
        var td = h('td', { class: 'c lock', tabindex: kind === 'show' ? '0' : null, 'aria-label': kind === 'show' ? f.label + '：無權限' : null }, ['無權限'])
        if (used(f, kind)) td.appendChild(h('button', { class: 'cellbtn', type: 'button', 'data-fk': 'm:' + f.id + ':' + kind + ':rm', 'aria-label': '移除 ' + f.label + ' 的' + KIND_NAME[kind],
          text: '移除', onclick: function () { removeUse(f, kind); changed() } }))
        return td
      }
      function check(kind, onchange, extra) {
        var cb = h('input', { type: 'checkbox', 'data-fk': 'm:' + f.id + ':' + kind, 'aria-label': f.label + ' ' + KIND_NAME[kind], checked: used(f, kind), disabled: summary && kind === 'show',
          title: summary && kind === 'show' ? '「僅彙總」版型不使用此欄。' : null,
          onchange: function (e) { var cur = e.target; if (onchange(cur.checked) === false) cur.checked = false; changed() } })
        var td = h('td', { class: 'c' }, [h('label', { class: 'hit' }, [cb])])
        if (extra) extra(td)
        return td
      }
      ;['show', 'f', 'g', 'agg'].forEach(function (kind) {
        if (!good) { tr.appendChild(cellCap(f, kind) || !good ? lockedCell(kind) : null); return }
        if (!cellCap(f, kind)) { tr.appendChild(h('td', { class: 'c na', title: naReason(f, kind), text: '—' })); return }
        if (kind === 'show') tr.appendChild(check('show', function (on) { toggle(S.cols, f.id, on); if (!on) { dropAgg(f.id); if (S.sort && S.sort.field === f.id) S.sort = null } }))
        else if (kind === 'f') tr.appendChild(check('f', function (on) { return setFilter(f, on) }))
        else if (kind === 'g') {
          tr.appendChild(check('g', function (on) {
            if (on && S.groups.length >= LIM.groupBy) { toast('分組最多 ' + LIM.groupBy + ' 層。'); return false }
            if (on) S.groups.push({ field: f.id, bucket: f.type === 'date' ? ((f.bucket && f.bucket[0]) || 'month') : null }); else removeUse(f, 'g')
          }, function (td) {
            if (f.type === 'date' && f.bucket && f.bucket.length > 1 && groupOf(f.id)) {
              td.appendChild(h('select', { 'data-fk': 'm:' + f.id + ':bucket', 'aria-label': f.label + ' 分組單位', onchange: function (e) { groupOf(f.id).bucket = e.target.value; changed() } },
                f.bucket.map(function (b) { return h('option', { value: b, selected: groupOf(f.id).bucket === b, text: BUCKET_NAME[b] || b }) })))
            }
          }))
        } else {
          tr.appendChild(check('agg', function (on) {
            if (on && S.aggs.length >= LIM.aggregates) { toast('彙總最多 ' + LIM.aggregates + ' 項。'); return false }
            if (on) { S.aggs.push({ field: f.id, fn: defaultFn(f) }); if (S.layout === 'detail') toggle(S.cols, f.id, true) } else dropAgg(f.id)
          }, function (td) {
            var a = aggOf(f.id)
            if (a && f.aggregate.length > 1) {
              td.appendChild(h('select', { 'data-fk': 'm:' + f.id + ':fn', 'aria-label': f.label + ' 彙總方式', onchange: function (e) { aggOf(f.id).fn = e.target.value; changed() } },
                f.aggregate.map(function (fn) { return h('option', { value: fn, selected: a.fn === fn, text: AGG_NAME[fn] || fn }) })))
            }
          }))
        }
      })
      if (!good) tr.appendChild(lockedCell('sort'))
      else if (!cellCap(f, 'sort')) tr.appendChild(h('td', { class: 'c na', title: naReason(f, 'sort'), text: '—' }))
      else {
        var cur = S.sort && S.sort.field === f.id ? S.sort.dir : ''
        tr.appendChild(h('td', { class: 'c' }, [h('button', { class: 'cellbtn' + (cur ? ' on' : ''), type: 'button', 'data-fk': 'm:' + f.id + ':sort',
          'aria-label': f.label + ' 排序：' + (cur === 'asc' ? '由小到大' : cur === 'desc' ? '由大到小' : '無'),
          text: cur === 'asc' ? '↑' : cur === 'desc' ? '↓' : '·', disabled: summary, title: summary ? '「僅彙總」版型依分組欄位排序。' : null,
          onclick: function () {
            S.sort = !cur ? { field: f.id, dir: 'asc' } : cur === 'asc' ? { field: f.id, dir: 'desc' } : null
            if (S.sort && f.select) toggle(S.cols, f.id, true)       // 排序欄必須是顯示欄之一
            changed()
          } })]))
      }
      body.appendChild(tr)
    })
    var lg = $('legend'); clear(lg)
    if (anyLock) lg.appendChild(h('li', { id: 'lg-lock', text: LOCK_TEXT }))
    lg.appendChild(h('li', { text: '「—」：該欄位的型別不支援此用途（例如金額不能分組、文字欄位不能彙總）。' }))
    $('lyDetail').setAttribute('aria-pressed', String(!summary)); $('lySummary').setAttribute('aria-pressed', String(summary))
    $('cntLbl').hidden = !summary; $('cntBox').checked = S.count; $('sumNote').hidden = !summary
    renderPresets(); renderSel()
  }
  function renderSel() {
    var n = Object.keys(S.picked).filter(function (k) { return S.picked[k] }).length
    $('selCount').textContent = '已選 ' + n + ' 列'
  }

  function setFilter(f, on) {
    if (!on) { removeUse(f, 'f'); return }
    if (S.filters.length >= LIM.filters) { toast('篩選最多 ' + LIM.filters + ' 項。'); return false }
    S.filters.push(initialFilter(f))
  }
  function initialFilter(f) {
    var d = { field: f.id }
    if (f.isMe) { d.op = 'is_me' }
    else if (f.type === 'date') { d.op = 'relative'; d.value = 'this_year' }
    else if (f.type === 'enum') { d.op = 'in'; d.value = (f.options && f.options[0]) ? [f.options[0][0]] : [] }
    else if (f.type === 'text') { d.op = 'contains'; d.value = '' }
    else { d.op = 'gte'; d.value = '' }
    return d
  }
  function opsFor(f) {
    var l = (f.ops || []).slice()
    if (f.isMe) l.unshift('is_me')
    return l.concat(['empty', 'not_empty'])
  }
  function opLabel(f, op) { return f.type === 'date' && DATE_OPNAME[op] ? DATE_OPNAME[op] : OPNAME[op] || op }
  function valueFor(f, op) {                                  // 換運算子時給一個型別正確的初值
    if (op === 'relative') return 'this_year'
    if (op === 'between') return ['', '']
    if (op === 'in') return f.type === 'enum' ? ((f.options && f.options[0]) ? [f.options[0][0]] : []) : []
    if (f.type === 'enum' && (op === 'eq' || op === 'neq')) return f.options && f.options[0] ? f.options[0][0] : ''
    return ''
  }
  function renderFilters() {
    var box = $('filters'); clear(box)
    if (!S.filters.length) { box.appendChild(h('p', { class: 'cr-empty', text: '目前沒有篩選條件。報表將包含您有權限查看的全部資料。' })); return }
    S.filters.forEach(function (flt, i) {
      var f = FBY(flt.field)
      var row = h('div', { class: 'cr-fl', 'data-testid': 'cr-filter-' + flt.field }, [])
      row.appendChild(h('span', { class: 'nm', text: f ? f.label : '已不存在的欄位' }))
      if (!f || !f.visible) {
        row.appendChild(h('span', { class: 'cr-chip', text: f ? '無權限' : '已不存在' }))
        row.appendChild(h('span', { class: 'cr-note flat', text: '此條件使用了您無法使用的欄位。' }))
      } else {
        row.appendChild(h('select', { 'data-fk': 'f:' + flt.field + ':op', 'aria-label': f.label + ' 條件', onchange: function (e) {
          flt.op = e.target.value; flt.value = valueFor(f, flt.op); changed()
        } }, opsFor(f).map(function (o) { return h('option', { value: o, selected: flt.op === o, text: opLabel(f, o) }) })))
        row.appendChild(h('span', { class: 'val' }, valueInputs(f, flt)))
      }
      row.appendChild(h('button', { class: 'btn cr-btn-sm', type: 'button', 'data-fk': 'f:' + flt.field + ':rm', 'aria-label': '移除 ' + (f ? f.label : '') + ' 條件', text: '移除', onclick: function () { S.filters.splice(i, 1); changed() } }))
      box.appendChild(row)
    })
  }
  function valueInputs(f, flt) {
    var out = [], op = flt.op
    function onv(k) { return function (e) { if (k === null) flt.value = e.target.value; else { if (!Array.isArray(flt.value)) flt.value = ['', '']; flt.value[k] = e.target.value } touched() } }
    if (op === 'is_me') return [h('span', { class: 'cr-note flat', text: '執行者本人（換人執行時自動改為該人）' })]
    if (op === 'empty' || op === 'not_empty') return []
    if (op === 'relative') return [h('select', { 'aria-label': f.label + ' 期間', onchange: function (e) { flt.value = e.target.value; touched() } },
      PERIODS.map(function (p) { return h('option', { value: p[0], selected: flt.value === p[0], text: p[1] }) }))]
    if (f.type === 'enum' && op === 'in') {
      var cur0 = Array.isArray(flt.value) ? flt.value : []
      var opts = (f.options || []).slice()
      cur0.forEach(function (v) { if (!opts.some(function (o) { return o[0] === v })) opts.push([v, v]) })   // 條件裡的值不在目前選項（例如預設條件）也要看得到、取消得掉
      return opts.map(function (o) {
        var cur = Array.isArray(flt.value) ? flt.value : []
        return h('label', { class: 'hit' }, [h('input', { type: 'checkbox', 'aria-label': f.label + ' ' + o[1], checked: has(cur, o[0]), onchange: function (e) {
          var v = Array.isArray(flt.value) ? flt.value.slice() : []; toggle(v, o[0], e.target.checked); flt.value = v; touched() } }), ' ' + o[1]])
      })
    }
    if (f.type === 'enum') return [h('select', { 'aria-label': f.label + ' 值', onchange: onv(null) }, (f.options || []).map(function (o) { return h('option', { value: o[0], selected: flt.value === o[0], text: o[1] }) }))]
    if (f.type === 'text' && op === 'in') return [h('input', { type: 'text', 'aria-label': f.label + ' 值（以逗號分隔）', placeholder: '以逗號分隔', value: Array.isArray(flt.value) ? flt.value.join(',') : '',
      oninput: function (e) { flt.value = e.target.value.split(/[,，、]/).map(function (s) { return s.trim() }).filter(Boolean); touched() } })]
    var kind = f.type === 'date' ? 'date' : f.type === 'text' ? 'text' : 'number'
    if (op === 'between') {
      var v = Array.isArray(flt.value) ? flt.value : ['', '']
      return [h('input', { type: kind, 'aria-label': f.label + ' 起', value: v[0], oninput: onv(0), onchange: onv(0) }), '至', h('input', { type: kind, 'aria-label': f.label + ' 迄', value: v[1], oninput: onv(1), onchange: onv(1) })]
    }
    out.push(h('input', { type: kind, 'aria-label': f.label + ' 值', value: typeof flt.value === 'string' || typeof flt.value === 'number' ? flt.value : '', oninput: onv(null), onchange: onv(null) }))
    return out
  }
  function touched() { renderBar(); schedulePreview(false) }       // 條件值打字中：不重畫條件列（避免掉焦點），只更新儲存列與預覽

  function fmtCell(c, v) {
    if (v == null || v === '') return ''
    if (typeof v === 'number') return c.type === 'percent' ? num(v) + '%' : num(v)
    return String(v)
  }
  function renderPreview() {
    var box = $('preview'); clear(box)
    var jump = $('jump'), fc = $('fcount')
    fc.textContent = ''
    if (P.state === 'idle') return
    if (P.state === 'local') {
      var lc = P.info
      jump.textContent = '前往預覽'
      if (lc.unavailable) box.appendChild(h('div', { class: 'cr-banner deny', role: 'alert' }, [lc.unavailable]))
      else if (lc.refuse) box.appendChild(h('div', { class: 'cr-banner deny', role: 'alert', 'data-testid': 'cr-refuse' }, [
        '此報表使用了您無法使用的欄位：' + lc.refuse.join('、') + '。無法執行。請移除這些條件（可按矩陣中標示「無權限」格子旁的「移除」），或改由有權限的同仁執行。',
        h('button', { class: 'btn cr-btn-sm', type: 'button', 'data-fk': 'rm-blocked', 'data-testid': 'cr-rm-blocked', text: '移除無權限的條件', onclick: function () { removeBlockedUses(); changed() } })]))
      else box.appendChild(h('div', { class: 'cr-banner', text: lc.note }))
      return
    }
    if (P.state === 'error') {
      jump.textContent = '預覽：無法執行，前往查看'
      var kids = [P.message]
      if (P.action === 'remove_conditions') kids.push(h('button', { class: 'btn cr-btn-sm', type: 'button', 'data-fk': 'rm-blocked', text: '移除無法使用的條件', onclick: function () { removeBlockedUses(); changed() } }))
      box.appendChild(h('div', { class: 'cr-banner deny', role: 'alert', 'data-testid': 'cr-error' }, kids))
      return
    }
    var d = P.state === 'loading' ? P.prev : P.data
    if (P.state === 'loading') box.appendChild(h('p', { class: 'cr-note flat', 'data-testid': 'cr-loading', text: '更新預覽中…' }))
    if (!d) { jump.textContent = '前往預覽'; return }
    var summary = S.layout === 'summary'
    fc.textContent = (summary ? '彙總後共 ' : '符合 ') + num(d.totalRows) + (summary ? ' 列。' : ' 筆。')
    jump.textContent = '前往預覽（共 ' + num(d.totalRows) + ' 筆）'
    box.appendChild(h('p', { class: 'cr-sumline', 'data-testid': 'cr-summary', text: '共 ' + num(d.totalRows) + (summary ? ' 列' : ' 筆') + '；顯示 ' + d.columns.length + ' 欄' + (d.hiddenCount ? '；已隱藏 ' + d.hiddenCount + ' 欄（依您的權限）' : '') }))
    if (d.hiddenCount) {
      var w = h('p', { class: 'cr-sumline' }, [])
      d.hiddenFields.forEach(function (x) { w.appendChild(h('span', { class: 'cr-chip', text: x })) })
      box.appendChild(w)
    }
    if (S.loaded && S.loaded.partiallyHidden) box.appendChild(h('div', { class: 'cr-banner info', 'data-testid': 'cr-partially-hidden', text: '這份報表有部分條件或欄位因您的權限不顯示，下列結果只依您可使用的部分計算。' }))
    if (P.skipped) box.appendChild(h('div', { class: 'cr-banner', text: '有 ' + P.skipped + ' 項條件尚未填值，預覽暫不套用。' }))
    ;(d.notes || []).forEach(function (n) { box.appendChild(h('div', { class: 'cr-banner', text: n })) })
    var tb = h('table', { 'data-testid': 'cr-preview' }, [h('caption', { class: 'cr-sr', text: '報表預覽（前 ' + LIM.previewRows + ' 列）' })])
    var isNum = d.columns.map(function (c) { return c.type === 'money' || c.type === 'percent' || c.type === 'number' })
    tb.appendChild(h('thead', {}, [h('tr', {}, d.columns.map(function (c, i) { return h('th', { class: isNum[i] ? 'n' : '', scope: 'col', text: c.label }) }))]))
    var body = h('tbody', {}, [])
    d.rows.forEach(function (r) {
      body.appendChild(h('tr', { class: r.k === 'row' ? '' : r.k }, r.v.map(function (v, i) { return h('td', { class: isNum[i] ? 'n' : '', text: fmtCell(d.columns[i], v) }) })))
    })
    if (!d.rows.length) body.appendChild(h('tr', {}, [h('td', { colspan: Math.max(1, d.columns.length), text: '沒有符合條件的資料。請調整篩選條件。' })]))
    tb.appendChild(body); box.appendChild(h('div', { class: 'cr-scroll' }, [tb]))
    if (d.truncated) box.appendChild(h('p', { class: 'cr-note', text: '預覽僅顯示前 ' + LIM.previewRows + ' 列；匯出會包含全部（上限 ' + num(EXPORT_MAX) + ' 列）。' }))
  }

  function renderBar() {
    var n = dirtyCount()
    if (UNDO && UNDO.after && UNDO.after !== snap()) UNDO = null    // 批次之後又做了別的編輯：復原會連那些編輯一起還原，所以作廢
    var L = S.loaded
    var mine = !L || L.isOwner
    $('sbTitle').textContent = L ? L.name + (mine ? '' : '（' + (L.ownerName || '同事') + ' 分享，唯讀）') : '新報表（尚未儲存）'
    $('savebar').className = 'cr-savebar' + (n ? ' dirty' : '')
    var canX = !!L && !n && CAN_EXPORT
    $('sbState').textContent = n ? '您有 ' + n + ' 項未儲存的修改；儲存後才能匯出。' : (L ? '已儲存。' : '設定完成後請按「儲存」；儲存後才能匯出。')
    $('btnDiscard').hidden = !n
    $('btnSave').hidden = !mine
    $('btnSave').disabled = !n && !!L
    $('btnSaveAs').hidden = !L
    $('btnExport').hidden = !CAN_EXPORT
    $('btnExport').disabled = !canX
    $('btnUndo').hidden = !UNDO
    window.motrixIsDirty = n > 0                                   // 離開頁面的守門（sidebar.js）
  }
  function renderAll() { renderList(); renderTabs(); renderMatrix(); renderFilters(); renderPreview(); renderBar() }
  function render() { keepFocus(renderAll) }
  function changed() { render(); schedulePreview(false) }

  // ───────── 批次與常用組合（兩者規則一致：略過無權限欄、回報略過、可復原）─────────
  function say(msg) { $('batchMsg').textContent = msg }
  function skipTxt(skip) { return skip.length ? '，略過 ' + skip.length + ' 項：' + skip.join('、') : '' }
  function pushUndo() { UNDO = { before: pack(), after: null } }
  function commitUndo() { if (UNDO) UNDO.after = snap() }
  function batchShow(on) {
    pushUndo(); var done = 0, skip = []
    FIELDS().forEach(function (f) {
      if (!f.select) return
      if (!ok(f)) { skip.push(f.label + '（無權限）'); return }
      toggle(S.cols, f.id, on); if (!on) dropAgg(f.id); done++
    })
    if (!on) S.sort = null
    commitUndo(); say('已套用到草稿 ' + done + ' 項' + skipTxt(skip) + '。尚未儲存。'); changed()
  }
  function runBatch(kind) {
    var done = 0, skip = []
    pushUndo()
    FIELDS().forEach(function (f) {
      if (!S.picked[f.id]) return
      if (!ok(f)) { skip.push(f.label + '（無權限）'); return }
      if (kind === 'show') { if (!f.select) skip.push(f.label + '（不能顯示）'); else { toggle(S.cols, f.id, true); done++ } }
      else if (kind === 'hide') { toggle(S.cols, f.id, false); dropAgg(f.id); if (S.sort && S.sort.field === f.id) S.sort = null; done++ }
      else if (!f.group) skip.push(f.label + '（不支援分組）')
      else if (S.groups.length >= LIM.groupBy && !groupOf(f.id)) skip.push(f.label + '（分組最多 ' + LIM.groupBy + ' 層）')
      else if (!groupOf(f.id)) { S.groups.push({ field: f.id, bucket: f.type === 'date' ? ((f.bucket && f.bucket[0]) || 'month') : null }); done++ }
      else done++
    })
    commitUndo(); say('已套用到草稿 ' + done + ' 項' + skipTxt(skip) + '。尚未儲存。'); changed()
  }

  // 常用組合不寫死欄位：由目前來源的預設欄位、第一個可分組的日期欄與選項欄、第一個可加總的欄位組出來
  function presets() {
    var fs = FIELDS().filter(ok), out = []
    var d = (curSrc().defaults || {})
    out.push({ key: 'list', label: '基本清單', want: { cols: (d.columns || []).filter(function (id) { var f = FBY(id); return f && ok(f) }), groups: [], aggs: [], count: false, layout: 'detail' } })
    var amt = fs.filter(function (f) { return f.aggregate && has(f.aggregate, 'sum') })[0]
    function summaryOf(g) {
      return { cols: [g.id].concat(amt ? [amt.id] : []), groups: [{ field: g.id, bucket: g.type === 'date' ? ((g.bucket && has(g.bucket, 'month')) ? 'month' : g.bucket[0]) : null }],
        aggs: amt ? [{ field: amt.id, fn: 'sum' }] : [], count: true, layout: 'summary' }
    }
    var dt = fs.filter(function (f) { return f.type === 'date' && f.group && f.bucket && f.bucket.length })[0]
    var en = fs.filter(function (f) { return f.type === 'enum' && f.group })[0]
    var tx = fs.filter(function (f) { return f.type === 'text' && f.group })[0]
    if (tx) out.push({ key: 'g1', label: '依' + tx.label + '彙總', want: summaryOf(tx) })
    if (en) out.push({ key: 'g2', label: '依' + en.label + '彙總', want: summaryOf(en) })
    if (dt) out.push({ key: 'g3', label: '依' + dt.label + '（月）彙總', want: summaryOf(dt) })
    return out.slice(0, 4)
  }
  function renderPresets() {
    var box = $('presets'); clear(box)
    presets().forEach(function (p) {
      box.appendChild(h('button', { class: 'btn cr-btn-sm', type: 'button', 'data-fk': 'preset:' + p.key, 'data-testid': 'cr-preset-' + p.key, text: '套用' + p.label, onclick: function () {
        confirmDlg('套用常用組合', '套用後將取代目前的欄位、分組與彙總設定，篩選條件不變。套用後可按「復原上一次批次」還原。', '套用', function () {
          pushUndo()
          S.cols = p.want.cols.slice(); S.groups = clone(p.want.groups); S.aggs = clone(p.want.aggs); S.count = p.want.count; S.layout = p.want.layout
          if (S.sort && !has(S.cols, S.sort.field)) S.sort = null
          if (p.key === 'list') { var s = (curSrc().defaults || {}).sort; S.sort = s && FBY(s.field) && ok(FBY(s.field)) ? { field: s.field, dir: s.dir } : null }
          commitUndo(); say('已套用到草稿：' + p.label + '。尚未儲存。'); changed()
        })
      } }))
    })
  }

  // ───────── 儲存、另存、刪除 ─────────
  function incompleteFilters() { return S.filters.filter(function (x) { return !filterDone(x) }).length }
  function nameDialog(asNew) {
    var d = $('dlgName'), L = S.loaded
    $('dlgNameTitle').textContent = asNew ? '另存新檔' : '儲存報表'
    $('inName').value = asNew && L ? (L.name + '（複本）').slice(0, LIST.nameMax) : ''
    $('inName').maxLength = LIST.nameMax; $('nameErr').textContent = ''
    $('nameOk').disabled = false
    $('nameOk').onclick = function () {
      var nm = $('inName').value.trim()
      if (!nm) { $('nameErr').textContent = '請填寫報表名稱。'; return }
      if (LIST.mine.some(function (x) { return x.name === nm })) { $('nameErr').textContent = '已有同名的報表，請改用其他名稱。'; return }
      if (LIST.mine.length >= LIST.max) { $('nameErr').textContent = '我的報表最多 ' + LIST.max + ' 份，請先刪除不需要的報表。'; return }
      $('nameOk').disabled = true
      api('POST', API, { name: nm, definition: curDef(false) }).then(function (r) {
        $('nameOk').disabled = false
        if (!r.ok) { $('nameErr').textContent = errMsg(r, '儲存失敗，請稍後再試。'); return }
        d.close(); toast('已儲存。')
        var def = r.data.definition || curDef(false)
        refreshList().then(function () { apply(def, { id: r.data.id, name: r.data.name, etag: r.data.etag, isOwner: true, partiallyHidden: false, ownerName: '', lastExportedAt: '' }) })
      })
    }
    $('nameCancel').onclick = function () { d.close() }
    d.showModal(); $('inName').focus()
  }
  function saveClick() {
    var L = S.loaded
    var inc = incompleteFilters()
    if (inc) { toast('有 ' + inc + ' 項條件尚未填值，請填寫或移除後再儲存。'); return }
    if (!L) { nameDialog(false); return }
    if (!L.isOwner) return
    $('btnSave').disabled = true
    api('PUT', API + '/' + L.id, { definition: curDef(false) }, { 'If-Match': L.etag || '' }).then(function (r) {
      if (!r.ok) {
        $('btnSave').disabled = false
        toast(errMsg(r, '儲存失敗，請稍後再試。'))
        return
      }
      var etag = r.data && r.data.etag
      var done = function (tag) { L.etag = tag || L.etag; S.base = snap(); UNDO = null; toast('已儲存。'); refreshList(); render() }
      if (etag) done(etag)
      else api('GET', API + '/' + L.id).then(function (g) { done(g.ok && g.data ? g.data.etag : '') })
    })
  }
  function saveAsClick() {
    var L = S.loaded
    if (!L) return
    if (incompleteFilters()) { toast('有條件尚未填值，請填寫或移除後再另存。'); return }
    if (!L.isOwner && dirtyCount() === 0) {                          // 分享來的報表原封不動複製：由後端複製（有些條件因權限看不到時，後端會拒絕而不是悄悄改掉意義）
      api('POST', API + '/' + L.id + '/copy').then(function (r) {
        if (!r.ok) { toast(errMsg(r, '複製失敗，請稍後再試。')); return }
        toast('已複製到「我的報表」。')
        refreshList().then(function () { openReport(r.data.id) })
      })
      return
    }
    nameDialog(true)
  }
  function deleteReport(rp) {
    confirmDlg('刪除報表', LIST.recycleDeleted ? '報表會移到刪除暫存區，需要時可由管理員還原。是否繼續？' : '刪除後無法復原，是否繼續？', '刪除', function () {
      api('DELETE', API + '/' + rp.id).then(function (r) {
        if (!r.ok && r.status !== 404) { toast(errMsg(r, '刪除失敗，請稍後再試。')); return }
        toast('已刪除。')
        var wasOpen = S.loaded && S.loaded.id === rp.id
        refreshList().then(function () { if (wasOpen) newReport(S.source) })
      })
    })
  }

  // ───────── 匯出 ─────────
  function describeCond(x) {
    var f = FBY(x.field); if (!f) return ''
    var opts = {}; (f.options || []).forEach(function (o) { opts[o[0]] = o[1] })
    function show(v) { return Array.isArray(v) ? v.map(function (z) { return opts[z] || z }).join('、') : (opts[v] != null ? opts[v] : String(v)) }
    if (x.op === 'is_me') return f.label + '：產製者本人'
    if (x.op === 'empty') return f.label + ' 未填'
    if (x.op === 'not_empty') return f.label + ' 有填'
    if (x.op === 'relative') { var p = PERIODS.filter(function (q) { return q[0] === x.value })[0]; return f.label + '：' + (p ? p[1] : x.value) }
    if (x.op === 'between') return f.label + ' 介於 ' + (x.value || []).join(' ～ ')
    return f.label + ' ' + opLabel(f, x.op) + ' ' + show(x.value)
  }
  function openExport() {
    var L = S.loaded
    if (!L || dirtyCount() > 0 || P.state !== 'ok') { toast(P.state === 'ok' ? '請先儲存報表再匯出。' : '預覽尚未完成，請稍候再試。'); return }
    var d = P.data, f1 = $('xl1'), f2 = $('xl2'); clear(f1); clear(f2)
    var conds = S.filters.filter(filterDone).map(describeCond).filter(Boolean)
    ;[L.name + '　—　MOTRIX PLATFORM', '條件：' + (conds.length ? conds.join('；') : '無'), '欄位：' + d.columns.map(function (c) { return c.label }).join('、'), '小計與總計以實際數值寫入，不使用 Excel 公式。']
      .forEach(function (t) { f1.appendChild(h('div', { text: t })) })
    ;['資料來源：' + srcLabel(S.source), '列數：' + num(d.totalRows) + '（上限 ' + num(EXPORT_MAX) + '）', '已隱藏欄位：' + (d.hiddenCount || 0) + ' 欄（依產製者的權限）', '產製者與產製時間由系統於匯出時寫入。']
      .forEach(function (t) { f2.appendChild(h('div', { text: t })) })
    var over = d.totalRows > EXPORT_MAX
    $('xlErr').textContent = over ? '資料超過 ' + num(EXPORT_MAX) + ' 列，無法匯出。請縮小篩選範圍。' : ''
    $('xlGo').disabled = over; $('xlPdf').disabled = over
    $('dlgExport').showModal()
  }
  function doExport(suffix, fallback, btn) {
    var L = S.loaded; if (!L) return
    $('xlErr').textContent = ''; $('xlGo').disabled = true; $('xlPdf').disabled = true
    var label = btn.textContent; btn.textContent = '產生中…'
    fetch(API + '/' + L.id + suffix, { method: 'POST', headers: { Authorization: 'Bearer ' + token() } }).then(function (res) {
      if (res.ok) return window.MotrixDownload.save(res, fallback).then(function () { $('dlgExport').close(); toast('已下載。'); refreshList() })
      return res.text().then(function (t) {
        var r = { ok: false, status: res.status, data: null }
        try { r.data = JSON.parse(t) } catch (_e) { r.data = null }
        $('xlErr').textContent = errMsg(r, '匯出失敗，請稍後再試。')
      })
    }).catch(function () { $('xlErr').textContent = '匯出失敗，請稍後再試。' }).then(function () {
      btn.textContent = label; $('xlGo').disabled = false; $('xlPdf').disabled = false
    })
  }

  // ───────── 事件 ─────────
  function bind() {
    $('btnNew').addEventListener('click', function () { guard(function () { newReport(S.source && SRC[S.source] ? S.source : firstSource()) }) })
    Array.prototype.forEach.call(document.querySelectorAll('[data-layout]'), function (b) {
      b.addEventListener('click', function () { S.layout = b.getAttribute('data-layout'); changed() })
    })
    Array.prototype.forEach.call(document.querySelectorAll('[data-batch]'), function (b) {
      b.addEventListener('click', function () { runBatch(b.getAttribute('data-batch')) })
    })
    $('cntBox').addEventListener('change', function (e) { S.count = e.target.checked; changed() })
    $('btnUndo').addEventListener('click', function () {
      if (!UNDO) return
      unpack(UNDO.before); UNDO = null; say('已復原上一次批次。'); changed()
    })
    $('btnDiscard').addEventListener('click', function () {
      var L = S.loaded
      if (L) { openReport(L.id); toast('已放棄修改。') } else { newReport(S.source); toast('已放棄修改。') }
    })
    $('btnSave').addEventListener('click', saveClick)
    $('btnSaveAs').addEventListener('click', saveAsClick)
    $('btnExport').addEventListener('click', openExport)
    $('xlClose').addEventListener('click', function () { $('dlgExport').close() })
    $('xlGo').addEventListener('click', function () { doExport('/export', 'report.xlsx', $('xlGo')) })
    $('xlPdf').addEventListener('click', function () { doExport('/export-pdf', 'report.pdf', $('xlPdf')) })
    window.motrixDirtyProbe = function () { return dirtyCount() > 0 }
  }

  function fail(msg) {
    var e = $('crLoadError'); e.textContent = msg; e.hidden = false
  }
  function init() {
    bind()
    Promise.all([api('GET', API + '/sources'), api('GET', API)]).then(function (rs) {
      var s = rs[0], l = rs[1]
      if (!s.ok) {
        fail(s.status === 404 ? '自訂報表目前尚未開放。' : s.status === 403 ? '您的帳號沒有使用自訂報表的權限，請聯絡管理員。' : errMsg(s, '載入失敗，請重新整理。'))
        return
      }
      ;(s.data.sources || []).forEach(function (x) { SRC[x.id] = x; ORDER.push(x.id) })
      if (s.data.limits) Object.keys(s.data.limits).forEach(function (k) { LIM[k] = s.data.limits[k] })
      CAN_EXPORT = !!s.data.canExport
      if (l.ok && l.data) LIST = { mine: l.data.mine || [], shared: l.data.shared || [], sharingEnabled: !!l.data.sharingEnabled, recycleDeleted: !!l.data.recycleDeleted, max: l.data.max || 30, nameMax: l.data.nameMax || 40 }
      $('crLayout').hidden = false
      if (window.innerWidth <= 760) $('repDetails').removeAttribute('open')
      var want = /^#(\d+)$/.exec(location.hash || '')
      if (want) openReport(want[1])
      else if (firstSource()) newReport(firstSource())
      else { renderAll() }
    })
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init()
})()
