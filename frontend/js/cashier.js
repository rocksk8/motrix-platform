/* global Alpine */
// 出納模組（2026-08-31 新增，同日 v2 加強）：跨案件彙整待付款（已核准未匯款
// 的承攬商匯款申請）／待收款（案件款項期別，含全部歷史，併入 receivables.
// html 原本的發票登錄/搜尋篩選/取消收款/手續費統計功能）／執行歷史（已匯款/
// 已收款彙整＋Excel 匯出），並整合銀行對帳單比對（原本掛在 reports.html 資金
// 水位頁籤下，這輪搬過來——概念上更貼近出納工作）。

function cashierApp() {
  return {
    session: {},
    loading: false,
    error: '',
    activeTab: 'payable',   // payable / receivable / history / bank

    payable: [],
    receivable: [],   // status=all，含已收+未收全部歷史（併入 receivables.html 用途）

    // ── 待收款 tab：搜尋/篩選（併入 receivables.html 原有功能）──────────────
    receivableSearch: '',
    receivableFilterTab: 'unreceived',   // all / unreceived / received / uninvoiced

    // ── 標記已匯款 Modal（比照 case-management.js payVoucherModal 的做法）──
    payVoucherModal:   false,
    payVoucherTarget:  null,
    payVoucherDate:    '',
    payVoucherNote:    '',
    payVoucherSaving:  false,

    // ── 標記已收款 Modal ──────────────────────────────────────────────────
    receiveModal:         false,
    receiveTarget:        null,
    receiveDate:          '',
    receiveActualAmount:  null,
    receiveFeeAmount:     0,
    receiveNote:          '',
    receiveSaving:        false,

    // ── 發票登錄 Modal（併入 receivables.html）───────────────────────────────
    invoiceModal:  { show: false, item: null, no: '' },

    // ── 執行歷史（2026-08-31 v2 新增）────────────────────────────────────────
    historyStart: '',
    historyEnd:   '',
    historyLoading: false,
    historyOutgoing: [],
    historyIncoming: [],
    historyOutgoingTotal: 0,
    historyIncomingTotal: 0,
    exporting: false,

    // ── 銀行對帳單比對（搬自 reports.js，邏輯不變）──────────────────────────
    bankReconciling: false,
    bankResult:      null,
    bankPayModal:    false,
    bankPayRow:      null,
    bankPayDate:     '',
    bankPaySaving:   false,

    // ── Auth / helpers ────────────────────────────────────────────────────
    _token() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.token || ''
    },
    _role() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.role || ''
    },
    _modules() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.modules || []
    },
    // 查詢類存取：admin+／cashier／finance 皆可看（finance 沿用 receivables.html
    // 原本的可視範圍，併頁面不代表砍掉他們的查詢權，只是不能執行標記動作，
    // 那些動作走的 API 本身只認 admin+/cashier，這裡前端沒放行也沒用）。
    canAccess() {
      return ['admin', 'superadmin'].includes(this._role())
        || this._modules().includes('cashier') || this._modules().includes('finance')
    },
    canExecute() {
      return ['admin', 'superadmin'].includes(this._role()) || this._modules().includes('cashier')
    },
    // 本地日期字串（YYYY-MM-DD），不用 toISOString()（UTC，台灣 UTC+8 每天
    // 00:00-08:00 之間會誤判成前一天，比照 case-management.js 同款修法）。
    _localDateStr(d) {
      d = d || new Date()
      const tz = d.getTimezoneOffset() * 60000
      return new Date(d.getTime() - tz).toISOString().slice(0, 10)
    },
    fmt(n) {
      return 'NT$ ' + (Math.round(n || 0)).toLocaleString()
    },

    async init() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (!s.token) { location.href = 'login.html'; return }
      this.session = s
      if (!this.canAccess()) { this.error = '僅管理員、出納或財務可存取出納模組'; return }
      const today = new Date()
      this.historyStart = this._localDateStr(new Date(today.getFullYear(), today.getMonth(), 1))
      this.historyEnd = this._localDateStr(today)
      this.loading = true
      await Promise.all([this.loadPayable(), this.loadReceivable(), this.loadHistory()])
      this.loading = false
    },

    async loadPayable() {
      try {
        const r = await fetch('/api/cashier/payable-queue', { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) this.payable = await r.json()
        else if (r.status === 403) this.error = '僅管理員、出納或財務可存取出納模組'
      } catch (e) { console.error(e) }
    },

    async loadReceivable() {
      try {
        const r = await fetch('/api/cashier/receivable-queue?status=all', { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) this.receivable = await r.json()
        else if (r.status === 403) this.error = '僅管理員、出納或財務可存取出納模組'
      } catch (e) { console.error(e) }
    },

    async loadHistory() {
      this.historyLoading = true
      try {
        const qs = `?start=${this.historyStart}&end=${this.historyEnd}`
        const r = await fetch('/api/cashier/execution-history' + qs, { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) {
          const d = await r.json()
          this.historyOutgoing = d.outgoing || []
          this.historyIncoming = d.incoming || []
          this.historyOutgoingTotal = d.outgoingTotal || 0
          this.historyIncomingTotal = d.incomingTotal || 0
        }
      } catch (e) { console.error(e) }
      this.historyLoading = false
    },

    async exportHistory() {
      this.exporting = true
      try {
        const qs = `?start=${this.historyStart}&end=${this.historyEnd}`
        const r = await fetch('/api/cashier/export' + qs, { headers: { Authorization: 'Bearer ' + this._token() } })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '匯出失敗'); this.exporting = false; return }
        const blob = await r.blob()
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = `MOTRIX_出納執行紀錄_${this.historyStart}_${this.historyEnd}.xlsx`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(a.href)
      } catch (e) { alert('匯出失敗：' + e.message) }
      this.exporting = false
    },

    isOverdue(dateStr) {
      return !!dateStr && dateStr < this._localDateStr()
    },
    isDueSoon(dateStr) {
      if (!dateStr || this.isOverdue(dateStr)) return false
      const soon = new Date()
      soon.setDate(soon.getDate() + 7)
      return dateStr <= this._localDateStr(soon)
    },

    // ── 頂部 KPI 統計列（全部從已抓回的陣列前端加總，不需要額外後端彙總）──────
    get kpiPayableTotal() {
      return this.payable.reduce((s, v) => s + (v.grandTotal || 0), 0)
    },
    get kpiPayableOverdue() {
      return this.payable.filter(v => this.isOverdue(v.payableDate)).length
    },
    get kpiReceivableTotal() {
      return this.receivable.filter(i => !i.received).reduce((s, i) => s + (i.amount || 0), 0)
    },
    get kpiReceivableOverdue() {
      return this.receivable.filter(i => i.overdue).length
    },

    // ── 待收款 tab：篩選/搜尋（併入 receivables.html 原有邏輯）───────────────
    get filteredReceivable() {
      let list = this.receivable
      if (this.receivableFilterTab === 'unreceived') list = list.filter(i => !i.received)
      if (this.receivableFilterTab === 'received')   list = list.filter(i => i.received)
      if (this.receivableFilterTab === 'uninvoiced') list = list.filter(i => !i.invoiceNo)
      const q = this.receivableSearch.trim().toLowerCase()
      if (q) list = list.filter(i =>
        (i.quoteNo || '').toLowerCase().includes(q) ||
        (i.customer || '').toLowerCase().includes(q) ||
        (i.type || '').toLowerCase().includes(q) ||
        (i.invoiceNo || '').toLowerCase().includes(q)
      )
      return list
    },
    get receivableUninvoicedCount() {
      return this.receivable.filter(i => !i.invoiceNo).length
    },

    // ── 標記已匯款 ────────────────────────────────────────────────────────
    openPayVoucherModal(v) {
      this.payVoucherTarget = v
      this.payVoucherDate = v.payableDate || this._localDateStr()
      this.payVoucherNote = ''
      this.payVoucherModal = true
    },

    async confirmPayVoucher() {
      const v = this.payVoucherTarget
      if (!v || !this.payVoucherDate) return
      this.payVoucherSaving = true
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/paid-toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ action: 'pay', paid_at: this.payVoucherDate, note: this.payVoucherNote })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); this.payVoucherSaving = false; return }
        this.payVoucherModal = false
        this.payVoucherTarget = null
        await Promise.all([this.loadPayable(), this.loadHistory()])
      } catch (e) { alert('網路錯誤：' + e.message) }
      this.payVoucherSaving = false
    },

    // ── 標記已收款 ────────────────────────────────────────────────────────
    openReceiveModal(it) {
      this.receiveTarget = it
      this.receiveDate = this._localDateStr()
      this.receiveActualAmount = it.amount
      this.receiveFeeAmount = 0
      this.receiveNote = ''
      this.receiveModal = true
    },

    async confirmReceive() {
      const it = this.receiveTarget
      if (!it || !this.receiveDate) return
      this.receiveSaving = true
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(it.quoteNo)}/payment/${it.idx}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({
            received: true, receivedAt: this.receiveDate, receivedBy: this.session.displayName || this.session.username || '',
            actualAmount: this.receiveActualAmount, feeAmount: this.receiveFeeAmount || 0, note: this.receiveNote,
          })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); this.receiveSaving = false; return }
        this.receiveModal = false
        this.receiveTarget = null
        await Promise.all([this.loadReceivable(), this.loadHistory()])
      } catch (e) { alert('網路錯誤：' + e.message) }
      this.receiveSaving = false
    },

    async toggleReceived(item, received) {
      if (!confirm(received ? '標記此款項為已收？' : '取消此款項的收款紀錄？')) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(item.quoteNo)}/payment/${item.idx}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ received, receivedAt: '', receivedBy: '' })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); return }
        await this.loadReceivable()
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    // ── 發票登錄（併入 receivables.html）──────────────────────────────────
    openInvoiceModal(item) {
      this.invoiceModal = { show: true, item, no: item.invoiceNo || '' }
    },

    async confirmInvoice() {
      const item = this.invoiceModal.item
      if (!item) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(item.quoteNo)}/payment/${item.idx}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ invoiceNo: this.invoiceModal.no.trim() })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); return }
        item.invoiceNo = this.invoiceModal.no.trim()
        this.invoiceModal.show = false
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    // ── 銀行對帳單比對（搬自 frontend/js/reports.js，2026-08-31）──────────────
    async uploadBankCsv(evt) {
      var file = evt.target.files[0]
      if (!file) return
      this.bankReconciling = true
      this.bankResult = null
      try {
        var fd = new FormData()
        fd.append('file', file)
        var res = await fetch('/api/reports/bank-reconcile', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this._token() },
          body: fd,
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '比對失敗')
        }
        this.bankResult = await res.json()
      } catch (e) {
        alert('銀行對帳比對失敗：' + (e.message || e))
      } finally {
        this.bankReconciling = false
        evt.target.value = ''
      }
    },

    // 銀行 CSV 各家欄位格式不一（見 backend _parse_bank_csv() 寬鬆偵測），r.date
    // 是原始文字，不保證是 YYYY-MM-DD——這裡盡量猜出來預先帶入 Modal，猜不出來
    // 就留空讓使用者自己看畫面上「銀行日期」欄手動填，不會拿猜錯的日期硬送。
    _guessDateFromBankText(raw) {
      const s = (raw || '').trim()
      if (!s) return ''
      let m = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/)
      if (m) return this._normalizeYmd(+m[1], +m[2], +m[3])
      m = s.match(/^(\d{4})(\d{2})(\d{2})(\d{0,6})?$/)
      if (m) return this._normalizeYmd(+m[1], +m[2], +m[3])
      // 民國年（台灣銀行常見，例如 115/08/20 = 2026/08/20）
      m = s.match(/^(\d{2,3})[-/.](\d{1,2})[-/.](\d{1,2})$/)
      if (m && +m[1] >= 1 && +m[1] <= 200) return this._normalizeYmd(+m[1] + 1911, +m[2], +m[3])
      return ''
    },

    _normalizeYmd(y, mo, d) {
      if (mo < 1 || mo > 12 || d < 1 || d > 31) return ''
      const dt = new Date(y, mo - 1, d)
      if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return ''
      return y + '-' + String(mo).padStart(2, '0') + '-' + String(d).padStart(2, '0')
    },

    openBankPayModal(row) {
      if (!row || !row.match) return
      this.bankPayRow = row
      this.bankPayDate = this._guessDateFromBankText(row.date) || this._localDateStr()
      this.bankPayModal = true
    },

    async confirmBankPay() {
      const row = this.bankPayRow
      if (!row || !row.match || !this.bankPayDate) return
      const voucherNo = row.match.voucherNo
      this.bankPaySaving = true
      try {
        var res = await fetch('/api/contractor-vouchers/' + voucherNo + '/paid-toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ action: 'pay', paid_at: this.bankPayDate, note: '銀行對帳單比對後標記' }),
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '標記失敗')
        }
        row.match._paid = true
        this.bankPayModal = false
        this.bankPayRow = null
        await Promise.all([this.loadPayable(), this.loadHistory()])
      } catch (e) {
        alert('標記失敗：' + (e.message || e))
      }
      this.bankPaySaving = false
    },
  }
}
