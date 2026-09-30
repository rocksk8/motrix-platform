// 報表設定（總帳 B1）：科目的報表歸屬與現金流量分類、報表列名稱／排序／停用、設定完整性檢查。
// 判斷（驗證、能不能停用）都在後端；這裡只呈現後端的回答與訊息。

function ledgerSettingsPage() {
  return {
    loaded: false,
    error: '',
    notice: '',
    accounts: [],
    lines: [],
    classes: [],
    check: null,
    q: '',
    onlyProblems: false,
    tab: 'accounts',
    saving: '',
    canWrite: false,

    _initDone: false,
    async init() {
      if (this._initDone) return
      this._initDone = true
      const s = this._session()
      this.canWrite = s.role === 'superadmin' || (s.modules || []).indexOf('finance') >= 0
      await this.load()
    },

    _session() {
      try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) { return {} }
    },
    async _api(verb, path, body) {
      const method = typeof verb === 'string' ? verb : verb.method
      const opt = { method, headers: { Authorization: 'Bearer ' + (this._session().token || ''), 'Content-Type': 'application/json' } }
      if (body !== undefined) opt.body = JSON.stringify(body)
      const r = await fetch(path, opt)
      let data = {}
      try { data = await r.json() } catch (e) { data = {} }
      if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (r.status === 403 ? '沒有權限執行這個動作' : '操作失敗（' + r.status + '）'))
      return data
    },

    async load() {
      this.error = ''
      try {
        const [a, f, c] = await Promise.all([
          this._api('GET', '/api/ledger/accounts?only_postable=true'),
          this._api('GET', '/api/ledger/fs-lines'),
          this._api('GET', '/api/ledger/setup-check'),
        ])
        this.accounts = a.accounts
        this.lines = f.lines
        this.classes = f.cashflow_classes
        this.check = c
      } catch (e) { this.error = e.message }
      this.loaded = true
    },

    classLabel(c) { return ({ cash: '現金及約當現金', operating: '營業活動', investing: '投資活動', financing: '籌資活動' })[c] || '（未分類）' },
    isBs(a) { return a.acct_type === 'asset' || a.acct_type === 'liability' || a.acct_type === 'equity' },
    typeLabel(t) {
      return ({ asset: '資產', liability: '負債', equity: '權益', revenue: '收入', cost: '成本', expense: '費用', other_income: '營業外收益',
        other_expense: '營業外費損', tax: '稅', oci: '其他綜合損益', summary: '彙總' })[t] || t
    },
    problem(a) {
      if (a.acct_type === 'summary') return false          // 彙總列（例：本期稅後淨利）不出現在科目歸屬，與後端守門一致
      return !a.fs_line || (this.isBs(a) && !a.cashflow_class)
    },
    get shown() {
      const q = this.q.trim()
      let rows = this.accounts.filter(a => (!q || a.code.indexOf(q) === 0 || (a.display_name || a.name).indexOf(q) >= 0) && (!this.onlyProblems || this.problem(a)))
      return rows.slice(0, 300)
    },
    get matchCount() {
      const q = this.q.trim()
      return this.accounts.filter(a => (!q || a.code.indexOf(q) === 0 || (a.display_name || a.name).indexOf(q) >= 0) && (!this.onlyProblems || this.problem(a))).length
    },
    linesOf(stmt) { return this.lines.filter(l => l.statement === stmt) },
    lineLabel(code) { const l = this.lines.find(x => x.code === code); return l ? l.label : code },

    async saveAccount(a, field, value) {
      this.error = ''
      this.notice = ''
      this.saving = a.code + field
      try {
        const body = {}
        body[field] = value
        await this._api({ method: 'PATCH' }, '/api/ledger/accounts/' + encodeURIComponent(a.code), body)
        a[field] = value
        this.notice = a.code + ' 已更新'
        this.check = await this._api('GET', '/api/ledger/setup-check')
      } catch (e) {
        this.error = e.message
        await this.load()
      }
      this.saving = ''
    },
    async saveLine(l, field, value) {
      this.error = ''
      this.notice = ''
      this.saving = l.code + field
      try {
        const body = {}
        body[field] = value
        await this._api({ method: 'PATCH' }, '/api/ledger/fs-lines/' + encodeURIComponent(l.code), body)
        l[field] = value
        this.notice = l.code + ' 已更新'
        this.check = await this._api('GET', '/api/ledger/setup-check')
      } catch (e) {
        this.error = e.message
        await this.load()
      }
      this.saving = ''
    },
  }
}
