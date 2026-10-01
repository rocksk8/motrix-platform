/* definition-form.js — 依「定義」渲染表單（A2-4；A2-0 #8 的共用元件）
 *
 * 用途：費用單據（expense_type 定義）的「新增請款」表單；之後建構器預覽／其他定義表單可共用。
 * 約定：
 *   MotrixDefinitionForm.mount(el, {definition, viewer, categories, users, departments, values, lines, readOnly, onChange})
 *     ⇒ {getValue() → {data, lines, total}, validate() → [{path,message}], setValue({data,lines}), destroy()}
 *   - 無框架（不依賴 Alpine，所以不碰 alpine double-init 守門）、無 CDN；顏色只用 CSS 變數。
 *   - 金額一律由後端重算為準：這裡只做「即時預覽」（明細 qty×unitCost 四捨五入、amount 權威、總計＝明細合計）。
 *   - `locked` 欄位唯讀（預填值以後端為準）；`editableBy:"cashier"` 欄位對申請人唯讀並註明「出納填寫」。
 *   - 明細表 key 是 camelCase（unitCost／invoiceNo）；定義自訂的明細欄原樣保留（不丟鍵）。
 *   - 純函式（calc.*）可單獨測：node 載入本檔也能跑（無 window 時不掛載）。
 */
;(function (root) {
  'use strict'

  var CLS = 'df-'
  var KNOWN_TOKENS = { requester: 1, today: 1 }

  // ── 純函式 ─────────────────────────────────────────────────────────────
  function roundHalfUp(x) {
    // 與後端 legal_params.round_half_up 一致：0.5 一律往遠離 0 進位（金額不為負）
    var n = Number(x)
    if (!isFinite(n)) return 0
    return n < 0 ? -Math.floor(-n + 0.5) : Math.floor(n + 0.5)
  }
  function isNum(v) {
    if (v === '' || v === null || v === undefined || typeof v === 'boolean') return false
    return isFinite(Number(v))
  }
  /** 一列的金額：qty、unitCost 都是數字 ⇒ round_half_up(qty×unitCost)；否則 amount 為權威；都沒有 ⇒ 0 */
  function lineAmount(row) {
    row = row || {}
    if (isNum(row.qty) && isNum(row.unitCost)) return roundHalfUp(Number(row.qty) * Number(row.unitCost))
    if (isNum(row.amount)) return roundHalfUp(Number(row.amount))
    return 0
  }
  function totalOf(rows) {
    var t = 0
    ;(rows || []).forEach(function (r) { t += lineAmount(r) })
    return t
  }
  function today() {
    var d = new Date()
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
  }
  /** 預填值：{"$":"requester"|"today"} 或字面值；未知 token ⇒ 空字串（後端會再驗） */
  function defaultValue(field, viewer) {
    var d = field.default
    if (d && typeof d === 'object' && !Array.isArray(d) && '$' in d) {
      if (d.$ === 'requester') return (viewer && viewer.username) || ''
      if (d.$ === 'today') return today()
      return ''
    }
    if (d !== undefined && d !== null) return d
    if (field.type === 'daterange') return { from: '', to: '' }
    return ''
  }
  function formatMoney(n) { return Math.round(Number(n) || 0).toLocaleString('zh-TW') }
  function linesField(def) {
    var fs = (def && def.fields) || []
    for (var i = 0; i < fs.length; i++) if (fs[i].type === 'table' && fs[i].key === 'lines') return fs[i]
    return null
  }
  function isCashierOnly(f) { return f.editableBy === 'cashier' }

  /** 前端檢查（只做體驗用；伺服器端 validate_values 才是權威）⇒ [{path,message}] */
  function validate(def, data, lines, viewer) {
    var out = []
    ;((def && def.fields) || []).forEach(function (f) {
      if (f.type === 'table' || f.type === 'formula' || f.type === 'file') return
      if (isCashierOnly(f) && !(viewer && viewer.isCashier)) return
      var v = data ? data[f.key] : undefined
      var empty = v === undefined || v === null || v === '' ||
        (f.type === 'daterange' && (!v || !v.from || !v.to))
      if (f.required && empty) out.push({ path: f.key, message: (f.label || f.key) + '必填' })
      if (!empty && f.type === 'number') {
        if (!isNum(v)) out.push({ path: f.key, message: (f.label || f.key) + '要是數字' })
        else if (f.min !== undefined && Number(v) < f.min) out.push({ path: f.key, message: (f.label || f.key) + '不可小於 ' + f.min })
      }
      if (!empty && f.type === 'daterange' && v.from > v.to) out.push({ path: f.key, message: (f.label || f.key) + '起日不可晚於迄日' })
    })
    var lf = linesField(def)
    if (lf) {
      var rows = lines || []
      var min = lf.minRows === undefined ? 1 : lf.minRows
      if (rows.length < min) out.push({ path: 'lines', message: '至少要有 ' + min + ' 列明細' })
      rows.forEach(function (r, i) {
        ;(lf.columns || []).forEach(function (c) {
          if (c.type === 'formula' || !c.required) return
          var v = r[c.key]
          if (v === undefined || v === null || v === '') out.push({ path: 'lines.' + i + '.' + c.key, message: '第 ' + (i + 1) + ' 列：' + (c.label || c.key) + '必填' })
        })
      })
    }
    return out
  }

  var calc = { roundHalfUp: roundHalfUp, lineAmount: lineAmount, totalOf: totalOf, defaultValue: defaultValue, validate: validate, formatMoney: formatMoney }

  if (typeof document === 'undefined') {            // node（單元測）：只匯出純函式
    if (typeof module !== 'undefined' && module.exports) module.exports = { calc: calc }
    return
  }

  // ── DOM ───────────────────────────────────────────────────────────────
  function el(tag, attrs, kids) {
    var n = document.createElement(tag)
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k]
      if (v === null || v === undefined || v === false) return
      if (k === 'class') n.className = v
      else if (k === 'text') n.textContent = v
      else if (k === 'value') n.value = v
      else n.setAttribute(k, v === true ? '' : v)
    })
    ;(kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c) })
    return n
  }
  function clone(x) { try { return JSON.parse(JSON.stringify(x)) } catch (e) { return x } }
  function uid() { return 'k' + Math.random().toString(36).slice(2, 9) }

  function ensureStyle() {
    if (document.getElementById('df-style')) return
    var css = [
      '.df-sec{margin-bottom:16px}',
      '.df-sec__t{font-size:13px;font-weight:600;color:var(--text-secondary);margin-bottom:8px}',
      '.df-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}',
      '.df-f{display:flex;flex-direction:column;gap:4px;min-width:0}',
      '.df-f--wide{grid-column:1/-1}',
      '.df-f label{font-size:12px;color:var(--text-secondary)}',
      '.df-f .req{color:var(--danger,#c0392b);margin-left:2px}',
      '.df-f input,.df-f select,.df-f textarea{font:inherit;font-size:13px;padding:6px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-card,var(--bg));color:var(--text-primary);min-width:0}',
      '.df-f textarea{min-height:64px;resize:vertical}',
      '.df-f.is-bad input,.df-f.is-bad select,.df-f.is-bad textarea{border-color:var(--danger,#c0392b)}',
      '.df-f .df-err{font-size:11px;color:var(--danger,#c0392b)}',
      '.df-f .df-help{font-size:11px;color:var(--text-secondary)}',
      '.df-ro{padding:6px 8px;font-size:13px;color:var(--text-primary);background:var(--border-light);border-radius:6px;min-height:20px}',
      '.df-range{display:flex;gap:6px;align-items:center}',
      '.df-opts{display:flex;gap:12px;flex-wrap:wrap}',
      '.df-opts label{display:flex;gap:4px;align-items:center;font-size:13px;color:var(--text-primary)}',
      '.df-tbl{overflow-x:auto}',
      '.df-tbl table{width:100%;border-collapse:collapse;font-size:12px}',
      '.df-tbl th,.df-tbl td{padding:4px 6px;border-bottom:1px solid var(--border-light);text-align:left;vertical-align:top}',
      '.df-tbl th{font-size:11px;color:var(--text-secondary);font-weight:600}',
      '.df-tbl td input,.df-tbl td select{width:100%;min-width:72px}',
      '.df-tbl td input.num{text-align:right}',
      '.df-total{display:flex;justify-content:flex-end;gap:8px;font-size:14px;font-weight:600;margin-top:6px}',
      '.df-readonly input,.df-readonly select,.df-readonly textarea{pointer-events:none;opacity:.85}'
    ].join('\n')
    document.head.appendChild(el('style', { id: 'df-style', text: css }))
  }

  function mount(container, opts) {
    ensureStyle()
    opts = opts || {}
    var def = opts.definition || {}
    var viewer = opts.viewer || {}
    var readOnly = !!opts.readOnly
    var fields = def.fields || []
    var lf = linesField(def)
    var data = {}
    var lines = []
    var errors = {}
    var inputs = {}
    var alive = true

    // ── 選項來源 ──
    function optionsOf(f) {
      if (f.type === 'ref' && f.target === 'users') {
        return (opts.users || []).map(function (u) { return { value: u.username, label: u.display_name || u.name || u.username } })
      }
      if (f.type === 'ref' && f.target === 'departments') {
        return (opts.departments || []).map(function (d) { return { value: String(d.id), label: d.name } })
      }
      if (f.optionsFrom === 'expense_categories') {
        return (opts.categories || []).map(function (c) {
          return typeof c === 'string' ? { value: c, label: c } : { value: c.name || c.category || c.code, label: c.name || c.category || c.code }
        })
      }
      return (f.options || []).map(function (o) { return typeof o === 'string' ? { value: o, label: o } : { value: o.value, label: o.label || o.value } })
    }

    function init(values, rows) {
      data = {}
      fields.forEach(function (f) {
        if (f.type === 'table' || f.type === 'formula' || f.type === 'file') return
        var cur = values && values[f.key]
        data[f.key] = (cur !== undefined && cur !== null) ? clone(cur) : defaultValue(f, viewer)
        if (f.type === 'daterange' && (!data[f.key] || typeof data[f.key] !== 'object')) data[f.key] = { from: '', to: '' }
      })
      // 保留未知鍵（靜默遺失第一條）
      Object.keys(values || {}).forEach(function (k) { if (!(k in data) && k !== 'lines') data[k] = clone(values[k]) })
      lines = (rows || []).map(function (r) { var c = clone(r); c._k = uid(); return c })
      if (lf && !lines.length && !readOnly) {
        var n = lf.minRows === undefined ? 1 : lf.minRows
        for (var i = 0; i < Math.max(1, n); i++) lines.push(blankRow())
      }
    }
    function blankRow() {
      var r = { _k: uid() }
      ;((lf && lf.columns) || []).forEach(function (c) { if (c.type !== 'formula') r[c.key] = c.type === 'number' ? '' : '' })
      return r
    }
    function stripRow(r) { var c = {}; Object.keys(r).forEach(function (k) { if (k !== '_k') c[k] = r[k] }); return c }

    function changed() { if (typeof opts.onChange === 'function') opts.onChange(api.getValue()) }

    function fieldEditable(f) {
      if (readOnly) return false
      if (f.locked) return false
      if (isCashierOnly(f) && !viewer.isCashier) return false
      return true
    }

    // ── 單一欄位 ──
    function renderField(f) {
      var wrap = el('div', { class: CLS + 'f' + (f.type === 'table' || f.type === 'textarea' ? ' ' + CLS + 'f--wide' : ''), 'data-field': f.key })
      var id = 'df-in-' + f.key
      wrap.appendChild(el('label', { for: id }, [f.label || f.key, f.required ? el('span', { class: 'req', text: '*' }) : null]))
      var editable = fieldEditable(f)
      var inp = null
      if (f.type === 'formula') {
        inp = el('div', { class: CLS + 'ro', id: id, 'data-formula': f.key })
        inputs['__formula_' + f.key] = inp
      } else if (f.type === 'table') {
        wrap.appendChild(renderTable(f)); return wrap
      } else if (f.type === 'file') {
        wrap.appendChild(el('div', { class: CLS + 'help', text: '請在下方「附件」區上傳' })); return wrap
      } else if (f.type === 'textarea') {
        inp = el('textarea', { id: id, maxlength: f.maxLength || null, placeholder: f.placeholder || '', disabled: !editable })
        inp.value = data[f.key] || ''
        inp.addEventListener('input', function () { data[f.key] = inp.value; changed() })
      } else if (f.type === 'number') {
        inp = el('input', { type: 'number', step: 'any', id: id, min: f.min, max: f.max, disabled: !editable })
        inp.value = data[f.key] === undefined ? '' : data[f.key]
        inp.addEventListener('input', function () { data[f.key] = inp.value === '' ? '' : Number(inp.value); changed() })
      } else if (f.type === 'date') {
        inp = el('input', { type: 'date', id: id, disabled: !editable })
        inp.value = data[f.key] || ''
        inp.addEventListener('input', function () { data[f.key] = inp.value; changed() })
      } else if (f.type === 'daterange') {
        var a = el('input', { type: 'date', id: id, 'aria-label': '起', disabled: !editable })
        var b = el('input', { type: 'date', 'aria-label': '迄', disabled: !editable })
        a.value = (data[f.key] || {}).from || ''; b.value = (data[f.key] || {}).to || ''
        a.addEventListener('input', function () { data[f.key].from = a.value; changed() })
        b.addEventListener('input', function () { data[f.key].to = b.value; changed() })
        inp = el('div', { class: CLS + 'range', 'data-range': f.key }, [a, el('span', { text: '～' }), b])
      } else if (f.type === 'radio') {
        inp = el('div', { class: CLS + 'opts', role: 'radiogroup', 'data-radio': f.key })
        optionsOf(f).forEach(function (o) {
          var r = el('input', { type: 'radio', name: 'df-rd-' + f.key, value: o.value, disabled: !editable })
          r.checked = String(data[f.key]) === String(o.value)
          r.addEventListener('change', function () { if (r.checked) { data[f.key] = o.value; changed() } })
          inp.appendChild(el('label', {}, [r, el('span', { text: o.label })]))
        })
      } else if (f.type === 'select' || f.type === 'ref') {
        inp = el('select', { id: id, disabled: !editable })
        inp.appendChild(el('option', { value: '', text: '（未選）' }))
        var list = optionsOf(f), has = false
        list.forEach(function (o) {
          var op = el('option', { value: o.value, text: o.label })
          if (String(data[f.key]) === String(o.value)) { op.selected = true; has = true }
          inp.appendChild(op)
        })
        // 目前值不在選項裡（例如停用的類別）⇒ 仍顯示，免得無聲被清掉
        if (!has && data[f.key]) { var cur = el('option', { value: data[f.key], text: String(data[f.key]) }); cur.selected = true; inp.appendChild(cur) }
        inp.addEventListener('change', function () { data[f.key] = inp.value; changed() })
      } else {
        inp = el('input', { type: 'text', id: id, maxlength: f.maxLength || null, placeholder: f.placeholder || '', disabled: !editable })
        inp.value = data[f.key] === undefined ? '' : data[f.key]
        inp.addEventListener('input', function () { data[f.key] = inp.value; changed() })
      }
      inputs[f.key] = inp
      wrap.appendChild(inp)
      if (f.locked) wrap.appendChild(el('div', { class: CLS + 'help', text: '已鎖定' }))
      else if (isCashierOnly(f)) wrap.appendChild(el('div', { class: CLS + 'help', text: '核准後由出納填寫' }))
      if (f.help && !f.locked) wrap.appendChild(el('div', { class: CLS + 'help', text: f.help }))
      wrap.appendChild(el('div', { class: CLS + 'err', 'data-err': f.key }))
      return wrap
    }

    // ── 明細表 ──
    var tblBody = null
    function renderTable(f) {
      var cols = f.columns || []
      var box = el('div', { class: CLS + 'tbl', 'data-table': f.key })
      var tbl = el('table')
      var head = el('tr')
      cols.forEach(function (c) { head.appendChild(el('th', { text: c.label || c.key })) })
      head.appendChild(el('th'))
      tbl.appendChild(el('thead', {}, [head]))
      tblBody = el('tbody')
      tbl.appendChild(tblBody)
      box.appendChild(tbl)
      if (!readOnly) {
        box.appendChild(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-add-row': f.key, text: '＋ ' + (f.addLabel || '新增一列') }))
        box.lastChild.addEventListener('click', function () {
          if (lines.length >= (f.maxRows || 200)) return
          lines.push(blankRow()); renderRows(f); changed()
        })
      }
      box.appendChild(el('div', { class: CLS + 'total' }, [el('span', { text: '合計' }), el('span', { 'data-lines-total': '1', text: '0' })]))
      renderRows(f)
      return box
    }
    function renderRows(f) {
      while (tblBody.firstChild) tblBody.removeChild(tblBody.firstChild)
      lines.forEach(function (row, ri) {
        var tr = el('tr', { 'data-row': ri })
        ;(f.columns || []).forEach(function (c) {
          var td = el('td', { 'data-col': c.key })
          if (c.type === 'formula' || c.key === 'amount' && isNum(row.qty) && isNum(row.unitCost) && hasQtyUnit(f)) {
            td.appendChild(el('div', { class: CLS + 'ro', 'data-calc': c.key, text: formatMoney(lineAmount(row)) }))
          } else if (c.type === 'select' || c.optionsFrom) {
            var s = el('select', { disabled: readOnly })
            s.appendChild(el('option', { value: '', text: '（未選）' }))
            var seen = false
            optionsOf(c).forEach(function (o) {
              var op = el('option', { value: o.value, text: o.label })
              if (String(row[c.key]) === String(o.value)) { op.selected = true; seen = true }
              s.appendChild(op)
            })
            if (!seen && row[c.key]) { var cu = el('option', { value: row[c.key], text: String(row[c.key]) }); cu.selected = true; s.appendChild(cu) }
            s.addEventListener('change', function () { row[c.key] = s.value; changed() })
            td.appendChild(s)
          } else {
            var isN = c.type === 'number'
            var i = el('input', { type: isN ? 'number' : (c.type === 'date' ? 'date' : 'text'), step: isN ? 'any' : null, min: c.min, class: isN ? 'num' : null, disabled: readOnly })
            i.value = row[c.key] === undefined || row[c.key] === null ? '' : row[c.key]
            i.addEventListener('input', function () {
              row[c.key] = isN ? (i.value === '' ? '' : Number(i.value)) : i.value
              refreshCalcs(); changed()
            })
            td.appendChild(i)
          }
          tr.appendChild(td)
        })
        var x = el('td')
        if (!readOnly) {
          var del = el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-remove-row': ri, 'aria-label': '刪除這一列', text: '✕' })
          del.addEventListener('click', function () {
            var min = f.minRows === undefined ? 1 : f.minRows
            if (lines.length <= Math.max(1, min)) return
            lines.splice(ri, 1); renderRows(f); changed()
          })
          x.appendChild(del)
        }
        tr.appendChild(x)
        tblBody.appendChild(tr)
      })
      refreshCalcs()
    }
    function hasQtyUnit(f) {
      var k = {}
      ;(f.columns || []).forEach(function (c) { k[c.key] = 1 })
      return k.qty && k.unitCost
    }
    function refreshCalcs() {
      if (!alive) return
      var rows = tblBody ? tblBody.children : []
      for (var i = 0; i < rows.length && i < lines.length; i++) {
        var c = rows[i].querySelector('[data-calc]')
        if (c) c.textContent = formatMoney(lineAmount(lines[i]))
      }
      var total = totalOf(lines)
      var t = container.querySelector('[data-lines-total]')
      if (t) t.textContent = formatMoney(total)
      Object.keys(inputs).forEach(function (k) {
        if (k.indexOf('__formula_') === 0) inputs[k].textContent = formatMoney(total)
      })
    }

    // ── 版面 ──
    function sections() {
      var g = def.ui && def.ui.form && def.ui.form.groups
      var byKey = {}
      fields.forEach(function (f) { byKey[f.key] = f })
      if (g && g.length) {
        var used = {}
        var out = g.map(function (s) {
          return { title: s.title, fields: (s.fields || []).map(function (k) { used[k] = 1; return byKey[k] }).filter(Boolean) }
        })
        var rest = fields.filter(function (f) { return !used[f.key] })
        if (rest.length) out.push({ title: '其他', fields: rest })
        return out
      }
      return [{ title: '', fields: fields }]
    }

    function render() {
      while (container.firstChild) container.removeChild(container.firstChild)
      inputs = {}
      var root_ = el('div', { class: 'df-root' + (readOnly ? ' df-readonly' : ''), 'data-df-type': def.name || '' })
      sections().forEach(function (s) {
        var sec = el('div', { class: CLS + 'sec' })
        if (s.title) sec.appendChild(el('div', { class: CLS + 'sec__t', text: s.title }))
        var grid = el('div', { class: CLS + 'grid' })
        s.fields.forEach(function (f) { grid.appendChild(renderField(f)) })
        sec.appendChild(grid)
        root_.appendChild(sec)
      })
      container.appendChild(root_)
      refreshCalcs()
    }

    function showErrors(problems) {
      container.querySelectorAll('.is-bad').forEach(function (n) { n.classList.remove('is-bad') })
      container.querySelectorAll('[data-err]').forEach(function (n) { n.textContent = '' })
      problems.forEach(function (p) {
        var key = String(p.path || '').split('.')[0]
        var box = container.querySelector('[data-field="' + key + '"]')
        if (box) {
          box.classList.add('is-bad')
          var e = box.querySelector('[data-err]')
          if (e && !e.textContent) e.textContent = p.message
        }
      })
    }

    var api = {
      getValue: function () {
        var d = clone(data)
        return { data: d, lines: lines.map(stripRow), total: totalOf(lines) }
      },
      setValue: function (v) { init((v && v.data) || {}, (v && v.lines) || []); render() },
      validate: function () {
        var v = api.getValue()
        var problems = validate(def, v.data, v.lines, viewer)
        showErrors(problems)
        return problems
      },
      showProblems: showErrors,
      destroy: function () { alive = false; while (container.firstChild) container.removeChild(container.firstChild) }
    }

    init(opts.values || {}, opts.lines || [])
    render()
    return api
  }

  root.MotrixDefinitionForm = { mount: mount, calc: calc }
})(typeof window !== 'undefined' ? window : this)
