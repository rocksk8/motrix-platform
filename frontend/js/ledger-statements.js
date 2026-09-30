// 財務報表（總帳 B2：資產負債表、綜合損益表；B3、B4 會在同一頁加權益變動表、現金流量表）。設計 proposal-gl/04-reports.md。
// 數字與對帳全由後端算；這裡只呈現、展開科目明細、匯出目前這張表為 CSV。checks.balanced=false 一律明說，不當正常。

function ledgerStatementsPage() {
  const today = new Date()
  const pad = n => String(n).padStart(2, '0')
  const ymd = d => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
  const firstOfYear = today.getFullYear() + '-01-01'
  return {
    tab: 'bs',
    asOf: ymd(today),
    compareAsOf: '',
    start: firstOfYear,
    end: ymd(today),
    compareStart: '',
    compareEnd: '',
    drafts: false,
    showZero: false,
    loading: false,
    error: '',
    bs: null,
    is: null,
    eq: null,
    cf: null,
    open: {},

    _initDone: false,
    async init() {
      if (this._initDone) return
      this._initDone = true
      await this.run()
    },

    _token() {
      try { return JSON.parse(localStorage.getItem('motrix_session') || '{}').token || '' } catch (e) { return '' }
    },
    async _api(path) {
      const r = await fetch(path, { headers: { Authorization: 'Bearer ' + this._token() } })
      let data = {}
      try { data = await r.json() } catch (e) { data = {} }
      if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (r.status === 403 ? '沒有權限查看財務報表' : '查詢失敗（' + r.status + '）'))
      return data
    },
    fmt(n) { return (n || 0).toLocaleString('zh-TW') },
    setTab(t) { this.tab = t; this.run() },
    toggle(code) { this.open = Object.assign({}, this.open, { [code]: !this.open[code] }) },

    // 連續查詢時以最後發出的請求為準，舊請求晚到的回應丟掉（避免畫面停在上一個條件的數字）。
    _seq: 0,
    async run() {
      const seq = ++this._seq
      this.error = ''
      this.loading = true
      const base = '&include_drafts=' + this.drafts + '&show_zero=' + this.showZero
      try {
        if (this.tab === 'bs') {
          const r = await this._api('/api/ledger/balance-sheet?as_of=' + this.asOf + (this.compareAsOf ? '&compare_as_of=' + this.compareAsOf : '') + base)
          if (seq !== this._seq) return
          this.bs = r
        } else if (this.tab === 'cf') {
          const r = await this._api('/api/ledger/cash-flow?start=' + this.start + '&end=' + this.end + '&include_drafts=' + this.drafts)
          if (seq !== this._seq) return
          this.cf = r
        } else if (this.tab === 'eq') {
          const r = await this._api('/api/ledger/equity-statement?start=' + this.start + '&end=' + this.end + '&include_drafts=' + this.drafts)
          if (seq !== this._seq) return
          this.eq = r
        } else if (this.tab === 'is') {
          const cmp = this.compareStart && this.compareEnd ? '&compare_start=' + this.compareStart + '&compare_end=' + this.compareEnd : ''
          const r = await this._api('/api/ledger/income-statement?start=' + this.start + '&end=' + this.end + cmp + base)
          if (seq !== this._seq) return
          this.is = r
        }
      } catch (e) {
        if (seq !== this._seq) return
        this.error = e.message
      }
      this.loading = false
    },

    // 資產負債表的呈現列（攤平成一張表：區段、小節、科目列、可展開的科目明細、小計、總計）
    bsRows() {
      if (!this.bs) return []
      const s = this.bs.sections, rows = []
      const groups = [
        { key: 'assets', title: '資產', parts: [s.current_assets, s.noncurrent_assets], total: this.bs.totals.assets, totalLabel: '資產總計' },
        { key: 'liab', title: '負債', parts: [s.current_liabilities, s.noncurrent_liabilities], total: this.bs.totals.liabilities, totalLabel: '負債總計' },
        { key: 'eq', title: '權益', parts: [s.equity], total: this.bs.totals.equity, totalLabel: '權益總計' },
      ]
      for (const g of groups) {
        rows.push({ type: 'sec', label: g.title, amount: null, cmp: null, indent: 10, testid: 'st-bs-sec-' + g.key })
        for (const p of g.parts) {
          if (g.parts.length > 1) rows.push({ type: 'sub', label: p.title, amount: null, cmp: null, indent: 10 })
          for (const i of p.items) {
            const key = i.code || i.label
            rows.push({ type: 'item', label: i.label, amount: i.amount, cmp: this.compareAmount(i.code, i.label), indent: 28, key, testid: 'st-bs-line-' + (i.code || 'pl') })
            if (this.open[key]) for (const a of i.accounts) rows.push({ type: 'acct', label: a.code + ' ' + a.name, amount: a.amount, cmp: null, indent: 52 })
          }
          if (g.parts.length > 1) rows.push({ type: 'sub', label: p.title + '合計', amount: p.total, cmp: null, indent: 10 })
        }
        rows.push({ type: 'total', label: g.totalLabel, amount: g.total, cmp: null, indent: 10, testid: 'st-bs-total-' + g.key })
      }
      rows.push({ type: 'total', label: '負債及權益總計', amount: this.bs.totals.liabilities_and_equity, cmp: null, indent: 10, testid: 'st-bs-total-le' })
      return rows
    },
    rowClass(r) { return ({ sec: 'st-sec', sub: 'st-sub', item: 'st-item', acct: 'st-acct', total: 'st-total' })[r.type] || '' },
    compareAmount(code, label) {
      if (!this.bs || !this.bs.compare) return null
      const secs = this.bs.compare.sections
      for (const k of Object.keys(secs)) {
        const it = secs[k].items.find(i => (code && i.code === code) || (!code && i.label === label))
        if (it) return it.amount
      }
      return 0
    },
    compareIs(code) {
      if (!this.is || !this.is.compare) return null
      const l = this.is.compare.lines.find(x => x.code === code)
      return l ? l.period : 0
    },

    exportCsv() {
      const rows = []
      if (this.tab === 'bs' && this.bs) {
        rows.push(['項目', this.bs.as_of])
        for (const r of this.bsRows()) rows.push([r.label, r.amount === null ? '' : r.amount])
      } else if (this.tab === 'cf' && this.cf) {
        rows.push(['項目', this.cf.start + '～' + this.cf.end])
        for (const sec of this.cf.sections) {
          rows.push([sec.title, ''])
          for (const l of sec.lines) rows.push(['　' + l.label, l.amount])
          rows.push([sec.title + '淨額', sec.total])
        }
        rows.push(['本期現金及約當現金淨變動', this.cf.net_change])
        rows.push(['期初現金及約當現金', this.cf.cash_opening])
        rows.push(['期末現金及約當現金', this.cf.cash_closing])
      } else if (this.tab === 'eq' && this.eq) {
        rows.push(['項目'].concat(this.eq.columns.map(c => c.label)))
        for (const r of this.eq.rows) rows.push([r.label].concat(this.eq.columns.map(c => r.amounts[c.key])))
      } else if (this.tab === 'is' && this.is) {
        rows.push(['項目', '本期 ' + this.is.start + '～' + this.is.end, '年初至今'])
        for (const l of this.is.lines) rows.push([l.label, l.period, l.ytd])
      } else return
      const csv = rows.map(r => r.map(c => '"' + String(c === null || c === undefined ? '' : c).replace(/"/g, '""') + '"').join(',')).join('\r\n')
      const a = document.createElement('a')
      a.href = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }))
      a.download = 'statement-' + this.tab + '.csv'
      a.click()
      URL.revokeObjectURL(a.href)
    },
  }
}
