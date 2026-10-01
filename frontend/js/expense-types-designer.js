// expense-types-designer.js — 請款類型編輯頁接上共用「表單設計器」（static/form-designer.js）的轉接層。
// 設計器只改 fields／ui（欄位與版面）；類型設定（名稱、單號前綴、docType、payable、enabled）、驗證、存草稿、差異、版本、發布仍是本頁外框。
// 本頁不認得的鍵（例如 output.template）原樣保留：設計器的 getDef() 本來就保留未知鍵，這裡只把 fields／ui 寫回工作副本。
// 開關：預設用舊的表格式編輯（使用者預覽裁示前不換）；網址 ?designer=1 或 localStorage.et_designer='1' ⇒ 新版設計器；?designer=0 強制舊版。
(function () {
  var RESERVED_TYPES = { applicant: 'ref', dept: 'ref', cost_dept: 'ref', req_date: 'date', pay_date: 'date', urgency: 'select', pay_terms: 'text', remit_date: 'date' }
  var FIXED_KEYS = Object.assign({ lines: 'table' }, RESERVED_TYPES)         // lines 也要確認才能刪（驗證器要求恰好一個）
  var URGENCY = ['一般', '急件', '特急']
  var CASHIER_KEYS = ['pay_terms', 'remit_date', 'pay_date']
  // 與伺服器同一份判準（helpers/expense_types._BANK_RE），但伺服器放行系統自己寫的科目快照 accountCode ⇒ 這裡也放行
  var BANNED = /bank|iban|swift|帳號|帳戶|銀行|戶名|account(?!code)/i
  var ALLOWED_TYPES = ['text', 'textarea', 'number', 'date', 'daterange', 'select', 'radio', 'ref', 'formula', 'file', 'table']
  // 請款常用欄位（型別固定；從這裡加才不會打錯）：{label, desc, icon, field}
  var PRESETS = [
    ['applicant', '申請人', '填單的人，自動帶入本人', 'user', { label: '申請人', type: 'ref', target: 'users', locked: true, default: { $: 'requester' } }],
    ['dept', '部門', '申請人所屬部門', 'dept', { label: '部門', type: 'ref', target: 'departments' }],
    ['cost_dept', '費用歸屬部門', '這筆錢算在哪個部門', 'dept', { label: '費用歸屬部門', type: 'ref', target: 'departments' }],
    ['req_date', '填表日期', '預設今天', 'cal', { label: '填表日期', type: 'date', default: { $: 'today' } }],
    ['pay_date', '支付日期', '只有出納能填', 'cal', { label: '支付日期', type: 'date', editableBy: 'cashier' }],
    ['urgency', '急迫性', '一般／急件／特急', 'select', { label: '急迫性', type: 'select', options: URGENCY.slice() }],
    ['pay_terms', '付款條件', '只有出納能填', 'text', { label: '付款條件', type: 'text', editableBy: 'cashier' }],
    ['remit_date', '匯款日', '只有出納能填', 'cal', { label: '匯款日', type: 'date', editableBy: 'cashier' }]
  ]

  function clone(x) { return JSON.parse(JSON.stringify(x === undefined ? null : x)) }

  window.ExpenseTypesDesigner = function () {
    return {
      useFD: false, _fd: null, fdCatalog: null, fdSources: [], _fdBusy: false,

      fdInitSwitch: function () {
        try {
          var q = new URLSearchParams(location.search).get('designer')
          this.useFD = q === '1' ? true : (q === '0' ? false : localStorage.getItem('et_designer') === '1')
        } catch (e) {}
        var self = this
        this.$watch('problems', function () { self.fdSyncProblems() })
        this._call('GET', '/api/custom-modules/catalog').then(function (r) { if (r.ok) self.fdCatalog = r.data }).catch(function () {})
        this._call('GET', '/api/platform/prefill-sources').then(function (r) {
          self.fdSources = r.ok && Array.isArray(r.data) ? r.data : []
          if (self._fd) self._fd.caps.prefillSources = self.fdSources
        }).catch(function () {})
      },
      toggleFD: function () {
        this.useFD = !this.useFD
        try { localStorage.setItem('et_designer', this.useFD ? '1' : '0') } catch (e) {}
        if (this.useFD) this.fdMount(); else this.fdDestroy()
      },
      fdCaps: function () {
        var cat = this.fdCatalog || {}
        var els = (cat.fieldElements || []).filter(function (e) {
          return ALLOWED_TYPES.indexOf(e.type) >= 0 && !(e.preset && e.preset.multiple)
        })
        var published = ((this.meta && this.meta.latest && this.meta.latest.body && this.meta.latest.body.fields) || []).map(function (f) { return f.key })
        return {
          elements: els, specs: cat.fieldTypeSpecs || {}, prefillSources: this.fdSources, hasCase: false, isSuper: true,
          fixedTypeKeys: FIXED_KEYS, onlyOneTable: 'lines', requiredColumns: ['category', 'summary', 'amount'], pairColumns: ['qty', 'unitCost'],
          cashierKeys: CASHIER_KEYS, bannedWords: BANNED, maxRows: 200, publishedKeys: published, titleFallback: '（未命名的請款單）',
          columnPresets: [
            { label: '數量＋單價', desc: '金額由「數量×單價」自動算出', cols: [{ key: 'qty', label: '數量', type: 'number' }, { key: 'unitCost', label: '單價', type: 'number' }] },
            { label: '發票號碼', desc: '每一列可填發票號碼', cols: [{ key: 'invoiceNo', label: '發票號碼', type: 'text' }] }
          ],
          extraPalette: [{ title: '請款常用欄位', items: PRESETS.map(function (p) { return { id: p[0], label: p[1], desc: p[2], icon: p[3], field: Object.assign({ key: p[0] }, clone(p[4])) } }) }]
        }
      },
      fdProblems: function () {
        return (this.problems || []).filter(function (p) { return /^(fields|ui)/.test(String(p.path || '')) }).map(function (p) { return { path: p.path, message: p.message } })
      },
      // 點問題清單的一列 ⇒ 設計器選到那個欄位（path 是 fields[i]／fields[i].columns[j]…；對照表由設計器依最近一次輸出維護）
      fdFocus: function (p) {
        if (!this._fd || !this.useFD || !p) return
        var k = this._fd.keyOfPath(p.path)
        if (k) this._fd.focus(k)
      },
      fdSyncProblems: function () { if (this._fd) this._fd.setProblems(this.fdProblems()) },
      fdDestroy: function () { if (this._fd) { try { this._fd.destroy() } catch (e) {} this._fd = null } },
      // 開啟／新增類型後呼叫：x-if 會重建主機元素 ⇒ 每次都重建設計器
      fdMount: function () {
        var self = this
        if (!this.useFD || !this.body) return
        this.$nextTick(function () {
          var host = document.getElementById('et-fd-host')
          if (!host || !window.FormDesigner) return
          self.fdDestroy()
          self._fd = window.FormDesigner.init(host, { def: clone(self.body), caps: self.fdCaps(), onChange: function (d) { self.fdChanged(d) } })
          self._fd.setProblems(self.fdProblems())
        })
      },
      fdChanged: function (d) {
        if (!this.body || this._fdBusy) return
        var fields = clone(d.fields || [])
        // 急迫性的選項固定（設計器不強制）：被改掉就改回去並讓設計器重載
        var fixed = false
        fields.forEach(function (f) {
          if (f.key === 'urgency' && f.type === 'select' && JSON.stringify(f.options || []) !== JSON.stringify(URGENCY)) { f.options = URGENCY.slice(); fixed = true }
        })
        this.body.fields = fields
        this.body.ui = Object.assign({}, this.body.ui || {}, clone(d.ui || {}))
        if (fixed && this._fd) {
          var self = this
          this._fdBusy = true
          try { this._fd.setDef(clone(this.body)) } finally { this._fdBusy = false }
          this.msg = '急迫性的選項是固定的（一般、急件、特急），已改回。'
          self.fdSyncProblems()
        }
      }
    }
  }
})()
