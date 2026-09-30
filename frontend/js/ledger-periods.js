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

    // 期初餘額
    op: { year: '', date: '', text: '', filename: '', result: null, error: '', busy: false },

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
    async _api(method, path, body) {
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
        await this._api('POST', '/api/ledger/years', { year: y })
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
      const id = d.period.id
      this.busy = true
      try {
        if (d.kind === 'close') await this._api('POST', '/api/ledger/periods/' + id + '/close', { accept_warnings: d.accept, reason: d.reason })
        else if (d.kind === 'reopen') await this._api('POST', '/api/ledger/periods/' + id + '/reopen', { reason: d.reason })
        else await this._api('POST', '/api/ledger/periods/' + id + '/unlock', { reason: d.reason })
        this.dlg = null
        await this.load()
      } catch (e) { this.dlgError = e.message }
      this.busy = false
    },

    async lock(p) {
      this.error = ''
      try { await this._api('POST', '/api/ledger/periods/' + p.id + '/lock'); await this.load() } catch (e) { this.error = e.message }
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
      try { this.op.result = await this._api('POST', '/api/ledger/opening/preview', { rows: this.parseRows() }) }
      catch (e) { this.op.error = e.message }
      this.op.busy = false
    },
    async importOpening() {
      this.op.error = ''
      this.notice = ''
      if (!this.op.year || !this.op.date) { this.op.error = '請選年度並填開帳日期'; return }
      this.op.busy = true
      try {
        const r = await this._api('POST', '/api/ledger/opening', {
          year: parseInt(this.op.year, 10), opening_date: this.op.date, rows: this.parseRows(), filename: this.op.filename,
        })
        this.notice = '已建立期初傳票草稿 ' + r.voucher_no + '；請到傳票頁送審、核准、過帳後才會入帳'
        this.op.result = null
        this.op.text = ''
        await this.load()
      } catch (e) { this.op.error = e.message }
      this.op.busy = false
    },
    async undoBatch(b) {
      this.error = ''
      try { await this._api('POST', '/api/ledger/opening/' + b.id + '/undo'); await this.load() } catch (e) { this.error = e.message }
    },
    batchLabel(b) {
      if (b.undone_at) return '已撤銷'
      return b.voucher_status || '—'
    },
    actionLabel(a) {
      return ({ create: '建立年度', close: '結帳', reopen: '重開', lock: '鎖定', unlock: '解鎖', opening_import: '匯入期初', opening_undo: '撤銷期初' })[a] || a
    },
  }
}
