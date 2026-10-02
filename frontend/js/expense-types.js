/* expense-types.js — 請款類型定義編輯頁 v1（A2-2 的編輯畫面；超級管理員）
 * 契約：docs／plan-expense-a2.md §8。沿用既有定義庫路由 /api/definitions/expense_type[/{key}/…]，不新增編輯端點；
 * 伺服器端驗證為準（POST …/validate 回 problems），前端只把 [{path,message}] 列出來。
 * 工作副本是 clone 出來的：本頁不認得的鍵（例如 output.template）原樣保留、存回去。 */
function expenseTypesPage() {
  var KIND = 'expense_type'
  var KEY_RE = /^[a-z][a-z0-9_]{0,39}$/
  var FIELD_TYPES = [['text', '單行文字'], ['textarea', '多行文字'], ['number', '數字'], ['date', '日期'], ['daterange', '日期區間'],
                     ['select', '下拉'], ['radio', '單選'], ['ref', '參照'], ['formula', '公式'], ['file', '附件']]
  var COL_TYPES = [['text', '文字'], ['number', '數字'], ['date', '日期'], ['select', '下拉'], ['formula', '公式']]
  // 平台保留欄位（§7.2）：型別固定，從這裡加才不會打錯
  var RESERVED = {
    applicant: { key: 'applicant', label: '申請人', type: 'ref', target: 'users', locked: true, default: { $: 'requester' } },
    dept: { key: 'dept', label: '部門', type: 'ref', target: 'departments' },
    cost_dept: { key: 'cost_dept', label: '費用歸屬部門', type: 'ref', target: 'departments' },
    req_date: { key: 'req_date', label: '填表日期', type: 'date', default: { $: 'today' } },
    pay_date: { key: 'pay_date', label: '支付日期', type: 'date' },
    urgency: { key: 'urgency', label: '急迫性', type: 'select', options: ['一般', '急件', '特急'] },
    pay_terms: { key: 'pay_terms', label: '付款條件', type: 'text', editableBy: 'cashier' },
    remit_date: { key: 'remit_date', label: '匯款日', type: 'date', editableBy: 'cashier' }
  }
  var LINE_COLS = {
    category: { key: 'category', label: '費用類別', type: 'select', optionsFrom: 'expense_categories', required: true },
    summary: { key: 'summary', label: '摘要', type: 'text', required: true },
    qty: { key: 'qty', label: '數量', type: 'number' },
    unitCost: { key: 'unitCost', label: '單價', type: 'number' },
    amount: { key: 'amount', label: '金額', type: 'number', required: true },
    invoiceNo: { key: 'invoiceNo', label: '發票號碼', type: 'text' }
  }
  function clone(x) { return JSON.parse(JSON.stringify(x === undefined ? null : x)) }
  function newBody() {
    return {
      name: '', numbering: { prefix: '' }, payable: true, docType: '', enabled: true,
      fields: [clone(RESERVED.applicant), clone(RESERVED.req_date),
        { key: 'lines', label: '明細', type: 'table', minRows: 1, columns: [clone(LINE_COLS.category), clone(LINE_COLS.summary), clone(LINE_COLS.amount)] }],
      ui: { form: { groups: [] }, list: { columns: [] } }
    }
  }
  var page = {
    FIELD_TYPES: FIELD_TYPES, COL_TYPES: COL_TYPES,
    view: 'list', rows: [], docTypes: [], loading: true,
    key: '', isNew: false, newKey: '', body: null, meta: null,
    problems: [], msg: '', err: '', busy: false, note: '', changes: null, _initDone: false, _prev: null,

    _hdr: function () {
      var s = {}
      try { s = JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) {}
      return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (s.token || '') }
    },
    async _call(method, url, payload) {
      var r = await fetch(url, { method: method, headers: this._hdr(), body: payload === undefined ? undefined : JSON.stringify(payload) })
      var d = await r.json().catch(function () { return null })
      return { ok: r.ok, status: r.status, data: d }
    },
    _fail: function (res, fallback) {
      var d = res.data || {}
      this.problems = Array.isArray(d.problems) ? d.problems : []
      this.err = (d.detail ? String(d.detail) : (fallback + '（' + res.status + '）'))
    },
    async init() {
      // Alpine 3 會自動呼叫資料物件的 init()，<body> 又寫 x-init="init()" ⇒ 不守衛會跑兩遍（重複打 API）
      if (this._initDone) return
      this._initDone = true
      if (this.fdInitSwitch) this.fdInitSwitch()
      try {
        var t = await this._call('GET', '/api/settings/approval-doc-types')
        if (t.ok) this.docTypes = (t.data && t.data.docTypes) || []
      } catch (e) { /* 下拉沒有資料時仍可手填 docType */ }
      await this.loadList()
      var k = new URLSearchParams(location.search).get('key')
      if (k) await this.open(k)
    },
    async loadList() {
      this.loading = true
      try {
        var r = await this._call('GET', '/api/definitions/' + KIND)
        if (!r.ok) { this._fail(r, '讀取失敗'); this.rows = []; return }
        var rows = r.data || []
        var self = this
        // 清單要顯示名稱／前綴／payable／啟用：逐筆讀（類型只有個位數）
        await Promise.all(rows.map(async function (row) {
          var g = await self._call('GET', '/api/definitions/' + KIND + '/' + encodeURIComponent(row.key))
          var b = g.ok && g.data ? ((g.data.draft || g.data.latest || {}).body || {}) : {}
          row.name = b.name || ''
          row.prefix = (b.numbering || {}).prefix || ''
          row.payable = b.payable
          row.enabled = b.enabled !== false
        }))
        // 程式預設的四個類型在定義庫裡沒有列（還沒人改過）⇒ 併入清單，否則「改預設類型」無從開始
        var t = await this._call('GET', '/api/expense-types')
        if (t.ok && Array.isArray(t.data)) {
          var have = {}
          rows.forEach(function (x) { have[x.key] = true })
          t.data.forEach(function (x) {
            if (!have[x.code]) rows.push({ key: x.code, name: x.name, prefix: x.prefix, payable: x.payable, enabled: true,
                                           latestVersion: 0, hasDraft: false, isDefault: true })
          })
        }
        this.err = ''
        this.rows = rows
      } catch (e) { this.err = '網路連線失敗，請重新整理' } finally { this.loading = false }
    },
    startNew() {
      this.msg = ''; this.err = ''; this.problems = []; this.changes = null
      this.isNew = true; this.newKey = ''; this.key = ''; this.meta = { versions: [] }; this.body = newBody(); this.view = 'edit'
      if (this.fdMount) this.fdMount()
    },
    async open(key) {
      this.msg = ''; this.err = ''; this.problems = []; this.changes = null
      var r = await this._call('GET', '/api/definitions/' + KIND + '/' + encodeURIComponent(key))
      if (!r.ok) { this._fail(r, '讀取失敗'); return }
      this.meta = r.data
      var src = (r.data.draft || r.data.latest || {}).body
      if (!src) {                                   // 庫裡沒有（程式預設還沒人改）⇒ 以目前生效的預設當起點，不要開空白
        var cur = await this._call('GET', '/api/expense-types/' + encodeURIComponent(key))
        if (cur.ok && cur.data && cur.data.definition) src = cur.data.definition
      }
      this.isNew = false; this.key = key
      this.body = src ? clone(src) : newBody()
      if (!this.body.fields) this.body.fields = []
      if (!this.body.numbering) this.body.numbering = { prefix: '' }
      this.view = 'edit'
      if (this.fdMount) this.fdMount()
    },
    back() { if (this.fdDestroy) this.fdDestroy(); this.view = 'list'; this.body = null; this.loadList() },

    // ── 欄位（fields／lines.columns 共用一組操作；arr 是工作副本裡的陣列本身）
    get linesField() {
      return (this.body.fields || []).find(function (f) { return f.key === 'lines' && f.type === 'table' }) || null
    },
    get plainFields() { return (this.body.fields || []).filter(function (f) { return !(f.key === 'lines' && f.type === 'table') }) },
    get fieldKeys() { return this.plainFields.map(function (f) { return f.key }).filter(Boolean) },
    addField: function (arr, tpl) { arr.push(tpl) },
    addBlank: function () { this.body.fields.splice(this.body.fields.length - (this.linesField ? 1 : 0), 0, { key: '', label: '', type: 'text' }) },
    addReserved: function (k) {
      if (!k || !RESERVED[k] || this.fieldKeys.indexOf(k) >= 0) return
      this.body.fields.splice(this.body.fields.length - (this.linesField ? 1 : 0), 0, clone(RESERVED[k]))
    },
    reservedMissing: function () { var have = this.fieldKeys; return Object.keys(RESERVED).filter(function (k) { return have.indexOf(k) < 0 }) },
    reservedLabel: function (k) { return RESERVED[k].label + '（' + k + '）' },
    addLinesField: function () {
      this.body.fields.push({ key: 'lines', label: '明細', type: 'table', minRows: 1, columns: [clone(LINE_COLS.category), clone(LINE_COLS.summary), clone(LINE_COLS.amount)] })
    },
    addCol: function (k) {
      var f = this.linesField
      if (!f) return
      if (k === '_blank') f.columns.push({ key: '', label: '', type: 'text' })
      else if (LINE_COLS[k] && !f.columns.some(function (c) { return c.key === k })) f.columns.push(clone(LINE_COLS[k]))
    },
    colsMissing: function () {
      var f = this.linesField, have = f ? f.columns.map(function (c) { return c.key }) : []
      return Object.keys(LINE_COLS).filter(function (k) { return have.indexOf(k) < 0 })
    },
    colLabel: function (k) { return LINE_COLS[k].label + '（' + k + '）' },
    remove: function (arr, f) { var i = arr.indexOf(f); if (i >= 0) arr.splice(i, 1) },
    move: function (arr, f, d) {
      var i = arr.indexOf(f), j = i + d
      if (i < 0 || j < 0 || j >= arr.length) return
      // 明細表欄位固定排在最後（契約：lines 必含；版面靠 ui.form.groups，不靠陣列順序）
      if ((arr[j].key === 'lines' && arr[j].type === 'table') || (f.key === 'lines' && f.type === 'table')) return
      arr.splice(i, 1); arr.splice(j, 0, f)
    },
    optionsText: function (f) { return (f.options || []).join('\n') },
    setOptions: function (f, txt) { f.options = String(txt || '').split('\n').map(function (s) { return s.trim() }).filter(Boolean) },
    defaultKind: function (f) { var d = f.default; return d && typeof d === 'object' ? d.$ : (d === undefined || d === null || d === '' ? '' : 'value') },
    setDefaultKind: function (f, k) {
      if (!k) delete f.default
      else if (k === 'value') f.default = ''
      else f.default = { $: k }
    },
    defaultValue: function (f) { return (f.default !== undefined && typeof f.default !== 'object') ? f.default : '' },
    setDefaultValue: function (f, v) { f.default = v },
    setCashier: function (f, on) { if (on) f.editableBy = 'cashier'; else delete f.editableBy },
    setType: function (f, t) {
      f.type = t
      if (t === 'ref' && !f.target) f.target = 'users'
      if (t !== 'ref') delete f.target
      if (['select', 'radio'].indexOf(t) < 0) delete f.options
      if (t !== 'formula') delete f.formula
    },
    setOptionsFrom: function (c, on) { if (on) { c.optionsFrom = 'expense_categories'; delete c.options } else delete c.optionsFrom },

    // ── 版面（ui.form.groups／ui.list.columns）
    get groups() { this.body.ui = this.body.ui || {}; this.body.ui.form = this.body.ui.form || {}; this.body.ui.form.groups = this.body.ui.form.groups || []; return this.body.ui.form.groups },
    get listCols() { this.body.ui = this.body.ui || {}; this.body.ui.list = this.body.ui.list || {}; this.body.ui.list.columns = this.body.ui.list.columns || []; return this.body.ui.list.columns },
    addGroup: function () { this.groups.push({ title: '', fields: [] }) },
    autoGroup: function () { this.body.ui.form.groups = [{ title: '基本資料', fields: this.fieldKeys.slice() }] },
    inGroup: function (g, k) { return (g.fields || []).indexOf(k) >= 0 },
    toggleIn: function (arr, k) { var i = arr.indexOf(k); if (i >= 0) arr.splice(i, 1); else arr.push(k) },
    inList: function (k) { return this.listCols.indexOf(k) >= 0 },

    // ── 驗證／存檔／發布（伺服器為準）
    pathLabel: function (p) {
      var self = this
      return String(p || '（整份）').replace(/fields\[(\d+)\]/, function (m, i) {
        var f = (self.body.fields || [])[+i]
        return '欄位「' + ((f && (f.label || f.key)) || ('#' + (+i + 1))) + '」'
      }).replace(/columns\[(\d+)\]/, function (m, i) {
        var lf = self.linesField, c = lf && lf.columns[+i]
        return '明細欄「' + ((c && (c.label || c.key)) || ('#' + (+i + 1))) + '」'
      })
    },
    _keyOk: function () {
      if (!this.isNew) return true
      if (!KEY_RE.test(this.newKey)) { this.err = '類型代碼只能用小寫英文、數字與底線，英文開頭（例：purchase_req）'; return false }
      if (this.rows.some(function (r) { return r.key === this.newKey }, this)) { this.err = '這個類型代碼已經有了'; return false }
      return true
    },
    _k: function () { return this.isNew ? this.newKey : this.key },
    async validate() {
      this.err = ''; this.msg = ''
      if (!this._keyOk()) return false
      var r = await this._call('POST', '/api/definitions/' + KIND + '/' + encodeURIComponent(this._k()) + '/validate', { body: this.body })
      if (!r.ok) { this._fail(r, '驗證失敗'); return false }
      this.problems = ((r.data || {}).problems || []).map(function (p) { return typeof p === 'string' ? { path: '', message: p } : p })
      this.msg = this.problems.length ? '' : '驗證通過'
      return this.problems.length === 0
    },
    async saveDraft() {
      if (this.busy) return
      this.err = ''; this.msg = ''
      if (!this._keyOk()) return
      this.busy = true
      try {
        var r = await this._call('PUT', '/api/definitions/' + KIND + '/' + encodeURIComponent(this._k()) + '/draft', { body: this.body })
        if (!r.ok) { this._fail(r, '儲存失敗'); return }
        this.problems = ((r.data || {}).problems || []).map(function (p) { return typeof p === 'string' ? { path: '', message: p } : p })
        var k = this._k()
        await this.open(k)
        this.msg = '草稿已儲存' + (this.problems.length ? '（還有 ' + this.problems.length + ' 項待修，見下方）' : '')
      } catch (e) { this.err = '網路連線失敗，請確認後再按一次' } finally { this.busy = false }
    },
    async publish() {
      if (this.busy) return
      this.err = ''; this.msg = ''
      if (!this._keyOk()) return
      this.busy = true
      try {
        var k = this._k()
        var s = await this._call('PUT', '/api/definitions/' + KIND + '/' + encodeURIComponent(k) + '/draft', { body: this.body })
        if (!s.ok) { this._fail(s, '儲存失敗'); return }
        var r = await this._call('POST', '/api/definitions/' + KIND + '/' + encodeURIComponent(k) + '/publish', { note: this.note })
        if (!r.ok) { this._fail(r, '發布失敗'); return }
        this.note = ''
        await this.open(k)
        this.problems = []
        this.msg = '已發布第 ' + r.data.version + ' 版'
      } catch (e) { this.err = '網路連線失敗，請確認後再按一次' } finally { this.busy = false }
    },
    async discardDraft() {
      if (this.busy || this.isNew) return
      this.busy = true
      try {
        var r = await this._call('DELETE', '/api/definitions/' + KIND + '/' + encodeURIComponent(this.key) + '/draft')
        if (!r.ok) { this._fail(r, '刪除草稿失敗'); return }
        if (this.meta && this.meta.latest) { var k = this.key; await this.open(k); this.msg = '草稿已丟棄，回到已發布版' } else this.back()
      } finally { this.busy = false }
    },
    async showChanges() {
      this.err = ''
      var r = await this._call('GET', '/api/definitions/' + KIND + '/' + encodeURIComponent(this.key) + '/diff?a=latest&b=draft')
      if (!r.ok) { this._fail(r, '讀取差異失敗'); return }
      this.changes = r.data.changes || []
    },
    async restore(v) {
      if (this.busy) return
      this.busy = true; this.err = ''
      try {
        var r = await this._call('POST', '/api/definitions/' + KIND + '/' + encodeURIComponent(this.key) + '/restore/' + v, { note: '還原第 ' + v + ' 版' })
        if (!r.ok) { this._fail(r, '還原失敗'); return }
        var k = this.key
        await this.open(k)
        this.msg = '已把第 ' + v + ' 版還原為第 ' + r.data.version + ' 版'
      } finally { this.busy = false }
    },
    get hasDraft() { return !!(this.meta && this.meta.draft) },
    statusLabel: function (r) { return (r.latestVersion ? 'v' + r.latestVersion : (r.isDefault ? '程式預設（草稿欄位待確認）' : '未發布')) + (r.hasDraft ? '（有草稿）' : '') },

    // ── 預覽：與建構器同一個元件（執行頁本身當預覽）
    showPreview() {
      var el = document.getElementById('et-preview')
      if (!el || !window.MotrixFormPreview) { this.err = '預覽元件載入失敗'; return }
      var draft = clone(this.body)
      if (this._prev) { try { this._prev.update(draft); return } catch (e) { /* 重建 */ } }
      el.innerHTML = ''
      this._prev = window.MotrixFormPreview.render(el, draft, { mode: 'form' })
    },
    async refreshPreview() { if (this._prev) this.showPreview() }
  }
  // 設計器轉接層的屬性／方法併進來（用描述子複製：本物件有 getter，Object.assign 會在 body 還是 null 時就去算它）
  if (window.ExpenseTypesDesigner) Object.defineProperties(page, Object.getOwnPropertyDescriptors(window.ExpenseTypesDesigner()))
  return page
}
