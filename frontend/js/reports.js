/* global Alpine */
function reportsApp() {
  return {
    // ── Period state ──────────────────────────────────────────────────────────
    periodType: 'month',
    year:       new Date().getFullYear(),
    month:      new Date().getMonth() + 1,
    quarter:    Math.ceil((new Date().getMonth() + 1) / 3),

    // ── UI state ──────────────────────────────────────────────────────────────
    loading:    false,
    exporting:  false,
    exportType: '',
    error:      '',
    data:       null,

    // ── Settlement modal ──────────────────────────────────────────────────────
    settlementModal:   false,
    settlementLoading: false,
    settlement:        null,   // { quoteNo, customerName, projectName, settlement, items, tot }

    // ── Helpers ───────────────────────────────────────────────────────────────
    get periodParam() {
      if (this.periodType === 'quarter') return this.year + '-Q' + this.quarter
      return this.year + '-' + String(this.month).padStart(2, '0')
    },
    get periodLabel() {
      if (!this.data) return ''
      return this.data.periodLabel || this.periodParam
    },
    get summary()      { return (this.data || {}).summary || {} },
    get periodItems()  { return (this.data || {}).periodItems  || [] },
    get outstanding()  { return (this.data || {}).outstanding  || [] },
    get casesAll()     { return (this.data || {}).casesAll     || [] },
    get casesPeriod()  { return (this.data || {}).casesPeriod  || [] },
    get salesPerf()    { return (this.data || {}).salesPerf    || [] },
    get marginCases()  { return (this.data || {}).marginCases  || [] },
    get warranty()     { return (this.data || {}).warranty     || [] },

    fmt(n) {
      return 'NT$ ' + (Math.round(n || 0)).toLocaleString()
    },
    pct(n) {
      return (n || 0).toFixed(1) + '%'
    },

    prevPeriod() {
      if (this.periodType === 'month') {
        if (this.month === 1) { this.year--; this.month = 12 } else { this.month-- }
      } else {
        if (this.quarter === 1) { this.year--; this.quarter = 4 } else { this.quarter-- }
      }
      this.loadData()
    },
    nextPeriod() {
      if (this.periodType === 'month') {
        if (this.month === 12) { this.year++; this.month = 1 } else { this.month++ }
      } else {
        if (this.quarter === 4) { this.year++; this.quarter = 1 } else { this.quarter++ }
      }
      this.loadData()
    },
    switchType(t) {
      this.periodType = t
      this.loadData()
    },

    // ── Auth ──────────────────────────────────────────────────────────────────
    _token() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.token || ''
    },
    _role() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.role || ''
    },

    // ── Load preview data ─────────────────────────────────────────────────────
    async loadData() {
      var role = this._role()
      if (role !== 'admin' && role !== 'superadmin') {
        this.error = '僅管理員以上可存取營運報表功能'
        return
      }
      this.loading = true
      this.error   = ''
      this.data    = null
      try {
        var res = await fetch('/api/reports/financial?period=' + this.periodParam, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '載入失敗')
        }
        this.data = await res.json()
      } catch (e) {
        this.error = e.message || '載入錯誤'
      } finally {
        this.loading = false
      }
    },

    // ── Export ────────────────────────────────────────────────────────────────
    async exportFile(fmt) {
      this.exporting  = true
      this.exportType = fmt
      var url = '/api/reports/financial/' + fmt + '?period=' + this.periodParam
      try {
        var res = await fetch(url, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '匯出失敗')
        }
        var blob = await res.blob()
        var ext  = fmt === 'excel' ? 'xlsx' : 'pdf'
        var fname = 'MOTRIX_營運報表_' + this.periodParam + '.' + ext
        var a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = fname
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(a.href)
      } catch (e) {
        alert('匯出失敗：' + (e.message || e))
      } finally {
        this.exporting  = false
        this.exportType = ''
      }
    },

    // ── Settlement modal ──────────────────────────────────────────────────────
    async openSettlement(quoteNo) {
      this.settlementModal   = true
      this.settlementLoading = true
      this.settlement        = null
      try {
        var res = await fetch('/api/quotations/' + quoteNo + '/settlement', {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) throw new Error('載入精算失敗')
        var d = await res.json()
        this.settlement = Object.assign({ quoteNo: quoteNo }, d)
      } catch (e) {
        alert('載入精算資料失敗：' + (e.message || e))
        this.settlementModal = false
      } finally {
        this.settlementLoading = false
      }
    },

    closeSettlement() {
      this.settlementModal = false
      this.settlement      = null
    },

    // helpers for settlement modal
    stlFmt(n) { return 'NT$ ' + (Math.round(n || 0)).toLocaleString() },
    stlSummary() { return (this.settlement && this.settlement.settlement && this.settlement.settlement.summary) || {} },
    stlItems()   { return (this.settlement && this.settlement.settlement && this.settlement.settlement.items)   || [] },
    stlExtras()  { return (this.settlement && this.settlement.settlement && this.settlement.settlement.extraItems) || [] },
    stlMemo()    { return (this.settlement && this.settlement.settlement && this.settlement.settlement.memo) || '' },
    stlStatus()  { return (this.settlement && this.settlement.settlement && this.settlement.settlement.status) || '' },
    stlFinAt()   { return (this.settlement && this.settlement.settlement && this.settlement.settlement.finalizedAt || '').slice(0,16).replace('T',' ') },
    stlFinBy()   { return (this.settlement && this.settlement.settlement && this.settlement.settlement.finalizedBy) || '' },
    stlCanOpen(c) { return c.settleStatus && c.settleStatus !== '' },

    activeTab: 'recv',

    async init() {
      var role = this._role()
      if (role !== 'admin' && role !== 'superadmin') {
        this.error = '僅管理員以上可存取營運報表功能'
        return
      }
      // 以伺服器時間為準，修正客戶端時鐘偏差
      try {
        var r = await fetch('/api/now')
        if (r.ok) {
          var t = await r.json()
          this.year    = t.year
          this.month   = t.month
          this.quarter = Math.ceil(t.month / 3)
        }
      } catch (_) {}
      this.loadData()
    }
  }
}
