// 會計期間與結帳、期初餘額（總帳 P1；設計 proposal-gl/03-periods-close.md）。
// 所有判斷（能不能結帳、鎖定、期初借貸是否平衡）都在後端；這裡只呈現後端的回答與訊息，不自己推。

function ledgerPeriodsPage() {
  return {
    loaded: false,
    error: '',
    notice: '',
    years: [],
    batches: [],
    log: [],
    role: '',
    newYear: '',
    busy: false,

    // 結帳／重開對話
    dlg: null,            // { kind:'close'|'reopen'|'unlock', period, checklist, reason, accept }
    dlgError: '',

    // 年度結轉與決算（B5）
    cdlg: null,           // { year, status, pv, error, busy, reason, accept, done }

    // 期初餘額
    op: { year: '', date: '', text: '', filename: '', result: null, error: '', busy: false },

    // 總帳申請（會計規定 C 類）：一般財務人員的結帳／重開／年度決算／期初批次先送申請，最高管理者核准後自動執行
    requests: [],

    _initDone: false,
    async init() {
      if (this._initDone) return
      this._initDone = true
      this.role = this._session().role || ''
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
      if (!r.ok) {
        const d = data.detail
        throw new Error(typeof d === 'string' ? d : (r.status === 403 ? '沒有權限執行這個動作' : '操作失敗（' + r.status + '）'))
      }
      return data
    },

    isSuper() { return this.role === 'superadmin' },
    async loadRequests() {
      try { this.requests = (await this._api('GET', '/api/ledger/action-requests')).requests } catch (e) { this.requests = [] }
    },
    canWithdraw(r) { return r.status === '待審核' && r.requested_by === (this._session().username || '') },
    async withdrawReq(r) {
      this.error = ''
      try {
        await this._api({ method: 'POST' }, '/api/ledger/action-requests/' + r.id + '/withdraw')
        await this.loadRequests()
        this.notice = '已撤回申請 ' + r.request_no + '。'
      } catch (e) { this.error = e.message }
    },
    statusLabel(s) { return ({ open: '開放', closed: '已結帳', locked: '已鎖定' })[s] || s },
    fmt(n) { return (n || 0).toLocaleString('zh-TW') },

    async load() {
      this.error = ''
      try {
        const d = await this._api('GET', '/api/ledger/years')
        this.years = d.years
        this.batches = d.batches
        const l = await this._api('GET', '/api/ledger/period-log')
        this.log = (l.log || []).slice(0, 50)
        await this.loadRequests()
        this.loaded = true
      } catch (e) {
        this.error = e.message
        this.loaded = true
      }
    },

    async createYear() {
      this.error = ''
      this.notice = ''
      const y = parseInt(this.newYear, 10)
      if (!y) { this.error = '請輸入年度（西元，例如 2026）'; return }
      this.busy = true
      try {
        await this._api({ method: 'POST' }, '/api/ledger/years', { year: y })
        this.notice = y + ' 年度已建立（12 個期間）'
        this.newYear = ''
        await this.load()
      } catch (e) { this.error = e.message }
      this.busy = false
    },

    async openClose(p) {
      this.dlgError = ''
      try {
        const c = await this._api('GET', '/api/ledger/periods/' + p.id + '/checklist')
        this.dlg = { kind: 'close', period: p, checklist: c, reason: '', accept: false }
      } catch (e) { this.error = e.message }
    },
    openReopen(p) { this.dlgError = ''; this.dlg = { kind: 'reopen', period: p, reason: '' } },
    openUnlock(p) { this.dlgError = ''; this.dlg = { kind: 'unlock', period: p, reason: '' } },
    closeDlg() { this.dlg = null },

    async submitDlg() {
      const d = this.dlg
      if (!d) return
      this.dlgError = ''
      this.notice = ''          // 不留上一個動作的訊息（撤回後再申請時會誤判成新訊息）
      const id = d.period.id
      this.busy = true
      try {
        let r = {}
        if (d.kind === 'close') r = await this._api({ method: 'POST' }, '/api/ledger/periods/' + id + '/close', { accept_warnings: d.accept, reason: d.reason })
        else if (d.kind === 'reopen') r = await this._api({ method: 'POST' }, '/api/ledger/periods/' + id + '/reopen', { reason: d.reason })
        else await this._api({ method: 'POST' }, '/api/ledger/periods/' + id + '/unlock', { reason: d.reason })
        this.dlg = null
        await this.load()
        if (r && r.pending) this.notice = r.message
      } catch (e) { this.dlgError = e.message }
      this.busy = false
    },

    // ── 年度結轉與決算 ─────────────────────────────────────────────
    async openClosing(y) {
      this.error = ''
      try {
        const pv = await this._api('GET', '/api/ledger/years/' + y.year + '/closing/preview')
        this.cdlg = { year: y.year, status: y.status, pv, error: '', busy: false, reason: '', accept: false, done: '' }
      } catch (e) { this.error = e.message }
    },
    closeClosing() { this.cdlg = null },
    async _closingAct(fn) {
      const c = this.cdlg
      c.error = ''
      c.done = ''
      c.busy = true
      try { await fn(c) } catch (e) { c.error = e.message }
      c.busy = false
    },
    async generateClosing(regenerate) {
      await this._closingAct(async c => {
        const r = await this._api({ method: 'POST' }, '/api/ledger/years/' + c.year + '/closing/generate', { regenerate: !!regenerate })
        c.done = '已產生結轉傳票草稿：' + r.vouchers.map(v => v.voucher_no).join('、') + '。請到傳票頁送審、核准、過帳後，再回來決算。'
        c.pv = await this._api('GET', '/api/ledger/years/' + c.year + '/closing/preview')
        await this.load()
      })
    },
    async closeYearAct() {
      await this._closingAct(async c => {
        const r = await this._api({ method: 'POST' }, '/api/ledger/years/' + c.year + '/close', { accept_warnings: c.accept })
        if (r.pending) { c.done = r.message; await this.load(); return }
        c.done = c.year + ' 年度已決算（本期淨利 ' + this.fmt(r.net_income) + '）；四大表已凍結。'
        await this.load()
        c.status = 'closed'
      })
    },
    async reopenYearAct() {
      await this._closingAct(async c => {
        if (!c.reason.trim()) throw new Error('重開年度必須填寫理由。')
        const r = await this._api({ method: 'POST' }, '/api/ledger/years/' + c.year + '/reopen', { reason: c.reason })
        c.done = c.year + ' 年度已重開；作廢結轉傳票 ' + (r.voided.length ? r.voided.join('、') : '（無）') + '。'
        c.pv = await this._api('GET', '/api/ledger/years/' + c.year + '/closing/preview')
        c.status = 'open'
        await this.load()
      })
    },
    async exportStatements(y, fmt) {
      this.error = ''
      try {
        const r = await fetch('/api/ledger/years/' + y.year + '/statements/export' + (fmt === 'pdf' ? '/pdf' : ''), { headers: { Authorization: 'Bearer ' + (this._session().token || '') } })
        if (!r.ok) {
          let d = {}
          try { d = await r.json() } catch (e) { d = {} }
          throw new Error(typeof d.detail === 'string' ? d.detail : '匯出失敗（' + r.status + '）')
        }
        const blob = await r.blob()
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = '財務報表_' + y.year + '年度' + (y.status === 'closed' ? '_決算' : '') + (fmt === 'pdf' ? '.pdf' : '.xlsx')
        a.click()
        URL.revokeObjectURL(a.href)
      } catch (e) { this.error = e.message }
    },

    async lock(p) {
      this.error = ''
      try { await this._api({ method: 'POST' }, '/api/ledger/periods/' + p.id + '/lock'); await this.load() } catch (e) { this.error = e.message }
    },

    // ── 期初餘額 ─────────────────────────────────────────────────
    // 貼上格式：每行「科目代號,借方,貸方」；Excel 直接複製是 Tab 分隔，CSV 是逗號分隔（金額可用雙引號包住千分位，如 "5,000"）。
    // 第一個欄位不是數字開頭的行（標題）略過。
    splitLine(line) {
      if (line.indexOf('\t') >= 0) return line.split('\t').map(s => s.trim())
      const out = []
      let cur = '', q = false
      for (const ch of line) {
        if (ch === '"') q = !q
        else if ((ch === ',' || ch === '，') && !q) { out.push(cur.trim()); cur = '' }
        else cur += ch
      }
      out.push(cur.trim())
      return out
    },
    parseRows() {
      const rows = []
      for (const raw of this.op.text.split(/\r?\n/)) {
        const line = raw.trim()
        if (!line) continue
        const parts = this.splitLine(line)
        if (!/^[0-9]/.test(parts[0])) continue        // 標題列
        rows.push({ account_code: parts[0], debit: parts[1] || '', credit: parts[2] || '' })
      }
      return rows
    },
    async previewOpening() {
      this.op.error = ''
      this.op.result = null
      this.op.busy = true
      try { this.op.result = await this._api({ method: 'POST' }, '/api/ledger/opening/preview', { rows: this.parseRows() }) }
      catch (e) { this.op.error = e.message }
      this.op.busy = false
    },
    async importOpening() {
      this.op.error = ''
      this.notice = ''
      if (!this.op.year || !this.op.date) { this.op.error = '請選年度並填開帳日期'; return }
      this.op.busy = true
      try {
        const r = await this._api({ method: 'POST' }, '/api/ledger/opening', {
          year: parseInt(this.op.year, 10), opening_date: this.op.date, rows: this.parseRows(), filename: this.op.filename,
        })
        this.op.result = null
        this.op.text = ''
        await this.load()
        this.notice = r.pending ? r.message : '已建立期初傳票草稿 ' + r.voucher_no + '；請到傳票頁送審、核准、過帳後才會入帳'
      } catch (e) { this.op.error = e.message }
      this.op.busy = false
    },
    async undoBatch(b) {
      this.error = ''
      try { await this._api({ method: 'POST' }, '/api/ledger/opening/' + b.id + '/undo'); await this.load() } catch (e) { this.error = e.message }
    },
    batchLabel(b) {
      if (b.undone_at) return '已撤銷'
      return b.voucher_status || '—'
    },
    actionLabel(a) {
      return ({ create: '建立年度', close: '結帳', reopen: '重開', lock: '鎖定', unlock: '解鎖', closing_generate: '產生結轉傳票', year_close: '年度決算', year_reopen: '年度重開', opening_import: '匯入期初', opening_undo: '撤銷期初' })[a] || a
    },
  }
}
