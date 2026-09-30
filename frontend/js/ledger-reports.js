// 帳簿報表（總帳 P1：試算表、總分類帳、明細分類帳、序時帳簿；設計 proposal-gl/04-reports.md）。
// 數字全由後端算；這裡只負責篩選條件、呈現、逐層點入（試算表→總分類帳）與匯出目前這張表為 CSV。

function ledgerReportsPage() {
  const today = new Date()
  const pad = n => String(n).padStart(2, '0')
  const first = today.getFullYear() + '-' + pad(today.getMonth() + 1) + '-01'
  const last = today.getFullYear() + '-' + pad(today.getMonth() + 1) + '-' + pad(new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate())
  return {
    tab: 'tb',
    start: first,
    end: last,
    drafts: false,
    account: '',
    dimension: 'party_key',
    accounts: [],
    loading: false,
    error: '',
    tb: null,
    gl: null,
    sub: null,
    jr: null,

    _initDone: false,
    async init() {
      if (this._initDone) return
      this._initDone = true
      try {
        const d = await this._api('/api/ledger/accounts?only_postable=true')
        this.accounts = d.accounts
      } catch (e) { this.error = e.message }
      await this.run()
    },

    _token() {
      try { return JSON.parse(localStorage.getItem('motrix_session') || '{}').token || '' } catch (e) { return '' }
    },
    async _api(path) {
      const r = await fetch(path, { headers: { Authorization: 'Bearer ' + this._token() } })
      let data = {}
      try { data = await r.json() } catch (e) { data = {} }
      if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (r.status === 403 ? '沒有權限查看總帳' : '查詢失敗（' + r.status + '）'))
      return data
    },
    fmt(n) { return (n || 0).toLocaleString('zh-TW') },
    dash(n) { return n ? (n).toLocaleString('zh-TW') : '' },
    q() { return 'start=' + this.start + '&end=' + this.end + '&include_drafts=' + this.drafts },
    setTab(t) { this.tab = t; this.run() },

    // 連續查詢時，較晚發出的請求以它的回應為準：舊請求晚到的回應一律丟掉（否則使用者看到的是上一個條件的數字）。
    _seq: 0,
    async run() {
      const seq = ++this._seq
      this.error = ''
      if (this.start && this.end && this.start > this.end) { this.error = '起日不可晚於迄日。'; return }   // 使用者改到一半的日期不送出（後端也會擋，但不必多打一個 400）
      this.loading = true
      try {
        if (this.tab === 'tb') {
          const r = await this._api('/api/ledger/trial-balance?' + this.q())
          if (seq !== this._seq) return
          this.tb = r
        } else if (this.tab === 'gl') {
          if (!this.account) { this.gl = null; this.loading = false; return }
          const r = await this._api('/api/ledger/general-ledger?account=' + encodeURIComponent(this.account) + '&' + this.q())
          if (seq !== this._seq) return
          this.gl = r
        } else if (this.tab === 'sub') {
          if (!this.account) { this.sub = null; this.loading = false; return }
          const r = await this._api('/api/ledger/subledger?account=' + encodeURIComponent(this.account) + '&dimension=' + this.dimension + '&' + this.q())
          if (seq !== this._seq) return
          this.sub = r
        } else {
          const r = await this._api('/api/ledger/journal?' + this.q())
          if (seq !== this._seq) return
          this.jr = r
        }
      } catch (e) {
        if (seq !== this._seq) return
        this.error = e.message
        this.tb = this.tab === 'tb' ? null : this.tb
      }
      this.loading = false
    },
    openLedger(code) { if (!code) return; this.account = code; this.setTab('gl') },
    dimLabel(d) { return ({ party_key: '交易對象', case_no: '案件', doc_no: '單據號', counterparty: '往來（自由文字）' })[d] || d },

    exportCsv() {
      let rows = []
      if (this.tab === 'tb' && this.tb) {
        rows.push(['科目', '名稱', '期初借', '期初貸', '本期借', '本期貸', '期末借', '期末貸'])
        for (const r of this.tb.rows) rows.push([r.code, r.name, r.opening_debit, r.opening_credit, r.period_debit, r.period_credit, r.closing_debit, r.closing_credit])
        const t = this.tb.totals
        rows.push(['合計', '', t.opening_debit, t.opening_credit, t.period_debit, t.period_credit, t.closing_debit, t.closing_credit])
      } else if (this.tab === 'gl' && this.gl) {
        rows.push(['日期', '傳票號', '摘要', '借方', '貸方', '餘額'])
        rows.push(['期初', '', '', '', '', this.gl.opening])
        for (const l of this.gl.lines) rows.push([l.voucher_date, l.voucher_no, l.summary, l.debit, l.credit, l.balance])
      } else if (this.tab === 'sub' && this.sub) {
        rows.push([this.dimLabel(this.sub.dimension), '期初', '本期借', '本期貸', '期末'])
        for (const r of this.sub.rows) rows.push([r.key, r.opening, r.period_debit, r.period_credit, r.closing])
      } else return
      const csv = rows.map(r => r.map(c => '"' + String(c === null || c === undefined ? '' : c).replace(/"/g, '""') + '"').join(',')).join('\r\n')
      const a = document.createElement('a')
      a.href = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }))
      a.download = 'ledger-' + this.tab + '-' + this.start + '_' + this.end + '.csv'
      a.click()
      URL.revokeObjectURL(a.href)
    },
  }
}
