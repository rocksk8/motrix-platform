/* expense-type-refresh.js — 請款類型「與出貨範本比較」的純函式（D15；設計 PUBLISHED-TYPE-REFRESH-DESIGN.md 做法 A＋C）
 * compute(mine, def) → 差異項目 [{id, op, path, label, group, mine, def}]
 *   op：add＝出貨範本有、我的沒有；remove＝我的有、出貨範本沒有；change＝兩邊都有但不同。
 *   物件逐鍵比；元素都有字串 `key` 的陣列（fields、明細欄 columns）依 key 配對（不看順序）；其餘陣列（ui.form.groups、ui.list.columns、options）整個當一項。
 * apply(body, item) → 把這一項「採用出貨的」寫進 body（原地修改；呼叫者再存草稿，不自動發布）。
 * 不認得的鍵照常比對與套用——本檔不做白名單，驗證以伺服器為準。 */
(function (root) {
  var PROP = { name: '名稱', label: '顯示名稱', help: '說明', type: '型別', required: '必填', default: '預設值', options: '選項', target: '參照對象',
               locked: '鎖定', editableBy: '可編輯者', formula: '公式', enabled: '啟用', payable: '可請款', docType: '單據類型', prefix: '編號前綴',
               minRows: '最少列數', optionsFrom: '選項來源', template: '版型' }
  function clone(x) { return JSON.parse(JSON.stringify(x === undefined ? null : x)) }
  function same(a, b) { return JSON.stringify(a) === JSON.stringify(b) }
  function isObj(x) { return x !== null && typeof x === 'object' && !Array.isArray(x) }
  function keyed(a) { return Array.isArray(a) && a.every(function (e) { return isObj(e) && typeof e.key === 'string' && e.key !== '' }) }
  function tokStr(t) { return typeof t === 'string' ? t : '[' + t.key + ']' }
  function pathStr(toks) { return toks.map(function (t, i) { return typeof t === 'string' ? (i ? '.' : '') + t : '[' + t.key + ']' }).join('') }
  function nameOf(node) { return isObj(node) ? (node.label || node.name || node.key || '') : '' }

  function labelFor(toks, mineRoot, defRoot, op) {
    // 例：fields[applicant].help ⇒ 欄位「申請人」的說明；fields[lines].columns[amount] ⇒ 明細欄「金額」
    var out = [], mNode = mineRoot, dNode = defRoot
    for (var i = 0; i < toks.length; i++) {
      var t = toks[i]
      if (typeof t === 'string') {
        mNode = isObj(mNode) ? mNode[t] : undefined; dNode = isObj(dNode) ? dNode[t] : undefined
        if (t === 'fields' || t === 'columns') continue
        out.push(PROP[t] || t)
      } else {
        var m = (mNode || []).find(function (e) { return e.key === t.key }), d = (dNode || []).find(function (e) { return e.key === t.key })
        var parentTok = toks[i - 1]
        var nm = nameOf(m) || nameOf(d) || t.key
        out.push((parentTok === 'columns' ? '明細欄「' : '欄位「') + nm + '」' + (nm !== t.key ? '(' + t.key + ')' : ''))
        mNode = m; dNode = d
      }
    }
    var s = out.join(' › ')
    return s + (op === 'add' ? '（出貨範本新增）' : op === 'remove' ? '（出貨範本沒有）' : '')
  }
  function groupOf(toks) {
    if (!toks.length) return '其他'
    var t0 = toks[0]
    if (t0 === 'fields') return toks.length > 1 && toks[1].key === 'lines' && toks[2] === 'columns' ? '明細欄' : '欄位'
    if (t0 === 'ui') return '版面'
    if (t0 === 'output') return '輸出版型'
    return '基本設定'
  }

  function compute(mine, def) {
    var items = []
    function walk(a, b, toks) {
      if (isObj(a) && isObj(b)) {
        var ks = {}
        Object.keys(a).forEach(function (k) { ks[k] = 1 }); Object.keys(b).forEach(function (k) { ks[k] = 1 })
        Object.keys(ks).sort().forEach(function (k) {
          var p = toks.concat([k])
          if (!(k in a)) push('add', p, undefined, b[k])
          else if (!(k in b)) push('remove', p, a[k], undefined)
          else walk(a[k], b[k], p)
        })
      } else if (keyed(a) && keyed(b)) {
        var seen = {}
        b.forEach(function (e) {
          seen[e.key] = 1
          var p = toks.concat([{ key: e.key }]), m = a.find(function (x) { return x.key === e.key })
          if (!m) push('add', p, undefined, e); else walk(m, e, p)
        })
        a.forEach(function (e) { if (!seen[e.key]) push('remove', toks.concat([{ key: e.key }]), e, undefined) })
      } else if (!same(a, b)) push('change', toks, a, b)
    }
    function push(op, toks, m, d) {
      items.push({ id: pathStr(toks), op: op, path: toks, label: labelFor(toks, mine, def, op), group: groupOf(toks), mine: m, def: d })
    }
    walk(mine || {}, def || {}, [])
    return items
  }

  function parentOf(body, toks) {
    var node = body
    for (var i = 0; i < toks.length - 1; i++) {
      var t = toks[i]
      if (typeof t === 'string') { if (!isObj(node[t]) && !Array.isArray(node[t])) node[t] = (typeof toks[i + 1] === 'string') ? {} : []; node = node[t] }
      else node = node.find(function (e) { return e.key === t.key })
      if (node === undefined) return null
    }
    return node
  }
  function apply(body, item) {
    var toks = item.path, last = toks[toks.length - 1], par = parentOf(body, toks)
    if (!par) return false
    if (typeof last === 'string') {
      if (item.op === 'remove') delete par[last]; else par[last] = clone(item.def)
      return true
    }
    // keyed 陣列的一個元素
    var i = par.findIndex(function (e) { return e.key === last.key })
    if (item.op === 'remove') { if (i >= 0) par.splice(i, 1); return true }
    if (item.op === 'add') {
      if (i >= 0) return true
      var li = par.findIndex(function (e) { return e.key === 'lines' && e.type === 'table' })          // 明細表固定排最後
      if (li >= 0 && li === par.length - 1) par.splice(li, 0, clone(item.def)); else par.push(clone(item.def))
      return true
    }
    if (i >= 0) par[i] = clone(item.def)
    return true
  }
  function preview(v) {
    if (v === undefined) return '（無）'
    var s = typeof v === 'string' ? v : JSON.stringify(v)
    return s.length > 90 ? s.slice(0, 90) + '…' : s
  }

  var api = { compute: compute, apply: apply, preview: preview }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  root.ExpenseTypeRefresh = api
})(typeof window !== 'undefined' ? window : globalThis)
