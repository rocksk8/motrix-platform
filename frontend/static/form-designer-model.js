// form-designer-model.js — 表單設計器的資料層（純函式，不碰 DOM；單元測試直接載入這支）。
//
// 設計器直接編輯「現行定義 JSON」（fields[]／ui.form.groups／ui.list.columns），沒有第二份資料模型：
//   · 載入後不做任何「整理」——不動就輸出，位元相同（G-D2）：空 groups 仍是空、list.columns 保持原順序、不認得的鍵原樣保留。
//   · 設計器自己的暫存放在欄位物件的「底線開頭」鍵（`_calc`），輸出時剔除。
//   · 計算器（自動計算）⇄ 公式字串：build／parse 往返；認不得的公式＝「進階公式」，原樣保留。
// 規格：docs/platform/plans/FORM-DESIGNER-DESIGN.md（§5 資料相容、§6 計算器與自動帶入、§12 實作約束）。
(function (root) {
  'use strict'

  var KEY_RE = /^[a-z][a-z0-9_]{0,39}$/
  var OPTION_TYPES = { select: 1, radio: 1, multiselect: 1, checkboxes: 1 }

  function clone(x) { return x === undefined ? undefined : JSON.parse(JSON.stringify(x)) }

  /** 輸出用：剔除底線開頭的設計器暫存鍵（欄位層與明細表欄層）。 */
  function strip(def) {
    var d = clone(def) || {}
    function cut(o) { Object.keys(o).forEach(function (k) { if (k.charAt(0) === '_') delete o[k] }) }
    ;(d.fields || []).forEach(function (f) {
      if (!f || typeof f !== 'object') return
      cut(f)
      ;(f.columns || []).forEach(function (c) { if (c && typeof c === 'object') cut(c) })
    })
    return d
  }

  // ───────────────────────── 欄位／種類 ─────────────────────────
  function fieldByKey(d, k) { return (d.fields || []).find(function (f) { return f.key === k }) || null }
  function indexOfKey(d, k) { return (d.fields || []).findIndex(function (f) { return f.key === k }) }
  /** 畫面上的「種類」：金額＝number＋min:0 的視覺別名不另存；人員／部門由 ref 的 target 決定。 */
  function kindOf(f) {
    if (f.type === 'ref') return f.target === 'departments' ? (f.multiple ? 'depts' : 'dept') : (f.multiple ? 'users' : 'user')
    if (f.type === 'date' && f.withTime) return 'datetime'
    return f.type
  }
  function newKey(d, base) {
    base = String(base || 'field').toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/^[^a-z]+/, 'f')
    var n = 1, k
    do { k = (base + '_' + (++n)).slice(0, 40) } while (fieldByKey(d, k))
    return fieldByKey(d, base) ? k : base
  }

  // ───────────────────────── 區塊（groups）─────────────────────────
  /**
   * 畫面用的區塊清單：[{title, keys, virtual?, other?}]。
   * groups 為空 ⇒ 一個無標題的虛擬區塊（含全部欄位，依 fields 順序）——與渲染器行為一致，不改資料。
   * groups 非空 ⇒ 依序各群組（不存在的鍵略過）；沒進任何群組的欄位接在最後「其他」（other:true，也是渲染器的行為）。
   */
  function groupsOf(d) {
    var g = d.ui && d.ui.form && d.ui.form.groups
    var keys = (d.fields || []).map(function (f) { return f.key })
    if (!Array.isArray(g) || !g.length) return [{ title: '', keys: keys.slice(), virtual: true }]
    var used = {}, out = g.map(function (x) {
      var ks = (x.fields || []).filter(function (k) { return keys.indexOf(k) >= 0 && !used[k] && (used[k] = true) })
      return { title: x.title || '', keys: ks }
    })
    var rest = keys.filter(function (k) { return !used[k] })
    if (rest.length) out.push({ title: '其他', keys: rest, other: true })
    return out
  }
  function hasExplicitGroups(d) { var g = d.ui && d.ui.form && d.ui.form.groups; return Array.isArray(g) && g.length > 0 }
  function ensureForm(d) { d.ui = d.ui || {}; d.ui.form = d.ui.form || {}; if (!Array.isArray(d.ui.form.groups)) d.ui.form.groups = [] }
  /** 第一次需要明確區塊時才「實體化」：[{title:'基本資料', fields:全部欄位}]。 */
  function materialize(d) {
    ensureForm(d)
    if (d.ui.form.groups.length) return
    d.ui.form.groups = [{ title: '基本資料', fields: (d.fields || []).map(function (f) { return f.key }) }]
  }
  /** 重複出現在兩個以上區塊的鍵（渲染器可能畫兩次）。 */
  function duplicateKeys(d) {
    var seen = {}, dup = {}
    ;((d.ui && d.ui.form && d.ui.form.groups) || []).forEach(function (g) {
      ;(g.fields || []).forEach(function (k) { if (seen[k]) dup[k] = true; seen[k] = true })
    })
    return Object.keys(dup)
  }
  function orphans(d) {
    var o = groupsOf(d).find(function (g) { return g.other })
    return o ? o.keys.slice() : []
  }
  function removeFromGroups(d, key) {
    ;((d.ui && d.ui.form && d.ui.form.groups) || []).forEach(function (g) { g.fields = (g.fields || []).filter(function (k) { return k !== key }) })
  }
  /** 把欄位放進「畫面上第 gi 個區塊」的第 idx 個位置（gi 指向虛擬／其他區塊時的規則見註解）。 */
  function placeKey(d, key, gi, idx) {
    var view = groupsOf(d), target = view[gi]
    if (!target) return
    if (target.virtual) {   // 沒有明確區塊：只調整 fields 順序（渲染順序＝fields 順序）
      var from = indexOfKey(d, key)
      if (from < 0) return
      var f = d.fields.splice(from, 1)[0]
      var at = Math.min(idx > from ? idx - 1 : idx, d.fields.length)
      d.fields.splice(at, 0, f)
      return
    }
    materialize(d)
    removeFromGroups(d, key)
    if (target.other) return                 // 放回「其他」＝從所有區塊移除（本來就是孤兒）
    var grp = d.ui.form.groups[gi]
    if (!grp) return
    grp.fields = grp.fields || []
    grp.fields.splice(Math.min(idx, grp.fields.length), 0, key)
  }

  // ───────────────────────── 清單欄位 ─────────────────────────
  function listColumns(d) { return (d.ui && d.ui.list && Array.isArray(d.ui.list.columns)) ? d.ui.list.columns : [] }
  function isListed(d, key) { return listColumns(d).indexOf(key) >= 0 }
  /** 開／關「在清單中顯示」：關＝移除；開＝插在表單順序中「它前面最近的已顯示欄位」之後（沒有就最前面），不重排其他欄。 */
  function setListed(d, key, on) {
    d.ui = d.ui || {}
    d.ui.list = d.ui.list || {}
    var cols = Array.isArray(d.ui.list.columns) ? d.ui.list.columns : (d.ui.list.columns = [])
    var at = cols.indexOf(key)
    if (!on) { if (at >= 0) cols.splice(at, 1); return }
    if (at >= 0) return
    var order = []
    groupsOf(d).forEach(function (g) { order = order.concat(g.keys) })
    var pos = order.indexOf(key), ins = 0
    for (var i = pos - 1; i >= 0; i--) { var j = cols.indexOf(order[i]); if (j >= 0) { ins = j + 1; break } }
    cols.splice(ins, 0, key)
  }

  // ───────────────────────── 新增／刪除／複製 ─────────────────────────
  /**
   * 依目錄的元件（{id,type,preset}）新增欄位。回傳新欄位的 key。
   * 位置：at＝{g,i}（畫面區塊索引、位置）；省略 ⇒ 加在 after 欄位後面，再沒有就加在最後一個區塊的最後。
   * 預設標籤由呼叫端給（label）。附件類、明細表不預設加進清單。
   */
  function addField(d, el, label, at, after) {
    d.fields = d.fields || []
    var f = Object.assign({ key: newKey(d, el.id === el.type ? el.type : el.id), label: label || el.label || el.type, type: el.type, dataClass: 'T1' }, clone(el.preset || {}))
    var view = groupsOf(d)
    var gi, idx
    if (at && view[at.g]) { gi = at.g; idx = at.i }
    else {
      var w = after && findKey(view, after)
      if (w) { gi = w.g; idx = w.i + 1 } else { gi = view.length - 1; idx = view[gi].keys.length }
    }
    d.fields.push(f)
    // 先放到「虛擬區塊」或明確區塊
    if (view[gi] && view[gi].virtual) {
      var last = d.fields.splice(d.fields.length - 1, 1)[0]
      var base = d.fields.map(function (x) { return x.key })
      var pos = Math.min(idx, base.length)
      d.fields.splice(pos, 0, last)
    } else if (view[gi] && !view[gi].other) {
      materialize(d)
      d.ui.form.groups[gi].fields.splice(Math.min(idx, d.ui.form.groups[gi].fields.length), 0, f.key)
    } else {      // 「其他」區塊：欄位留作孤兒（渲染器會把它放在「其他」）；實際加入時改放最後一個明確區塊
      var gs = d.ui.form.groups; gs[gs.length - 1].fields.push(f.key)
    }
    if (f.type !== 'file' && f.type !== 'image' && f.type !== 'table' && f.type !== 'formula') setListed(d, f.key, true)
    return f.key
  }
  function findKey(view, key) {
    for (var g = 0; g < view.length; g++) { var i = view[g].keys.indexOf(key); if (i >= 0) return { g: g, i: i } }
    return null
  }
  function removeField(d, key) {
    d.fields = (d.fields || []).filter(function (f) { return f.key !== key })
    removeFromGroups(d, key)
    setListed(d, key, false)
  }
  function duplicateField(d, key) {
    var f = fieldByKey(d, key); if (!f) return null
    var c = clone(f); c.key = newKey(d, f.type); c.label = f.label + '（複本）'; delete c._calc
    var view = groupsOf(d), w = findKey(view, key)
    d.fields.push(c)
    if (view[w.g].virtual) { var last = d.fields.pop(); d.fields.splice(indexOfKey(d, key) + 1, 0, last) }
    else if (!view[w.g].other) { materialize(d); var g = d.ui.form.groups[w.g]; g.fields.splice(g.fields.indexOf(key) + 1, 0, c.key) }
    if (isListed(d, key)) setListed(d, c.key, true)
    return c.key
  }
  function nudge(d, key, dir) {
    var view = groupsOf(d), w = findKey(view, key); if (!w) return false
    var to = w.i + dir
    if (to < 0 || to >= view[w.g].keys.length) {      // 到區塊邊緣 ⇒ 跨到相鄰的（明確）區塊
      var ng = view[w.g + dir]
      if (!ng || ng.other || view[w.g].virtual) return false
      placeKey(d, key, w.g + dir, dir > 0 ? 0 : ng.keys.length)
      return true
    }
    placeKey(d, key, w.g, dir > 0 ? to + 1 : to)
    return true
  }
  function addSection(d, title) {
    materialize(d)
    d.ui.form.groups.push({ title: title || '新區塊', fields: [] })
    return d.ui.form.groups.length - 1
  }
  function removeSection(d, gi) {   // 刪區塊＝連同其中欄位一起刪（呼叫端先確認）
    var view = groupsOf(d), g = view[gi]; if (!g || g.virtual || g.other) return []
    var keys = g.keys.slice()
    keys.forEach(function (k) { removeField(d, k) })
    d.ui.form.groups.splice(gi, 1)
    return keys
  }
  function moveSection(d, gi, dir) {
    var gs = d.ui.form.groups, to = gi + dir
    if (!gs || to < 0 || to >= gs.length) return false
    var t = gs[gi]; gs[gi] = gs[to]; gs[to] = t
    return true
  }

  // ───────────────────────── 引用檢查（刪除前）─────────────────────────
  function wordRe(k) { return new RegExp('(^|[^A-Za-z0-9_])' + k + '([^A-Za-z0-9_]|$)') }
  /** 還有誰用到這個欄位？[{where, text}]：其他欄位的公式、其他設定值、明細表欄公式、版面輸出（output）。 */
  function usedBy(d, key) {
    var out = [], re = wordRe(key)
    ;(d.fields || []).forEach(function (f) {
      if (f.key === key) return
      var hit = false
      Object.keys(f).forEach(function (a) {
        if (['key', 'label', 'help', 'options', 'placeholder', 'type', 'dataClass', 'columns', '_calc'].indexOf(a) >= 0) return
        var v = typeof f[a] === 'string' ? f[a] : (f[a] && typeof f[a] === 'object' ? JSON.stringify(f[a]) : '')
        if (v && re.test(v)) hit = true
      })
      if (hit) out.push({ where: 'field', key: f.key, text: '「' + (f.label || f.key) + '」的設定用到它' })
      ;(f.columns || []).forEach(function (c) { if (typeof c.formula === 'string' && re.test(c.formula)) out.push({ where: 'column', key: f.key, text: '「' + (f.label || f.key) + '」的明細欄「' + (c.label || c.key) + '」的計算用到它' }) })
    })
    if (d.output && re.test(JSON.stringify(d.output))) out.push({ where: 'output', key: '', text: '輸出版面（列印／PDF）用到它' })
    return out
  }

  // ───────────────────────── 自動計算（計算器 ⇄ 公式字串）─────────────────────────
  var CALCS = [
    { id: 'sumtable', name: '加總明細', why: '把明細表每一列的某個金額加起來。', ex: '三列 1,000＋2,000＋3,000 ＝ 6,000' },
    { id: 'sum', name: '加總欄位', why: '把你勾選的幾個數字欄位加起來。', ex: '「機票」1,000＋「住宿」2,000 ＝ 3,000' },
    { id: 'tax', name: '稅額計算', why: '輸入未稅算出稅額和含稅，或輸入含稅拆出稅。', ex: '未稅 10,000，稅率 5% ⇒ 稅額 500、含稅 10,500' },
    { id: 'mul', name: '數量 × 單價', why: '兩個欄位相乘。', ex: '數量 3 × 單價 500 ＝ 1,500' },
    { id: 'pct', name: '百分比', why: '某個金額的幾 %。', ex: '總額 10,000 的 30%（訂金）＝ 3,000' },
    { id: 'sub', name: '相減', why: 'A 減 B。', ex: '預算 10,000 − 已用 4,000 ＝ 6,000' },
    { id: 'days', name: '日期相差幾天', why: '兩個日期之間相差幾天。', ex: '5/1 到 5/4 ＝ 3 天' }
  ]
  function rateOf(c) { return c.rate === 'free' ? 0 : c.rate === 'custom' ? (+c.custom || 0) / 100 : 0.05 }
  function num(x) { return String(+x) }
  function buildCalc(c) {
    if (!c || !c.p) return ''
    var A = c.a, B = c.b
    switch (c.p) {
      case 'sumtable': return c.tbl && c.col ? 'total(' + c.tbl + ', "' + c.col + '")' : ''
      case 'sum': return (c.keys || []).join(' + ')
      case 'mul': return A && B ? (c.round ? 'round_half_up(' + A + ' * ' + B + ')' : A + ' * ' + B) : ''
      case 'sub': return A && B ? A + ' - ' + B : ''
      case 'pct': return A && c.pct !== '' && c.pct != null ? 'round_half_up(' + A + ' * ' + num(c.pct) + ' / 100)' : ''
      case 'days': return A && B ? 'days_between(' + A + ', ' + B + ')' : ''
      case 'tax':
        if (!A) return ''
        var r = rateOf(c)
        if (c.mode === 'split') return r === 0 ? '0' : 'round_half_up(' + A + ' - ' + A + ' / ' + num(1 + r) + ')'
        return c.out === 'gross' ? 'round_half_up(' + A + ' * ' + num(1 + r) + ')' : 'round_half_up(' + A + ' * ' + num(r) + ')'
    }
    return ''
  }
  /** 公式字串 ⇒ 計算器；空字串 ⇒ {p:''}（還沒選）；認不得 ⇒ null（進階公式）。 */
  function parseCalc(formula) {
    var s = String(formula || '').trim(), m
    if (!s) return { p: '' }
    if ((m = /^total\((\w+),\s*"(\w+)"\)$/.exec(s))) return { p: 'sumtable', tbl: m[1], col: m[2] }
    if ((m = /^(\w+) \* (\w+)$/.exec(s))) return { p: 'mul', a: m[1], b: m[2] }
    if ((m = /^(\w+) - (\w+)$/.exec(s))) return { p: 'sub', a: m[1], b: m[2] }
    if ((m = /^round_half_up\((\w+) \* ([A-Za-z_]\w*)\)$/.exec(s))) return { p: 'mul', a: m[1], b: m[2], round: true }
    if ((m = /^round_half_up\((\w+) \* ([\d.]+) \/ 100\)$/.exec(s))) return { p: 'pct', a: m[1], pct: m[2] }
    if ((m = /^days_between\((\w+), (\w+)\)$/.exec(s))) return { p: 'days', a: m[1], b: m[2] }
    if ((m = /^round_half_up\((\w+) \* ([\d.]+)\)$/.exec(s))) {
      var v = +m[2]
      if (v === 0.05) return { p: 'tax', a: m[1], mode: 'net', out: 'tax', rate: '5' }
      if (v === 1.05) return { p: 'tax', a: m[1], mode: 'net', out: 'gross', rate: '5' }
      if (v === 0) return { p: 'tax', a: m[1], mode: 'net', out: 'tax', rate: 'free' }
      if (v === 1) return { p: 'tax', a: m[1], mode: 'net', out: 'gross', rate: 'free' }
      if (v > 0 && v < 1) return { p: 'tax', a: m[1], mode: 'net', out: 'tax', rate: 'custom', custom: String(Math.round(v * 10000) / 100) }
      if (v > 1 && v < 2) return { p: 'tax', a: m[1], mode: 'net', out: 'gross', rate: 'custom', custom: String(Math.round((v - 1) * 10000) / 100) }
      return null
    }
    if ((m = /^round_half_up\((\w+) - (\w+) \/ ([\d.]+)\)$/.exec(s)) && m[1] === m[2]) {
      var w = +m[3]
      if (w > 1 && w < 2) return { p: 'tax', a: m[1], mode: 'split', rate: w === 1.05 ? '5' : 'custom', custom: String(Math.round((w - 1) * 10000) / 100) }
    }
    if (/^\w+( \+ \w+)+$/.test(s) || /^\w+$/.test(s)) return { p: 'sum', keys: s.split(' + ') }
    return null
  }
  /** build(parse(x)) 與 x 相同才算「認得」；否則視為進階公式（不改寫使用者原本的字串）。 */
  function parseCalcExact(formula) {
    var c = parseCalc(formula)
    if (c && c.p && buildCalc(c) !== String(formula).trim()) return null
    return c
  }
  /** 範例數字：每個欄位用固定樣本（數量 3、單價 500，其餘 1000×序），明細加總固定 6,000，日期差 3。 */
  function sampleOf(d, k) {
    var fixed = { qty: 3, unitCost: 500 }
    if (fixed[k] != null) return fixed[k]
    var i = Math.max(0, indexOfKey(d, k))
    return 1000 * (1 + (i % 4))
  }
  function calcResult(d, c) {
    if (!c || !c.p) return null
    var v = function (k) { return sampleOf(d, k) }
    switch (c.p) {
      case 'sumtable': return 6000
      case 'sum': return (c.keys || []).reduce(function (a, k) { return a + v(k) }, 0)
      case 'mul': return c.a && c.b ? v(c.a) * v(c.b) : null
      case 'sub': return c.a && c.b ? v(c.a) - v(c.b) : null
      case 'pct': return c.a && c.pct !== '' && c.pct != null ? Math.round(v(c.a) * (+c.pct) / 100) : null
      case 'days': return c.a && c.b ? 3 : null
      case 'tax':
        if (!c.a) return null
        var r = rateOf(c), a = v(c.a)
        if (c.mode === 'split') return r === 0 ? 0 : Math.round(a - a / (1 + r))
        return c.out === 'gross' ? Math.round(a * (1 + r)) : Math.round(a * r)
    }
    return null
  }

  // ───────────────────────── 自動帶入（預設值）─────────────────────────
  /** 目前選到的來源：'' ｜ token ｜ '*custom'（固定內容）｜ '*option'（先選好某一項）。 */
  function fillSelection(f) {
    var d = f.default
    if (d && typeof d === 'object' && d.$) return d.$
    if (d !== undefined && d !== null && d !== '') return (f.type === 'select' || f.type === 'radio') ? '*option' : '*custom'
    return ''
  }
  /** 這個欄位可選哪些來源。registry＝GET /api/platform/prefill-sources 的清單（單一來源）；needsCase＝表單有沒有案件情境。 */
  function fillsFor(f, registry, hasCase) {
    return (registry || []).filter(function (s) {
      if (s.needs_context && !hasCase) return false
      return (s.applies_to || []).some(function (a) {
        var t = a[0] != null ? a[0] : a.type, tg = a[1] != null ? a[1] : a.target
        if (t !== f.type) return false
        if (t === 'ref') return !tg || tg === f.target
        if (s.requires_time && !f.withTime) return false
        return true
      })
    })
  }
  /** 「不能改（locked）」可不可用：沒選來源、或來源 lockable=false ⇒ 不可。 */
  function canLock(f, registry) {
    var sel = fillSelection(f)
    if (!sel) return { ok: false, why: 'none' }
    if (sel.charAt(0) === '*') return { ok: true }
    var s = (registry || []).find(function (x) { return x.token === sel })
    if (s && s.lockable === false) return { ok: false, why: 'unlockable' }
    return { ok: true }
  }

  // ───────────────────────── 本機檢查（發布前、輸入時；伺服器 validate 另做）─────────────────────────
  /** caps：{bannedWords: RegExp, requiredColumns:[], pairColumns:[a,b], onlyOneTable:'lines', cashierKeys:[], fixedTypeKeys:{key:type}} */
  function localProblems(d, caps) {
    caps = caps || {}
    var out = []
    ;(d.fields || []).forEach(function (f, i) {
      var p = 'fields[' + i + ']'
      if (!f.label || !String(f.label).trim()) out.push({ path: p + '.label', message: '欄位還沒有名稱。', key: f.key })
      if (caps.bannedWords && (caps.bannedWords.test(f.key) || caps.bannedWords.test(f.label || ''))) out.push({ path: p + '.label', message: '這個名稱含有不能使用的字眼（銀行、帳號等）。', key: f.key })
      if (OPTION_TYPES[f.type] && !(f.options || []).some(function (o) { return String(o).trim() })) out.push({ path: p + '.options', message: '還沒有任何選項。', key: f.key })
      if (f.type === 'formula' && !String(f.formula || '').trim()) out.push({ path: p + '.formula', message: '還沒選要算什麼。', key: f.key })
      if (f.locked && fillSelection(f) === '') out.push({ path: p + '.locked', message: '要先選好「自動帶入」才能設「不能改」。', key: f.key })
      if (f.type === 'table') {
        var cols = f.columns || [], ks = cols.map(function (c) { return c.key })
        ;(caps.requiredColumns || []).forEach(function (rk) { if (ks.indexOf(rk) < 0) out.push({ path: p + '.columns', message: '明細表一定要有欄位：' + rk, key: f.key }) })
        var pr = caps.pairColumns || []
        if (pr.length === 2 && (ks.indexOf(pr[0]) >= 0) !== (ks.indexOf(pr[1]) >= 0)) out.push({ path: p + '.columns', message: '「數量」和「單價」要一起有，或一起沒有。', key: f.key })
        cols.forEach(function (c, j) {
          if (OPTION_TYPES[c.type] && !(c.options || []).length && !c.optionsFrom) out.push({ path: p + '.columns[' + j + '].options', message: '這一欄還沒有選項。', key: f.key })
          if (caps.bannedWords && caps.bannedWords.test(c.label || '')) out.push({ path: p + '.columns[' + j + '].label', message: '這個欄名含有不能使用的字眼。', key: f.key })
        })
      }
    })
    duplicateKeys(d).forEach(function (k) { out.push({ path: 'ui.form.groups', message: '「' + ((fieldByKey(d, k) || {}).label || k) + '」被放進兩個區塊。', key: k }) })
    return out
  }

  var api = {
    KEY_RE: KEY_RE, OPTION_TYPES: OPTION_TYPES, CALCS: CALCS,
    clone: clone, strip: strip,
    fieldByKey: fieldByKey, indexOfKey: indexOfKey, kindOf: kindOf, newKey: newKey,
    groupsOf: groupsOf, hasExplicitGroups: hasExplicitGroups, materialize: materialize, duplicateKeys: duplicateKeys, orphans: orphans,
    placeKey: placeKey, findKey: findKey,
    listColumns: listColumns, isListed: isListed, setListed: setListed,
    addField: addField, removeField: removeField, duplicateField: duplicateField, nudge: nudge,
    addSection: addSection, removeSection: removeSection, moveSection: moveSection,
    usedBy: usedBy,
    buildCalc: buildCalc, parseCalc: parseCalc, parseCalcExact: parseCalcExact, calcResult: calcResult, sampleOf: sampleOf,
    fillSelection: fillSelection, fillsFor: fillsFor, canLock: canLock,
    localProblems: localProblems
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  root.FDModel = api
})(typeof window !== 'undefined' ? window : globalThis)
