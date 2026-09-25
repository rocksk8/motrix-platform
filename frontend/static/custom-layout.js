/* custom-layout.js — 自訂模組的版面（CUSTOMIZATION-SPEC §8.1 ③）：表單分組與列表欄位。
 *
 * 建構器（module-builder.html）與執行頁（custom-records.html）共用同一份規則，
 * 所以「建構器看到的樣子」與「使用者看到的樣子」只有一個來源。
 *
 * 版面存在定義的 `ui` 鍵（引擎不讀它）：
 *   ui.form.groups  = [{title, fields:[欄位 key…]}]   表單的分組與欄位順序
 *   ui.list.columns = ['$recordNo', '$status', 'qty', …] 列表要顯示的欄位與順序（$ 開頭＝系統欄）
 *
 * 📌 P9 共用排版元件之後要從這裡抽出：本檔只有純函式（不碰 DOM、不綁 Alpine），
 *    抽離時搬檔即可，兩個呼叫端不用改寫。
 */
;(function () {
  //: 列表可用的系統欄（值來自單據本身，不是欄位）
  var SYSTEM_COLUMNS = [
    { key: '$recordNo', label: '編號' },
    { key: '$status', label: '狀態' },
    { key: '$createdBy', label: '建立者' },
    { key: '$createdAt', label: '建立時間' },
  ]

  function fieldsOf(def) {
    return (def && Array.isArray(def.fields)) ? def.fields.filter(function (f) { return f && f.key }) : []
  }

  function uiOf(def) {
    var ui = (def && def.ui && typeof def.ui === 'object') ? def.ui : {}
    return ui
  }

  /** 表單分組：[{title, fields:[欄位物件…]}]。沒有分到組的欄位依欄位順序放在最後一組「其他」
   *  （完全沒設分組 ⇒ 一組、沒有標題）。已刪除的欄位 key 自動略過。 */
  function formSections(def) {
    var fields = fieldsOf(def)
    var byKey = {}
    fields.forEach(function (f) { byKey[f.key] = f })
    var groups = ((uiOf(def).form || {}).groups) || []
    var used = {}
    var out = []
    groups.forEach(function (g) {
      var fs = (g.fields || []).filter(function (k) { return byKey[k] && !used[k] }).map(function (k) { used[k] = true; return byKey[k] })
      out.push({ title: g.title || '', fields: fs })
    })
    var rest = fields.filter(function (f) { return !used[f.key] })
    if (rest.length) out.push({ title: out.length ? '其他' : '', fields: rest })
    return out.filter(function (s) { return s.fields.length })
  }

  /** 列表欄：[{key, label, system}]。沒設定 ⇒ 編號、狀態、前三個欄位、建立時間。 */
  function listColumns(def) {
    var fields = fieldsOf(def)
    var labels = {}
    SYSTEM_COLUMNS.forEach(function (c) { labels[c.key] = c.label })
    fields.forEach(function (f) { labels[f.key] = f.label || f.key })
    var cols = ((uiOf(def).list || {}).columns)
    if (!Array.isArray(cols) || !cols.length) {
      cols = ['$recordNo', '$status'].concat(fields.slice(0, 3).map(function (f) { return f.key })).concat(['$createdAt'])
    }
    return cols.filter(function (k) { return labels[k] !== undefined }).map(function (k) {
      return { key: k, label: labels[k], system: k.charAt(0) === '$' }
    })
  }

  /** 列表儲存格的值：系統欄取單據本身，其餘取 data。 */
  function cellValue(rec, key, stateLabels) {
    if (!rec) return ''
    if (key === '$recordNo') return rec.record_no || ''
    if (key === '$status') return (stateLabels && stateLabels[rec.status]) || rec.status || ''
    if (key === '$createdBy') return rec.created_by || ''
    if (key === '$createdAt') return (rec.created_at || '').slice(0, 16).replace('T', ' ')
    var v = (rec.data || {})[key]
    if (v === null || v === undefined) return ''
    if (v === true) return '是'
    if (v === false) return '否'
    return String(v)
  }

  /** 陣列內移動一格（dir＝-1 上移、+1 下移）；超出邊界就不動。回傳新陣列。 */
  function move(arr, index, dir) {
    var a = arr.slice()
    var j = index + dir
    if (index < 0 || index >= a.length || j < 0 || j >= a.length) return a
    var t = a[index]; a[index] = a[j]; a[j] = t
    return a
  }

  // ── 編輯操作（建構器 ③ 用；P9 排版器共用）：一律回傳新的 ui 物件，不改傳入的 ──

  function cloneUi(def) {
    var ui = JSON.parse(JSON.stringify(uiOf(def)))
    ui.form = ui.form || {}
    ui.form.groups = Array.isArray(ui.form.groups) ? ui.form.groups : []
    ui.list = ui.list || {}
    ui.list.columns = Array.isArray(ui.list.columns) ? ui.list.columns : []
    return ui
  }

  /** 新增一個分組（標題可空）。 */
  function addGroup(def, title) {
    var ui = cloneUi(def)
    ui.form.groups.push({ title: title || '', fields: [] })
    return ui
  }

  /** 刪除分組：組內欄位回到「未分組」。 */
  function removeGroup(def, gi) {
    var ui = cloneUi(def)
    ui.form.groups.splice(gi, 1)
    return ui
  }

  function renameGroup(def, gi, title) {
    var ui = cloneUi(def)
    if (ui.form.groups[gi]) ui.form.groups[gi].title = title
    return ui
  }

  function moveGroup(def, gi, dir) {
    var ui = cloneUi(def)
    ui.form.groups = move(ui.form.groups, gi, dir)
    return ui
  }

  /** 把欄位放進分組 gi（先從其他組拿掉）；gi＝-1 ⇒ 回到未分組。 */
  function assignField(def, fieldKey, gi) {
    var ui = cloneUi(def)
    ui.form.groups.forEach(function (g) { g.fields = (g.fields || []).filter(function (k) { return k !== fieldKey }) })
    if (gi >= 0 && ui.form.groups[gi]) ui.form.groups[gi].fields.push(fieldKey)
    return ui
  }

  function moveFieldInGroup(def, gi, index, dir) {
    var ui = cloneUi(def)
    if (ui.form.groups[gi]) ui.form.groups[gi].fields = move(ui.form.groups[gi].fields || [], index, dir)
    return ui
  }

  /** 沒有被分到任何組的欄位 key（依欄位順序）。 */
  function ungroupedFields(def) {
    var used = {}
    ;(((uiOf(def).form || {}).groups) || []).forEach(function (g) { (g.fields || []).forEach(function (k) { used[k] = true }) })
    return fieldsOf(def).filter(function (f) { return !used[f.key] }).map(function (f) { return f.key })
  }

  /** 列表可以選的欄：系統欄＋所有欄位。 */
  function availableColumns(def) {
    return SYSTEM_COLUMNS.map(function (c) { return { key: c.key, label: c.label, system: true } })
      .concat(fieldsOf(def).map(function (f) { return { key: f.key, label: f.label || f.key, system: false } }))
  }

  /** 列表欄開／關。第一次設定時以目前的預設欄為起點（避免一勾就只剩一欄）。 */
  function toggleColumn(def, colKey) {
    var ui = cloneUi(def)
    if (!ui.list.columns.length) ui.list.columns = listColumns(def).map(function (c) { return c.key })
    var i = ui.list.columns.indexOf(colKey)
    if (i >= 0) ui.list.columns.splice(i, 1)
    else ui.list.columns.push(colKey)
    return ui
  }

  function moveColumn(def, index, dir) {
    var ui = cloneUi(def)
    if (!ui.list.columns.length) ui.list.columns = listColumns(def).map(function (c) { return c.key })
    ui.list.columns = move(ui.list.columns, index, dir)
    return ui
  }

  /** 欄位改名或刪除之後，把版面裡的舊 key 換掉或拿掉（newKey 空 ⇒ 刪除）。 */
  function renameFieldKey(def, oldKey, newKey) {
    var ui = cloneUi(def)
    ui.form.groups.forEach(function (g) {
      g.fields = (g.fields || []).map(function (k) { return k === oldKey ? newKey : k }).filter(function (k) { return k })
    })
    ui.list.columns = ui.list.columns.map(function (k) { return k === oldKey ? newKey : k }).filter(function (k) { return k })
    return ui
  }

  // ══ P9：內建模組的版面（CUSTOMIZATION-SPEC §3.10）══════════════════════════════
  // 輸入＝可自訂點（`catalog.layout_points(模組)`，由 GET /api/layout/{模組} 帶回）＋排版操作（ui_definitions 的
  // layout body.ops）。**排版器（layout-editor.js）與執行時（layout-runtime.js）都只經這裡**把「點＋操作」變成畫面狀態，
  // 所以「編輯時看到的」與「發布後使用者看到的」只有一個來源。只有純函式：不碰 DOM、不打 API。
  //
  // 畫面狀態（pageModel 的回傳，applyOps 之後同形）：
  //   lists[key]  = {id, key, label, columns:[{id, field, label, core, visible, ops}]}
  //   forms[key]  = {id, key, label, sections:[{id, key, label, ops, fields:[{id, field, label, core, visible, ops}]}]}
  //   actions     = [{id, key, label, hidden, ops}]         頁面按鈕（順序＝陣列順序）
  //   menus       = [{id, key, label, hidden, items:[按鈕 id], ops}]
  //   exports     = [{id, key, label, format, hidden, ops}]
  //   outputs     = [{id, key, label, template, templates, ops}]（模組層級，每一頁都列）
  //   sidebar     = {id, label, group, hidden, index, ops} 或 null（index＝null ⇒ 原位置）

  function _after(id, sep) { var i = id.lastIndexOf(sep); return i < 0 ? '' : id.slice(i + sep.length) }
  function _clone(x) { return JSON.parse(JSON.stringify(x)) }

  /** 這一頁的原始版面（模組 module.json 登記的樣子）。points 以外的東西一律不出現。 */
  function pageModel(points, page) {
    var st = { lists: {}, forms: {}, actions: [], menus: [], exports: [], outputs: [], sidebar: null }
    var sections = {}
    ;(points || []).forEach(function (p) {
      var base = p.id.split('/')[0]
      var onPage = base.slice(base.indexOf(':') + 1) === page
      if (p.kind === 'output') {
        st.outputs.push({ id: p.id, key: _after(p.id, ':output:'), label: p.label, template: p.template,
                          templates: (p.templates || []).slice(), ops: p.ops })
        return
      }
      if (!onPage) return
      if (p.kind === 'sidebar') {
        st.sidebar = { id: p.id, label: p.label, group: (p.menu || {}).group || '', hidden: false, index: null, ops: p.ops }
      } else if (p.kind === 'list') {
        st.lists[_after(p.id, '/list:')] = { id: p.id, key: _after(p.id, '/list:'), label: p.label, columns: [] }
      } else if (p.kind === 'form') {
        st.forms[_after(p.id, '/form:')] = { id: p.id, key: _after(p.id, '/form:'), label: p.label, sections: [] }
      } else if (p.kind === 'section') {
        var f = st.forms[_after(p.parent, '/form:')]
        var s = { id: p.id, key: _after(p.id, '/section:'), label: p.label, ops: p.ops, fields: [] }
        if (f) { f.sections.push(s); sections[p.id] = s }
      } else if (p.kind === 'field') {
        var fld = { id: p.id, field: p.field, label: p.label, core: !!p.core, visible: p.visible !== false, ops: p.ops }
        if (p.parent && p.parent.indexOf('/section:') > 0) {
          if (sections[p.parent]) sections[p.parent].fields.push(fld)
        } else {
          var l = st.lists[_after(p.parent || '', '/list:')]
          if (l) l.columns.push(fld)
        }
      } else if (p.kind === 'action') {
        st.actions.push({ id: p.id, key: _after(p.id, '/action:'), label: p.label, hidden: false, ops: p.ops })
      } else if (p.kind === 'menu') {
        st.menus.push({ id: p.id, key: _after(p.id, '/menu:'), label: p.label, hidden: false, items: (p.items || []).slice(), ops: p.ops })
      } else if (p.kind === 'export') {
        st.exports.push({ id: p.id, key: _after(p.id, '/export:'), label: p.label, format: p.format, hidden: false, ops: p.ops })
      }
    })
    return st
  }

  /** id ⇒ {obj, arr（它所在的陣列）, kind}；找不到 ⇒ null。 */
  function findPoint(st, id) {
    var hit = null
    Object.keys(st.lists).forEach(function (k) {
      var l = st.lists[k]
      if (l.id === id) hit = { obj: l, kind: 'list' }
      l.columns.forEach(function (c) { if (c.id === id) hit = { obj: c, arr: l.columns, kind: 'field', parent: l } })
    })
    Object.keys(st.forms).forEach(function (k) {
      var f = st.forms[k]
      if (f.id === id) hit = { obj: f, kind: 'form' }
      f.sections.forEach(function (s) {
        if (s.id === id) hit = { obj: s, arr: f.sections, kind: 'section', parent: f }
        s.fields.forEach(function (x) { if (x.id === id) hit = { obj: x, arr: s.fields, kind: 'field', parent: s, form: f } })
      })
    })
    ;[['actions', 'action'], ['menus', 'menu'], ['exports', 'export'], ['outputs', 'output']].forEach(function (a) {
      st[a[0]].forEach(function (x) { if (x.id === id) hit = { obj: x, arr: st[a[0]], kind: a[1] } })
    })
    if (st.sidebar && st.sidebar.id === id) hit = { obj: st.sidebar, kind: 'sidebar' }
    return hit
  }

  function _moveTo(arr, obj, index) {
    var i = arr.indexOf(obj)
    if (i >= 0) arr.splice(i, 1)
    var j = (typeof index === 'number' && index >= 0 && index <= arr.length) ? index : arr.length
    arr.splice(j, 0, obj)
  }

  function _reorder(arr, order, idOf) {
    if (!Array.isArray(order) || order.length !== arr.length) return false
    var by = {}
    arr.forEach(function (x) { by[idOf(x)] = x })
    if (!order.every(function (id) { return by[id] })) return false
    var out = order.map(function (id) { return by[id] })
    arr.splice.apply(arr, [0, arr.length].concat(out))
    return true
  }

  /** 原始版面依序套用排版操作 ⇒ {state, skipped:[套不上的操作 index]}。
   *  操作是否合法由後端 check_layout 決定（發布前擋、執行時 dropped）；這裡只負責「怎麼套」，套不上的記下來不猜。 */
  function applyOps(points, page, ops) {
    var st = pageModel(points, page)
    var skipped = []
    ;(ops || []).forEach(function (o, i) {
      var t = o && findPoint(st, o.target)
      if (!t) { skipped.push(i); return }
      var ok = true
      if (o.op === 'reorder') {
        if (t.kind === 'list') ok = _reorder(t.obj.columns, o.order, function (c) { return c.id })
        else if (t.kind === 'form') ok = _reorder(t.obj.sections, o.order, function (s) { return s.id })
        else if (t.kind === 'menu') ok = _reorder(t.obj.items, o.order, function (x) { return x })
        else ok = false
      } else if (o.op === 'move') {
        if (t.kind === 'sidebar') { t.obj.index = o.index }
        else if (t.kind === 'field' && t.form && o.to) {
          var dest = findPoint(st, o.to)
          if (!dest || dest.kind !== 'section') ok = false
          else { t.arr.splice(t.arr.indexOf(t.obj), 1); _moveTo(dest.obj.fields, t.obj, o.index) }
        } else if (t.kind === 'action' && o.to) {
          var mn = findPoint(st, o.to)
          if (!mn || mn.kind !== 'menu') ok = false
          else {
            st.menus.forEach(function (m) { var k = m.items.indexOf(t.obj.id); if (k >= 0) m.items.splice(k, 1) })
            var items = mn.obj.items
            items.splice((typeof o.index === 'number' && o.index <= items.length) ? o.index : items.length, 0, t.obj.id)
          }
        } else if (t.arr) { _moveTo(t.arr, t.obj, o.index) }
        else ok = false
      } else if (o.op === 'hide' || o.op === 'show') {
        if (t.kind === 'field') t.obj.visible = o.op === 'show'
        else t.obj.hidden = o.op === 'hide'
      } else if (o.op === 'relabel') {
        t.obj.label = o.label
      } else if (o.op === 'add_section' && t.kind === 'form') {
        t.obj.sections.push({ id: t.obj.id + '/section:' + o.key, key: o.key, label: o.label, ops: ['move', 'relabel'], fields: [], added: true })
      } else if (o.op === 'select_template' && t.kind === 'output') {
        t.obj.template = o.template
      } else ok = false
      if (!ok) skipped.push(i)
    })
    return { state: st, skipped: skipped }
  }

  function _ids(arr) { return arr.map(function (x) { return x.id }) }
  function _same(a, b) { return JSON.stringify(a) === JSON.stringify(b) }

  /** 畫面狀態 ⇒ 最少的排版操作（與原始版面比較；確定性：同一個狀態永遠產生同一串操作）。
   *  applyOps(points, page, compileOps(points, page, s)).state 與 s 相同（round trip，e2e 守門）。 */
  function compileOps(points, page, st) {
    var d = pageModel(points, page)
    var ops = []
    function labelHide(cur, def, isField) {
      if (isField) {
        if (cur.visible !== def.visible) ops.push({ op: cur.visible ? 'show' : 'hide', target: cur.id })
      } else if (cur.hidden && !def.hidden) ops.push({ op: 'hide', target: cur.id })
      if (cur.label !== def.label) ops.push({ op: 'relabel', target: cur.id, label: cur.label })
    }
    Object.keys(d.lists).forEach(function (k) {
      var cur = st.lists[k], def = d.lists[k]
      if (!cur) return
      if (!_same(_ids(cur.columns), _ids(def.columns))) ops.push({ op: 'reorder', target: def.id, order: _ids(cur.columns) })
      var byId = {}
      def.columns.forEach(function (c) { byId[c.id] = c })
      cur.columns.forEach(function (c) { if (byId[c.id]) labelHide(c, byId[c.id], true) })
    })
    Object.keys(d.forms).forEach(function (k) {
      var cur = st.forms[k], def = d.forms[k]
      if (!cur) return
      var reg = cur.sections.filter(function (s) { return !s.added })
      if (!_same(_ids(reg), _ids(def.sections))) ops.push({ op: 'reorder', target: def.id, order: _ids(reg) })
      var defSec = {}, defFld = {}
      def.sections.forEach(function (s) { defSec[s.id] = s; s.fields.forEach(function (f) { defFld[f.id] = f }) })
      cur.sections.forEach(function (s) { if (defSec[s.id] && s.label !== defSec[s.id].label) ops.push({ op: 'relabel', target: s.id, label: s.label }) })
      var curMap = {}
      cur.sections.forEach(function (s) { curMap[s.id] = _ids(s.fields) })
      var changed = def.sections.some(function (s) { return !_same(curMap[s.id] || [], _ids(s.fields)) })
      if (changed) {
        cur.sections.forEach(function (s) {
          s.fields.forEach(function (f, i) { ops.push({ op: 'move', target: f.id, to: s.id, index: i }) })
        })
      }
      cur.sections.forEach(function (s) { s.fields.forEach(function (f) { if (defFld[f.id]) labelHide(f, defFld[f.id], true) }) })
    })
    ;['actions', 'menus', 'exports'].forEach(function (k) {
      var cur = st[k], def = d[k]
      if (!_same(_ids(cur), _ids(def))) cur.forEach(function (x, i) { ops.push({ op: 'move', target: x.id, index: i }) })
      var byId = {}
      def.forEach(function (x) { byId[x.id] = x })
      cur.forEach(function (x) {
        if (!byId[x.id]) return
        labelHide(x, byId[x.id], false)
        if (k === 'menus' && !_same(x.items, byId[x.id].items)) ops.push({ op: 'reorder', target: x.id, order: x.items.slice() })
      })
    })
    st.outputs.forEach(function (o) {
      var def = d.outputs.filter(function (x) { return x.id === o.id })[0]
      if (def && o.template !== def.template) ops.push({ op: 'select_template', target: o.id, template: o.template })
    })
    if (st.sidebar && d.sidebar) {
      if (st.sidebar.hidden) ops.push({ op: 'hide', target: d.sidebar.id })
      if (typeof st.sidebar.index === 'number') ops.push({ op: 'move', target: d.sidebar.id, index: st.sidebar.index })
    }
    return ops
  }

  /** 兩個畫面狀態的差異 ⇒ 人看得懂的句子（「發布前看差異」）。 */
  function describeDiff(a, b) {
    var out = []
    function lab(x) { return '「' + x.label + '」' }
    function pair(pre, x, y, isField) {
      if (isField && x.visible !== y.visible) out.push(pre + '：' + (y.visible ? '顯示' : '隱藏'))
      if (!isField && !!x.hidden !== !!y.hidden) out.push(pre + '：' + (y.hidden ? '隱藏' : '顯示'))
      if (x.label !== y.label) out.push(pre + '：標籤 ' + lab(x) + ' → ' + lab(y))
    }
    function byId(arr) { var m = {}; arr.forEach(function (x) { m[x.id] = x }); return m }
    Object.keys(b.lists).forEach(function (k) {
      var x = a.lists[k], y = b.lists[k]
      if (!x) return
      if (!_same(_ids(x.columns), _ids(y.columns))) out.push(lab(y) + '：欄位順序 ' + y.columns.map(function (c) { return c.label }).join('、'))
      var m = byId(x.columns)
      y.columns.forEach(function (c) { if (m[c.id]) pair(lab(y) + ' › ' + lab(m[c.id]), m[c.id], c, true) })
    })
    Object.keys(b.forms).forEach(function (k) {
      var x = a.forms[k], y = b.forms[k]
      if (!x) return
      if (!_same(_ids(x.sections), _ids(y.sections))) out.push(lab(y) + '：區塊順序 ' + y.sections.map(function (s) { return s.label }).join('、'))
      var ms = byId(x.sections), mf = {}
      x.sections.forEach(function (s) { s.fields.forEach(function (f) { mf[f.id] = f }) })
      y.sections.forEach(function (s) {
        if (ms[s.id]) {
          if (ms[s.id].label !== s.label) out.push(lab(y) + ' › 區塊 ' + lab(ms[s.id]) + '：改名為 ' + lab(s))
          if (!_same(_ids(ms[s.id].fields), _ids(s.fields))) out.push(lab(y) + ' › 區塊 ' + lab(s) + '：欄位 ' + s.fields.map(function (f) { return f.label }).join('、'))
        }
        s.fields.forEach(function (f) { if (mf[f.id]) pair(lab(y) + ' › ' + lab(mf[f.id]), mf[f.id], f, true) })
      })
    })
    ;[['actions', '按鈕'], ['menus', '選單'], ['exports', '匯出']].forEach(function (kv) {
      var x = a[kv[0]], y = b[kv[0]]
      if (!_same(_ids(x), _ids(y))) out.push(kv[1] + '順序：' + y.map(function (v) { return v.label }).join('、'))
      var m = byId(x)
      y.forEach(function (v) {
        if (!m[v.id]) return
        pair(kv[1] + ' ' + lab(m[v.id]), m[v.id], v, false)
        if (kv[0] === 'menus' && !_same(m[v.id].items, v.items)) out.push('選單 ' + lab(v) + '：項目順序變更')
      })
    })
    var mo = byId(a.outputs)
    b.outputs.forEach(function (o) { if (mo[o.id] && mo[o.id].template !== o.template) out.push('輸出 ' + lab(o) + '：版型 ' + mo[o.id].template + ' → ' + o.template) })
    if (a.sidebar && b.sidebar) {
      if (a.sidebar.hidden !== b.sidebar.hidden) out.push('側欄 ' + lab(b.sidebar) + '：' + (b.sidebar.hidden ? '隱藏' : '顯示'))
      if (a.sidebar.index !== b.sidebar.index) out.push('側欄 ' + lab(b.sidebar) + '：位置 ' + (b.sidebar.index === null ? '原位置' : '群組內第 ' + (b.sidebar.index + 1) + ' 項'))
    }
    return out
  }

  // ── 個人層（§1 裁示：個人只能調欄位的顯示與排序；沿用清單偏好 user_list_prefs）──
  // 存法：GET/PUT /api/list-prefs/<personalKey>，sortMode='columns'、customOrder＝欄位 key 依序，隱藏的加前綴 '-'。
  // 只能作用在「公司／角色層之後仍顯示」的欄位；核心欄位的 '-' 一律不理（不可隱藏）；不認得的 key 不理。

  function personalKey(module, listKey) { return 'layout-cols.' + module + '.' + listKey }

  /** 公司／角色層套完的列表欄 ＋ 個人偏好 ⇒ 欄位（含 visible）。上層隱藏的欄位不出現（個人不能打開）。 */
  function applyPersonal(columns, pref) {
    var shown = (columns || []).filter(function (c) { return c.visible })
    var order = (pref && pref.sortMode === 'columns' && Array.isArray(pref.customOrder)) ? pref.customOrder : []
    var by = {}
    shown.forEach(function (c) { by[c.field] = c })
    var used = {}, out = []
    order.forEach(function (e) {
      if (typeof e !== 'string') return
      var hide = e.charAt(0) === '-'
      var f = hide ? e.slice(1) : e
      var c = by[f]
      if (!c || used[f]) return
      used[f] = true
      out.push(Object.assign({}, c, { visible: (hide && !c.core) ? false : true }))
    })
    shown.forEach(function (c) { if (!used[c.field]) out.push(Object.assign({}, c)) })
    return out
  }

  /** 個人欄位設定（applyPersonal 的輸出形狀）⇒ 清單偏好的 body。 */
  function personalPref(columns) {
    return { sortMode: 'columns', sortDir: 'desc',
             customOrder: (columns || []).map(function (c) { return (c.visible || c.core ? '' : '-') + c.field }) }
  }

  window.MotrixCustomLayout = {
    // P9 內建模組版面
    pageModel: pageModel,
    findPoint: findPoint,
    applyOps: applyOps,
    compileOps: compileOps,
    describeDiff: describeDiff,
    personalKey: personalKey,
    applyPersonal: applyPersonal,
    personalPref: personalPref,
    clone: _clone,
    SYSTEM_COLUMNS: SYSTEM_COLUMNS,
    formSections: formSections,
    listColumns: listColumns,
    cellValue: cellValue,
    move: move,
    // 編輯操作
    addGroup: addGroup,
    removeGroup: removeGroup,
    renameGroup: renameGroup,
    moveGroup: moveGroup,
    assignField: assignField,
    moveFieldInGroup: moveFieldInGroup,
    ungroupedFields: ungroupedFields,
    availableColumns: availableColumns,
    toggleColumn: toggleColumn,
    moveColumn: moveColumn,
    renameFieldKey: renameFieldKey,
  }
})()
