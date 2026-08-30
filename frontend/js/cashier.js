/* global Alpine */
// 出納模組（2026-08-31 新增）：跨案件彙整待付款（已核准未匯款的承攬商匯款
// 申請）／待收款（未收款的案件款項期別），並整合銀行對帳單比對（原本掛在
// reports.html 資金水位頁籤下，這輪搬過來——概念上更貼近出納工作）。

function cashierApp() {
  return {
    session: {},
    loading: false,
    error: '',
    activeTab: 'payable',   // payable / receivable / bank

    payable: [],
    receivable: [],

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
    receiveSaving:        false,

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
    canAccess() {
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
      if (!this.canAccess()) { this.error = '僅管理員或出納可存取出納模組'; return }
      this.loading = true
      await Promise.all([this.loadPayable(), this.loadReceivable()])
      this.loading = false
    },

    async loadPayable() {
      try {
        const r = await fetch('/api/cashier/payable-queue', { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) this.payable = await r.json()
        else if (r.status === 403) this.error = '僅管理員或出納可存取出納模組'
      } catch (e) { console.error(e) }
    },

    async loadReceivable() {
      try {
        const r = await fetch('/api/cashier/receivable-queue', { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) this.receivable = await r.json()
        else if (r.status === 403) this.error = '僅管理員或出納可存取出納模組'
      } catch (e) { console.error(e) }
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
        await this.loadPayable()
      } catch (e) { alert('網路錯誤：' + e.message) }
      this.payVoucherSaving = false
    },

    // ── 標記已收款 ────────────────────────────────────────────────────────
    openReceiveModal(it) {
      this.receiveTarget = it
      this.receiveDate = this._localDateStr()
      this.receiveActualAmount = it.amount
      this.receiveFeeAmount = 0
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
            received: true, receivedAt: this.receiveDate,
            actualAmount: this.receiveActualAmount, feeAmount: this.receiveFeeAmount || 0,
          })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); this.receiveSaving = false; return }
        this.receiveModal = false
        this.receiveTarget = null
        await this.loadReceivable()
      } catch (e) { alert('網路錯誤：' + e.message) }
      this.receiveSaving = false
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
        await this.loadPayable()
      } catch (e) {
        alert('標記失敗：' + (e.message || e))
      }
      this.bankPaySaving = false
    },
  }
}
